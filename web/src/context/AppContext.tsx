import { createContext, useContext } from "react";
import type { Tone } from "../lib/tones";
import type { ConfigPayload, Settings, StatusPayload } from "../lib/types";
import type { SocketState } from "../lib/ws";

// The provider component lives in AppProvider.tsx so this module exports no components (keeps fast refresh working).

export interface Toast {
  id: number;
  title: string;
  message: string;
  tone: Tone;
}

export interface AppValue {
  symbol: string;
  setSymbol: (symbol: string) => void;
  timeframe: string;
  setTimeframe: (timeframe: string) => void;
  status: StatusPayload | null;
  refreshStatus: () => void;
  config: ConfigPayload | null;
  settings: Settings | null;
  saveSettings: (patch: Record<string, unknown>) => Promise<Settings>;
  wsState: SocketState;
  voiceOn: boolean;
  setVoiceOn: (value: boolean) => void;
  assistantOpen: boolean;
  setAssistantOpen: (value: boolean) => void;
  toasts: Toast[];
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
  say: (text: string) => void;
  needsToken: boolean;
  submitToken: (token: string) => void;
}

export const AppContext = createContext<AppValue | null>(null);

export function useApp(): AppValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}
