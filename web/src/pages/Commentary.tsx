import { useState } from "react";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { istTime, num } from "../lib/format";
import { useApi, useEvents } from "../lib/hooks";
import type { ReplayState } from "../lib/types";
import CommentaryFeed from "../components/CommentaryFeed";
import { toneForLabel } from "../lib/tones";
import { Button, Card, Checkbox, ErrorNote, Field, Input, Meter, PageHeader, Pill, Select, Tabs } from "../components/ui";

interface ReplayUpdate {
  progress: number;
  bar_time: string;
  price: number;
  symbol: string;
  timeframe: string;
  signal: { label: string; bullish_pct: number; model_confidence: number };
  regime: string;
  events: string[];
}

export default function Commentary() {
  const { symbol, settings, say, voiceOn } = useApp();
  const [mode, setMode] = useState<"all" | "live" | "replay">("all");
  const [onlySymbol, setOnlySymbol] = useState(false);
  const [replaySymbol, setReplaySymbol] = useState(symbol || "NIFTY");
  const [replayTf, setReplayTf] = useState("5m");
  const [sessionDate, setSessionDate] = useState("");
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [last, setLast] = useState<ReplayUpdate | null>(null);
  const replay = useApi<ReplayState>("/api/replay/status", { interval: 4000 });

  useEvents(["replay_update"], (message) => {
    const data = message.data as ReplayUpdate | (ReplayState & { finished: true });
    if ("finished" in data) replay.reload();
    else setLast(data);
  });

  async function start() {
    setError(null);
    setLast(null);
    try {
      await post("/api/replay/start", { symbol: replaySymbol, timeframe: replayTf, session_date: sessionDate || null, interval_seconds: speed });
      replay.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function stop() {
    await post("/api/replay/stop").catch(setError);
    replay.reload();
  }

  const state = replay.data;
  const running = Boolean(state?.running);

  return (
    <div className="space-y-3">
      <PageHeader
        title="AI commentary"
        subtitle="Short notes when something important happens in the market, written by the engine or the AI."
        info={`Notes are written only on real changes, with pauses (${settings?.commentary.event_cooldown_seconds ?? 900}s per event, ${settings?.commentary.min_interval_seconds ?? 120}s between notes). Important notes may be written by the AI model; any AI note with a number that isn't in the data is rejected.`}
      >
        <Button onClick={() => say("Voice check. Commentary will be spoken for high priority events.")} disabled={!voiceOn}>
          Test voice
        </Button>
      </PageHeader>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <Tabs
              tabs={[
                { id: "all", label: "All" },
                { id: "live", label: "Live" },
                { id: "replay", label: "Replay" },
              ]}
              value={mode}
              onChange={setMode}
            />
            <Checkbox label={`Only ${symbol}`} checked={onlySymbol} onChange={setOnlySymbol} />
          </div>
          <CommentaryFeed key={`${mode}-${onlySymbol}-${symbol}`} mode={mode === "all" ? undefined : mode} symbol={onlySymbol ? symbol : undefined} limit={150} title="Commentary feed" />
        </div>

        <Card title="Session replay" actions={running ? <Pill tone="accent">replay running</Pill> : undefined}>
          <p className="text-[11px] text-muted">
            Steps through a recorded session bar by bar using the same analysis and commentary pipeline. Output is labelled REPLAY. Option chains are excluded (no historical chains).
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Field label="Symbol">
              <Input value={replaySymbol} onChange={(event) => setReplaySymbol(event.target.value.toUpperCase())} className="font-mono" disabled={running} />
            </Field>
            <Field label="Timeframe">
              <Select value={replayTf} onChange={(event) => setReplayTf(event.target.value)} disabled={running}>
                {["1m", "3m", "5m", "15m"].map((tf) => (
                  <option key={tf} value={tf}>
                    {tf}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Session date" hint="blank = last session">
              <Input type="date" value={sessionDate} onChange={(event) => setSessionDate(event.target.value)} disabled={running} />
            </Field>
            <Field label="Seconds per bar">
              <Input type="number" min={0.1} max={10} step={0.1} value={speed} onChange={(event) => setSpeed(Number(event.target.value) || 1)} disabled={running} />
            </Field>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => void start()} disabled={running}>
              Start replay
            </Button>
            <Button variant="danger" onClick={() => void stop()} disabled={!running}>
              Stop
            </Button>
          </div>
          <ErrorNote error={error ?? state?.error} />
          {state?.bars !== undefined && (
            <div className="mt-3 space-y-1 text-xs">
              <div className="flex justify-between text-muted">
                <span>
                  {state.symbol} {state.timeframe} · {state.session_date}
                </span>
                <span className="font-mono">
                  {state.processed ?? 0}/{state.bars}
                </span>
              </div>
              <Meter value={state.processed ?? 0} max={state.bars || 1} />
              {state.available_dates && <div className="text-[11px] text-muted">Available: {state.available_dates.join(", ")}</div>}
              {state.finished_at && <div className="text-[11px] text-muted">Finished {istTime(state.finished_at, { seconds: true })}</div>}
            </div>
          )}
          {last && (
            <div className="mt-3 rounded border border-edge bg-bg/40 p-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="accent">replay</Pill>
                <span className="font-mono">{istTime(last.bar_time, { date: true })}</span>
                <span className="font-mono">{num(last.price)}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Pill tone={toneForLabel(last.signal.label)}>{last.signal.label}</Pill>
                <span className="text-muted">
                  bullish {num(last.signal.bullish_pct, 1)}% · confidence {num(last.signal.model_confidence, 1)}%
                </span>
              </div>
              <div className="mt-1 text-muted">Regime: {last.regime}</div>
              {last.events.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {last.events.map((event) => (
                    <li key={event}>· {event}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
