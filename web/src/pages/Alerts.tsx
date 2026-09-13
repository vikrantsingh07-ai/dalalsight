import { useState } from "react";
import { useApp } from "../context/AppContext";
import { del, post, put } from "../lib/api";
import { humanize, istTime } from "../lib/format";
import { useApi, useEvents } from "../lib/hooks";
import type { AlertEventRow, AlertRow } from "../lib/types";
import { Button, Card, Checkbox, Empty, ErrorNote, Field, Input, PageHeader, Pill, Select, Table } from "../components/ui";

const RULE_TYPES: Record<string, string> = {
  price_above: "Price crosses above",
  price_below: "Price crosses below",
  signal_label: "Signal label becomes",
  confidence_above: "Model confidence rises above",
  event: "Technical event occurs",
  regime_change: "Market regime changes",
  pcr_above: "PCR (OI) rises above",
  pcr_below: "PCR (OI) falls below",
  support_test: "Support test",
  resistance_test: "Resistance test",
};
const VALUE_TYPES = new Set(["price_above", "price_below", "confidence_above", "pcr_above", "pcr_below"]);
const LABELS = ["BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP", "LOW-QUALITY SETUP", "WATCH", "NO TRADE / WAIT FOR CONFIRMATION"];
const EVENT_KINDS = ["ema_crossover", "ema_crossover_confirmed", "vwap_breakout", "vwap_breakdown", "vwap_rejection", "rsi_overbought", "rsi_oversold", "rsi_divergence", "macd_crossover", "volume_spike", "breakout", "breakdown", "false_breakout", "false_breakdown", "volatility_expansion", "consolidation", "supertrend_flip", "sharp_move", "oi_shift"];
const CHANNELS = ["dashboard", "browser", "sound", "voice", "telegram", "email", "webhook"];

export default function Alerts() {
  const { symbol, config } = useApp();
  const alerts = useApi<AlertRow[]>("/api/alerts");
  const events = useApi<AlertEventRow[]>("/api/alerts/events?limit=200");
  const [form, setForm] = useState({ name: "", type: "price_above", symbol: symbol || "NIFTY", timeframe: "", value: "", label: "BULLISH SETUP", event_kind: "breakout", cooldown_seconds: 900 });
  const [channels, setChannels] = useState<string[]>(["dashboard", "browser", "sound"]);
  const [error, setError] = useState<unknown>(null);
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

  async function create() {
    setError(null);
    try {
      const rule: Record<string, unknown> = { type: form.type, symbol: form.symbol, timeframe: form.timeframe || null };
      if (VALUE_TYPES.has(form.type)) rule.value = Number(form.value);
      if (form.type === "signal_label") rule.label = form.label;
      if (form.type === "event") rule.event_kind = form.event_kind;
      await post("/api/alerts", { name: form.name || `${form.symbol} ${RULE_TYPES[form.type]}`, rule, channels, cooldown_seconds: form.cooldown_seconds, enabled: true });
      alerts.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function toggle(alert: AlertRow) {
    await put(`/api/alerts/${alert.id}`, { name: alert.name, rule: alert.rule, channels: alert.channels, cooldown_seconds: alert.cooldown_seconds, enabled: !alert.enabled }).catch(setError);
    alerts.reload();
  }

  return (
    <div className="space-y-3">
      <PageHeader title="Alerts" subtitle="Rules are evaluated on every monitor cycle with per-alert cooldowns. Dashboard, browser, sound and voice are delivered here; Telegram, email and webhook are sent by the backend when configured in .env.">
        <Button
          onClick={() => {
            if ("Notification" in window) void Notification.requestPermission().then(setPermission);
          }}
          disabled={permission === "granted" || permission === "unsupported"}
        >
          Browser notifications: {permission}
        </Button>
        <Button onClick={() => post("/api/alerts/test", { channels }).then(() => events.reload()).catch(setError)}>Send test alert</Button>
      </PageHeader>

      <Card title="New alert">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Name">
            <Input value={form.name} placeholder="optional" maxLength={80} onChange={(event) => setForm({ ...form, name: event.target.value })} className="w-48" />
          </Field>
          <Field label="Condition">
            <Select value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })} className="w-56">
              {Object.entries(RULE_TYPES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Symbol">
            <Input value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })} className="w-32 font-mono" />
          </Field>
          <Field label="Timeframe">
            <Select value={form.timeframe} onChange={(event) => setForm({ ...form, timeframe: event.target.value })} className="w-24">
              <option value="">any</option>
              {(config?.timeframes ?? []).map((tf) => (
                <option key={tf}>{tf}</option>
              ))}
            </Select>
          </Field>
          {VALUE_TYPES.has(form.type) && (
            <Field label="Value">
              <Input type="number" value={form.value} onChange={(event) => setForm({ ...form, value: event.target.value })} className="w-28" />
            </Field>
          )}
          {form.type === "signal_label" && (
            <Field label="Label">
              <Select value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} className="w-64">
                {LABELS.map((label) => (
                  <option key={label}>{label}</option>
                ))}
              </Select>
            </Field>
          )}
          {form.type === "event" && (
            <Field label="Event">
              <Select value={form.event_kind} onChange={(event) => setForm({ ...form, event_kind: event.target.value })} className="w-52">
                {EVENT_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {humanize(kind)}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Cooldown (s)">
            <Input type="number" min={30} max={86400} value={form.cooldown_seconds} onChange={(event) => setForm({ ...form, cooldown_seconds: Number(event.target.value) || 900 })} className="w-24" />
          </Field>
          <Button variant="primary" onClick={() => void create()} disabled={channels.length === 0}>
            Create alert
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-3">
          {CHANNELS.map((channel) => (
            <Checkbox
              key={channel}
              label={
                <span>
                  {channel}
                  {channel in external && !external[channel] && <span className="text-warn"> (not configured)</span>}
                </span>
              }
              checked={channels.includes(channel)}
              onChange={(checked) => setChannels(checked ? [...channels, channel] : channels.filter((c) => c !== channel))}
            />
          ))}
        </div>
        <div className="mt-2">
          <ErrorNote error={error} />
        </div>
      </Card>

      <div className="grid gap-3 xl:grid-cols-2">
        <Card title="Alert rules" bodyClass="p-0">
          {alerts.data?.length === 0 ? (
            <div className="p-3">
              <Empty>No alerts yet.</Empty>
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Rule</th>
                  <th>Channels</th>
                  <th>Last fired</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(alerts.data ?? []).map((alert) => (
                  <tr key={alert.id} className={alert.enabled ? "" : "opacity-50"}>
                    <td>{alert.name}</td>
                    <td className="text-[11px]">
                      <span className="font-mono">{alert.rule.symbol}</span> {RULE_TYPES[alert.rule.type] ?? alert.rule.type} {alert.rule.value ?? alert.rule.label ?? (alert.rule.event_kind ? humanize(alert.rule.event_kind) : "")}
                      {alert.rule.timeframe ? ` · ${alert.rule.timeframe}` : ""} · cooldown {alert.cooldown_seconds}s
                    </td>
                    <td className="text-[11px] text-muted">{alert.channels.join(", ")}</td>
                    <td className="text-muted">{alert.last_triggered_at ? istTime(alert.last_triggered_at, { date: true }) : "never"}</td>
                    <td className="whitespace-nowrap">
                      <Button variant="ghost" onClick={() => void toggle(alert)}>
                        {alert.enabled ? "Disable" : "Enable"}
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
        <Card title="Alert log" bodyClass="max-h-[520px] overflow-y-auto p-0">
          {events.data?.length === 0 ? (
            <div className="p-3">
              <Empty>No alerts fired yet.</Empty>
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Message</th>
                  <th>Delivery</th>
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
                            {channel}
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
