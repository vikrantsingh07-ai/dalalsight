import { useState } from "react";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { istTime, num } from "../lib/format";
import { useApi, useLocalState } from "../lib/hooks";
import type { OptionSummary, StrategyResult } from "../lib/types";
import { PayoffChart } from "../components/charts";
import { toneForLabel } from "../lib/tones";
import { Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Pill, Select, Spinner, Stat, Table, Tabs } from "../components/ui";

interface LegDraft {
  option_type: "CE" | "PE";
  side: 1 | -1;
  strike: number;
  lots: number;
}

interface Suggestions {
  symbol: string;
  expiry: string;
  timeframe: string;
  iv_context: { level: string; value: number | null; basis: string };
  signal_label: string;
  regime: string;
  suggestions: { key: string; name: string; risk: string; rationale: string; evaluation: StrategyResult | null; error?: string }[];
  note: string | null;
}

const money = (value: number | string) => (typeof value === "string" ? value : `₹${num(value, 0)}`);

export default function Strategies() {
  const { timeframe, config } = useApp();
  const [underlying, setUnderlying] = useLocalState("cc_strategy_symbol", "NIFTY");
  const [input, setInput] = useState(underlying);
  const [expiry, setExpiry] = useState("");
  const [mode, setMode] = useState<"template" | "custom">("template");
  const [template, setTemplate] = useLocalState("cc_strategy_template", "iron_condor");
  const [lots, setLots] = useState(1);
  const [width, setWidth] = useState("");
  const [legs, setLegs] = useState<LegDraft[]>([]);
  const [result, setResult] = useState<StrategyResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const expiries = useApi<string[]>(`/api/options/${underlying}/expiries`);
  const activeExpiry = expiry && expiries.data?.includes(expiry) ? expiry : (expiries.data?.[0] ?? "");
  const chain = useApi<OptionSummary>(activeExpiry ? `/api/options/${underlying}/chain?expiry=${activeExpiry}` : null);
  const suggestions = useApi<Suggestions>(activeExpiry && timeframe ? `/api/strategies/suggest?symbol=${underlying}&expiry=${activeExpiry}&timeframe=${timeframe}` : null);
  const templates = config?.strategy_templates ?? {};
  const strikes = chain.data?.symbol === underlying ? chain.data.table.map((row) => row.strike) : [];
  const atm = chain.data?.atm_strike ?? strikes[Math.floor(strikes.length / 2)] ?? 0;

  const load = (value: string) => {
    const next = value.trim().toUpperCase();
    if (!next) return;
    expiries.setData(null);
    chain.setData(null);
    suggestions.setData(null);
    setExpiry("");
    setLegs([]);
    setResult(null);
    setUnderlying(next);
    setInput(next);
  };

  async function build(templateKey?: string) {
    setBusy(true);
    setError(null);
    try {
      const body =
        mode === "custom" && !templateKey
          ? { symbol: underlying, expiry: activeExpiry, legs }
          : { symbol: underlying, expiry: activeExpiry, template: templateKey ?? template, lots, width_steps: width ? Number(width) : null };
      setResult(await post<StrategyResult>("/api/strategies/build", body));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const updateLeg = (index: number, patch: Partial<LegDraft>) => setLegs(legs.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)));

  return (
    <div className="space-y-3">
      <PageHeader
        title="Strategy builder"
        subtitle="Build an options strategy and see its possible profit and loss before trading."
        info="Each leg is priced from the live NSE option chain. Shows the payoff, breakeven prices, maximum profit and loss, an estimated probability of profit and net Greeks. Margin needs a broker API."
      />
      <Card>
        <div className="flex flex-wrap items-end gap-2">
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              load(input);
            }}
          >
            <Field label="Underlying">
              <Input value={input} onChange={(event) => setInput(event.target.value.toUpperCase())} className="w-36 font-mono" />
            </Field>
            <Button type="submit">Load</Button>
          </form>
          <Field label="Expiry">
            <Select value={activeExpiry} onChange={(event) => setExpiry(event.target.value)} className="w-36">
              {(expiries.data ?? []).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </Field>
          <Tabs
            tabs={[
              { id: "template", label: "Template" },
              { id: "custom", label: "Custom legs" },
            ]}
            value={mode}
            onChange={(value) => {
              setMode(value);
              if (value === "custom" && legs.length === 0 && atm) setLegs([{ option_type: "CE", side: 1, strike: atm, lots: 1 }]);
            }}
          />
          {mode === "template" ? (
            <>
              <Field label="Strategy">
                <Select value={template} onChange={(event) => setTemplate(event.target.value)} className="w-56">
                  {Object.entries(templates).map(([key, info]) => (
                    <option key={key} value={key}>
                      {info.name} · {info.view}
                      {info.risk === "unlimited" ? " · UNLIMITED RISK" : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Lots">
                <Input type="number" min={1} max={100} value={lots} onChange={(event) => setLots(Math.max(1, Number(event.target.value) || 1))} className="w-20" />
              </Field>
              <Field label="Width (strike steps)" hint={`default ${templates[template]?.default_width ?? "—"}`}>
                <Input type="number" min={1} max={40} value={width} placeholder="default" onChange={(event) => setWidth(event.target.value)} className="w-28" />
              </Field>
            </>
          ) : null}
          <Button variant="primary" onClick={() => void build()} disabled={busy || !activeExpiry || (mode === "custom" && legs.length === 0)}>
            {busy ? "Pricing…" : "Build & evaluate"}
          </Button>
        </div>
        {mode === "custom" && (
          <div className="mt-3 space-y-2">
            {legs.map((leg, index) => (
              <div key={index} className="flex flex-wrap items-end gap-2">
                <Field label="Action">
                  <Select value={leg.side} onChange={(event) => updateLeg(index, { side: Number(event.target.value) === 1 ? 1 : -1 })} className="w-24">
                    <option value={1}>BUY</option>
                    <option value={-1}>SELL</option>
                  </Select>
                </Field>
                <Field label="Type">
                  <Select value={leg.option_type} onChange={(event) => updateLeg(index, { option_type: event.target.value === "PE" ? "PE" : "CE" })} className="w-20">
                    <option value="CE">CE</option>
                    <option value="PE">PE</option>
                  </Select>
                </Field>
                <Field label="Strike">
                  <Select value={leg.strike} onChange={(event) => updateLeg(index, { strike: Number(event.target.value) })} className="w-28">
                    {strikes.map((strike) => (
                      <option key={strike} value={strike}>
                        {num(strike, 0)}
                        {strike === atm ? " (ATM)" : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Lots">
                  <Input type="number" min={1} max={100} value={leg.lots} onChange={(event) => updateLeg(index, { lots: Math.max(1, Number(event.target.value) || 1) })} className="w-20" />
                </Field>
                <Button variant="danger" onClick={() => setLegs(legs.filter((_, i) => i !== index))}>
                  Remove
                </Button>
              </div>
            ))}
            <Button onClick={() => setLegs([...legs, { option_type: "PE", side: 1, strike: atm, lots: 1 }])} disabled={legs.length >= 8 || !atm}>
              Add leg
            </Button>
          </div>
        )}
      </Card>
      <ErrorNote error={error ?? expiries.error} />

      <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0">
          {result ? (
            <StrategyView result={result} />
          ) : (
            <Card title="Payoff">
              <Empty>Choose a template or legs and press “Build & evaluate”.</Empty>
            </Card>
          )}
        </div>
        <Card title="Suggested for current conditions" actions={suggestions.data ? <Pill tone={toneForLabel(suggestions.data.signal_label)}>{suggestions.data.signal_label}</Pill> : undefined}>
          {suggestions.loading && !suggestions.data && <Spinner />}
          <ErrorNote error={suggestions.error} />
          {suggestions.data && (
            <div className="space-y-2">
              <div className="text-[11px] text-muted">
                Regime: {suggestions.data.regime} · IV {suggestions.data.iv_context.level} ({suggestions.data.iv_context.basis}) · timeframe {suggestions.data.timeframe}
              </div>
              {suggestions.data.suggestions.length === 0 && <Empty>{suggestions.data.note}</Empty>}
              {suggestions.data.suggestions.map((item) => (
                <div key={item.key} className="rounded border border-edge bg-bg/40 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{item.name}</span>
                    <Pill tone={item.risk === "unlimited" ? "bear" : "muted"}>{item.risk} risk</Pill>
                  </div>
                  <p className="mt-1 text-[11px] text-muted">{item.rationale}</p>
                  {item.evaluation ? (
                    <div className="mt-1 flex flex-wrap gap-x-3 text-[11px]">
                      <span>Max profit {money(item.evaluation.max_profit)}</span>
                      <span>Max loss {money(item.evaluation.max_loss)}</span>
                      <span>POP {item.evaluation.probability_of_profit === null ? "—" : `${num(item.evaluation.probability_of_profit, 1)}%`}</span>
                    </div>
                  ) : (
                    <div className="mt-1 text-[11px] text-warn">{item.error}</div>
                  )}
                  <Button
                    className="mt-2"
                    onClick={() => {
                      setMode("template");
                      setTemplate(item.key);
                      if (item.evaluation) setResult(item.evaluation);
                      else void build(item.key);
                    }}
                  >
                    Load
                  </Button>
                </div>
              ))}
              <p className="text-[10px] text-muted">Suggestions are rule-based on signal label, regime and IV level. Not investment advice.</p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function StrategyView({ result }: { result: StrategyResult }) {
  return (
    <Card title={`${result.name} · ${result.symbol} ${result.expiry}`} actions={<span className="text-[11px] text-muted">chain {istTime(result.chain_timestamp, { date: true })}</span>}>
      <PayoffChart prices={result.payoff.prices} expiry={result.payoff.expiry_pnl} t0={result.payoff.t0_pnl} spot={result.spot} breakevens={result.breakevens} />
      <div className="mt-1 flex gap-4 text-[11px] text-muted">
        <span>
          <span className="text-accent">━</span> P&amp;L at expiry
        </span>
        {result.payoff.t0_pnl && (
          <span>
            <span className="text-info">┅</span> P&amp;L today (Black-Scholes)
          </span>
        )}
        <span>● breakevens</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label={`Net ${result.premium_type}`} value={`₹${num(Math.abs(result.net_premium), 0)}`} tone={result.premium_type === "credit" ? "bull" : "warn"} />
        <Stat label="Max profit" value={money(result.max_profit)} tone="bull" />
        <Stat label="Max loss" value={money(result.max_loss)} tone="bear" />
        <Stat label="Reward : risk" value={result.reward_to_risk === null ? "—" : `${num(result.reward_to_risk, 2)} : 1`} />
        <Stat label="Breakevens" value={result.breakevens.map((b) => num(b, 0)).join(" / ") || "—"} />
        <Stat label="Probability of profit" value={result.probability_of_profit === null ? "—" : `${num(result.probability_of_profit, 1)}%`} sub="model estimate" />
        <Stat label="Days to expiry" value={num(result.days_to_expiry, 1)} sub={`lot ${result.lot_size}`} />
        <Stat label="Capital at risk" value={result.capital.capital_at_risk === null ? "unlimited" : `₹${num(result.capital.capital_at_risk, 0)}`} />
      </div>
      <p className="mt-2 text-[11px] text-muted">
        POP basis: {result.pop_basis}. Margin: {result.capital.margin}.
      </p>
      {result.net_greeks ? (
        <div className="mt-2 grid grid-cols-4 gap-2">
          <Stat label="Net delta (units)" value={num(result.net_greeks.delta, 1)} />
          <Stat label="Net gamma" value={num(result.net_greeks.gamma, 4)} />
          <Stat label="Theta ₹/day" value={num(result.net_greeks.theta, 0)} tone={result.net_greeks.theta >= 0 ? "bull" : "bear"} />
          <Stat label="Vega ₹/vol pt" value={num(result.net_greeks.vega, 0)} />
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-warn">{result.greeks_note}</p>
      )}
      <div className="mt-3">
        <Table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Option</th>
              <th>Lots</th>
              <th>Premium</th>
              <th>IV</th>
              <th>Price source</th>
            </tr>
          </thead>
          <tbody>
            {result.legs.map((leg, index) => (
              <tr key={index}>
                <td className={leg.side > 0 ? "text-bull" : "text-bear"}>{leg.action}</td>
                <td className="font-mono">
                  {num(leg.strike, 0)} {leg.option_type}
                </td>
                <td className="font-mono">{leg.lots}</td>
                <td className="font-mono">{num(leg.premium)}</td>
                <td className="font-mono">{leg.iv === null ? "—" : `${num(leg.iv * 100, 1)}%`}</td>
                <td className="text-muted">{leg.price_source}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      <p className="mt-2 text-[10px] text-muted">Data: {result.provider}. Simulated evaluation; not investment advice. Verify prices and margin with your broker.</p>
    </Card>
  );
}
