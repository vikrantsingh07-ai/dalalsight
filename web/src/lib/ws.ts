import { BUILT_API_BASE, apiBase, discoverServerUrl, getToken } from "./api";

export interface WsMessage {
  type: string;
  ts?: string;
  data: unknown;
}

type Handler = (message: WsMessage) => void;
export type SocketState = "connecting" | "open" | "closed";

function tokenProtocol(token: string): string {
  const bytes = new TextEncoder().encode(token);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return `cc-token.${btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`;
}

/** Same origin by default; a dashboard hosted apart from the API (e.g. on Vercel) connects to the API host. */
function socketUrl(): string {
  const base = apiBase();
  const toSocket = (http: string) => `${http.replace(/^http/, "ws")}/ws`;
  if (base && base !== BUILT_API_BASE) return toSocket(base); // a server link saved in this browser
  const explicit = (import.meta.env.VITE_WS_URL ?? "").trim();
  if (explicit) return explicit;
  if (base) return toSocket(base);
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
}

class DashboardSocket {
  private socket: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private stateHandlers = new Set<(state: SocketState) => void>();
  private retries = 0;
  private retryTimer: number | undefined;
  private pingTimer: number | undefined;
  state: SocketState = "closed";

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    const url = socketUrl();
    const token = getToken();
    this.setState("connecting");
    // The access token is sent as a subprotocol, never in the URL.
    const socket = token ? new WebSocket(url, [tokenProtocol(token)]) : new WebSocket(url);
    this.socket = socket;
    socket.onopen = () => {
      this.retries = 0;
      this.setState("open");
      this.pingTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send("ping");
      }, 25_000);
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as WsMessage;
        this.handlers.forEach((handler) => handler(message));
      } catch {
        /* ignore malformed frames */
      }
    };
    socket.onclose = () => {
      window.clearInterval(this.pingTimer);
      if (this.socket !== socket) return;
      this.socket = null;
      this.setState("closed");
      // A few retries against a stale link (e.g. the tunnel restarted with a new hostname) are expected; look up
      // the current one from Supabase before the next attempt, same as the REST layer.
      if (this.retries >= 2) void discoverServerUrl();
      const delay = Math.min(30_000, 1000 * 2 ** this.retries++);
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
    };
    socket.onerror = () => socket.close();
  }

  reconnect(): void {
    window.clearTimeout(this.retryTimer);
    const current = this.socket;
    this.socket = null;
    current?.close();
    this.connect();
  }

  subscribe(handler: Handler): () => void {
    this.handlers.add(handler);
    this.connect();
    return () => {
      this.handlers.delete(handler);
    };
  }

  onState(handler: (state: SocketState) => void): () => void {
    this.stateHandlers.add(handler);
    handler(this.state);
    return () => {
      this.stateHandlers.delete(handler);
    };
  }

  private setState(state: SocketState): void {
    this.state = state;
    this.stateHandlers.forEach((handler) => handler(state));
  }
}

export const socket = new DashboardSocket();
