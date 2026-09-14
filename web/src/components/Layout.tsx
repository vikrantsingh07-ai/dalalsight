import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { istTime, shortModel } from "../lib/format";
import AssistantPanel from "./AssistantPanel";
import { TEXT_TONES, toneForStatus, type Tone } from "../lib/tones";
import { Button, Input, Pill } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◧" },
  { to: "/market", label: "Market Overview", icon: "▦" },
  { to: "/stocks", label: "Stocks & Scanner", icon: "◎" },
  { to: "/options", label: "Options Chain", icon: "⋮" },
  { to: "/strategies", label: "Strategy Builder", icon: "⟋" },
  { to: "/hedging", label: "Hedging", icon: "◇" },
  { to: "/commentary", label: "AI Commentary", icon: "✎" },
  { to: "/agents", label: "Trading Agents", icon: "⚇" },
  { to: "/watchlist", label: "Watchlist", icon: "☆" },
  { to: "/signals", label: "Signals · Paper · Backtest", icon: "↯" },
  { to: "/alerts", label: "Alerts", icon: "!" },
  { to: "/settings", label: "Settings", icon: "⚙" },
  { to: "/health", label: "System Health", icon: "♥" },
];

export default function Layout() {
  const { assistantOpen, needsToken, status } = useApp();
  const [navOpen, setNavOpen] = useState(false);
  return (
    <div className="flex h-full overflow-hidden">
      {navOpen && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setNavOpen(false)} aria-hidden="true" />}
      <aside className={`${navOpen ? "fixed inset-y-0 left-0 z-40 flex" : "hidden"} w-56 shrink-0 flex-col border-r border-edge bg-panel lg:static lg:flex`}>
        <div className="flex items-center gap-2 border-b border-edge px-3 py-3">
          <svg viewBox="0 0 100 100" className="h-7 w-7 shrink-0" aria-hidden="true">
            <rect width="100" height="100" rx="20" fill="var(--color-bg)" />
            <path d="M14 70 L34 48 L50 58 L86 24" stroke="var(--color-accent)" strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="86" cy="24" r="7" fill="var(--color-bull)" />
          </svg>
          <div className="leading-tight">
            <div className="font-display text-sm font-semibold">DalalSight</div>
            <div className="text-[10px] uppercase tracking-widest text-muted">NSE · BSE · F&amp;O desk</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setNavOpen(false)}
              className={({ isActive }) => `flex items-center gap-2 rounded px-2.5 py-1.5 text-sm ${isActive ? "bg-panel-2 text-text" : "text-muted hover:bg-panel-2/60 hover:text-text"}`}
            >
              <span className="w-4 text-center font-mono text-xs text-accent">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-edge p-3 text-[10px] leading-snug text-muted">
          Research and decision support, not investment advice. Live order execution{" "}
          {status?.execution.live_execution_enabled ? "is enabled in env but has no broker adapter" : "is disabled"}.
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setNavOpen((value) => !value)} />
        <main className="min-h-0 flex-1 overflow-y-auto p-3 lg:p-4">
          <Outlet />
        </main>
      </div>
      {assistantOpen && <AssistantPanel />}
      <Toasts />
      {needsToken && <TokenPrompt />}
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { status, wsState, voiceOn, setVoiceOn, assistantOpen, setAssistantOpen } = useApp();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const market = status?.market;
  const marketTone: Tone = !market ? "muted" : market.is_trading ? "bull" : market.session === "CLOSED" ? "muted" : "warn";
  const mode = status?.execution.mode ?? "analysis";
  const aiTitle = status
    ? `${status.ai.status} · ${status.ai.active_model ?? "no model available"} · ${status.ai.calls_today}/${status.ai.daily_budget} calls today${status.ai.last_error ? ` · last error: ${status.ai.last_error}` : ""}`
    : "loading";
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-edge bg-panel px-3 py-2">
      <Button variant="ghost" className="lg:hidden" onClick={onMenu} aria-label="Toggle navigation">
        ☰
      </Button>
      <Pill
        tone={marketTone}
        title={market ? `${market.reason}${market.exchange_message ? ` · NSE: ${market.exchange_message}` : ""}` : "loading"}
      >
        {market?.label ?? "Market…"}
      </Pill>
      <span className="font-mono text-xs text-muted">{now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST</span>
      {market && !market.is_trading && (
        <span className="hidden text-[11px] text-muted md:inline">
          Last session {market.session_date}
          {market.next_open ? ` · next open ${istTime(market.next_open, { date: true })}` : ""}
        </span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        <Pill tone={wsState === "open" ? "bull" : wsState === "connecting" ? "warn" : "bear"} title="Live push connection to the backend">
          {wsState === "open" ? "push live" : `push ${wsState}`}
        </Pill>
        <Pill tone={toneForStatus(status?.provider.status)} title={status?.provider.name}>
          data {status?.provider.status ?? "…"}
        </Pill>
        <Pill tone={toneForStatus(status?.ai.status)} title={aiTitle}>
          AI {shortModel(status?.ai.active_model)}
        </Pill>
        <Pill
          tone={mode === "paper" ? "accent" : mode === "live" ? "bear" : "info"}
          title={status?.execution.live_execution_enabled ? "LIVE_EXECUTION_ENABLED is set, but no broker adapter exists" : "Live order execution is disabled"}
        >
          {mode}
        </Pill>
        <Button variant={voiceOn ? "primary" : "default"} onClick={() => setVoiceOn(!voiceOn)} title="Speak high-priority commentary and alerts">
          {voiceOn ? "Voice on" : "Voice off"}
        </Button>
        <Button variant={assistantOpen ? "primary" : "default"} onClick={() => setAssistantOpen(!assistantOpen)}>
          Assistant
        </Button>
      </div>
    </header>
  );
}

function Toasts() {
  const { toasts, dismissToast } = useApp();
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-3 left-3 z-50 flex w-80 max-w-[calc(100vw-1.5rem)] flex-col gap-2" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="rounded-lg border border-edge bg-panel p-3 shadow-2xl">
          <div className="flex items-start justify-between gap-2">
            <div className={`text-xs font-semibold ${TEXT_TONES[toast.tone]}`}>{toast.title}</div>
            <button type="button" className="text-xs text-muted hover:text-text" onClick={() => dismissToast(toast.id)} aria-label="Dismiss">
              ✕
            </button>
          </div>
          <div className="mt-1 text-xs leading-snug text-text">{toast.message}</div>
        </div>
      ))}
    </div>
  );
}

function TokenPrompt() {
  const { submitToken } = useApp();
  const [token, setTokenValue] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <form
        className="w-full max-w-sm rounded-lg border border-edge bg-panel p-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (token.trim()) submitToken(token);
        }}
      >
        <h2 className="font-display text-base font-semibold">Access token required</h2>
        <p className="mt-1 text-xs text-muted">This server has CC_ACCESS_TOKEN set. Enter it to continue; it is stored only in this browser.</p>
        <Input className="mt-3" type="password" autoFocus value={token} onChange={(event) => setTokenValue(event.target.value)} aria-label="Access token" />
        <Button type="submit" variant="primary" className="mt-3 w-full">
          Unlock
        </Button>
      </form>
    </div>
  );
}
