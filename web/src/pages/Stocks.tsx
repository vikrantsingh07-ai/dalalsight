import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { Help } from "../components/InfoTip";
import { post } from "../lib/api";
import { compact, humanize, istTime, num, pct } from "../lib/format";
import { useApi, useLocalState } from "../lib/hooks";
import { moodOf, strengthOf, verdictFor } from "../lib/plain";
import { isUnavailable, type InstrumentMeta, type Levels, type Quote, type Regime, type Signal, type TechEvent, type Unavailable } from "../lib/types";
import { TEXT_TONES, toneForNumber } from "../lib/tones";
import { Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Pill, Select, Spinner, Stat, Table, Tabs, UnavailableNote } from "../components/ui";

interface ScoreComponent {
  name: string;
  weight: number;
  available: boolean;
  score: number | null;
  criteria: { label: string; passed: boolean | null }[];
}

interface MiniSignal {
  signal: Signal;
  regime: Regime;
  levels: Levels;
  events: TechEvent[];
}

interface StockAnalysis {
  symbol: string;
  meta: InstrumentMeta;
  quote: Quote | Unavailable;
  metrics: Record<string, number | string | boolean | null>;
  score: { total: number | null; rating: string; components: ScoreComponent[]; coverage?: number; missing?: string[]; method?: string; note: string };
  fundamentals: { status: string; values?: Record<string, number | string | null>; missing?: string[]; source: string; fetched_at?: string; reason?: string };
  daily_source: string;
  presets_matched: string[];
  signal_1D: MiniSignal | Unavailable;
  signal_1h: MiniSignal | Unavailable;
  beta_vs_nifty: { beta: number; correlation: number; r_squared: number; observations: number; basis: string } | null;
}

interface ScanRow {
  symbol: string;
  close: number;
  change_pct: number | null;
  ret_20d: number | null;
  rs_20: number | null;
  rsi: number | null;
  adx: number | null;
  vol_ratio: number | null;
  atr_pct: number | null;
  dist_52w_high_pct: number;
  avg_traded_value_cr: number | null;
  technical_score: number | null;
  rating: string;
  last_date: string;
}

interface ScanResult {
  universe: string;
  preset: string | null;
  preset_definition: string | null;
  scanned: number;
  matched: number;
  results: ScanRow[];
  unavailable: { symbol: string; reason: string }[];
  note: string;
  generated_at: string;
}

const percent100 = (v: number) => `${num(v * 100, 1)}%`;
const FUNDAMENTALS: [string, string, (value: number) => string][] = [
  ["marketCap", "Company size (market cap)", (v) => `₹${compact(v)}`],
  ["trailingPE", "P/E: price vs last year's profit", (v) => num(v, 1)],
  ["forwardPE", "P/E vs expected profit", (v) => num(v, 1)],
  ["priceToBook", "Price vs book value", (v) => num(v, 2)],
  ["returnOnEquity", "Profit on owners' money (ROE)", percent100],
  ["returnOnAssets", "Profit on all assets (ROA)", percent100],
  ["debtToEquity", "Borrowing vs owners' money", (v) => num(v / 100, 2)],
  ["revenueGrowth", "Sales growth (latest)", percent100],
  ["earningsGrowth", "Profit growth (latest)", percent100],
  ["profitMargins", "Net profit margin", percent100],
  ["operatingMargins", "Operating margin", percent100],
  ["dividendYield", "Dividend yield (as reported)", (v) => num(v, 2)],
  ["trailingEps", "Profit per share (EPS)", (v) => num(v, 2)],
  ["bookValue", "Book value per share", (v) => num(v, 2)],
  ["beta", "Beta (from vendor)", (v) => num(v, 2)],
];

const HEALTH_TONE = (total: number | null) => (total === null ? "muted" : total >= 55 ? "bull" : total >= 45 ? "info" : "bear");

export default function Stocks() {
  const { symbol, config } = useApp();
  const [tab, setTab] = useLocalState<"analysis" | "scanner">("cc_stocks_tab", "analysis");
  const [stock, setStock] = useLocalState("cc_stock_symbol", "RELIANCE");
  const indices = config?.indices ?? {};
  return (
    <div className="space-y-3">
      <PageHeader
        title="Stocks"
        subtitle="Check one stock's health, or scan a list of stocks to find the strong ones."
        info="Scores are rule-based and use daily prices. Company numbers (fundamentals) come from the data vendor and show as unavailable when not published."
      >
        <Tabs
          tabs={[
            { id: "analysis", label: "Check a stock" },
            { id: "scanner", label: "Find stocks" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </PageHeader>
      {tab === "analysis" ? (
        <StockAnalysisView symbol={stock} onSymbol={setStock} suggestion={!indices[symbol] ? symbol : undefined} />
      ) : (
        <ScannerView
          onOpen={(value) => {
            setStock(value);
            setTab("analysis");
          }}
        />
      )}
    </div>
  );
}

function StockAnalysisView({ symbol, onSymbol, suggestion }: { symbol: string; onSymbol: (symbol: string) => void; suggestion?: string }) {
  const { setSymbol } = useApp();
  const navigate = useNavigate();
  const [input, setInput] = useState(symbol);
  const analysis = useApi<StockAnalysis>(`/api/stocks/${symbol}`);
  const data = analysis.data?.symbol === symbol ? analysis.data : null;
  const quote = data && !isUnavailable(data.quote) ? data.quote : null;

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (input.trim()) onSymbol(input.trim().toUpperCase());
        }}
      >
        <Field label="NSE stock symbol" hint="For example RELIANCE, TCS or HDFCBANK">
          <Input id="stock-symbol" value={input} onChange={(event) => setInput(event.target.value.toUpperCase())} className="w-44 font-mono" />
        </Field>
        <Button type="submit" variant="primary">
          Check stock
        </Button>
        {suggestion && suggestion !== symbol && (
          <Button
            onClick={() => {
              setInput(suggestion);
              onSymbol(suggestion);
            }}
          >
            Use {suggestion} from Home
          </Button>
        )}
        {analysis.loading && <Spinner label="Loading stock data" />}
      </form>
      <ErrorNote error={analysis.error} />
      {data && (
        <>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="font-display text-lg font-semibold">
                  {data.meta.name} <span className="font-mono text-sm text-muted">{data.symbol}</span>
                </div>
                <div className="text-xs text-muted">
                  {data.meta.sector ?? (data.fundamentals.values?.industry as string | undefined) ?? "Sector not known"} · {data.meta.lot_size ? `F&O lot size ${data.meta.lot_size}` : "not traded in F&O"}
                </div>
              </div>
              {quote && (
                <div className="text-right">
                  <div className="font-mono text-xl">{num(quote.price)}</div>
                  <div className={`font-mono text-xs ${TEXT_TONES[toneForNumber(quote.change)]}`}>
                    {num(quote.change)} ({pct(quote.change_pct)}) · {istTime(quote.timestamp, { date: true })}
                  </div>
                </div>
              )}
              <Button
                onClick={() => {
                  setSymbol(data.symbol);
                  navigate("/");
                }}
              >
                Open chart on Home
              </Button>
            </div>
            {data.presets_matched.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1 text-xs text-muted">
                Matches:
                {data.presets_matched.map((preset) => (
                  <Pill key={preset} tone="info">
                    {humanize(preset)}
                  </Pill>
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-3 xl:grid-cols-3">
            <Card title="Stock health score" info={<Help topic="healthScore" />} className="xl:col-span-2">
              <div className="flex flex-wrap items-center gap-3">
                <div className={`font-display text-3xl font-semibold ${TEXT_TONES[HEALTH_TONE(data.score.total)]}`}>{data.score.total === null ? "—" : num(data.score.total, 0)}</div>
                <div>
                  <Pill tone={HEALTH_TONE(data.score.total)}>{data.score.rating}</Pill>
                  <div className="mt-0.5 text-xs text-muted">out of 100 · based on {num((data.score.coverage ?? 0) * 100, 0)}% of the checks</div>
                </div>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {data.score.components.map((component) => (
                  <div key={component.name} className="rounded border border-edge bg-bg/40 p-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium">{humanize(component.name)}</span>
                      <span className="font-mono">{component.available ? `${num(component.score, 0)}/100` : "no data"}</span>
                    </div>
                    <ul className="mt-1 space-y-0.5 text-[11px]">
                      {component.criteria.map((criterion) => (
                        <li key={criterion.label} className={criterion.passed === null ? "text-muted" : criterion.passed ? "text-bull" : "text-bear"}>
                          {criterion.passed === null ? "○" : criterion.passed ? "✓" : "✗"} {criterion.label}
                          {criterion.passed === null && " (no data)"}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-muted">✓ passed · ✗ failed · ○ no data. {data.score.note}</p>
            </Card>

            <Card title="Company numbers" info={<Help topic="fundamentals" align="right" />}>
              {data.fundamentals.status !== "ok" ? (
                <UnavailableNote info={{ what: "Company numbers", reason: data.fundamentals.reason ?? "the data vendor returned nothing", source: data.fundamentals.source }} />
              ) : (
                <>
                  <Table>
                    <tbody>
                      {FUNDAMENTALS.map(([key, label, format]) => {
                        const value = data.fundamentals.values?.[key];
                        return (
                          <tr key={key}>
                            <td className="text-muted">{label}</td>
                            <td className="text-right font-mono">{typeof value === "number" ? format(value) : <span className="text-warn">not published</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                  <p className="mt-2 text-[11px] text-muted">
                    {data.fundamentals.source} · fetched {istTime(data.fundamentals.fetched_at, { date: true })}
                  </p>
                </>
              )}
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-3">
            <Card title="Recent performance" info={<Help topic="performance" />}>
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Last 20 days" value={pct(data.metrics.ret_20d as number | null)} tone={toneForNumber(data.metrics.ret_20d as number | null)} />
                <Stat label="Last 60 days" value={pct(data.metrics.ret_60d as number | null)} tone={toneForNumber(data.metrics.ret_60d as number | null)} />
                <Stat label="vs NIFTY, 20 days" value={pct(data.metrics.rs_20 as number | null)} tone={toneForNumber(data.metrics.rs_20 as number | null)} />
                <Stat label="vs NIFTY, 60 days" value={pct(data.metrics.rs_60 as number | null)} tone={toneForNumber(data.metrics.rs_60 as number | null)} />
                <Stat label="RSI (momentum)" value={num(data.metrics.rsi as number | null, 0)} sub="70+ stretched · 30− weak" />
                <Stat label="Trend strength (ADX)" value={num(data.metrics.adx as number | null, 0)} sub="25+ strong trend" />
                <Stat label="Typical daily move" value={`${num(data.metrics.atr_pct as number | null, 2)}%`} />
                <Stat label="From 52-week high" value={pct(data.metrics.dist_52w_high_pct as number | null)} />
                <Stat label="Traded per day" value={data.metrics.avg_traded_value_cr === null ? "—" : `₹${num(data.metrics.avg_traded_value_cr as number, 1)} Cr`} />
                <Stat label="Moves vs NIFTY (beta)" value={num(data.beta_vs_nifty?.beta, 2)} sub={data.beta_vs_nifty ? `${data.beta_vs_nifty.observations} sessions` : "not enough history"} />
              </div>
            </Card>
            <MiniSignalCard title="Signal on daily candles" data={data.signal_1D} />
            <MiniSignalCard title="Signal on hourly candles" data={data.signal_1h} />
          </div>
        </>
      )}
    </div>
  );
}

function MiniSignalCard({ title, data }: { title: string; data: MiniSignal | Unavailable }) {
  if (isUnavailable(data)) {
    return (
      <Card title={title}>
        <UnavailableNote info={data} />
      </Card>
    );
  }
  const { signal, regime, levels } = data;
  const view = verdictFor(signal.label, signal.direction, signal.bullish_pct);
  const strength = strengthOf(signal.model_confidence);
  const mood = moodOf(regime.code, regime.direction);
  return (
    <Card title={title} info={<Help topic="signal" align="right" />}>
      <div className={`font-display text-lg font-semibold ${TEXT_TONES[view.tone]}`}>
        <span aria-hidden="true">{view.icon}</span> {view.title}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-text">{view.text}</p>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Stat label="Strength" value={`${strength.label} (${num(signal.model_confidence, 0)})`} tone={strength.tone} />
        <Stat label="Mood" value={mood.title || regime.label} tone={mood.tone} />
        <Stat label="Floor (support)" value={num(levels.nearest_support?.price)} tone="bull" />
        <Stat label="Ceiling (resistance)" value={num(levels.nearest_resistance?.price)} tone="bear" />
      </div>
    </Card>
  );
}

function ScannerView({ onOpen }: { onOpen: (symbol: string) => void }) {
  const { config } = useApp();
  const [universe, setUniverse] = useLocalState("cc_scan_universe", "NIFTY 50");
  const [preset, setPreset] = useLocalState("cc_scan_preset", "momentum");
  const [limit, setLimit] = useState(50);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const presets = config?.scanner_presets ?? {};

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await post<ScanResult>("/api/scanner/run", { universe, preset: preset || null, limit }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <Card title="Find stocks" info={<Help topic="scanner" />}>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Which stocks">
            <Select id="scan-universe" value={universe} onChange={(event) => setUniverse(event.target.value)} className="w-40">
              {(config?.universes ?? ["NIFTY 50"]).map((u) => (
                <option key={u} value={u}>
                  {u === "FNO" ? "F&O stocks" : u === "WATCHLIST" ? "My watchlist" : u}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Looking for">
            <Select id="scan-preset" value={preset} onChange={(event) => setPreset(event.target.value)} className="w-56">
              <option value="">Everything (best score first)</option>
              {Object.entries(presets).map(([key, info]) => (
                <option key={key} value={key}>
                  {info.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Show up to">
            <Input id="scan-limit" type="number" min={1} max={250} value={limit} onChange={(event) => setLimit(Number(event.target.value) || 50)} className="w-24" />
          </Field>
          <Button variant="primary" onClick={() => void run()} disabled={busy}>
            {busy ? "Searching…" : "Find stocks"}
          </Button>
          {busy && <Spinner label="Checking daily prices" />}
        </div>
        {preset && presets[preset] && <p className="mt-2 text-xs text-muted">What this looks for: {presets[preset].description}</p>}
      </Card>
      <ErrorNote error={error} />
      {result && (
        <Card
          title={`${result.matched} of ${result.scanned} stocks match · ${result.universe}${result.preset ? ` · ${humanize(result.preset)}` : ""}`}
          actions={<span className="text-[11px] text-muted">Click a stock to check it · {istTime(result.generated_at, { seconds: true })}</span>}
        >
          {result.results.length === 0 ? (
            <Empty>No stocks match right now. Try "Everything" or a bigger list.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Price</th>
                  <th>Today</th>
                  <th>20 days</th>
                  <th>vs NIFTY</th>
                  <th>RSI</th>
                  <th>Trend</th>
                  <th>Volume ×</th>
                  <th>Daily move</th>
                  <th>From 52w high</th>
                  <th>₹ Cr/day</th>
                  <th>Health</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => (
                  <tr key={row.symbol} className="cursor-pointer hover:bg-panel-2" onClick={() => onOpen(row.symbol)}>
                    <td className="font-mono text-accent">{row.symbol}</td>
                    <td className="font-mono">{num(row.close)}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(row.change_pct)]}`}>{pct(row.change_pct)}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(row.ret_20d)]}`}>{pct(row.ret_20d, 1)}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(row.rs_20)]}`}>{pct(row.rs_20, 1)}</td>
                    <td className="font-mono">{num(row.rsi, 0)}</td>
                    <td className="font-mono">{num(row.adx, 0)}</td>
                    <td className="font-mono">{num(row.vol_ratio, 2)}</td>
                    <td className="font-mono">{num(row.atr_pct, 2)}%</td>
                    <td className="font-mono">{pct(row.dist_52w_high_pct, 1)}</td>
                    <td className="font-mono">{num(row.avg_traded_value_cr, 0)}</td>
                    <td>
                      <span className={`font-mono ${TEXT_TONES[HEALTH_TONE(row.technical_score)]}`}>{num(row.technical_score, 0)}</span> <span className="text-muted">{row.rating}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <p className="mt-2 text-[11px] leading-relaxed text-muted">
            Today / 20 days: price change · vs NIFTY: better (+) or worse (−) than NIFTY over 20 days · RSI: momentum (70+ stretched, 30− weak) · Trend: ADX, 25+ is a strong trend · Volume ×: today's volume vs normal · Daily move: typical swing · Health: 0–100 score.
          </p>
          <p className="mt-1 text-[11px] text-muted">
            {result.note}
            {result.unavailable.length > 0 && ` No data for ${result.unavailable.length}: ${result.unavailable.map((u) => u.symbol).join(", ")}.`}
          </p>
        </Card>
      )}
    </div>
  );
}
