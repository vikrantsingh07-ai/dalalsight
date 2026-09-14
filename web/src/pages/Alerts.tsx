import { useState } from "react";
import { useApp } from "../context/AppContext";
import { Help } from "../components/InfoTip";
import { del, post, put } from "../lib/api";
import { humanize, istTime, num } from "../lib/format";
import { useApi, useEvents } from "../lib/hooks";
import { plainLabel } from "../lib/plain";
import { TIMEFRAME_LABELS } from "../lib/timeframes";
import type { AlertEventRow, AlertRow } from "../lib/types";
import { Button, Card, Checkbox, Empty, ErrorNote, Field, Input, PageHeader, Pill, Select, Table } from "../components/ui";

const RULE_TYPES: Record<string, string> = {
  price_above: "Price goes above",
  price_below: "Price goes below",
  signal_label: "Signal becomes",
  event: "A chart event happens",
  support_test: "Price touches its floor (support)",
  resistance_test: "Price touches its ceiling (resistance)",
  regime_change: "Market mood changes",
  confidence_above: "Signal strength goes above",
  pcr_above: "Put/call ratio goes above (options)",
  pcr_below: "Put/call ratio goes below (options)",
};
const VALUE_HINTS: Record<string, string> = {
  price_above: "Price",
  price_below: "Price",
  confidence_above: "Strength (0–100)",
  pcr_above: "Ratio, e.g. 1.2",
  pcr_below: "Ratio, e.g. 0.8",
};
const LABELS = ["BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP", "LOW-QUALITY SETUP", "WATCH", "NO TRADE / WAIT FOR CONFIRMATION"];
const EVENT_NAMES: Record<string, string> = {
  breakout: "Breakout above the recent high",
  breakdown: "Breakdown below the recent low",
  false_breakout: "Fake breakout",
  false_breakdown: "Fake breakdown",
  sharp_move: "Sharp move",
  volume_spike: "Volume spike",
  ema_crossover: "Averages cross",
  ema_crossover_confirmed: "Averages cross (confirmed)",
  vwap_breakout: "Price climbs above VWAP",
  vwap_breakdown: "Price drops below VWAP",
  vwap_rejection: "Price bounces off VWAP",
  rsi_overbought: "RSI very high (overbought)",
  rsi_oversold: "RSI very low (oversold)",
  rsi_divergence: "RSI divergence",
  macd_crossover: "MACD cross",
  volatility_expansion: "Moves getting bigger",
  consolidation: "Price squeezing into a narrow range",
  supertrend_flip: "Supertrend flips",
  oi_shift: "Options open interest shifts",
};
const CHANNEL_NAMES: Record<string, string> = {
  dashboard: "On this page",
  browser: "Browser pop-up",
  sound: "Sound",
  voice: "Voice",
  telegram: "Telegram",
  email: "Email",
  webhook: "Webhook",
};
const REPEAT: [number, string][] = [
  [300, "5 min"],
  [900, "15 min"],
  [1800, "30 min"],
  [3600, "1 hour"],
  [14400, "4 hours"],
  [86400, "1 day"],
];

const repeatLabel = (seconds: number) => REPEAT.find(([value]) => value === seconds)?.[1] ?? `${Math.round(seconds / 60)} min`;

function describeRule(rule: AlertRow["rule"]): string {
  let what = (RULE_TYPES[rule.type] ?? humanize(rule.type)).toLowerCase();
  if (rule.type === "signal_label" && rule.label) what = `signal becomes ${plainLabel(rule.label)}`;
  else if (rule.type === "event" && rule.event_kind) what = (EVENT_NAMES[rule.event_kind] ?? humanize(rule.event_kind)).toLowerCase();
  else if (rule.value !== null && rule.value !== undefined) what = `${what} ${num(rule.value, 2)}`;
  else if (rule.type in VALUE_HINTS) what = `${what} …`;
  const candles = rule.timeframe ? ` (${TIMEFRAME_LABELS[rule.timeframe] ?? rule.timeframe} candles)` : "";
  return `${rule.symbol}: ${what}${candles}`;
}

export default function Alerts() {
  const { symbol, config } = useApp();
  const alerts = useApi<AlertRow[]>("/api/alerts");
  const events = useApi<AlertEventRow[]>("/api/alerts/events?limit=200");
  const [form, setForm] = useState({ name: "", type: "price_above", symbol: symbol || "NIFTY", timeframe: "", value: "", label: "BULLISH SETUP", event_kind: "breakout", cooldown_seconds: 900 });
  const [channels, setChannels] = useState<string[]>(["dashboard", "browser", "sound"]);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [permission, setPermission] = useState(() => ("Notification" in window ? Notification.permission : "unsupported"));

  useEvents(["alert", "alert_delivery"], () => {
    events.reload();
    alerts.reload();
  });

  const external: Record<string, boolean> = {
    telegram: Boolean(config?.public.telegram_configured),
    email: Boolean(config?.public.email_configured),
    webhook: Boolean(config?.public.webhook_configured),
  };
  const needsValue = form.type in VALUE_HINTS;
  const draftRule: AlertRow["rule"] = {
    type: form.type,
    symbol: form.symbol || "…",
    timeframe: form.timeframe || null,
    value: needsValue && form.value !== "" ? Number(form.value) : null,
    label: form.type === "signal_label" ? form.label : null,
    event_kind: form.type === "event" ? form.event_kind : null,
  };

  async function create() {
    setError(null);
    setCreated(null);
    if (needsValue && form.value === "") {
      setError(new Error(`Enter a value for "${RULE_TYPES[form.type]}".`));
      return;
    }
    try {
      const rule: Record<string, unknown> = { type: form.type, symbol: form.symbol, timeframe: form.timeframe || null };
      if (needsValue) rule.value = Number(form.value);
      if (form.type === "signal_label") rule.label = form.label;
      if (form.type === "event") rule.event_kind = form.event_kind;
      const name = form.name || describeRule(draftRule);
      await post("/api/alerts", { name, rule, channels, cooldown_seconds: form.cooldown_seconds, enabled: true });
      setCreated(name);
      alerts.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function toggle(alert: AlertRow) {
    await put(`/api/alerts/${alert.id}`, { name: alert.name, rule: alert.rule, channels: alert.channels, cooldown_seconds: alert.cooldown_seconds, enabled: !alert.enabled }).catch(setError);
    alerts.reload();
  }

  const quickStart: [string, Partial<typeof form>][] = [
    ["Price alert", { type: "price_above" }],
    ["BUY setup alert", { type: "signal_label", label: "BULLISH SETUP" }],
    ["SELL setup alert", { type: "signal_label", label: "BEARISH SETUP" }],
    ["Breakout alert", { type: "event", event_kind: "breakout" }],
  ];

  return (
    <div className="space-y-3">
      <PageHeader
        title="Alerts"
        subtitle="Get a sound, pop-up or message when a price is crossed or the signal changes."
        info="Alerts are checked every 30 seconds while the market is open, with a pause after each alert so you aren't flooded. On-page, browser, sound and voice alerts show here; Telegram, email and webhook alerts need settings in the server's .env file."
      >
        <Button
          onClick={() => {
            if ("Notification" in window) void Notification.requestPermission().then(setPermission);
          }}
          disabled={permission === "granted" || permission === "unsupported"}
        >
          {permission === "granted" ? "Browser pop-ups allowed" : permission === "unsupported" ? "Pop-ups not supported" : "Allow browser pop-ups"}
        </Button>
        <Button onClick={() => post("/api/alerts/test", { channels }).then(() => events.reload()).catch(setError)}>Send a test alert</Button>
      </PageHeader>

      <Card title="Create an alert" info={<Help topic="alertCondition" />}>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted">Quick start:</span>
          {quickStart.map(([label, patch]) => (
            <Button key={label} onClick={() => setForm({ ...form, ...patch })}>
              {label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Stock or index">
            <Input id="alert-symbol" value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })} className="w-32 font-mono" />
          </Field>
          <Field
            label={
              <span className="flex items-center gap-1">
                Tell me when <Help topic="alertCondition" />
              </span>
            }
          >
            <Select id="alert-type" value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })} className="w-64">
              {Object.entries(RULE_TYPES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          {needsValue && (
            <Field label={VALUE_HINTS[form.type]}>
              <Input id="alert-value" type="number" value={form.value} onChange={(event) => setForm({ ...form, value: event.target.value })} className="w-32" />
            </Field>
          )}
          {form.type === "signal_label" && (
            <Field label="Signal">
              <Select id="alert-label" value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} className="w-52">
                {LABELS.map((label) => (
                  <option key={label} value={label}>
                    {plainLabel(label)}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {form.type === "event" && (
            <Field label="Event">
              <Select id="alert-event" value={form.event_kind} onChange={(event) => setForm({ ...form, event_kind: event.target.value })} className="w-64">
                {Object.entries(EVENT_NAMES).map(([kind, label]) => (
                  <option key={kind} value={kind}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Candle size">
            <Select id="alert-timeframe" value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })} className="w-28">
              <option value="">Any</option>
              {(config?.timeframes ?? []).map((tf) => (
                <option key={tf} value={tf}>
                  {TIMEFRAME_LABELS[tf] ?? tf}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={
              <span className="flex items-center gap-1">
                Repeat at most every <Help topic="alertRepeat" />
              </span>
            }
          >
            <Select id="alert-repeat" value={form.cooldown_seconds} onChange={(event) => setForm({ ...form, cooldown_seconds: Number(event.target.value) })} className="w-28">
              {REPEAT.map(([seconds, label]) => (
                <option key={seconds} value={seconds}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name (optional)">
            <Input id="alert-name" value={form.name} placeholder="made for you if empty" maxLength={80} onChange={(event) => setForm({ ...form, name: event.target.value })} className="w-48" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1 text-xs text-muted">
            Tell me by <Help topic="alertChannels" />
          </span>
          {Object.entries(CHANNEL_NAMES).map(([channel, label]) => (
            <Checkbox
              key={channel}
              label={
                <span>
                  {label}
                  {channel in external && !external[channel] && <span className="text-warn"> (not set up)</span>}
                </span>
              }
              checked={channels.includes(channel)}
              onChange={(checked) => setChannels(checked ? [...channels, channel] : channels.filter((c) => c !== channel))}
            />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded border border-edge bg-bg/40 px-3 py-2 text-xs">
          <span>
            <span className="text-muted">You will be told when </span>
            {describeRule(draftRule).replace(": ", " ")}
            <span className="text-muted">
              {" "}
              by {channels.length ? channels.map((c) => CHANNEL_NAMES[c].toLowerCase()).join(", ") : "nothing (pick at least one way)"}, at most every {repeatLabel(form.cooldown_seconds)}.
            </span>
          </span>
          <Button variant="primary" onClick={() => void create()} disabled={channels.length === 0}>
            Create alert
          </Button>
        </div>
        <div className="mt-2 space-y-1">
          <ErrorNote error={error} />
          {created && <div className="text-xs text-bull">Alert created: {created}</div>}
        </div>
      </Card>

      <div className="grid gap-3 xl:grid-cols-2">
        <Card title="My alerts" bodyClass="p-0">
          {alerts.data?.length === 0 ? (
            <div className="p-3">
              <Empty>No alerts yet. Use a quick start button above to make your first one.</Empty>
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Alert</th>
                  <th>How</th>
                  <th>Last sent</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(alerts.data ?? []).map((alert) => (
                  <tr key={alert.id} className={alert.enabled ? "" : "opacity-50"}>
                    <td>
                      <div>{alert.name}</div>
                      <div className="text-[11px] text-muted">
                        {describeRule(alert.rule)} · repeats at most every {repeatLabel(alert.cooldown_seconds)}
                      </div>
                    </td>
                    <td className="text-[11px] text-muted">{alert.channels.map((c) => CHANNEL_NAMES[c] ?? c).join(", ")}</td>
                    <td className="text-muted">{alert.last_triggered_at ? istTime(alert.last_triggered_at, { date: true }) : "never"}</td>
                    <td className="whitespace-nowrap">
                      <Button variant="ghost" onClick={() => void toggle(alert)}>
                        {alert.enabled ? "Pause" : "Resume"}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() =>
                          del(`/api/alerts/${alert.id}`)
                            .then(() => alerts.reload())
                            .catch(setError)
                        }
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card title="Alerts sent" bodyClass="max-h-[520px] overflow-y-auto p-0">
          {events.data?.length === 0 ? (
            <div className="p-3">
              <Empty>No alerts sent yet.</Empty>
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Message</th>
                  <th>Sent by</th>
                </tr>
              </thead>
              <tbody>
                {(events.data ?? []).map((event) => (
                  <tr key={event.id}>
                    <td className="whitespace-nowrap text-muted">{istTime(event.ts, { date: true, seconds: true })}</td>
                    <td>{event.message}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(event.delivery).map(([channel, state]) => (
                          <Pill key={channel} tone={state.startsWith("failed") ? "bear" : state === "pending" ? "warn" : "bull"} title={state}>
                            {CHANNEL_NAMES[channel] ?? channel}
                          </Pill>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </div>
  );
}
