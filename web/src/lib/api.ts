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
  const response = await fetch(path, { ...rest, headers, body });
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
