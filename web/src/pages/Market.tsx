import { useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { useApi } from "../lib/hooks";
import { istTime, num, pct } from "../lib/format";
import { isUnavailable, type MarketStatus, type Unavailable } from "../lib/types";
import { TEXT_TONES, toneForLabel, toneForNumber } from "../lib/tones";
import { Card, ErrorNote, PageHeader, Pill, Spinner, Table, UnavailableNote } from "../components/ui";

interface IndexTile {
  symbol: string;
  name: string;
  tradingview: string;
  price?: number;
  change?: number | null;
  change_pct?: number | null;
  high?: number | null;
  low?: number | null;
  prev_close?: number | null;
  timestamp?: string;
  provider?: string;
  extra?: Record<string, number | string | null>;
  unavailable?: Unavailable | null;
}

interface Breadth {
  advances: number | null;
  declines: number | null;
  unchanged: number | null;
  timestamp: string;
  source: string;
}

interface Overview {
  market: MarketStatus;
  indices: IndexTile[];
  sectors: IndexTile[];
  breadth: Breadth | Unavailable | null;
  snapshots: Record<string, { symbol: string; timeframe: string; label: string; bullish_pct: number; model_confidence: number; regime: string; price: number; generated_at: string }>;
  generated_at: string;
}

export default function Market() {
  const { setSymbol, status } = useApp();
  const navigate = useNavigate();
  const overview = useApi<Overview>("/api/overview", { interval: status?.market.is_trading ? 30_000 : 300_000 });
  const data = overview.data;
  const open = (symbol: string) => {
    setSymbol(symbol);
    navigate("/");
  };
  const maxSector = Math.max(0.5, ...(data?.sectors ?? []).map((s) => Math.abs(s.change_pct ?? 0)));

  return (
    <div className="space-y-3">
      <PageHeader title="Market overview" subtitle={data ? `${data.market.label} · updated ${istTime(data.generated_at, { seconds: true })}` : undefined}>
        {overview.loading && <Spinner label="Refreshing" />}
      </PageHeader>
      <ErrorNote error={overview.error} />
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
            {data.indices.map((tile) => (
              <button key={tile.symbol} type="button" onClick={() => open(tile.symbol)} className="rounded-lg border border-edge bg-panel p-2.5 text-left hover:border-muted">
                <div className="truncate text-[11px] uppercase tracking-wide text-muted">{tile.name}</div>
                {tile.unavailable || tile.price === undefined ? (
                  <div className="mt-1 text-xs text-warn" title={tile.unavailable?.reason}>
                    Data unavailable
                  </div>
                ) : (
                  <>
                    <div className="mt-0.5 font-mono text-base">{num(tile.price)}</div>
                    <div className={`font-mono text-xs ${TEXT_TONES[toneForNumber(tile.change)]}`}>
                      {num(tile.change)} ({pct(tile.change_pct)})
                    </div>
                    <div className="mt-1 text-[10px] text-muted">
                      L {num(tile.low)} · H {num(tile.high)}
                    </div>
                  </>
                )}
              </button>
            ))}
          </div>

          <div className="grid gap-3 xl:grid-cols-3">
            <Card title="Market breadth (NSE)">
              {!data.breadth || isUnavailable(data.breadth) ? (
                <UnavailableNote info={isUnavailable(data.breadth) ? data.breadth : { reason: "breadth feed not available from this provider" }} />
              ) : (
                <BreadthBar breadth={data.breadth} />
              )}
            </Card>
            <Card title="Sector indices" className="xl:col-span-2">
              <div className="grid gap-x-6 gap-y-1.5 md:grid-cols-2">
                {data.sectors.map((sector) => (
                  <button key={sector.symbol} type="button" onClick={() => open(sector.symbol)} className="grid grid-cols-[1fr_auto] items-center gap-2 text-left text-xs hover:text-accent">
                    <span className="truncate">{sector.name}</span>
                    <span className={`font-mono ${TEXT_TONES[toneForNumber(sector.change_pct)]}`}>{sector.unavailable ? "n/a" : pct(sector.change_pct)}</span>
                    <div className="col-span-2 flex h-1.5 rounded bg-edge/50">
                      <div className="flex w-1/2 justify-end">
                        {(sector.change_pct ?? 0) < 0 && <div className="h-1.5 rounded-l bg-bear" style={{ width: `${(Math.abs(sector.change_pct ?? 0) / maxSector) * 100}%` }} />}
                      </div>
                      <div className="w-1/2">{(sector.change_pct ?? 0) > 0 && <div className="h-1.5 rounded-r bg-bull" style={{ width: `${((sector.change_pct ?? 0) / maxSector) * 100}%` }} />}</div>
                    </div>
                  </button>
                ))}
              </div>
            </Card>
          </div>

          <Card title="Monitored signals (market monitor)">
            {Object.keys(data.snapshots).length === 0 ? (
              <div className="text-xs text-muted">The monitor has not completed a cycle yet.</div>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>TF</th>
                    <th>Price</th>
                    <th>Signal</th>
                    <th>Bullish scenario</th>
                    <th>Model confidence</th>
                    <th>Regime</th>
                    <th>Computed</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(data.snapshots).map((row) => (
                    <tr key={`${row.symbol}${row.timeframe}`} className="cursor-pointer hover:bg-panel-2" onClick={() => open(row.symbol)}>
                      <td className="font-mono">{row.symbol}</td>
                      <td>{row.timeframe}</td>
                      <td className="font-mono">{num(row.price)}</td>
                      <td>
                        <Pill tone={toneForLabel(row.label)}>{row.label}</Pill>
                      </td>
                      <td className="font-mono">{num(row.bullish_pct, 1)}%</td>
                      <td className="font-mono">{num(row.model_confidence, 1)}%</td>
                      <td>{row.regime}</td>
                      <td className="text-muted">{istTime(row.generated_at, { seconds: true })}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function BreadthBar({ breadth }: { breadth: Breadth }) {
  const adv = breadth.advances ?? 0;
  const dec = breadth.declines ?? 0;
  const unch = breadth.unchanged ?? 0;
  const total = Math.max(1, adv + dec + unch);
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded">
        <div className="bg-bull" style={{ width: `${(adv / total) * 100}%` }} />
        <div className="bg-edge" style={{ width: `${(unch / total) * 100}%` }} />
        <div className="bg-bear" style={{ width: `${(dec / total) * 100}%` }} />
      </div>
      <div className="mt-2 grid grid-cols-3 text-center text-xs">
        <div>
          <div className="font-mono text-bull">{num(adv, 0)}</div>
          <div className="text-muted">advances</div>
        </div>
        <div>
          <div className="font-mono">{num(unch, 0)}</div>
          <div className="text-muted">unchanged</div>
        </div>
        <div>
          <div className="font-mono text-bear">{num(dec, 0)}</div>
          <div className="text-muted">declines</div>
        </div>
      </div>
      <div className="mt-2 text-[11px] text-muted">
        Advance/decline ratio {num(dec ? adv / dec : null, 2)} · {breadth.source} · {istTime(breadth.timestamp, { date: true })}
      </div>
    </div>
  );
}
