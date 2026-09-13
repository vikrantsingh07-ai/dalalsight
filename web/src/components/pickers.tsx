import { useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { get } from "../lib/api";
import { Button, Input } from "./ui";

interface SearchResult {
  symbol: string;
  name: string;
  kind: string;
}

const QUICK = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

export function SymbolPicker({ value, onChange, quick = true }: { value?: string; onChange?: (symbol: string) => void; quick?: boolean }) {
  const app = useApp();
  const current = value ?? app.symbol;
  const choose = onChange ?? app.setSymbol;
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const id = window.setTimeout(() => {
      get<SearchResult[]>(`/api/symbols/search?q=${encodeURIComponent(trimmed)}`)
        .then(setResults)
        .catch(() => setResults([]));
    }, 200);
    return () => window.clearTimeout(id);
  }, [query]);

  const pick = (symbol: string) => {
    choose(symbol);
    setOpen(false);
    setQuery("");
    setResults([]);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Input
          value={open ? query : current}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onChange={(event) => setQuery(event.target.value.toUpperCase())}
          onKeyDown={(event) => {
            if (event.key === "Enter" && query.trim()) pick(results[0]?.symbol ?? query.trim());
            if (event.key === "Escape") (event.target as HTMLInputElement).blur();
          }}
          className="w-44 font-mono"
          placeholder="Search symbol"
          aria-label="Symbol"
        />
        {open && query.trim() && results.length > 0 && (
          <ul className="absolute z-30 mt-1 max-h-72 w-80 overflow-auto rounded border border-edge bg-panel shadow-2xl">
            {results.map((result) => (
              <li key={result.symbol}>
                <button type="button" onMouseDown={() => pick(result.symbol)} className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs hover:bg-panel-2">
                  <span className="font-mono">{result.symbol}</span>
                  <span className="truncate text-muted">
                    {result.name} · {result.kind}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {quick && (
        <div className="hidden flex-wrap gap-1 md:flex">
          {QUICK.map((symbol) => (
            <Button key={symbol} variant={symbol === current ? "primary" : "ghost"} onClick={() => pick(symbol)}>
              {symbol}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TimeframePicker({ value, onChange, options }: { value: string; onChange: (timeframe: string) => void; options?: string[] }) {
  const { config } = useApp();
  const list = options ?? config?.timeframes ?? ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"];
  return (
    <div className="inline-flex rounded border border-edge bg-bg p-0.5" role="group" aria-label="Timeframe">
      {list.map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => onChange(tf)}
          aria-pressed={tf === value}
          className={`rounded px-2 py-1 font-mono text-[11px] ${tf === value ? "bg-accent text-bg" : "text-muted hover:text-text"}`}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}
