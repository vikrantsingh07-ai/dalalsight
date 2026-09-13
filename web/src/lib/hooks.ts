import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { socket, type WsMessage } from "./ws";

export function useApi<T>(path: string | null, options: { interval?: number } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((value) => value + 1), []);
  const interval = options.interval;

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    const load = () => {
      setLoading(true);
      api<T>(path)
        .then((value) => {
          if (!cancelled) {
            setData(value);
            setError(null);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };
    load();
    const id = interval ? window.setInterval(load, interval) : undefined;
    return () => {
      cancelled = true;
      if (id) window.clearInterval(id);
    };
  }, [path, tick, interval]);

  return { data, error, loading, reload, setData };
}

export function useEvents(types: string[], handler: (message: WsMessage) => void) {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  const key = types.join(",");
  useEffect(() => {
    const wanted = new Set(key.split(","));
    return socket.subscribe((message) => {
      if (wanted.has(message.type)) ref.current(message);
    });
  }, [key]);
}

export function useLocalState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable */
    }
  }, [key, value]);
  return [value, setValue] as const;
}
