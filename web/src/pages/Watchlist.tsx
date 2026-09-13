import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";
import { get } from "../lib/api";
import { istTime, num, pct } from "../lib/format";
import { useApi } from "../lib/hooks";
import { isUnavailable, type InstrumentMeta, type Quote, type Unavailable } from "../lib/types";
import { TEXT_TONES, toneForNumber } from "../lib/tones";
import { Button, Card, Empty, ErrorNote, Input, PageHeader, Spinner, Table } from "../components/ui";

export default function Watchlist() {
  const { settings, saveSettings, setSymbol, status } = useApp();
  const navigate = useNavigate();
  const list = settings?.watchlist ?? [];
  const quotes = useApi<Record<string, Quote | Unavailable>>(list.length ? `/api/quotes?symbols=${encodeURIComponent(list.join(","))}` : null, {
    interval: status?.market.is_trading ? 15_000 : 120_000,
  });
  const [input, setInput] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function save(next: string[]) {
    setError(null);
    try {
      await saveSettings({ watchlist: next });
    } catch (err) {
      setError(err);
    }
  }

  async function add() {
    const value = input.trim().toUpperCase();
    if (!value || list.includes(value)) return;
    setError(null);
    try {
      const meta = await get<InstrumentMeta>(`/api/instrument/${encodeURIComponent(value)}`);
      await save([...list, meta.symbol]);
      setInput("");
    } catch (err) {
      setError(err);
    }
  }

  const move = (index: number, delta: number) => {
    const next = [...list];
    const [item] = next.splice(index, 1);
    next.splice(Math.max(0, Math.min(next.length, index + delta)), 0, item);
    void save(next);
  };

  return (
    <div className="space-y-3">
      <PageHeader title="Watchlist" subtitle="Quotes: NSE public API for indices, Yahoo Finance for stocks. Timestamps show the actual quote time.">
        {quotes.loading && <Spinner label="Refreshing" />}
      </PageHeader>
      <Card>
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void add();
          }}
        >
          <Input value={input} onChange={(event) => setInput(event.target.value.toUpperCase())} placeholder="Add NSE symbol or index (e.g. TCS, BANKNIFTY)" className="w-72 font-mono" />
          <Button type="submit" variant="primary">
            Add
          </Button>
        </form>
        <div className="mt-2">
          <ErrorNote error={error} />
        </div>
      </Card>
      <Card bodyClass="p-0">
        {list.length === 0 ? (
          <div className="p-3">
            <Empty>The watchlist is empty.</Empty>
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Price</th>
                <th>Change</th>
                <th>%</th>
                <th>Day low</th>
                <th>Day high</th>
                <th>Quote time</th>
                <th>Source</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((item, index) => {
                const quote = quotes.data?.[item];
                const ok = quote && !isUnavailable(quote) ? quote : null;
                return (
                  <tr key={item}>
                    <td>
                      <button
                        type="button"
                        className="font-mono text-accent hover:underline"
                        onClick={() => {
                          setSymbol(item);
                          navigate("/");
                        }}
                      >
                        {item}
                      </button>
                    </td>
                    {ok ? (
                      <>
                        <td className="font-mono">{num(ok.price)}</td>
                        <td className={`font-mono ${TEXT_TONES[toneForNumber(ok.change)]}`}>{num(ok.change)}</td>
                        <td className={`font-mono ${TEXT_TONES[toneForNumber(ok.change_pct)]}`}>{pct(ok.change_pct)}</td>
                        <td className="font-mono">{num(ok.low)}</td>
                        <td className="font-mono">{num(ok.high)}</td>
                        <td className="text-muted">{istTime(ok.timestamp, { date: true })}</td>
                        <td className="max-w-48 truncate text-muted" title={ok.provider}>
                          {ok.provider}
                        </td>
                      </>
                    ) : (
                      <td colSpan={7} className="text-warn">
                        {quote && isUnavailable(quote) ? `Data unavailable: ${quote.reason}` : quotes.loading ? "…" : "Data unavailable"}
                      </td>
                    )}
                    <td className="whitespace-nowrap text-right">
                      <Button variant="ghost" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`Move ${item} up`}>
                        ↑
                      </Button>
                      <Button variant="ghost" onClick={() => move(index, 1)} disabled={index === list.length - 1} aria-label={`Move ${item} down`}>
                        ↓
                      </Button>
                      <Button variant="ghost" onClick={() => void save(list.filter((s) => s !== item))} aria-label={`Remove ${item}`}>
                        ✕
                      </Button>
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
