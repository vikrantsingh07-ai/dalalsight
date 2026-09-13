import { Link } from "react-router-dom";
import { humanize, istTime, num, pct } from "../lib/format";
import { NO_TRADE, type Levels, type Provenance, type Regime, type Snapshot, type TechEvent, type Technical, type TradePlan } from "../lib/types";
import { TEXT_TONES, toneForLabel, toneForPriority } from "../lib/tones";
import { Card, Empty, Meter, Pill, Stat, Table, UnavailableNote } from "./ui";

export function ScenarioBar({ bullish }: { bullish: number }) {
  const bearish = Math.round((100 - bullish) * 10) / 10;
  return (
    <div className="mt-3">
      <div className="flex justify-between text-[11px]">
        <span className="text-bull">Bullish scenario {num(bullish, 1)}%</span>
        <span className="text-bear">Bearish {num(bearish, 1)}%</span>
      </div>
      <div className="mt-1 flex h-2 overflow-hidden rounded">
        <div className="bg-bull" style={{ width: `${bullish}%` }} />
        <div className="bg-bear" style={{ width: `${bearish}%` }} />
      </div>
      <div className="mt-0.5 text-[10px] text-muted">Model-estimated from current signals, not a guaranteed outcome.</div>
    </div>
  );
}

export function PlanTable({ plan }: { plan: TradePlan }) {
  const rows: [string, string, string][] = [
    ["Entry zone", `${num(plan.entry_low)} – ${num(plan.entry_high)}`, "ATR-based zone at the signal bar close"],
    ["Stop-loss", num(plan.stop), plan.stop_basis],
    ["Target 1", num(plan.target1), plan.target1_basis],
    ["Target 2", num(plan.target2), plan.target2_basis],
    ["Risk : reward", `1 : ${num(plan.risk_reward)}`, `risk per unit ${num(plan.risk_per_unit)}`],
  ];
  if (plan.position_size_units !== null) rows.push(["Position size", `${num(plan.position_size_units, 0)} units`, plan.position_size_basis ?? ""]);
  return (
    <div className="mt-3 rounded border border-edge">
      <Table>
        <tbody>
          {rows.map(([label, value, basis]) => (
            <tr key={label}>
              <td className="whitespace-nowrap text-muted">{label}</td>
              <td className="whitespace-nowrap font-mono">{value}</td>
              <td className="text-[11px] text-muted">{basis}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="border-t border-edge px-2 py-1.5 text-[11px] text-muted">
        <span className="text-warn">Invalidation:</span> {plan.invalidation}
      </div>
    </div>
  );
}

export function SignalPanel({ snap }: { snap: Snapshot }) {
  const signal = snap.signal;
  const showPlan = signal.plan && signal.label !== NO_TRADE && signal.label !== "WATCH";
  return (
    <Card title="Signal confidence engine" actions={<Pill tone={snap.mode === "replay" ? "accent" : "muted"}>{snap.mode}</Pill>}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Pill tone={toneForLabel(signal.label)} className="px-2 py-1 text-xs">
          {signal.label}
        </Pill>
        <span className="font-mono text-lg">{num(snap.price)}</span>
      </div>
      <div className="mt-1 text-[11px] text-muted">
        Last completed bar {istTime(signal.bar_time, { date: true })}
        {snap.forming_bar_excluded ? " · forming bar excluded from analysis" : ""}
      </div>
      <ScenarioBar bullish={signal.bullish_pct} />
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Stat label="Model confidence" value={`${num(signal.model_confidence, 1)}%`} />
        <Stat label="Data coverage" value={`${num(signal.coverage * 100, 0)}%`} />
        <Stat label="Agreement" value={`${num(signal.agreement * 100, 0)}%`} />
      </div>
      {showPlan && signal.plan ? (
        <PlanTable plan={signal.plan} />
      ) : (
        <div className="mt-3 rounded border border-edge bg-bg/40 p-2 text-xs text-muted">
          {signal.label === NO_TRADE ? "NO TRADE / WAIT FOR CONFIRMATION — the evidence does not meet the confidence, coverage or agreement thresholds." : "No trade plan: the setup is below the threshold for entry, stop and targets."}
        </div>
      )}
      <ListBlock title="Supporting evidence" items={signal.reasons} empty="No component agrees strongly with a direction." />
      <ListBlock title="Risks and data gaps" items={signal.risks} empty="None flagged." />
      <ComponentTable snap={snap} />
      <p className="mt-3 text-[11px] leading-snug text-muted">
        {signal.disclaimer} Method: {signal.method}. Sources: {signal.data_sources.join("; ")}.
      </p>
    </Card>
  );
}

function ListBlock({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="mt-3">
      <div className="text-[11px] uppercase tracking-wide text-muted">{title}</div>
      {items.length ? (
        <ul className="mt-1 space-y-0.5 text-xs">
          {items.map((item) => (
            <li key={item} className="leading-snug">
              · {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-1 text-xs text-muted">{empty}</div>
      )}
    </div>
  );
}

function ComponentTable({ snap }: { snap: Snapshot }) {
  return (
    <details className="mt-3 rounded border border-edge">
      <summary className="px-2 py-1.5 text-xs text-muted hover:text-text">Component scores (weights configurable in Settings) ▾</summary>
      <Table>
        <thead>
          <tr>
            <th>Component</th>
            <th>Weight</th>
            <th>Score</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {snap.signal.components.map((component) => (
            <tr key={component.name} className={component.available ? "" : "opacity-60"}>
              <td className="whitespace-nowrap">{humanize(component.name)}</td>
              <td className="font-mono">{component.weight}</td>
              <td className="w-24">
                {component.available ? (
                  <div>
                    <div className={`font-mono ${TEXT_TONES[component.score > 0.1 ? "bull" : component.score < -0.1 ? "bear" : "muted"]}`}>{num(component.score, 2)}</div>
                    <div className="relative mt-0.5 h-1 rounded bg-edge/60">
                      <div
                        className={`absolute top-0 h-1 rounded ${component.score >= 0 ? "left-1/2 bg-bull" : "right-1/2 bg-bear"}`}
                        style={{ width: `${Math.abs(component.score) * 50}%` }}
                      />
                    </div>
                  </div>
                ) : (
                  <Pill>n/a</Pill>
                )}
              </td>
              <td className="text-[11px] leading-snug text-muted">{component.available ? component.evidence.join("; ") : `Data unavailable: ${component.unavailable_reason}`}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </details>
  );
}

export function RegimeCard({ regime }: { regime: Regime }) {
  const tone = regime.direction > 0 ? "bull" : regime.direction < 0 ? "bear" : "info";
  return (
    <Card title="Market regime">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={tone} className="px-2 py-1 text-xs">
          {regime.label}
        </Pill>
        <Pill>volatility {regime.volatility}</Pill>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        <Stat label="ADX" value={num(regime.adx, 1)} />
        <Stat label="ATR % price" value={num(regime.atr_pct, 2)} />
        <Stat label="ATR pctile" value={regime.atr_percentile === null ? "—" : num(regime.atr_percentile, 0)} />
      </div>
      <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
        {regime.evidence.map((item) => (
          <li key={item}>· {item}</li>
        ))}
      </ul>
    </Card>
  );
}

export function LevelsCard({ levels }: { levels: Levels }) {
  const sorted = [...levels.levels].sort((a, b) => b.price - a.price);
  return (
    <Card title="Support & resistance">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Nearest resistance" value={num(levels.nearest_resistance?.price)} sub={levels.nearest_resistance?.label} tone="bear" />
        <Stat label="Nearest support" value={num(levels.nearest_support?.price)} sub={levels.nearest_support?.label} tone="bull" />
        <Stat label="Breakout level" value={num(levels.breakout_level)} sub="prior 20-bar high" />
        <Stat label="Breakdown level" value={num(levels.breakdown_level)} sub="prior 20-bar low" />
      </div>
      <div className="mt-2 max-h-64 overflow-y-auto">
        <Table>
          <tbody>
            {sorted.map((level) => {
              const nearest = level.price === levels.nearest_support?.price || level.price === levels.nearest_resistance?.price;
              return (
                <tr key={`${level.price}-${level.label}`} className={nearest ? "bg-accent/5" : ""}>
                  <td className={`font-mono ${level.kind === "support" ? "text-bull" : "text-bear"}`}>{num(level.price)}</td>
                  <td>{level.label}</td>
                  <td className="text-[11px] text-muted">{level.source}</td>
                  <td className="font-mono text-accent" title="strength">
                    {"●".repeat(level.strength)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </div>
      {levels.trendlines.length > 0 && (
        <div className="mt-2 text-[11px] text-muted">
          {levels.trendlines.map((line) => (
            <div key={line.kind}>
              {humanize(line.kind)} projects to <span className="font-mono text-text">{num(line.projection)}</span> at the latest bar.
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function EventsCard({ events }: { events: TechEvent[] }) {
  return (
    <Card title="Technical events (latest completed bar)">
      {events.length === 0 ? (
        <Empty>No events on the latest completed bar.</Empty>
      ) : (
        <ul className="space-y-1.5">
          {events.map((event) => (
            <li key={event.key} className="flex items-start gap-2 text-xs">
              <Pill tone={toneForPriority(event.priority)}>{event.priority}</Pill>
              <span className={event.direction > 0 ? "text-bull" : event.direction < 0 ? "text-bear" : "text-text"}>{event.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function TechnicalCard({ technical }: { technical: Technical }) {
  const ema = technical.ema;
  return (
    <Card title="Indicator state">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {ema && (
          <Stat
            label={`EMA ${ema.fast_period}/${ema.slow_period}`}
            value={ema.relation}
            tone={ema.relation === "bullish" ? "bull" : "bear"}
            sub={`${ema.last_cross_bars_ago === null ? "no cross in 30 bars" : `crossed ${ema.last_cross_bars_ago} bars ago`}${ema.cross_confirmed ? " · confirmed" : ""}`}
          />
        )}
        {ema && <Stat label="Distance from slow EMA" value={pct(ema.distance_from_slow_pct)} sub={ema.distance_from_slow_atr === null ? undefined : `${num(ema.distance_from_slow_atr, 2)} ATR`} />}
        {technical.rsi && <Stat label="RSI" value={num(technical.rsi.value, 1)} sub={`${technical.rsi.zone}${technical.rsi.change_3_bars === null ? "" : ` · ${num(technical.rsi.change_3_bars, 1)} in 3 bars`}`} />}
        {technical.macd && <Stat label="MACD histogram" value={num(technical.macd.histogram, 2)} tone={technical.macd.histogram >= 0 ? "bull" : "bear"} sub={technical.macd.histogram_trend} />}
        <Stat label="VWAP" value={technical.vwap.value === null ? "Data unavailable" : num(technical.vwap.value)} sub={technical.vwap.unavailable_reason ?? `price ${technical.vwap.relation}`} />
        <Stat
          label="Volume vs 20-bar avg"
          value={technical.volume.ratio === undefined || technical.volume.ratio === null ? "Data unavailable" : `${num(technical.volume.ratio, 2)}×`}
          sub={technical.volume.unavailable_reason}
        />
        <Stat label="ATR" value={num(technical.atr)} sub={technical.volatility.atr_ratio === null ? undefined : `${num(technical.volatility.atr_ratio, 2)}× average`} />
        <Stat label="ADX" value={num(technical.adx, 1)} />
        <Stat label="Supertrend" value={technical.volatility.supertrend_dir === null ? "—" : technical.volatility.supertrend_dir > 0 ? "bullish" : "bearish"} />
      </div>
    </Card>
  );
}

export function OptionsSnapshotCard({ snap }: { snap: Snapshot }) {
  const options = snap.options;
  return (
    <Card title="Options positioning" actions={options ? <Link className="text-xs text-accent hover:underline" to="/options">Open chain →</Link> : undefined}>
      {!options ? (
        <UnavailableNote info={snap.options_status ?? { reason: "option chain not loaded" }} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="PCR (OI)" value={num(options.pcr_oi, 2)} />
            <Stat label="Max pain" value={num(options.max_pain, 0)} />
            <Stat label="Call wall" value={num(options.call_wall, 0)} tone="bear" />
            <Stat label="Put wall" value={num(options.put_wall, 0)} tone="bull" />
            <Stat label="ATM IV" value={options.atm_iv === null ? "—" : `${num(options.atm_iv, 2)}%`} />
            <Stat label="1σ range" value={options.expected_range ? `${num(options.expected_range[0], 0)}–${num(options.expected_range[1], 0)}` : "—"} />
          </div>
          <div className="mt-2 text-[11px] text-muted">
            Expiry {options.expiry} · NSE chain {istTime(options.timestamp, { date: true })}
          </div>
        </>
      )}
    </Card>
  );
}

export function ProvenanceLine({ provenance, generatedAt }: { provenance: Provenance; generatedAt?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
      <span>Source: {provenance.provider ?? "unknown"}</span>
      <span>Last bar {istTime(provenance.last_bar, { date: true })}</span>
      <span>{provenance.bars} bars</span>
      <span>Volume {provenance.has_volume ? "available" : "not available"}</span>
      {provenance.lag_seconds !== null && <span>Lag {provenance.lag_seconds}s</span>}
      {provenance.live_ticks_merged && <Pill tone="info">NSE ticks merged</Pill>}
      {provenance.stale && <Pill tone="warn">stale</Pill>}
      {generatedAt && <span>Computed {istTime(generatedAt, { seconds: true })}</span>}
    </div>
  );
}

export function ConfidenceMeter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-[11px] text-muted">
        <span>{label}</span>
        <span className="font-mono text-text">{num(value, 1)}%</span>
      </div>
      <Meter value={value} tone={value >= 60 ? "bull" : value >= 40 ? "warn" : "muted"} />
    </div>
  );
}
