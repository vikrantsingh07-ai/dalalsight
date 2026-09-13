import { useState } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { istTime, num, pct } from "../lib/format";
import { useApi, useEvents, useLocalState } from "../lib/hooks";
import type { BacktestRow, SignalRow } from "../lib/types";
import { LineSpark } from "../components/charts";
import { TEXT_TONES, toneForLabel, toneForNumber, toneForStatus } from "../lib/tones";
import { Button, Card, Checkbox, Empty, ErrorNote, Field, Input, Meter, PageHeader, Pill, Select, Stat, Table, Tabs } from "../components/ui";

type Tab = "signals" | "paper" | "backtest";

export default function Signals() {
  const [tab, setTab] = useLocalState<Tab>("cc_signals_tab", "signals");
  return (
    <div className="space-y-3">
      <PageHeader title="Signals, paper trading & backtests" subtitle="Every engine setup is recorded and evaluated against later bars. Paper trades fill at real quotes. Backtests replay the same engine without look-ahead.">
        <Tabs
          tabs={[
            { id: "signals", label: "Signal history" },
            { id: "paper", label: "Paper trading" },
            { id: "backtest", label: "Backtest" },
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
        title="Outcome statistics by label"
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
            Evaluate open signals now
          </Button>
        }
      >
        <ErrorNote error={error ?? stats.error} />
        {stats.data && Object.keys(stats.data.by_label).length === 0 ? (
          <Empty>No signals recorded yet. Setups are recorded by the market monitor during market hours.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Label</th>
                <th>Signals</th>
                <th>Open</th>
                <th>Closed</th>
                <th>Not triggered</th>
                <th>Evaluated</th>
                <th>Win rate</th>
                <th>Avg R</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.data?.by_label ?? {}).map(([label, s]) => (
                <tr key={label}>
                  <td>
                    <Pill tone={toneForLabel(label)}>{label}</Pill>
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
        {stats.data && <p className="mt-2 text-[11px] text-muted">{stats.data.note}</p>}
      </Card>
      <Card
        title="Recorded signals"
        actions={
          <Select value={status} onChange={(event) => setStatus(event.target.value as "" | "open" | "closed")} className="w-28">
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
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
                <th>Recorded</th>
                <th>Symbol</th>
                <th>Label</th>
                <th>Price</th>
                <th>Conf.</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>T1 / T2</th>
                <th>R:R</th>
                <th>Status</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {(signals.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td className="font-mono text-muted">{s.id}</td>
                  <td className="text-muted">{istTime(s.created_at, { date: true })}</td>
                  <td className="font-mono">
                    {s.symbol} {s.timeframe}
                  </td>
                  <td>
                    <Pill tone={toneForLabel(s.label)}>{s.label}</Pill>
                  </td>
                  <td className="font-mono">{num(s.price)}</td>
                  <td className="font-mono">{num(s.confidence, 0)}%</td>
                  <td className="font-mono">
                    {num(s.entry_low)}–{num(s.entry_high)}
                  </td>
                  <td className="font-mono">{num(s.stop)}</td>
                  <td className="font-mono">
                    {num(s.target1)} / {num(s.target2)}
                  </td>
                  <td className="font-mono">{num(s.rr, 2)}</td>
                  <td>
                    <Pill tone={s.status === "open" ? "info" : "muted"}>{s.status}</Pill>
                  </td>
                  <td className="font-mono">
                    {s.outcome?.status ?? "—"}
                    {s.outcome?.r_multiple !== undefined && <span className={TEXT_TONES[toneForNumber(s.outcome.r_multiple)]}> {num(s.outcome.r_multiple, 2)}R</span>}
                  </td>
                </tr>
              ))}
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
      setMessage(`PAPER fill: ${form.side} ${form.quantity} ${result.instrument} @ ${num(result.price)} (${result.price_source})`);
      positions.reload();
      orders.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-3">
      <Card title="Execution mode">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Pill tone={mode === "paper" ? "accent" : mode === "live" ? "bear" : "info"}>{mode}</Pill>
          {mode === "analysis" && (
            <span>
              Orders are refused in ANALYSIS mode. Switch to PAPER in <Link to="/settings" className="text-accent hover:underline">Settings</Link> to simulate fills at real quotes.
            </span>
          )}
          {mode === "paper" && <span>Simulated fills only. Nothing is sent to any broker.</span>}
          {mode === "live" && <span className="text-bear">LIVE mode is selected, but live execution is disabled and no broker adapter exists. Orders are refused.</span>}
        </div>
      </Card>
      <Card title="New paper order">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Symbol">
            <Input value={form.symbol} onChange={(event) => setForm({ ...form, symbol: event.target.value.toUpperCase() })} className="w-32 font-mono" />
          </Field>
          <Field label="Side">
            <Select value={form.side} onChange={(event) => setForm({ ...form, side: event.target.value })} className="w-24">
              <option>BUY</option>
              <option>SELL</option>
            </Select>
          </Field>
          <Field label="Quantity (units)">
            <Input type="number" min={1} value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} className="w-28" />
          </Field>
          <Field label="Instrument">
            <Select value={form.instrument_type} onChange={(event) => setForm({ ...form, instrument_type: event.target.value })} className="w-32">
              <option value="underlying">Underlying</option>
              <option value="option">Option</option>
            </Select>
          </Field>
          {form.instrument_type === "option" && (
            <>
              <Field label="Expiry">
                <Input type="date" value={form.expiry} onChange={(event) => setForm({ ...form, expiry: event.target.value })} className="w-40" />
              </Field>
              <Field label="Strike">
                <Input type="number" value={form.strike} onChange={(event) => setForm({ ...form, strike: event.target.value })} className="w-28" />
              </Field>
              <Field label="Type">
                <Select value={form.option_type} onChange={(event) => setForm({ ...form, option_type: event.target.value })} className="w-20">
                  <option>CE</option>
                  <option>PE</option>
                </Select>
              </Field>
            </>
          )}
          <Field label="Note">
            <Input value={form.note} maxLength={200} onChange={(event) => setForm({ ...form, note: event.target.value })} className="w-48" />
          </Field>
          <Button variant="primary" onClick={() => void place()}>
            Place paper order
          </Button>
        </div>
        <div className="mt-2 space-y-1">
          <ErrorNote error={error} />
          {message && <div className="text-xs text-bull">{message}</div>}
        </div>
      </Card>
      <Card title="Paper positions" bodyClass="p-0">
        {positions.data?.length === 0 ? (
          <div className="p-3">
            <Empty>No paper positions.</Empty>
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Qty</th>
                <th>Avg</th>
                <th>Mark</th>
                <th>Unrealised</th>
                <th>Realised</th>
                <th>Mark source</th>
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
      <Card title="Paper orders" bodyClass="p-0">
        <Table>
          <thead>
            <tr>
              <th>#</th>
              <th>Time</th>
              <th>Side</th>
              <th>Instrument</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Price source</th>
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
      <Card title="Backtest parameters">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Symbol">
            <Input value={params.symbol} onChange={(event) => setParams({ ...params, symbol: event.target.value.toUpperCase() })} className="w-28 font-mono" />
          </Field>
          <Field label="Timeframe">
            <Select value={params.timeframe} onChange={(event) => setParams({ ...params, timeframe: event.target.value })} className="w-24">
              {["5m", "15m", "30m", "1h", "4h", "1D"].map((tf) => (
                <option key={tf}>{tf}</option>
              ))}
            </Select>
          </Field>
          {(
            [
              ["bars", "Bars", 200, 3000, 1],
              ["window", "Window", 120, 600, 1],
              ["warmup", "Warm-up", 60, 500, 1],
              ["max_hold_bars", "Max hold", 1, 300, 1],
              ["slippage_bps", "Slippage bps", 0, 100, 0.5],
              ["cost_pct_per_side", "Cost %/side", 0, 1, 0.01],
              ["entry_window_bars", "Entry window (bars)", 1, 50, 1],
            ] as const
          ).map(([key, label, min, max, step]) => (
            <Field key={key} label={label}>
              <Input type="number" min={min} max={max} step={step} value={params[key]} onChange={(event) => setParams({ ...params, [key]: Number(event.target.value) })} className="w-24" />
            </Field>
          ))}
          <Field label="Exit target">
            <Select value={params.target} onChange={(event) => setParams({ ...params, target: event.target.value })} className="w-20">
              <option>T1</option>
              <option>T2</option>
            </Select>
          </Field>
          <Button variant="primary" onClick={() => void run()}>
            Run backtest
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-3">
          {SETUP_LABELS.map((label) => (
            <Checkbox
              key={label}
              label={label}
              checked={params.labels.includes(label)}
              onChange={(checked) => setParams({ ...params, labels: checked ? [...params.labels, label] : params.labels.filter((l) => l !== label) })}
            />
          ))}
          <Checkbox label="Square off intraday at session end" checked={params.square_off_intraday} onChange={(checked) => setParams({ ...params, square_off_intraday: checked })} />
        </div>
        <p className="mt-2 text-[11px] text-muted">Public intraday history is limited (Yahoo: 5m/15m ≈ 60 days, 1h ≈ 2 years); requested bars are capped by what the provider returns.</p>
        <ErrorNote error={error} />
      </Card>

      <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card title="Runs" bodyClass="max-h-[600px] overflow-y-auto p-2">
          {list.data?.length === 0 && <Empty>No backtests yet.</Empty>}
          <ul className="space-y-1">
            {(list.data ?? []).map((row) => (
              <li key={row.id}>
                <button type="button" onClick={() => setSelected(row.id)} className={`w-full rounded px-2 py-1.5 text-left text-xs ${row.id === selectedId ? "bg-panel-2" : "hover:bg-panel-2/60"}`}>
                  <div className="flex items-center justify-between">
                    <span>
                      <span className="font-mono">#{row.id}</span> {String(row.params.symbol)} {String(row.params.timeframe)}
                    </span>
                    <Pill tone={toneForStatus(row.status)}>{row.status}</Pill>
                  </div>
                  {row.status === "running" && <Meter value={progress[row.id] ?? 0} />}
                  {row.summary && (
                    <div className="mt-0.5 text-muted">
                      {row.summary.trades} trades · win {row.summary.win_rate ?? "—"}% · {num(row.summary.expectancy_r, 2)}R
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
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
                <Stat label="Trades" value={summary.trades} />
                <Stat label="Win rate" value={summary.win_rate === null ? "—" : `${num(summary.win_rate, 1)}%`} />
                <Stat label="Expectancy" value={`${num(summary.expectancy_r, 3)}R`} tone={toneForNumber(summary.expectancy_r)} />
                <Stat label="Total" value={`${num(summary.total_r, 2)}R`} tone={toneForNumber(summary.total_r)} />
                <Stat label="Profit factor" value={num(summary.profit_factor, 2)} />
                <Stat label="Max drawdown" value={`${num(summary.max_drawdown_r, 2)}R`} tone="bear" />
                <Stat label="Avg bars held" value={num(summary.avg_bars_held, 1)} />
                <Stat label="Unfilled / gapped" value={`${summary.entries_not_filled ?? 0} / ${summary.skipped_gap_entries}`} />
              </div>
              <Card title={`Equity curve (R) · ${summary.symbol} ${summary.timeframe} · ${istTime(summary.period.start, { date: true })} → ${istTime(summary.period.end, { date: true })}`}>
                {summary.equity_curve_r && summary.equity_curve_r.length > 1 ? <LineSpark values={summary.equity_curve_r} label="Cumulative R" /> : <Empty>No trades.</Empty>}
                <div className="mt-2 grid gap-3 text-[11px] md:grid-cols-3">
                  <div>
                    <div className="uppercase tracking-wide text-muted">Exit reasons</div>
                    {Object.entries(summary.exit_reasons).map(([reason, count]) => (
                      <div key={reason}>
                        {reason}: <span className="font-mono">{count}</span>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="uppercase tracking-wide text-muted">By label</div>
                    {Object.entries(summary.by_label).map(([label, s]) => (
                      <div key={label}>
                        {label}: {s.trades} · {num(s.win_rate, 0)}% · {num(s.avg_r, 2)}R
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="uppercase tracking-wide text-muted">Signal labels seen</div>
                    {Object.entries(summary.signal_label_counts).map(([label, count]) => (
                      <div key={label}>
                        {label}: <span className="font-mono">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
                  {summary.assumptions.map((a) => (
                    <li key={a}>· {a}</li>
                  ))}
                  {summary.data_source && <li>· data: {summary.data_source}</li>}
                </ul>
              </Card>
              <Card title="Trades" bodyClass="max-h-[420px] overflow-auto p-0">
                <Table>
                  <thead>
                    <tr>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>Label</th>
                      <th>Entry px</th>
                      <th>Exit px</th>
                      <th>Reason</th>
                      <th>Bars</th>
                      <th>R</th>
                      <th>P&amp;L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.data?.trades ?? []).map((t, i) => (
                      <tr key={i}>
                        <td className="text-muted">{istTime(t.entry_time, { date: true })}</td>
                        <td className="text-muted">{istTime(t.exit_time, { date: true })}</td>
                        <td>
                          <Pill tone={toneForLabel(t.label)}>{t.direction > 0 ? "long" : "short"}</Pill>
                        </td>
                        <td className="font-mono">{num(t.entry)}</td>
                        <td className="font-mono">{num(t.exit)}</td>
                        <td>{t.reason}</td>
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
