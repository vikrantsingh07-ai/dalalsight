import { useState } from "react";
import { post } from "../lib/api";
import { istTime, num, pct } from "../lib/format";
import { useLocalState } from "../lib/hooks";
import { TEXT_TONES, toneForNumber } from "../lib/tones";
import { Button, Card, ErrorNote, Field, Input, PageHeader, Select, Stat, Table, UnavailableNote } from "../components/ui";

interface PositionDraft {
  symbol: string;
  kind: "stock" | "future";
  quantity: string;
  avg_price: string;
}

interface HedgePosition {
  symbol: string;
  kind: string;
  quantity: number;
  avg_price: number | null;
  price: number;
  price_time: string;
  beta: number | null;
  beta_detail: { beta: number; correlation: number; r_squared: number; observations: number; basis: string } | null;
  value: number;
  beta_exposure: number | null;
  pnl: number | null;
}

interface FuturesHedge {
  action: string;
  lots: number;
  lot_size: number;
  notional: number;
  residual_exposure: number;
  hedge_ratio: number | null;
}

interface HedgeResult {
  positions: HedgePosition[];
  gross_value: number;
  net_value: number;
  beta_weighted_exposure: number;
  portfolio_beta: number | null;
  index: string;
  index_spot: number;
  index_units_equivalent: number;
  positions_without_beta: string[];
  assumptions: string[];
  futures_hedge: FuturesHedge | { status: string; reason: string };
  put_hedges?: { strike: number; moneyness_pct: number; premium: number; lots: number; cost: number; cost_pct_of_exposure: number; iv: number | null; oi: number | null; expiry: string }[];
  collar?: { put_strike: number; call_strike: number; lots: number; put_cost: number; call_credit: number; net_cost: number; expiry: string; note: string } | null;
  put_hedge_note?: string;
  scenarios?: { index_move_pct: number; index_level: number; unhedged: number; with_futures: number; with_puts?: number; with_collar?: number }[];
  generated_at: string;
}

const rupees = (value: number | null | undefined) => (value === null || value === undefined ? "—" : `₹${num(value, 0)}`);

export default function Hedging() {
  const [positions, setPositions] = useLocalState<PositionDraft[]>("cc_hedge_positions", [{ symbol: "RELIANCE", kind: "stock", quantity: "100", avg_price: "" }]);
  const [index, setIndex] = useLocalState<"NIFTY" | "BANKNIFTY">("cc_hedge_index", "NIFTY");
  const [result, setResult] = useState<HedgeResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const update = (i: number, patch: Partial<PositionDraft>) => setPositions(positions.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  async function analyse() {
    setBusy(true);
    setError(null);
    try {
      const body = {
        hedge_index: index,
        positions: positions
          .filter((p) => p.symbol.trim() && Number(p.quantity))
          .map((p) => ({ symbol: p.symbol.trim().toUpperCase(), kind: p.kind, quantity: Number(p.quantity), avg_price: p.avg_price ? Number(p.avg_price) : null })),
      };
      setResult(await post<HedgeResult>("/api/hedging/analyze", body));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const futures = result && "action" in result.futures_hedge ? result.futures_hedge : null;

  return (
    <div className="space-y-3">
      <PageHeader title="Portfolio hedging" subtitle="Beta-weighted exposure from one year of daily returns, index futures and protective-put/collar hedges priced from the live chain, and scenario P&L." />
      <Card title="Positions">
        <div className="space-y-2">
          {positions.map((position, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2">
              <Field label="Symbol">
                <Input value={position.symbol} onChange={(event) => update(i, { symbol: event.target.value.toUpperCase() })} className="w-36 font-mono" />
              </Field>
              <Field label="Type">
                <Select value={position.kind} onChange={(event) => update(i, { kind: event.target.value === "future" ? "future" : "stock" })} className="w-28">
                  <option value="stock">Stock</option>
                  <option value="future">Future</option>
                </Select>
              </Field>
              <Field label="Quantity (units, negative = short)">
                <Input type="number" value={position.quantity} onChange={(event) => update(i, { quantity: event.target.value })} className="w-40" />
              </Field>
              <Field label="Avg price (optional)">
                <Input type="number" value={position.avg_price} onChange={(event) => update(i, { avg_price: event.target.value })} className="w-32" />
              </Field>
              <Button variant="danger" onClick={() => setPositions(positions.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Button onClick={() => setPositions([...positions, { symbol: "", kind: "stock", quantity: "", avg_price: "" }])} disabled={positions.length >= 50}>
            Add position
          </Button>
          <Field label="Hedge index">
            <Select value={index} onChange={(event) => setIndex(event.target.value === "BANKNIFTY" ? "BANKNIFTY" : "NIFTY")} className="w-32">
              <option value="NIFTY">NIFTY</option>
              <option value="BANKNIFTY">BANKNIFTY</option>
            </Select>
          </Field>
          <Button variant="primary" onClick={() => void analyse()} disabled={busy}>
            {busy ? "Analysing…" : "Analyse hedge"}
          </Button>
        </div>
      </Card>
      <ErrorNote error={error} />

      {result && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <Stat label="Net value" value={rupees(result.net_value)} />
            <Stat label="Beta-weighted exposure" value={rupees(result.beta_weighted_exposure)} />
            <Stat label="Portfolio beta" value={num(result.portfolio_beta, 2)} />
            <Stat label={`${result.index} spot`} value={num(result.index_spot)} />
            <Stat label="Index units equivalent" value={num(result.index_units_equivalent, 1)} />
          </div>
          <Card title="Positions & betas">
            <Table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Value</th>
                  <th>Beta</th>
                  <th>R²</th>
                  <th>Beta exposure</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {result.positions.map((p) => (
                  <tr key={p.symbol}>
                    <td className="font-mono">{p.symbol}</td>
                    <td className="font-mono">{num(p.quantity, 0)}</td>
                    <td className="font-mono" title={istTime(p.price_time, { date: true })}>
                      {num(p.price)}
                    </td>
                    <td className="font-mono">{rupees(p.value)}</td>
                    <td className="font-mono">{p.beta === null ? <span className="text-warn">unavailable</span> : num(p.beta, 2)}</td>
                    <td className="font-mono">{num(p.beta_detail?.r_squared, 2)}</td>
                    <td className="font-mono">{rupees(p.beta_exposure)}</td>
                    <td className={`font-mono ${TEXT_TONES[toneForNumber(p.pnl)]}`}>{rupees(p.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {result.positions_without_beta.length > 0 && <p className="mt-2 text-[11px] text-warn">Excluded from beta exposure (insufficient history): {result.positions_without_beta.join(", ")}</p>}
          </Card>

          <div className="grid gap-3 lg:grid-cols-3">
            <Card title="Index futures hedge">
              {futures ? (
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Action" value={`${futures.action} ${futures.lots} lot(s)`} tone={futures.action === "SELL" ? "bear" : "bull"} />
                  <Stat label="Lot size" value={futures.lot_size} />
                  <Stat label="Notional" value={rupees(futures.notional)} />
                  <Stat label="Hedge ratio" value={num(futures.hedge_ratio, 2)} />
                  <Stat label="Residual exposure" value={rupees(futures.residual_exposure)} />
                </div>
              ) : (
                <UnavailableNote info={{ reason: "reason" in result.futures_hedge ? result.futures_hedge.reason : "unavailable" }} />
              )}
            </Card>
            <Card title="Protective puts">
              {result.put_hedges && result.put_hedges.length > 0 ? (
                <Table>
                  <thead>
                    <tr>
                      <th>Strike</th>
                      <th>% spot</th>
                      <th>Prem</th>
                      <th>Lots</th>
                      <th>Cost</th>
                      <th>% exp.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.put_hedges.map((put) => (
                      <tr key={put.strike}>
                        <td className="font-mono">{num(put.strike, 0)} PE</td>
                        <td className="font-mono">{num(put.moneyness_pct, 1)}</td>
                        <td className="font-mono">{num(put.premium)}</td>
                        <td className="font-mono">{put.lots}</td>
                        <td className="font-mono">{rupees(put.cost)}</td>
                        <td className="font-mono">{num(put.cost_pct_of_exposure, 2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <UnavailableNote info={{ reason: result.put_hedge_note ?? "no put hedge priced" }} />
              )}
              {result.put_hedges?.[0] && <p className="mt-2 text-[11px] text-muted">Expiry {result.put_hedges[0].expiry}</p>}
              {result.put_hedge_note && result.put_hedges && result.put_hedges.length > 0 && <p className="mt-1 text-[11px] text-warn">{result.put_hedge_note}</p>}
            </Card>
            <Card title="Collar">
              {result.collar ? (
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Buy put" value={`${num(result.collar.put_strike, 0)} PE`} />
                  <Stat label="Sell call" value={`${num(result.collar.call_strike, 0)} CE`} />
                  <Stat label="Put cost" value={rupees(result.collar.put_cost)} />
                  <Stat label="Call credit" value={rupees(result.collar.call_credit)} />
                  <Stat label="Net cost" value={rupees(result.collar.net_cost)} />
                  <Stat label="Lots" value={result.collar.lots} sub={result.collar.note} />
                </div>
              ) : (
                <UnavailableNote info={{ reason: "collar needs a priced put and an OTM call" }} />
              )}
            </Card>
          </div>

          {result.scenarios && (
            <Card title="Scenario P&L (index move → portfolio)">
              <Table>
                <thead>
                  <tr>
                    <th>Index move</th>
                    <th>Index level</th>
                    <th>Unhedged</th>
                    <th>With futures</th>
                    <th>With puts</th>
                    <th>With collar</th>
                  </tr>
                </thead>
                <tbody>
                  {result.scenarios.map((s) => (
                    <tr key={s.index_move_pct}>
                      <td className={`font-mono ${TEXT_TONES[toneForNumber(s.index_move_pct)]}`}>{pct(s.index_move_pct, 0)}</td>
                      <td className="font-mono">{num(s.index_level, 0)}</td>
                      {[s.unhedged, s.with_futures, s.with_puts, s.with_collar].map((value, i) => (
                        <td key={i} className={`font-mono ${TEXT_TONES[toneForNumber(value)]}`}>
                          {rupees(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          )}
          <Card title="Assumptions">
            <ul className="space-y-0.5 text-xs text-muted">
              {result.assumptions.map((a) => (
                <li key={a}>· {a}</li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-muted">Generated {istTime(result.generated_at, { date: true, seconds: true })}. Not investment advice.</p>
          </Card>
        </>
      )}
    </div>
  );
}
