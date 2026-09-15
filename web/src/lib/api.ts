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
const clean = (url: string) => url.trim().replace(/\/+$/, "");

/** Backend origin compiled in with VITE_API_BASE_URL (e.g. a dashboard on Vercel); empty means same origin. */
export const BUILT_API_BASE = clean(import.meta.env.VITE_API_BASE_URL ?? "");

/**
 * The backend to call. A server link saved in this browser (from the connect prompt) wins over the built-in one, so a
 * changing Cloudflare Tunnel link needs no rebuild.
 */
export function apiBase(): string {
  try {
    const saved = clean(localStorage.getItem(SERVER_KEY) ?? "");
    if (saved) return saved;
  } catch {
    /* storage unavailable */
  }
  return BUILT_API_BASE;
}

export function setServerUrl(url: string): void {
  try {
    if (clean(url)) localStorage.setItem(SERVER_KEY, clean(url));
    else localStorage.removeItem(SERVER_KEY);
  } catch {
    /* storage unavailable: the link lives only for this page load */
  }
}

const askToConnect = () => window.dispatchEvent(new CustomEvent("cc:connect"));

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
  const base = apiBase();
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...rest, headers, body });
  } catch (error) {
    // A separately hosted server that can't be reached (tunnel closed, link changed): ask for the link again.
    if (base) askToConnect();
    throw error;
  }
  if ((response.headers.get("content-type") ?? "").includes("text/html")) {
    // An HTML page instead of the API: this dashboard is hosted apart (e.g. Vercel) and has no server link yet.
    askToConnect();
    throw new ApiError(0, "This address is not a DalalSight server. Enter the server link.");
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
