import { useEffect, useState, type ReactNode } from "react";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { humanize } from "../lib/format";
import type { Priority, Settings } from "../lib/types";
import { listVoices, speak } from "../lib/voice";
import { Button, Card, Checkbox, ErrorNote, Field, Input, PageHeader, Pill, Select, Spinner } from "../components/ui";

const PRIORITIES: Priority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

function setPath<T extends object>(source: T, path: string[], value: unknown): T {
  const copy = structuredClone(source) as unknown as Record<string, unknown>;
  let node = copy;
  path.slice(0, -1).forEach((key) => {
    node = node[key] as Record<string, unknown>;
  });
  node[path[path.length - 1]] = value;
  return copy as unknown as T;
}

const csv = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);

export default function SettingsPage() {
  const { settings, saveSettings, config, timeframe } = useApp();
  const [draft, setDraft] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => listVoices());

  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const refresh = () => setVoices(listVoices());
    window.speechSynthesis.addEventListener("voiceschanged", refresh);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", refresh);
  }, []);

  const current = draft ?? settings;
  if (!current) return <Spinner label="Loading settings" />;

  const update = (path: string[], value: unknown) => {
    setSaved(false);
    setDraft(setPath(current, path, value));
  };
  const number = (label: string, path: string[], options: { step?: number; min?: number; max?: number; hint?: string } = {}) => {
    const value = path.reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], current) as number;
    return (
      <Field label={label} hint={options.hint}>
        <Input type="number" step={options.step ?? 1} min={options.min} max={options.max} value={Number.isFinite(value) ? value : ""} onChange={(event) => update(path, event.target.value === "" ? null : Number(event.target.value))} />
      </Field>
    );
  };
  const weightTotal = Object.values(current.signal.weights).reduce((sum, v) => sum + (Number(v) || 0), 0);

  async function save() {
    if (!current) return;
    setSaving(true);
    setError(null);
    try {
      await saveSettings(current as unknown as Record<string, unknown>);
      setDraft(null);
      setSaved(true);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    setError(null);
    try {
      await post("/api/settings/reset");
      window.location.reload();
    } catch (err) {
      setError(err);
    }
  }

  const pub = config?.public ?? {};

  return (
    <div className="space-y-3">
      <PageHeader title="Settings" subtitle="Validated on the server. Secrets (API keys, tokens) are configured only in .env and are never shown here.">
        {draft && <Pill tone="warn">unsaved changes</Pill>}
        {saved && <Pill tone="bull">saved</Pill>}
        <Button onClick={() => setDraft(null)} disabled={!draft}>
          Discard
        </Button>
        <Button variant="danger" onClick={() => void reset()}>
          Reset to defaults
        </Button>
        <Button variant="primary" onClick={() => void save()} disabled={!draft || saving}>
          {saving ? "Saving…" : "Save settings"}
        </Button>
      </PageHeader>
      <ErrorNote error={error} />

      <div className="grid gap-3 xl:grid-cols-2">
        <Section title="General">
          <Field label="Default symbol">
            <Input value={current.default_symbol} onChange={(event) => update(["default_symbol"], event.target.value.toUpperCase())} />
          </Field>
          <Field label="Default timeframe">
            <Select value={current.default_timeframe} onChange={(event) => update(["default_timeframe"], event.target.value)}>
              {(config?.timeframes ?? [timeframe]).map((tf) => (
                <option key={tf}>{tf}</option>
              ))}
            </Select>
          </Field>
          <Field label="Theme">
            <Select value={current.theme} onChange={(event) => update(["theme"], event.target.value)}>
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </Select>
          </Field>
          <Field label="Execution mode" hint="LIVE is refused unless LIVE_EXECUTION_ENABLED=true and a broker adapter exists (none in this build).">
            <Select value={current.execution_mode} onChange={(event) => update(["execution_mode"], event.target.value)}>
              <option value="analysis">Analysis only</option>
              <option value="paper">Paper trading</option>
              <option value="live">Live (disabled)</option>
            </Select>
          </Field>
          <Field label="AI model override" hint={`Blank uses DEFAULT_AI_MODEL (${String(pub.default_ai_model ?? "")}) with fallback ${String(pub.fallback_ai_model ?? "")}.`} className="sm:col-span-2">
            <Input value={current.ai_model_override} placeholder="e.g. nvidia/nemotron-3-super-120b-a12b:free" onChange={(event) => update(["ai_model_override"], event.target.value.trim())} />
          </Field>
        </Section>

        <Section title="Environment (read-only)">
          {(
            [
              ["AI provider", pub.ai_provider],
              ["AI key configured", pub.ai_key_configured ? `yes (${String(pub.ai_key_env)})` : "no"],
              ["Daily AI call budget", pub.ai_daily_call_budget],
              ["Market data provider", pub.market_data_provider],
              ["Option data provider", pub.option_data_provider],
              ["Live execution", pub.live_execution_enabled ? "enabled in env" : "disabled"],
              ["TradingView widget", pub.tradingview_widget_enabled ? "enabled" : "disabled"],
              ["Charting Library", pub.tradingview_library_configured ? "configured" : "not configured"],
              ["Telegram / email / webhook", `${pub.telegram_configured ? "yes" : "no"} / ${pub.email_configured ? "yes" : "no"} / ${pub.webhook_configured ? "yes" : "no"}`],
              ["Access token required", pub.access_token_required ? "yes" : "no"],
            ] as [string, unknown][]
          ).map(([label, value]) => (
            <div key={label} className="flex justify-between gap-2 border-b border-edge/50 py-1 text-xs sm:col-span-2">
              <span className="text-muted">{label}</span>
              <span className="font-mono">{String(value ?? "—")}</span>
            </div>
          ))}
        </Section>

        <Section title={`Signal weights (total ${weightTotal})`}>
          {Object.keys(current.signal.weights).map((key) => (
            <div key={key}>{number(humanize(key), ["signal", "weights", key], { min: 0, max: 100 })}</div>
          ))}
          <p className="text-[11px] text-muted sm:col-span-2">Weights are normalised over components that have data; unavailable components are excluded and reduce coverage.</p>
        </Section>

        <Section title="Signal thresholds & indicators">
          {number("Bullish threshold %", ["signal", "bullish_threshold"], { min: 50, max: 100 })}
          {number("Bearish threshold %", ["signal", "bearish_threshold"], { min: 0, max: 50 })}
          {number("Minimum model confidence %", ["signal", "min_confidence"], { min: 0, max: 100 })}
          {number("Minimum data coverage (0–1)", ["signal", "min_coverage"], { step: 0.05, min: 0, max: 1 })}
          {number("Minimum risk:reward", ["signal", "min_risk_reward"], { step: 0.1, min: 0.1 })}
          {number("WATCH band (points from 50)", ["signal", "watch_band"], { min: 0, max: 25 })}
          {number("EMA fast", ["signal", "ema_fast"], { min: 2 })}
          {number("EMA slow", ["signal", "ema_slow"], { min: 3 })}
          {number("Crossover confirmation bars", ["signal", "crossover_confirm_bars"], { min: 1, max: 10 })}
          {number("RSI period", ["signal", "rsi_period"], { min: 2 })}
          {number("RSI overbought", ["signal", "rsi_overbought"], { min: 50, max: 100 })}
          {number("RSI oversold", ["signal", "rsi_oversold"], { min: 0, max: 50 })}
          {number("Volume spike ×", ["signal", "volume_spike_mult"], { step: 0.1, min: 1 })}
          {number("Volume confirmation ×", ["signal", "volume_confirm_mult"], { step: 0.1, min: 1 })}
          {number("ATR period", ["signal", "atr_period"], { min: 2 })}
          {number("Supertrend period", ["signal", "supertrend_period"], { min: 2 })}
          {number("Supertrend multiplier", ["signal", "supertrend_mult"], { step: 0.1, min: 0.5 })}
          {number("Swing lookback", ["signal", "swing_lookback"], { min: 1, max: 20 })}
          {number("Breakout lookback", ["signal", "breakout_lookback"], { min: 5 })}
        </Section>

        <Section title="Risk">
          <Field label="Profile">
            <Select value={current.risk.profile} onChange={(event) => update(["risk", "profile"], event.target.value)}>
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="aggressive">Aggressive</option>
            </Select>
          </Field>
          {number("Capital (₹)", ["risk", "capital"], { min: 1, step: 1000 })}
          {number("Risk per trade %", ["risk", "risk_per_trade_pct"], { step: 0.1, min: 0.1, max: 10 })}
          {number("Max stop distance (ATR)", ["risk", "max_stop_atr"], { step: 0.1, min: 0.1 })}
        </Section>

        <Section title="Options">
          {number("Risk-free rate (decimal)", ["options", "risk_free_rate"], { step: 0.005, min: 0, max: 0.25 })}
          {number("Strikes around ATM", ["options", "strikes_around_atm"], { min: 3, max: 60 })}
          {number("Max bid-ask spread %", ["options", "max_spread_pct"], { step: 0.5, min: 0.1 })}
          {number("Min open interest", ["options", "min_oi"], { min: 0, step: 100 })}
          {number("Min volume", ["options", "min_volume"], { min: 0, step: 100 })}
          {number("Delta min", ["options", "delta_min"], { step: 0.05, min: 0.05, max: 0.95 })}
          {number("Delta max", ["options", "delta_max"], { step: 0.05, min: 0.05, max: 0.95 })}
          {number("Hedge min days to expiry", ["options", "hedge_min_days_to_expiry"], { min: 0, max: 120 })}
        </Section>

        <Section title="Commentary">
          <Checkbox label="Commentary enabled" checked={current.commentary.enabled} onChange={(v) => update(["commentary", "enabled"], v)} />
          <Checkbox label="Only during market hours (live)" checked={current.commentary.during_market_hours_only} onChange={(v) => update(["commentary", "during_market_hours_only"], v)} />
          {number("Min seconds between items", ["commentary", "min_interval_seconds"], { min: 10, max: 3600 })}
          {number("Per-event cooldown (s)", ["commentary", "event_cooldown_seconds"], { min: 30, max: 14400 })}
          {number("Confidence change (points)", ["commentary", "confidence_change_points"], { min: 1, max: 100 })}
          {number("Level test tolerance (ATR)", ["commentary", "level_test_atr"], { step: 0.05, min: 0.01, max: 2 })}
          <Field label="AI narration from priority">
            <Select value={current.commentary.llm_min_priority} onChange={(event) => update(["commentary", "llm_min_priority"], event.target.value)}>
              {PRIORITIES.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
          </Field>
          <Field label="Speak from priority">
            <Select value={current.commentary.speak_min_priority} onChange={(event) => update(["commentary", "speak_min_priority"], event.target.value)}>
              {PRIORITIES.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
          </Field>
        </Section>

        <Section title="Voice">
          <Checkbox label="Voice output enabled" checked={current.voice.enabled} onChange={(v) => update(["voice", "enabled"], v)} />
          <Field label="Voice">
            <Select value={current.voice.voice_name} onChange={(event) => update(["voice", "voice_name"], event.target.value)}>
              <option value="">Browser default</option>
              {voices.map((voice) => (
                <option key={voice.name} value={voice.name}>
                  {voice.name} ({voice.lang})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Language">
            <Input value={current.voice.lang} onChange={(event) => update(["voice", "lang"], event.target.value)} />
          </Field>
          {number("Rate", ["voice", "rate"], { step: 0.1, min: 0.5, max: 2 })}
          {number("Pitch", ["voice", "pitch"], { step: 0.1, min: 0.5, max: 2 })}
          <Button onClick={() => speak("NIFTY is testing support. Signal: no trade, wait for confirmation.", { voiceName: current.voice.voice_name, lang: current.voice.lang, rate: current.voice.rate, pitch: current.voice.pitch })}>
            Test voice
          </Button>
        </Section>

        <Section title="Market monitor">
          <Field label="Symbols (comma separated)" className="sm:col-span-2">
            <Input value={current.monitor.symbols.join(", ")} onChange={(event) => update(["monitor", "symbols"], csv(event.target.value))} />
          </Field>
          <Field label="Monitor timeframe">
            <Select value={current.monitor.timeframe} onChange={(event) => update(["monitor", "timeframe"], event.target.value)}>
              {(config?.timeframes ?? []).map((tf) => (
                <option key={tf}>{tf}</option>
              ))}
            </Select>
          </Field>
          <Field label="Option chain symbols">
            <Input value={current.monitor.option_symbols.join(", ")} onChange={(event) => update(["monitor", "option_symbols"], csv(event.target.value))} />
          </Field>
          {number("Poll seconds (market open)", ["monitor", "poll_seconds_open"], { min: 5, max: 600 })}
          {number("Poll seconds (closed)", ["monitor", "poll_seconds_closed"], { min: 30, max: 7200 })}
          {number("Option poll seconds", ["monitor", "option_poll_seconds"], { min: 30, max: 1800 })}
          {number("OI change event %", ["monitor", "oi_change_event_pct"], { step: 1, min: 1 })}
        </Section>

        <Section title="Market hours (IST)">
          {(["pre_open_start", "market_open", "closing_period_start", "market_close", "post_close_end"] as const).map((key) => (
            <Field key={key} label={humanize(key)}>
              <Input type="time" value={current.market_hours[key]} onChange={(event) => update(["market_hours", key], event.target.value)} />
            </Field>
          ))}
          <Field label="Extra holidays (YYYY-MM-DD, comma separated)" hint="NSE's holiday list is loaded automatically; add special closures here." className="sm:col-span-2">
            <Input
              value={current.market_hours.extra_holidays.join(", ")}
              onChange={(event) =>
                update(
                  ["market_hours", "extra_holidays"],
                  event.target.value
                    .split(",")
                    .map((d) => d.trim())
                    .filter(Boolean),
                )
              }
            />
          </Field>
        </Section>

        <Section title="Notifications & agents">
          {(["browser", "sound", "voice", "telegram", "webhook", "email"] as const).map((key) => (
            <Checkbox key={key} label={`${humanize(key)} notifications`} checked={current.notifications[key]} onChange={(v) => update(["notifications", key], v)} />
          ))}
          {Object.keys(current.agents.agent_weights).map((key) => (
            <div key={key}>{number(`${humanize(key)} agent weight`, ["agents", "agent_weights", key], { step: 0.1, min: 0, max: 10 })}</div>
          ))}
          {number("Max tool rounds per analyst", ["agents", "max_tool_rounds"], { min: 1, max: 20 })}
          {number("Max minutes per analyst", ["agents", "max_minutes_per_analyst"], { min: 2, max: 120, hint: "hard stop for slow free-tier models" })}
        </Section>

        <Section title="Watchlist">
          <Field label="Symbols (comma separated)" className="sm:col-span-2">
            <Input value={current.watchlist.join(", ")} onChange={(event) => update(["watchlist"], csv(event.target.value))} />
          </Field>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card title={title}>
      <div className="grid gap-2 sm:grid-cols-2">{children}</div>
    </Card>
  );
}
