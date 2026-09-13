import { useApi, useEvents } from "../lib/hooks";
import { istTime } from "../lib/format";
import type { CommentaryEntry } from "../lib/types";
import { toneForPriority } from "../lib/tones";
import { Card, Empty, ErrorNote, Pill } from "./ui";

export default function CommentaryFeed({ symbol, mode, limit = 50, title = "Live AI commentary", className = "" }: { symbol?: string; mode?: "live" | "replay"; limit?: number; title?: string; className?: string }) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (symbol) params.set("symbol", symbol);
  if (mode) params.set("mode", mode);
  const feed = useApi<CommentaryEntry[]>(`/api/commentary?${params.toString()}`);

  useEvents(["commentary", "commentary_update"], (message) => {
    if (message.type === "commentary") {
      const entry = message.data as CommentaryEntry;
      if ((symbol && entry.symbol !== symbol) || (mode && entry.mode !== mode)) return;
      feed.setData((list) => [entry, ...(list ?? []).filter((item) => item.id !== entry.id)].slice(0, limit));
    } else {
      const update = message.data as { id: number; text: string; text_source: string };
      feed.setData((list) => (list ?? []).map((item) => (item.id === update.id ? { ...item, text: update.text, text_source: update.text_source } : item)));
    }
  });

  return (
    <Card title={title} className={className} bodyClass="max-h-[520px] overflow-y-auto p-3">
      <ErrorNote error={feed.error} />
      {feed.data && feed.data.length === 0 && (
        <Empty>No commentary yet. It is produced only on material changes while the market is open, or during a labelled REPLAY.</Empty>
      )}
      <ol className="space-y-2.5">
        {(feed.data ?? []).map((entry) => (
          <li key={entry.id} className="rounded border border-edge bg-bg/40 p-2">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
              <span className="font-mono">{istTime(entry.ts, { seconds: true })}</span>
              <span className="font-mono text-text">
                {entry.symbol} {entry.timeframe}
              </span>
              <Pill tone={toneForPriority(entry.priority)}>{entry.priority}</Pill>
              {entry.mode === "replay" && <Pill tone="accent">replay</Pill>}
              <Pill tone={entry.text_source.startsWith("ai:") ? "accent" : "muted"} title={entry.text_source}>
                {entry.text_source.startsWith("ai:") ? "AI" : "engine"}
              </Pill>
              {entry.speak && <span title="Spoken when voice is on">🔊</span>}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-text">{entry.text}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
