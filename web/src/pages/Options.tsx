import { useState } from "react";
import { useApp } from "../context/AppContext";
import { compact, istTime, num } from "../lib/format";
import { useApi, useLocalState } from "../lib/hooks";
import type { OptionLegView, OptionSummary, Recommendations } from "../lib/types";
import { toneForLabel } from "../lib/tones";
import { Button, Card, Empty, ErrorNote, Field, Input, PageHeader, Pill, Select, Spinner, Stat, Table } from "../components/ui";

export default function OptionsPage() {
  const { symbol, timeframe, config } = useApp();
  const [underlying, setUnderlying] = useLocalState("cc_options_symbol", "NIFTY");
  const [input, setInput] = useState(underlying);
  const [expiry, setExpiry] = useState("");
  const expiries = useApi<string[]>(`/api/options/${underlying}/expiries`);
  const activeExpiry = expiry && expiries.data?.includes(expiry) ? expiry : (expiries.data?.[0] ?? "");
  const chain = useApi<OptionSummary>(activeExpiry ? `/api/options/${underlying}/chain?expiry=${activeExpiry}` : null, { interval: 90_000 });
  const recs = useApi<Recommendations>(activeExpiry && timeframe ? `/api/options/${underlying}/recommendations?expiry=${activeExpiry}&timeframe=${timeframe}` : null);
  const indexOptions = Object.entries(config?.indices ?? {})
    .filter(([, info]) => info.options)
    .map(([key]) => key);

  const choose = (value: string) => {
    const next = value.trim().toUpperCase();
    if (!next) return;
    expiries.setData(null);
    chain.setData(null);
    recs.setData(null);
    setExpiry("");
    setUnderlying(next);
    setInput(next);
  };

  const data = chain.data?.symbol === underlying && chain.data.expiry === activeExpiry ? chain.data : null;

  return (
    <div className="space-y-3">
      <PageHeader title="Options chain & analytics" subtitle="Live NSE option chain: OI, volume, bid/ask and IV from the exchange; Greeks via Black-Scholes. Recommendations only when the signal engine has a setup.">
        {(chain.loading || expiries.loading) && <Spinner label="Loading chain" />}
      </PageHeader>
      <Card>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            choose(input);
          }}
        >
          <Field label="Underlying (index or F&O stock)">
            <Input value={input} onChange={(event) => setInput(event.target.value.toUpperCase())} className="w-40 font-mono" />
          </Field>
          <Button type="submit" variant="primary">
            Load
          </Button>
          {indexOptions.map((key) => (
            <Button key={key} variant={key === underlying ? "primary" : "ghost"} onClick={() => choose(key)}>
              {key}
            </Button>
          ))}
          {symbol !== underlying && (
            <Button variant="ghost" onClick={() => choose(symbol)}>
              Dashboard: {symbol}
            </Button>
          )}
          <Field label="Expiry">
            <Select value={activeExpiry} onChange={(event) => setExpiry(event.target.value)} className="w-40" disabled={!expiries.data}>
              {(expiries.data ?? []).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </Field>
          <Button onClick={chain.reload}>Refresh</Button>
        </form>
      </Card>
      <ErrorNote error={expiries.error ?? chain.error} />

      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
            <Stat label="Spot" value={num(data.spot)} sub={`ATM ${num(data.atm_strike, 0)}`} />
            <Stat label="ATM IV" value={data.atm_iv === null ? "—" : `${num(data.atm_iv, 2)}%`} sub={data.iv_percentile ? `IV pctile ${num(data.iv_percentile.value, 0)}` : "IV pctile: history building"} />
            <Stat label="ATM straddle" value={num(data.atm_straddle)} sub={`${num(data.days_to_expiry, 1)} days to expiry`} />
            <Stat label="1σ expected range" value={data.expected_range ? `${num(data.expected_range[0], 0)}–${num(data.expected_range[1], 0)}` : "—"} sub={`±${num(data.expected_move_1sd, 0)}`} />
            <Stat label="PCR OI / volume" value={`${num(data.pcr_oi, 2)} / ${num(data.pcr_volume, 2)}`} />
            <Stat label="Max pain" value={num(data.max_pain, 0)} />
            <Stat label="Call wall" value={num(data.call_wall, 0)} tone="bear" sub="highest call OI ≥ spot" />
            <Stat label="Put wall" value={num(data.put_wall, 0)} tone="bull" sub="highest put OI ≤ spot" />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
            <span>
              {data.provider} · chain time {istTime(data.timestamp, { date: true, seconds: true })} · lot {data.lot_size ?? "unknown"} · r = {num(data.risk_free_rate * 100, 2)}%
            </span>
            {data.stale && <Pill tone="warn">stale</Pill>}
            {data.iv_skew && (
              <span>
                IV skew {num(data.iv_skew.skew_vol_points, 2)} vol pts ({data.iv_skew.put_strike} PE {num(data.iv_skew.put_iv, 1)}% vs {data.iv_skew.call_strike} CE {num(data.iv_skew.call_iv, 1)}%)
              </span>
            )}
          </div>

          <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_400px]">
            <Card title={`Option chain · ${data.symbol} ${data.expiry}`} bodyClass="p-0">
              <ChainTable data={data} />
            </Card>
            <div className="space-y-3">
              <Card title="Positioning read">
                <ul className="space-y-1 text-xs">
                  {data.interpretation.map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
                <div className="mt-3 grid grid-cols-2 gap-3 text-[11px]">
                  <OiList title="Top call OI" rows={data.top_call_oi} tone="text-bear" />
                  <OiList title="Top put OI" rows={data.top_put_oi} tone="text-bull" />
                  <OiList title="Call OI added" rows={data.top_call_oi_added} tone="text-bear" change />
                  <OiList title="Put OI added" rows={data.top_put_oi_added} tone="text-bull" change />
                </div>
              </Card>
              <RecommendationCard recs={recs.data} error={recs.error} loading={recs.loading} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function OiList({ title, rows, tone, change = false }: { title: string; rows: { strike: number; oi: number | null; oi_change: number | null }[]; tone: string; change?: boolean }) {
  return (
    <div>
      <div className="uppercase tracking-wide text-muted">{title}</div>
      {rows.length === 0 ? (
        <div className="text-muted">—</div>
      ) : (
        rows.map((row) => (
          <div key={row.strike} className="flex justify-between font-mono">
            <span className={tone}>{num(row.strike, 0)}</span>
            <span>{change ? `+${compact(row.oi_change)}` : compact(row.oi)}</span>
          </div>
        ))
      )}
    </div>
  );
}

function ChainTable({ data }: { data: OptionSummary }) {
  const maxOi = Math.max(1, ...data.table.flatMap((row) => [row.ce?.oi ?? 0, row.pe?.oi ?? 0]));
  const cell = (leg: OptionLegView | null, key: keyof OptionLegView, digits = 2) => {
    const value = leg?.[key];
    return typeof value === "number" ? num(value, digits) : "—";
  };
  return (
    <div className="max-h-[680px] overflow-auto">
      <table className="w-full border-collapse font-mono text-[11px]">
        <thead className="sticky top-0 z-10 bg-panel-2 text-muted">
          <tr>
            <th colSpan={7} className="border-b border-edge py-1 text-bear">
              CALLS
            </th>
            <th className="border-b border-edge py-1">STRIKE</th>
            <th colSpan={7} className="border-b border-edge py-1 text-bull">
              PUTS
            </th>
          </tr>
          <tr className="[&_th]:px-1.5 [&_th]:py-1 [&_th]:font-normal">
            <th>OI</th>
            <th>ΔOI</th>
            <th>Vol</th>
            <th>IV</th>
            <th>LTP</th>
            <th>Bid/Ask</th>
            <th>Δ</th>
            <th />
            <th>Δ</th>
            <th>Bid/Ask</th>
            <th>LTP</th>
            <th>IV</th>
            <th>Vol</th>
            <th>ΔOI</th>
            <th>OI</th>
          </tr>
        </thead>
        <tbody className="[&_td]:border-t [&_td]:border-edge/50 [&_td]:px-1.5 [&_td]:py-1 [&_td]:text-right">
          {data.table.map((row) => {
            const atm = row.strike === data.atm_strike;
            const ceItm = row.strike < data.spot;
            const peItm = row.strike > data.spot;
            return (
              <tr key={row.strike} className={atm ? "bg-accent/10" : ""}>
                <td className={`relative ${ceItm ? "bg-bear/5" : ""}`} title={row.ce?.buildup ?? undefined}>
                  <div className="absolute inset-y-1 right-0 bg-bear/25" style={{ width: `${((row.ce?.oi ?? 0) / maxOi) * 100}%` }} />
                  <span className="relative">{compact(row.ce?.oi)}</span>
                </td>
                <td className={`${ceItm ? "bg-bear/5" : ""} ${(row.ce?.oi_change ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{compact(row.ce?.oi_change)}</td>
                <td className={ceItm ? "bg-bear/5" : ""}>{compact(row.ce?.volume)}</td>
                <td className={ceItm ? "bg-bear/5" : ""} title={row.ce?.iv_source ?? undefined}>
                  {cell(row.ce, "iv", 1)}
                </td>
                <td className={`text-text ${ceItm ? "bg-bear/5" : ""}`}>{cell(row.ce, "ltp")}</td>
                <td className={`text-muted ${ceItm ? "bg-bear/5" : ""}`}>
                  {cell(row.ce, "bid")}/{cell(row.ce, "ask")}
                </td>
                <td className={ceItm ? "bg-bear/5" : ""}>{cell(row.ce, "delta")}</td>
                <td className={`text-center font-semibold ${atm ? "text-accent" : "text-text"}`}>{num(row.strike, 0)}</td>
                <td className={peItm ? "bg-bull/5" : ""}>{cell(row.pe, "delta")}</td>
                <td className={`text-muted ${peItm ? "bg-bull/5" : ""}`}>
                  {cell(row.pe, "bid")}/{cell(row.pe, "ask")}
                </td>
                <td className={`text-text ${peItm ? "bg-bull/5" : ""}`}>{cell(row.pe, "ltp")}</td>
                <td className={peItm ? "bg-bull/5" : ""} title={row.pe?.iv_source ?? undefined}>
                  {cell(row.pe, "iv", 1)}
                </td>
                <td className={peItm ? "bg-bull/5" : ""}>{compact(row.pe?.volume)}</td>
                <td className={`${peItm ? "bg-bull/5" : ""} ${(row.pe?.oi_change ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{compact(row.pe?.oi_change)}</td>
                <td className={`relative ${peItm ? "bg-bull/5" : ""}`} title={row.pe?.buildup ?? undefined}>
                  <div className="absolute inset-y-1 left-0 bg-bull/25" style={{ width: `${((row.pe?.oi ?? 0) / maxOi) * 100}%` }} />
                  <span className="relative">{compact(row.pe?.oi)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[10px] text-muted">Shaded cells are in the money. Hover OI for build-up (price change × OI change) and IV for its source.</p>
    </div>
  );
}

function RecommendationCard({ recs, error, loading }: { recs: Recommendations | null; error: unknown; loading: boolean }) {
  return (
    <Card title="Contract selection" actions={recs ? <Pill tone={toneForLabel(recs.signal.label)}>{recs.signal.label}</Pill> : undefined}>
      {loading && !recs && <Spinner />}
      <ErrorNote error={error} />
      {recs && (
        <div className="space-y-2">
          <div className="text-[11px] text-muted">
            Signal ({recs.timeframe}): bullish scenario {num(recs.signal.bullish_pct, 1)}%, model confidence {num(recs.signal.model_confidence, 1)}% · risk budget ₹{num(recs.risk_capital, 0)}
          </div>
          {recs.candidates.length === 0 ? (
            <Empty>{recs.note ?? "No strike passes the delta, liquidity and spread filters."}</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Strike</th>
                  <th>Prem</th>
                  <th>Δ</th>
                  <th>IV</th>
                  <th>θ/lot/day</th>
                  <th>B/E</th>
                  <th>Lots</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {recs.candidates.map((c) => (
                  <tr key={c.strike}>
                    <td className="font-mono">
                      {num(c.strike, 0)} {c.option_type}
                    </td>
                    <td className="font-mono">{num(c.premium)}</td>
                    <td className="font-mono">{num(c.delta, 2)}</td>
                    <td className="font-mono">{num(c.iv, 1)}</td>
                    <td className="font-mono">{num(c.theta_per_lot_per_day, 0)}</td>
                    <td className="font-mono">{num(c.breakeven_at_expiry, 0)}</td>
                    <td className="font-mono" title={`Max loss per lot ₹${num(c.max_loss_per_lot, 0)}`}>
                      {c.lots_within_risk_budget ?? "—"}
                    </td>
                    <td className="font-mono">{num(c.score, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {recs.score_basis && <p className="text-[11px] text-muted">Score: {recs.score_basis}. {recs.risk_note}</p>}
          {recs.rejected.length > 0 && (
            <details className="text-[11px]">
              <summary className="text-muted hover:text-text">{recs.rejected.length} strikes rejected ▾</summary>
              <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto text-muted">
                {recs.rejected.map((item) => (
                  <li key={item.strike}>
                    <span className="font-mono text-text">{num(item.strike, 0)}</span>: {item.reasons.join("; ")}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}
