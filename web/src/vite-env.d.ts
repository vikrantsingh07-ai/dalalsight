/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin when the dashboard is hosted apart from the API (e.g. on Vercel), such as https://api.example.com. Empty = same origin. */
  readonly VITE_API_BASE_URL?: string;
  /** Optional WebSocket URL override. Defaults to VITE_API_BASE_URL with ws(s):// and /ws. */
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
