import { useState } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { istTime, num, pct } from "../lib/format";
import { useApi, useEvents, useLocalState } from "../lib/hooks";
import { plainLabel, strengthOf } from "../lib/plain";
import { TIMEFRAME_LABELS } from "../lib/timeframes";
import type { BacktestRow, SignalRow } from "../lib/types";
import CalibrationCard from "../components/CalibrationCard";
import { LineSpark } from "../components/charts";
import { Help } from "../components/InfoTip";
import { TEXT_TONES, toneForLabel, toneForNumber, toneForStatus } from "../lib/tones";
import { Button, Card, Checkbox, Empty, ErrorNote, Field, Input, Meter, PageHeader, Pill, Select, Stat, Table, Tabs } from "../components/ui";

type Tab = "signals" | "paper" | "backtest";

const OUTCOMES: Record<string, string> = {
  target2: "Target 2 reached",
  target1_then_stop: "Target 1, then stop loss",
  stopped: "Stop loss hit",
  expired: "Time ran out",
  expired_after_target1: "Target 1, then time ran out",
  not_triggered: "Never started",
  open: "Waiting",
  not_applicable: "—",
};

export default function Signals() {
  const [tab, setTab] = useLocalState<Tab>("cc_signals_tab", "signals");
  return (
    <div className="space-y-3">
      <PageHeader
        title="Practice & history"
        subtitle="See past signals and how they worked out, practise with pretend trades, and test the signals on old data."
        info="Every engine setup is recorded and checked against the candles that came after it. Practice (paper) trades fill at real prices. Tests replay the same engine on history without peeking at the future."
      >
        <Tabs
          tabs={[
            { id: "signals", label: "Past signals" },
            { id: "paper", label: "Practice trades" },
            { id: "backtest", label: "Test on old data" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </PageHeader>
      {tab === "signals" && <SignalHistory />}
      {tab === "paper" && <PaperTrading />}
      {tab === "backtest" && <Backtests />}
    </div>
  );
}

interface SignalStats {
  by_label: Record<string, { signals: number; open: number; closed: number; not_triggered: number; wins: number; win_rate: number | null; avg_r: number | null; evaluated: number }>;
  total: number;
  note: string;
}

function SignalHistory() {
  const [status, setStatus] = useState<"" | "open" | "closed">("");
  const signals = useApi<SignalRow[]>(`/api/signals?limit=300${status ? `&status=${status}` : ""}`, { interval: 60_000 });
  const stats = useApi<SignalStats>("/api/signals/stats", { interval: 60_000 });
  const [error, setError] = useState<unknown>(null);
  useEvents(["signal"], () => {
    signals.reload();
    stats.reload();
  });

  return (
    <div className="space-y-3">
      <Card
        title="How past signals worked out"
        info={<Help topic="pastSignals" />}
        actions={
          <Button
            onClick={() =>
              post("/api/signals/evaluate")
                .then(() => {
                  signals.reload();
                  stats.reload();
                })
                .catch(setError)
            }
          >
            Check open signals now
          </Button>
        }
      >
        <ErrorNote error={error ?? stats.error} />
        {stats.data && Object.keys(stats.data.by_label).length === 0 ? (
          <Empty>No signals yet. They are saved automatically while the market is open.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Signal</th>
                <th>Found</th>
                <th>Still open</th>
                <th>Finished</th>
                <th>Never started</th>
                <th>Checked</th>
                <th>Win rate</th>
                <th>Average R</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.data?.by_label ?? {}).map(([label, s]) => (
                <tr key={label}>
                  <td>
                    <Pill tone={toneForLabel(label)}>{plainLabel(label)}</Pill>
                  </td>
                  <td className="font-mono">{s.signals}</td>
                  <td className="font-mono">{s.open}</td>
                  <td className="font-mono">{s.closed}</td>
                  <td className="font-mono">{s.not_triggered}</td>
                  <td className="font-mono">{s.evaluated}</td>
                  <td className="font-mono">{s.win_rate === null ? "—" : `${num(s.win_rate, 1)}%`}</td>
                  <td className={`font-mono ${TEXT_TONES[toneForNumber(s.avg_r)]}`}>{num(s.avg_r, 2)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {stats.data && (
          <p className="mt-2 text-[11px] text-muted">
            Each signal is checked against the candles that came after it. If one candle touched both the stop loss and a target, the stop loss is counted first (the careful choice).
          </p>
        )}
      </Card>
      <Card
        title="All saved signals"
        actions={
          <Select id="signal-status" value={status} onChange={(event) => setStatus(event.target.value as "" | "open" | "closed")} className="w-32">
            <option value="">All</option>
            <option value="open">Still open</option>
            <option value="closed">Finished</option>
          </Select>
        }
        bodyClass="p-0"
      >
        <ErrorNote error={signals.error} />
        {signals.data?.length === 0 ? (
          <div className="p-3">
            <Empty>No signals.</Empty>
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>#</th>
                <th>Found at</th>
                <th>Market</th>
                <th>Signal</th>
                <th>Price</th>
                <th>Strength</th>
                <th>Buy/sell zone</th>
                <th>Stop loss</th>
                <th>Target 1 / 2</th>
                <th>Reward : risk</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {(signals.data ?? []).map((s) => {
                const strength = strengthOf(s.confidence);
                return (
                  <tr key={s.id}>
                    <td className="font-mono text-muted">{s.id}</td>
                    <td className="text-muted">{istTime(s.created_at, { date: true })}</td>
                    <td className="font-mono">
                      {s.symbol} <span className="text-muted">{TIMEFRAME_LABELS[s.timeframe] ?? s.timeframe}</span>
                    </td>
                    <td>
                      <Pill tone={toneForLabel(s.label)}>{plainLabel(s.label, s.direction)}</Pill>
                    </td>
                    <td className="font-mono">{num(s.price)}</td>
                    <td className={TEXT_TONES[strength.tone]}>{strength.label}</td>
                    <td className="font-mono">
                      {num(s.entry_low)}–{num(s.entry_high)}
                    </td>
                    <td className="font-mono">{num(s.stop)}</td>
                    <td className="font-mono">
                      {num(s.target1)} / {num(s.target2)}
                    </td>
                    <td className="font-mono">1 : {num(s.rr, 1)}</td>
                    <td>
                      <Pill tone={s.status === "open" ? "info" : "muted"}>{s.status === "open" ? "open" : "finished"}</Pill>
                    </td>
                    <td>
                      {s.outcome?.status ? (OUTCOMES[s.outcome.status] ?? s.outcome.status) : "—"}
                      {s.outcome?.r_multiple !== undefined && <span className={`font-mono ${TEXT_TONES[toneForNumber(s.outcome.r_multiple)]}`}> {num(s.outcome.r_multiple, 2)}R</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

interface PaperPosition {
  instrument: string;
  symbol: string;
  quantity: number;
  avg_price: number;
  realized_pnl: number;
  mark: number | null;
  mark_source: string | null;
  unrealized_pnl: number | null;
}

interface PaperOrder {
  id: number;
  ts: string;
  instrument: string;
  side: string;
  quantity: number;
  price: number;
  price_source: string;
  status: string;
  note: string | null;
}

function PaperTrading() {
  const { status, symbol } = useApp();
  const mode = status?.execution.mode ?? "analysis";
  const positions = useApi<PaperPosition[]>("/api/paper/positions", { interval: 30_000 });
  const orders = useApi<PaperOrder[]>("/api/paper/orders", { interval: 30_000 });
  const [form, setForm] = useState({ symbol: symbol || "NIFTY", side: "BUY", quantity: "1", instrument_type: "underlying", expiry: "", strike: "", option_type: "CE", note: "" });
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function place() {
    setError(null);
    setMessage(null);
    try {
      const body: Record<string, unknown> = { symbol: form.symbol, side: form.side, quantity: Number(form.quantity), instrument_type: form.instrument_type, note: form.note || null };
      if (form.instrument_type === "option") Object.assign(body, { expiry: form.expiry, strike: Number(form.strike), option_type: form.option_type });
      const result = await post<{ instrument: string; price: number; price_source: string }>("/api/paper/orders", body);
      setMessage(`Practice trade saved: ${form.side} ${form.quantity} ${result.instrument} at ${num(result.price)} (${result.price_source})`);
      positions.reload();
      orders.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-3">
      <Card title="Mode" info={<Help topic="practice" />}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Pill tone={mode === "paper" ? "accent" : mode === "live" ? "bear" : "info"}>{mode === "paper" ? "Practice mode" : mode === "live" ? "Live (blocked)" : "View only"}</Pill>
          {mode === "analysis" && (
            <span>
              Practice trades are switched off. Turn them on in{" "}
              <Link to="/settings" className="text-accent hover:underline">
                Settings
              </Link>{" "}
              (Execution mode → Paper trading).
            </span>
          )}
          {mode === "paper" && <span>Practice mode is on. Trades are pretend only; nothing is sent to any broker.</span>}
          {mode === "live" && <span className="text-bear">Live mode is selected, but live trading is switched off and no broker is connected, so orders are refused.</span>}
        </div>
      </Card>
      <Card title="New practice trade" info={<Help topic="practiceTrade" />}>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Stock or index">
            <Input id="paper-symbol" value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })} className="w-32 font-mono" />
          </Field>
          <Field label="Buy or sell">
            <Select id="paper-side" value={form.side} onChange={(event) => setForm({ ...form, side: event.target.value })} className="w-24">
              <option>BUY</option>
              <option>SELL</option>
            </Select>
          </Field>
          <Field label="Quantity">
            <Input id="paper-quantity" type="number" min={1} value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} className="w-28" />
          </Field>
          <Field label="What">
            <Select id="paper-instrument" value={form.instrument_type} onChange={(event) => setForm({ ...form, instrument_type: event.target.value })} className="w-36">
              <option value="underlying">The stock / index</option>
              <option value="option">An option</option>
            </Select>
          </Field>
          {form.instrument_type === "option" && (
            <>
              <Field label="Expiry">
                <Input id="paper-expiry" type="date" value={form.expiry} onChange={(event) => setForm({ ...form, expiry: event.target.value })} className="w-40" />
              </Field>
              <Field label="Strike price">
                <Input id="paper-strike" type="number" value={form.strike} onChange={(event) => setForm({ ...form, strike: event.target.value })} className="w-28" />
              </Field>
              <Field label="Call or put">
                <Select id="paper-option-type" value={form.option_type} onChange={(event) => setForm({ ...form, option_type: event.target.value })} className="w-28">
                  <option value="CE">CE (call)</option>
                  <option value="PE">PE (put)</option>
                </Select>
              </Field>
            </>
          )}
          <Field label="Note (optional)">
            <Input id="paper-note" value={form.note} maxLength={200} onChange={(event) => setForm({ ...form, note: event.target.value })} className="w-48" />
          </Field>
          <Button variant="primary" onClick={() => void place()} disabled={mode !== "paper"}>
            Save practice trade
          </Button>
        </div>
        <div className="mt-2 space-y-1">
          <ErrorNote error={error} />
          {message && <div className="text-xs text-bull">{message}</div>}
        </div>
      </Card>
      <Card title="My practice positions" bodyClass="p-0">
        {positions.data?.length === 0 ? (
          <div className="p-3">
            <Empty>No practice positions yet.</Empty>
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>What</th>
                <th>Quantity</th>
                <th>Average price</th>
                <th>Price now</th>
                <th>Open profit/loss</th>
                <th>Booked profit/loss</th>
                <th>Price from</th>
              </tr>
            </thead>
            <tbody>
              {(positions.data ?? []).map((p) => (
                <tr key={p.instrument}>
                  <td className="font-mono">{p.instrument}</td>
                  <td className="font-mono">{num(p.quantity, 0)}</td>
                  <td className="font-mono">{num(p.avg_price)}</td>
                  <td className="font-mono">{num(p.mark)}</td>
                  <td className={`font-mono ${TEXT_TONES[toneForNumber(p.unrealized_pnl)]}`}>{num(p.unrealized_pnl)}</td>
                  <td className={`font-mono ${TEXT_TONES[toneForNumber(p.realized_pnl)]}`}>{num(p.realized_pnl)}</td>
                  <td className="text-muted">{p.mark_source ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card title="Practice trade log" bodyClass="p-0">
        <Table>
          <thead>
            <tr>
              <th>#</th>
              <th>Time</th>
              <th>Buy/Sell</th>
              <th>What</th>
              <th>Quantity</th>
              <th>Price</th>
              <th>Price from</th>
            </tr>
          </thead>
          <tbody>
            {(orders.data ?? []).map((o) => (
              <tr key={o.id}>
                <td className="font-mono text-muted">{o.id}</td>
                <td className="text-muted">{istTime(o.ts, { date: true, seconds: true })}</td>
                <td className={o.side === "BUY" ? "text-bull" : "text-bear"}>{o.side}</td>
                <td className="font-mono">{o.instrument}</td>
                <td className="font-mono">{num(o.quantity, 0)}</td>
                <td className="font-mono">{num(o.price)}</td>
                <td className="text-muted">{o.price_source}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}

const SETUP_LABELS = ["BULLISH SETUP", "BEARISH SETUP", "HIGH-RISK SETUP", "LOW-QUALITY SETUP"];
const EXIT_REASONS: Record<string, string> = {
  stop: "Stop loss",
  "stop (gap)": "Stop loss (price jumped past it)",
  target: "Target",
  "target (gap)": "Target (price jumped past it)",
  "time exit": "Held too long",
  "session square-off": "Closed at day end",
  "end of data": "Test data ended",
};

function Backtests() {
  const [params, setParams] = useLocalState("cc_backtest_params", {
    symbol: "NIFTY",
    timeframe: "15m",
    bars: 1200,
    window: 300,
    warmup: 120,
    max_hold_bars: 30,
    slippage_bps: 2,
    cost_pct_per_side: 0.03,
    target: "T1",
    labels: ["BULLISH SETUP", "BEARISH SETUP"],
    square_off_intraday: true,
    entry_window_bars: 5,
  });
  const list = useApi<BacktestRow[]>("/api/backtest", { interval: 30_000 });
  const [selected, setSelected] = useState<number | null>(null);
  const [progress, setProgress] = useState<Record<number, number>>({});
  const [error, setError] = useState<unknown>(null);
  const selectedId = selected ?? list.data?.[0]?.id ?? null;
  const detail = useApi<BacktestRow>(selectedId ? `/api/backtest/${selectedId}` : null);

  useEvents(["backtest_progress", "backtest_done"], (message) => {
    const data = message.data as { id: number; progress?: number };
    if (message.type === "backtest_progress" && data.progress !== undefined) setProgress((p) => ({ ...p, [data.id]: data.progress ?? 0 }));
    else {
      list.reload();
      detail.reload();
    }
  });

  async function run() {
    setError(null);
    try {
      const response = await post<{ id: number }>("/api/backtest", params);
      setSelected(response.id);
      list.reload();
    } catch (err) {
      setError(err);
    }
  }

  const summary = detail.data?.summary;
  return (
    <div className="space-y-3">
      <Card title="Test the signals on old data" info={<Help topic="backtest" />}>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Stock or index">
            <Input id="backtest-symbol" value={params.symbol} onChange={(event) => setParams({ ...params, symbol: event.target.value.toUpperCase() })} className="w-32 font-mono" />
          </Field>
          <Field label="Candle size">
            <Select id="backtest-timeframe" value={params.timeframe} onChange={(event) => setParams({ ...params, timeframe: event.target.value })} className="w-28">
              {["5m", "15m", "30m", "1h", "4h", "1D"].map((tf) => (
                <option key={tf} value={tf}>
                  {TIMEFRAME_LABELS[tf]}
                </option>
              ))}
            </Select>
          </Field>
          <Button variant="primary" onClick={() => void run()}>
            Run test
          </Button>
        </div>
        <p className="mt-2 text-[11px] text-muted">Free data only goes back so far: about 60 days for 5 and 15 min candles, and about 2 years for 1 hour candles.</p>
        <details className="group mt-2 rounded border border-edge">
          <summary className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted hover:text-text">
            <span className="transition group-open:rotate-90">▸</span> More test settings
          </summary>
          <div className="border-t border-edge p-2.5">
            <div className="flex flex-wrap items-end gap-2">
              {(
                [
                  ["bars", "Candles to load", 200, 3000, 1],
                  ["window", "Candles per check", 120, 600, 1],
                  ["warmup", "Warm-up candles", 60, 500, 1],
                  ["max_hold_bars", "Max candles held", 1, 300, 1],
                  ["slippage_bps", "Slippage (bps)", 0, 100, 0.5],
                  ["cost_pct_per_side", "Cost % per side", 0, 1, 0.01],
                  ["entry_window_bars", "Candles to get filled", 1, 50, 1],
                ] as const
              ).map(([key, label, min, max, step]) => (
                <Field key={key} label={label}>
                  <Input id={`backtest-${key}`} type="number" min={min} max={max} step={step} value={params[key]} onChange={(event) => setParams({ ...params, [key]: Number(event.target.value) })} className="w-28" />
                </Field>
              ))}
              <Field label="Exit at">
                <Select id="backtest-target" value={params.target} onChange={(event) => setParams({ ...params, target: event.target.value })} className="w-28">
                  <option value="T1">Target 1</option>
                  <option value="T2">Target 2</option>
                </Select>
              </Field>
            </div>
            <div className="mt-2 flex flex-wrap gap-3">
              <span className="text-xs text-muted">Trade these signals:</span>
              {SETUP_LABELS.map((label) => (
                <Checkbox
                  key={label}
                  label={plainLabel(label)}
                  checked={params.labels.includes(label)}
                  onChange={(checked) => setParams({ ...params, labels: checked ? [...params.labels, label] : params.labels.filter((l) => l !== label) })}
                />
              ))}
              <Checkbox label="Close intraday trades at day end" checked={params.square_off_intraday} onChange={(checked) => setParams({ ...params, square_off_intraday: checked })} />
            </div>
          </div>
        </details>
        <ErrorNote error={error} />
      </Card>

      <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card title="Tests" bodyClass="max-h-[600px] overflow-y-auto p-2">
          {list.data?.length === 0 && <Empty>No tests yet.</Empty>}
          <ul className="space-y-1">
            {(list.data ?? []).map((row) => (
              <li key={row.id}>
                <button type="button" onClick={() => setSelected(row.id)} className={`w-full rounded px-2 py-1.5 text-left text-xs ${row.id === selectedId ? "bg-panel-2" : "hover:bg-panel-2/60"}`}>
                  <div className="flex items-center justify-between">
                    <span>
                      <span className="font-mono">#{row.id}</span> {String(row.params.symbol)} · {TIMEFRAME_LABELS[String(row.params.timeframe)] ?? String(row.params.timeframe)}
                    </span>
                    <Pill tone={toneForStatus(row.status)}>{row.status}</Pill>
                  </div>
                  {row.status === "running" && <Meter value={progress[row.id] ?? 0} />}
                  {row.summary && (
                    <div className="mt-0.5 text-muted">
                      {row.summary.trades} trades · {row.summary.win_rate ?? "—"}% won · {num(row.summary.expectancy_r, 2)}R each
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <div className="min-w-0 space-y-3">
          <ErrorNote error={detail.data?.error ?? detail.error} />
          {summary && (
            <>
              <div className="flex items-center gap-1.5 text-xs text-muted">
                What these numbers mean <Help topic="results" />
              </div>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
                <Stat label="Trades" value={summary.trades} />
                <Stat label="Won" value={summary.win_rate === null ? "—" : `${num(summary.win_rate, 1)}%`} />
                <Stat label="Average result" value={`${num(summary.expectancy_r, 2)}R`} tone={toneForNumber(summary.expectancy_r)} />
                <Stat label="Total result" value={`${num(summary.total_r, 2)}R`} tone={toneForNumber(summary.total_r)} />
                <Stat label="Profit factor" value={num(summary.profit_factor, 2)} />
                <Stat label="Worst drop" value={`${num(summary.max_drawdown_r, 2)}R`} tone="bear" />
                <Stat label="Avg candles held" value={num(summary.avg_bars_held, 1)} />
                <Stat label="Missed / jumped" value={`${summary.entries_not_filled ?? 0} / ${summary.skipped_gap_entries}`} />
              </div>
              <Card title={`Result over time (R) · ${summary.symbol} ${TIMEFRAME_LABELS[summary.timeframe] ?? summary.timeframe} · ${istTime(summary.period.start, { date: true })} → ${istTime(summary.period.end, { date: true })}`}>
                {summary.equity_curve_r && summary.equity_curve_r.length > 1 ? <LineSpark values={summary.equity_curve_r} label="Cumulative R" /> : <Empty>No trades.</Empty>}
                <div className="mt-2 grid gap-3 text-[11px] md:grid-cols-3">
                  <div>
                    <div className="uppercase tracking-wide text-muted">Why trades ended</div>
                    {Object.entries(summary.exit_reasons).map(([reason, count]) => (
                      <div key={reason}>
                        {EXIT_REASONS[reason] ?? reason}: <span className="font-mono">{count}</span>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="uppercase tracking-wide text-muted">By signal</div>
                    {Object.entries(summary.by_label).map(([label, s]) => (
                      <div key={label}>
                        {plainLabel(label)}: {s.trades} trades · {num(s.win_rate, 0)}% won · {num(s.avg_r, 2)}R
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="uppercase tracking-wide text-muted">Signal on each candle</div>
                    {Object.entries(summary.signal_label_counts).map(([label, count]) => (
                      <div key={label}>
                        {plainLabel(label)}: <span className="font-mono">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <details className="mt-2 text-[11px] text-muted">
                  <summary className="hover:text-text">How the test works ▾</summary>
                  <ul className="mt-1 space-y-0.5">
                    {summary.assumptions.map((a) => (
                      <li key={a}>· {a}</li>
                    ))}
                    {summary.data_source && <li>· data: {summary.data_source}</li>}
                  </ul>
                </details>
              </Card>
              {summary.calibration && <CalibrationCard calibration={summary.calibration} />}
              <Card title="Test trades" bodyClass="max-h-[420px] overflow-auto p-0">
                <Table>
                  <thead>
                    <tr>
                      <th>Entered</th>
                      <th>Exited</th>
                      <th>Side</th>
                      <th>Entry price</th>
                      <th>Exit price</th>
                      <th>Why it ended</th>
                      <th>Candles</th>
                      <th>Result (R)</th>
                      <th>P&amp;L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.data?.trades ?? []).map((t, i) => (
                      <tr key={i}>
                        <td className="text-muted">{istTime(t.entry_time, { date: true })}</td>
                        <td className="text-muted">{istTime(t.exit_time, { date: true })}</td>
                        <td>
                          <Pill tone={toneForLabel(t.label)}>{t.direction > 0 ? "BUY" : "SELL"}</Pill>
                        </td>
                        <td className="font-mono">{num(t.entry)}</td>
                        <td className="font-mono">{num(t.exit)}</td>
                        <td>{EXIT_REASONS[t.reason] ?? t.reason}</td>
                        <td className="font-mono">{t.bars_held}</td>
                        <td className={`font-mono ${TEXT_TONES[toneForNumber(t.r_multiple)]}`}>{num(t.r_multiple, 2)}</td>
                        <td className={`font-mono ${TEXT_TONES[toneForNumber(t.pnl_pct)]}`}>{pct(t.pnl_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
