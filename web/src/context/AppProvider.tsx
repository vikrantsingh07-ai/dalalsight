import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiBase, get, put, setServerUrl, setToken } from "../lib/api";
import type { ConfigPayload, Settings, StatusPayload } from "../lib/types";
import { beep, speak } from "../lib/voice";
import { socket, type SocketState, type WsMessage } from "../lib/ws";
import { AppContext, type AppValue, type Toast } from "./AppContext";

function readStored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [symbol, setSymbolState] = useState(() => readStored("cc_symbol", ""));
  const [timeframe, setTimeframeState] = useState(() => readStored("cc_timeframe", ""));
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [config, setConfig] = useState<ConfigPayload | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [wsState, setWsState] = useState<SocketState>("connecting");
  const [voiceOn, setVoiceOnState] = useState(() => readStored("cc_voice", "off") === "on");
  const [assistantOpen, setAssistantOpenState] = useState(() => readStored("cc_assistant", "closed") === "open");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [needsToken, setNeedsToken] = useState(false);
  const [serverUrl, setServerUrlState] = useState(() => apiBase());
  const [authTick, setAuthTick] = useState(0);
  const [statusTick, setStatusTick] = useState(0);
  const settingsRef = useRef<Settings | null>(null);
  const voiceRef = useRef(voiceOn);

  useEffect(() => {
    settingsRef.current = settings;
    if (settings) document.documentElement.dataset.theme = settings.theme;
  }, [settings]);
  useEffect(() => {
    voiceRef.current = voiceOn;
  }, [voiceOn]);

  const setSymbol = useCallback((value: string) => {
    const next = value.trim().toUpperCase();
    if (!next) return;
    setSymbolState(next);
    writeStored("cc_symbol", next);
  }, []);
  const setTimeframe = useCallback((value: string) => {
    setTimeframeState(value);
    writeStored("cc_timeframe", value);
  }, []);
  const setVoiceOn = useCallback((value: boolean) => {
    setVoiceOnState(value);
    writeStored("cc_voice", value ? "on" : "off");
    if (value) speak("Voice enabled.", { lang: settingsRef.current?.voice.lang });
  }, []);
  const setAssistantOpen = useCallback((value: boolean) => {
    setAssistantOpenState(value);
    writeStored("cc_assistant", value ? "open" : "closed");
  }, []);

  useEffect(() => {
    get<ConfigPayload>("/api/config").then(setConfig).catch(() => undefined);
    get<Settings>("/api/settings").then(setSettings).catch(() => undefined);
  }, [authTick]);

  // Until the user picks a symbol or timeframe, the configured defaults apply.
  const activeSymbol = symbol || settings?.default_symbol || "";
  const activeTimeframe = timeframe || settings?.default_timeframe || "";

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      get<StatusPayload>("/api/status")
        .then((value) => {
          if (!cancelled) setStatus(value);
        })
        .catch(() => undefined);
    load();
    const id = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [authTick, statusTick]);

  useEffect(() => {
    // 401: the server wants the access token. cc:connect: no server link yet, or the saved one can't be reached.
    const ask = () => setNeedsToken(true);
    window.addEventListener("cc:unauthorized", ask);
    window.addEventListener("cc:connect", ask);
    return () => {
      window.removeEventListener("cc:unauthorized", ask);
      window.removeEventListener("cc:connect", ask);
    };
  }, []);

  useEffect(() => socket.onState(setWsState), []);

  const dismissToast = useCallback((id: number) => setToasts((list) => list.filter((toast) => toast.id !== id)), []);
  const pushToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list.slice(-4), { ...toast, id }]);
    window.setTimeout(() => setToasts((list) => list.filter((item) => item.id !== id)), 10_000);
  }, []);

  const say = useCallback((text: string) => {
    const current = settingsRef.current;
    if (!voiceRef.current || (current && !current.voice.enabled)) return;
    speak(text, { voiceName: current?.voice.voice_name, lang: current?.voice.lang, rate: current?.voice.rate, pitch: current?.voice.pitch });
  }, []);

  useEffect(
    () =>
      socket.subscribe((message: WsMessage) => {
        const current = settingsRef.current;
        if (message.type === "alert") {
          const data = message.data as { name: string; message: string; channels: string[]; priority?: string };
          pushToast({ title: `Alert · ${data.name}`, message: data.message, tone: "warn" });
          if (data.channels.includes("sound") && (current?.notifications.sound ?? true)) beep(data.priority ?? "HIGH");
          if (data.channels.includes("voice") && (current?.notifications.voice ?? true)) say(`Alert. ${data.message}`);
          if (data.channels.includes("browser") && (current?.notifications.browser ?? true) && "Notification" in window && Notification.permission === "granted") {
            const notification = new Notification(data.name, { body: data.message });
            notification.onclick = () => window.focus();
          }
        } else if (message.type === "commentary") {
          const data = message.data as { text: string; speak: boolean; priority: string; symbol: string; mode: string };
          if (data.speak) say(data.text);
          if (data.priority === "CRITICAL") pushToast({ title: `${data.symbol} · critical`, message: data.text, tone: "bear" });
        } else if (message.type === "signal") {
          const data = message.data as { symbol: string; timeframe: string; label: string; price: number };
          pushToast({ title: `${data.symbol} ${data.timeframe}`, message: `${data.label} recorded at ${data.price}`, tone: "info" });
        } else if (message.type === "agent_run") {
          const data = message.data as { id: number; symbol: string; status: string; consensus: { signal: string } | null };
          pushToast({ title: `Agent run #${data.id} ${data.status}`, message: `${data.symbol}: ${data.consensus?.signal ?? "no consensus"}`, tone: data.status === "completed" ? "info" : "bear" });
        }
      }),
    [pushToast, say],
  );

  const saveSettings = useCallback(async (patch: Record<string, unknown>) => {
    const next = await put<Settings>("/api/settings", patch);
    setSettings(next);
    setStatusTick((value) => value + 1);
    return next;
  }, []);

  const submitToken = useCallback((token: string, server?: string) => {
    if (server !== undefined) {
      setServerUrl(server);
      setServerUrlState(apiBase());
    }
    if (token.trim()) setToken(token.trim());
    setNeedsToken(false);
    setAuthTick((value) => value + 1);
    socket.reconnect();
  }, []);

  const refreshStatus = useCallback(() => setStatusTick((value) => value + 1), []);

  const value = useMemo<AppValue>(
    () => ({
      symbol: activeSymbol,
      setSymbol,
      timeframe: activeTimeframe,
      setTimeframe,
      status,
      refreshStatus,
      config,
      settings,
      saveSettings,
      wsState,
      voiceOn,
      setVoiceOn,
      assistantOpen,
      setAssistantOpen,
      toasts,
      pushToast,
      dismissToast,
      say,
      needsToken,
      submitToken,
      serverUrl,
    }),
    [activeSymbol, setSymbol, activeTimeframe, setTimeframe, status, refreshStatus, config, settings, saveSettings, wsState, voiceOn, setVoiceOn, assistantOpen, setAssistantOpen, toasts, pushToast, dismissToast, say, needsToken, submitToken, serverUrl],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
