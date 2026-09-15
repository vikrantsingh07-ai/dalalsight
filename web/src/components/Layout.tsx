import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { istTime, shortModel } from "../lib/format";
import { useLocalState } from "../lib/hooks";
import { TEXT_TONES, type Tone } from "../lib/tones";
import AssistantPanel from "./AssistantPanel";
import InfoTip, { Help } from "./InfoTip";
import { Button, Input, Pill } from "./ui";

interface NavEntry {
  to: string;
  label: string;
  hint?: string;
  icon: string;
}

const MAIN: NavEntry[] = [
  { to: "/", label: "Home", hint: "Signal, chart and price levels", icon: "◧" },
  { to: "/market", label: "Market today", hint: "All indices and sectors", icon: "▦" },
  { to: "/watchlist", label: "My watchlist", hint: "Markets and stocks you follow", icon: "☆" },
  { to: "/stocks", label: "Stocks", hint: "Check a stock or find strong ones", icon: "◎" },
  { to: "/alerts", label: "Alerts", hint: "Get told when something changes", icon: "!" },
  { to: "/signals", label: "Practice & history", hint: "Past signals, paper trades, tests", icon: "↯" },
];

const MORE: NavEntry[] = [
  { to: "/options", label: "Options chain", icon: "⋮" },
  { to: "/strategies", label: "Strategy builder", icon: "⟋" },
  { to: "/hedging", label: "Hedging", icon: "◇" },
  { to: "/commentary", label: "AI commentary", icon: "✎" },
  { to: "/agents", label: "AI analysts", icon: "⚇" },
  { to: "/settings", label: "Settings", icon: "⚙" },
  { to: "/health", label: "System health", icon: "♥" },
];

function NavItem({ item, onPick }: { item: NavEntry; onPick: () => void }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      onClick={onPick}
      className={({ isActive }) => `flex items-start gap-2.5 rounded px-2.5 py-1.5 ${isActive ? "bg-panel-2 text-text" : "text-muted hover:bg-panel-2/60 hover:text-text"}`}
    >
      <span className="mt-0.5 w-4 text-center font-mono text-xs text-accent">{item.icon}</span>
      <span className="min-w-0">
        <span className="block text-sm">{item.label}</span>
        {item.hint && <span className="block truncate text-[10.5px] text-muted">{item.hint}</span>}
      </span>
    </NavLink>
  );
}

export default function Layout() {
  const { assistantOpen, needsToken } = useApp();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  const [moreOpen, setMoreOpen] = useLocalState("cc_nav_more", false);
  const showMore = moreOpen || MORE.some((item) => location.pathname.startsWith(item.to));
  const close = () => setNavOpen(false);
  return (
    <div className="flex h-full overflow-hidden">
      {navOpen && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={close} aria-hidden="true" />}
      <aside className={`${navOpen ? "fixed inset-y-0 left-0 z-40 flex" : "hidden"} w-60 shrink-0 flex-col border-r border-edge bg-panel lg:static lg:flex`}>
        <div className="flex items-center gap-2 border-b border-edge px-3 py-3">
          <svg viewBox="0 0 100 100" className="h-7 w-7 shrink-0" aria-hidden="true">
            <rect width="100" height="100" rx="20" fill="var(--color-bg)" />
            <path d="M14 70 L34 48 L50 58 L86 24" stroke="var(--color-accent)" strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="86" cy="24" r="7" fill="var(--color-bull)" />
          </svg>
          <div className="leading-tight">
            <div className="font-display text-sm font-semibold">DalalSight</div>
            <div className="text-[10px] uppercase tracking-widest text-muted">Indian market helper</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main">
          {MAIN.map((item) => (
            <NavItem key={item.to} item={item} onPick={close} />
          ))}
          <button
            type="button"
            onClick={() => setMoreOpen(!showMore)}
            aria-expanded={showMore}
            className="mt-3 flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-[11px] uppercase tracking-wide text-muted hover:text-text"
          >
            <span className={`transition ${showMore ? "rotate-90" : ""}`}>▸</span>
            More tools
          </button>
          {showMore && MORE.map((item) => <NavItem key={item.to} item={item} onPick={close} />)}
        </nav>
        <div className="border-t border-edge p-3 text-[10.5px] leading-snug text-muted">For learning and research, not investment advice. DalalSight never places real orders.</div>
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
  const marketText = !market ? "Market…" : market.is_trading ? "Market open" : market.session === "CLOSED" ? "Market closed" : market.label;
  const mode = status?.execution.mode ?? "analysis";
  const modeText = mode === "paper" ? "Practice mode" : mode === "live" ? "Live (blocked)" : "View only";
  const dataOk = status?.provider.status === "ONLINE";
  const connection: { tone: Tone; text: string } = !status
    ? { tone: "muted", text: "Connecting…" }
    : wsState === "open" && dataOk
      ? { tone: "bull", text: "Live" }
      : wsState === "connecting"
        ? { tone: "warn", text: "Connecting…" }
        : wsState !== "open"
          ? { tone: "bear", text: "Offline" }
          : { tone: "warn", text: "Data problem" };
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-edge bg-panel px-3 py-2">
      <Button variant="ghost" className="lg:hidden" onClick={onMenu} aria-label="Open menu">
        ☰ Menu
      </Button>
      <span className="flex items-center gap-1.5">
        <Pill tone={marketTone}>{marketText}</Pill>
        <Help topic="marketStatus" />
      </span>
      <span className="font-mono text-xs text-muted">{now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST</span>
      {market && !market.is_trading && market.next_open && <span className="hidden text-xs text-muted md:inline">Opens {istTime(market.next_open, { date: true })}</span>}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs">
          <span className={`inline-block h-2 w-2 rounded-full ${connection.tone === "bull" ? "bg-bull" : connection.tone === "warn" ? "bg-warn" : connection.tone === "bear" ? "bg-bear" : "bg-muted"}`} aria-hidden="true" />
          <span className={TEXT_TONES[connection.tone]}>{connection.text}</span>
          <InfoTip title="Connection" align="right">
            <span className="block">Live updates: {wsState}</span>
            <span className="block">Market data (NSE, Yahoo): {status?.provider.status ?? "…"}</span>
            <span className="block">
              AI writer: {status ? `${status.ai.status}, ${shortModel(status.ai.active_model)}, ${status.ai.calls_today}/${status.ai.daily_budget} calls today` : "…"}
            </span>
          </InfoTip>
        </span>
        <span className="flex items-center gap-1.5">
          <Pill tone={mode === "paper" ? "accent" : mode === "live" ? "bear" : "info"}>{modeText}</Pill>
          <Help topic="practice" align="right" />
        </span>
        <Button variant={voiceOn ? "primary" : "default"} onClick={() => setVoiceOn(!voiceOn)} title="Read important updates aloud">
          Voice {voiceOn ? "on" : "off"}
        </Button>
        <Button variant={assistantOpen ? "primary" : "default"} onClick={() => setAssistantOpen(!assistantOpen)}>
          Ask assistant
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
  const { submitToken, serverUrl } = useApp();
  const [server, setServer] = useState(serverUrl);
  const [token, setTokenValue] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <form
        className="w-full max-w-md rounded-lg border border-edge bg-panel p-4"
        onSubmit={(event) => {
          event.preventDefault();
          submitToken(token, server);
        }}
      >
        <h2 className="font-display text-base font-semibold">Connect to your DalalSight server</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">
          Both are saved only in this browser. Server link: where DalalSight runs, for example your Cloudflare Tunnel link. Leave it empty when this page is opened from the server
          itself.
        </p>
        <label htmlFor="server-link" className="mt-3 block text-xs text-muted">
          Server link
        </label>
        <Input id="server-link" className="mt-1" type="url" placeholder="https://….trycloudflare.com" value={server} onChange={(event) => setServer(event.target.value)} />
        <label htmlFor="access-token" className="mt-3 block text-xs text-muted">
          Access token (CC_ACCESS_TOKEN from the server&apos;s .env)
        </label>
        <Input id="access-token" className="mt-1" type="password" autoFocus value={token} onChange={(event) => setTokenValue(event.target.value)} />
        <Button type="submit" variant="primary" className="mt-3 w-full">
          Connect
        </Button>
      </form>
    </div>
  );
}
