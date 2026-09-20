import { isUnavailable } from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(describe(detail));
    this.status = status;
    this.detail = detail;
  }
}

export function describe(detail: unknown): string {
  if (detail === null || detail === undefined || detail === "") return "Request failed";
  if (typeof detail === "string") return detail;
  if (isUnavailable(detail)) {
    return `Data unavailable: ${detail.what} — ${detail.reason}${detail.requirement ? ` (requires ${detail.requirement})` : ""}`;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = "loc" in item && Array.isArray(item.loc) ? `${item.loc.slice(1).join(".")}: ` : "";
          return `${loc}${String(item.msg)}`;
        }
        return String(item);
      })
      .join("; ");
  }
  if (typeof detail === "object" && "reason" in detail) return String((detail as { reason: unknown }).reason);
  return JSON.stringify(detail);
}

const TOKEN_KEY = "cc_access_token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable: the token lives only for this page load */
  }
}

const SERVER_KEY = "cc_server_url";
const DISCOVERED_KEY = "cc_discovered_server_url";
const clean = (url: string) => url.trim().replace(/\/+$/, "");

/** Backend origin compiled in with VITE_API_BASE_URL (e.g. a dashboard on Vercel); empty means same origin. */
export const BUILT_API_BASE = clean(import.meta.env.VITE_API_BASE_URL ?? "");

function savedServerUrl(): string {
  try {
    return clean(localStorage.getItem(SERVER_KEY) ?? "");
  } catch {
    return "";
  }
}

function discoveredServerUrl(): string {
  try {
    return clean(localStorage.getItem(DISCOVERED_KEY) ?? "");
  } catch {
    return "";
  }
}

/**
 * The backend to call, in order: a server link saved in this browser (from the connect prompt) — always wins, so a
 * link you pasted yourself is never silently replaced; then one auto-discovered from Supabase (see
 * `discoverServerUrl`); then the one compiled in with VITE_API_BASE_URL.
 */
export function apiBase(): string {
  return savedServerUrl() || discoveredServerUrl() || BUILT_API_BASE;
}

export function setServerUrl(url: string): void {
  try {
    if (clean(url)) localStorage.setItem(SERVER_KEY, clean(url));
    else localStorage.removeItem(SERVER_KEY);
  } catch {
    /* storage unavailable: the link lives only for this page load */
  }
}

// Supabase's public "anon" key — meant to be embedded in client code, not a secret. `endpoints` only exposes the
// backend's own current public URL, published there each time the tunnel restarts with a new hostname (see
// deploy/windows/run-tunnel-loop.ps1), so a Vercel-hosted dashboard finds it without anyone re-pasting a link.
const DISCOVERY_URL = "https://tdapqzuqjeruuyicihlq.supabase.co/rest/v1/endpoints?id=eq.backend&select=url";
const DISCOVERY_ANON_KEY = "sb_publishable_0i9GEZKzyVUN9LNkp4xmMA_ACb48ABz";

/** Looks up the backend's current URL from Supabase; caches it (for `apiBase`) and returns it, or "" if unavailable. */
export async function discoverServerUrl(): Promise<string> {
  try {
    const response = await fetch(DISCOVERY_URL, { headers: { apikey: DISCOVERY_ANON_KEY } });
    if (!response.ok) return "";
    const rows = (await response.json()) as { url?: string }[];
    const url = clean(rows[0]?.url ?? "");
    if (url) localStorage.setItem(DISCOVERED_KEY, url);
    return url;
  } catch {
    return "";
  }
}

const askToConnect = () => window.dispatchEvent(new CustomEvent("cc:connect"));

function attempt(base: string, path: string, rest: RequestInit, headers: Headers, body: BodyInit | null | undefined): Promise<Response> {
  return fetch(`${base}${path}`, { ...rest, headers, body });
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const headers = new Headers(rest.headers);
  const token = getToken();
  if (token) headers.set("X-Access-Token", token);
  let body = rest.body;
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }
  let base = apiBase();
  let response: Response;
  try {
    response = await attempt(base, path, rest, headers, body);
    if ((response.headers.get("content-type") ?? "").includes("text/html")) throw new Error("html");
  } catch {
    // The current base failed (link changed, tunnel restarted, or nothing saved yet). Unless the user pinned a
    // link themselves, look up the current one from Supabase and retry once before asking them to connect.
    if (savedServerUrl()) {
      askToConnect();
      throw new ApiError(0, "Can't reach that server. Check the server link.");
    }
    const discovered = await discoverServerUrl();
    if (!discovered || discovered === base) {
      askToConnect();
      throw new ApiError(0, "This address is not a DalalSight server. Enter the server link.");
    }
    base = discovered;
    try {
      response = await attempt(base, path, rest, headers, body);
    } catch (error) {
      askToConnect();
      throw error;
    }
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    if (response.status === 401) window.dispatchEvent(new CustomEvent("cc:unauthorized"));
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, json: unknown = {}) => api<T>(path, { method: "POST", json });
export const put = <T>(path: string, json: unknown) => api<T>(path, { method: "PUT", json });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
