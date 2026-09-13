import { useState } from "react";
import { useApp } from "../context/AppContext";
import { post } from "../lib/api";
import { humanize, istTime, num } from "../lib/format";
import { useApi, useEvents } from "../lib/hooks";
import type { AgentResult, AgentRun } from "../lib/types";
import { TimeframePicker } from "../components/pickers";
import { toneForLabel, toneForStatus } from "../lib/tones";
import { Button, Card, Checkbox, Empty, ErrorNote, Field, Input, PageHeader, Pill, Spinner, Stat, Table } from "../components/ui";

interface AgentsMeta {
  agents: Record<string, { name: string; kind: string; est_calls: number; description: string }>;
  budget_left: number;
  daily_budget: number;
  active_run: number | null;
  weights: Record<string, number>;
}

const LLM_AGENTS = ["market", "social", "news", "fundamentals", "derivatives"];

export default function Agents() {
  const { symbol, timeframe } = useApp();
  const meta = useApi<AgentsMeta>("/api/agents/meta", { interval: 15_000 });
  const runs = useApi<AgentRun[]>("/api/agents/runs?limit=30", { interval: 20_000 });
  const [runSymbol, setRunSymbol] = useState(symbol || "NIFTY");
  const [runTf, setRunTf] = useState(timeframe || "15m");
  const [selectedAgents, setSelectedAgents] = useState<string[]>(["market"]);
  const [kind, setKind] = useState<"analysts" | "full_pipeline">("analysts");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const selectedId = selected ?? runs.data?.[0]?.id ?? null;
  const run = useApi<AgentRun>(selectedId ? `/api/agents/runs/${selectedId}` : null, { interval: runs.data?.find((r) => r.id === selectedId)?.status === "running" ? 4000 : undefined });

  useEvents(["agent_progress", "agent_run"], () => {
    run.reload();
    runs.reload();
    meta.reload();
  });

  const estimate = kind === "full_pipeline" ? 30 : selectedAgents.reduce((sum, key) => sum + (meta.data?.agents[key]?.est_calls ?? 5) + 1, 0);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const response = await post<{ run_id: number }>("/api/agents/run", { symbol: runSymbol, timeframe: runTf, agents: selectedAgents, kind });
      setSelected(response.run_id);
      runs.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <PageHeader title="Trading agents" subtitle="The five TradingAgents analysts run unchanged on the configured model; each report is normalised to a shared schema and combined with the rule-based technical engine into a confidence-weighted consensus." />
      <div className="grid gap-3 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="space-y-3">
          <Card title="Run agents">
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Stat label="AI calls left today" value={meta.data ? `${meta.data.budget_left}/${meta.data.daily_budget}` : "—"} tone={meta.data && meta.data.budget_left < estimate ? "bear" : undefined} />
                <Stat label="Estimated calls" value={`~${estimate}`} />
              </div>
              <Field label="Symbol">
                <Input value={runSymbol} onChange={(event) => setRunSymbol(event.target.value.toUpperCase())} className="font-mono" />
              </Field>
              <Field label="Timeframe (technical context)">
                <TimeframePicker value={runTf} onChange={setRunTf} />
              </Field>
              <div className="space-y-1">
                {LLM_AGENTS.map((key) => (
                  <div key={key}>
                    <Checkbox
                      label={
                        <span>
                          {meta.data?.agents[key]?.name ?? humanize(key)} <span className="text-muted">· ~{meta.data?.agents[key]?.est_calls ?? "?"} calls</span>
                        </span>
                      }
                      checked={selectedAgents.includes(key)}
                      onChange={(checked) => setSelectedAgents(checked ? [...selectedAgents, key] : selectedAgents.filter((a) => a !== key))}
                    />
                    <div className="pl-6 text-[11px] text-muted">{meta.data?.agents[key]?.description}</div>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-1 text-xs">
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="kind" checked={kind === "analysts"} onChange={() => setKind("analysts")} /> Selected analysts + consensus
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="kind" checked={kind === "full_pipeline"} onChange={() => setKind("full_pipeline")} /> Full TradingAgents pipeline (debate → trader → risk → portfolio manager)
                </label>
              </div>
              <Button variant="primary" className="w-full" onClick={() => void start()} disabled={busy || selectedAgents.length === 0 || Boolean(meta.data?.active_run)}>
                {meta.data?.active_run ? `Run #${meta.data.active_run} in progress` : busy ? "Starting…" : "Run"}
              </Button>
              <ErrorNote error={error} />
              <p className="text-[11px] text-muted">Runs take minutes on free models. One run at a time; each model call counts against the daily budget.</p>
            </div>
          </Card>
          <Card title="Recent runs" bodyClass="max-h-[420px] overflow-y-auto p-2">
            {runs.data?.length === 0 && <Empty>No agent runs yet.</Empty>}
            <ul className="space-y-1">
              {(runs.data ?? []).map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => setSelected(item.id)} className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs ${item.id === selectedId ? "bg-panel-2" : "hover:bg-panel-2/60"}`}>
                    <span>
                      <span className="font-mono">#{item.id}</span> {item.symbol} {item.timeframe} <span className="text-muted">{istTime(item.started_at, { date: true })}</span>
                    </span>
                    <span className="flex gap-1">
                      <Pill tone={toneForStatus(item.status)}>{item.status}</Pill>
                      {item.consensus && <Pill tone={toneForLabel(item.consensus.signal)}>{item.consensus.signal.split(" /")[0]}</Pill>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="min-w-0">{run.data ? <RunDetail run={run.data} /> : run.loading ? <Spinner /> : <Empty>Select or start a run.</Empty>}</div>
      </div>
    </div>
  );
}

function RunDetail({ run }: { run: AgentRun }) {
  const consensus = run.consensus;
  return (
    <div className="space-y-3">
      <Card
        title={`Run #${run.id} · ${run.symbol} ${run.timeframe} · ${humanize(run.kind)}`}
        actions={
          <>
            <Pill tone={toneForStatus(run.status)}>{run.status}</Pill>
            {run.model && <Pill>{run.model.split("/").pop()}</Pill>}
          </>
        }
      >
        <div className="text-[11px] text-muted">
          Started {istTime(run.started_at, { date: true, seconds: true })}
          {run.finished_at ? ` · finished ${istTime(run.finished_at, { seconds: true })}` : ""}
        </div>
        {run.status === "running" && <Spinner label="Agents working" />}
        <ErrorNote error={run.error} />
        {consensus && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={toneForLabel(consensus.signal)} className="px-2 py-1 text-xs">
                Consensus: {consensus.signal}
              </Pill>
              {consensus.direction_view && <Pill tone={toneForLabel(consensus.direction_view)}>direction view {consensus.direction_view}</Pill>}
              <span className="text-xs text-muted">
                score {num(consensus.score, 3)} · agreement {num(consensus.agreement_pct, 1)}%
              </span>
            </div>
            <p className="text-xs">{consensus.reason}</p>
            <Table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>View</th>
                  <th>Confidence</th>
                  <th>Basis</th>
                  <th>Weight</th>
                </tr>
              </thead>
              <tbody>
                {consensus.votes.map((vote) => (
                  <tr key={vote.agent}>
                    <td>{vote.name}</td>
                    <td>
                      <Pill tone={toneForLabel(vote.signal)}>{vote.signal}</Pill>
                    </td>
                    <td className="font-mono">{num(vote.confidence, 0)}%</td>
                    <td className="text-muted">{vote.basis === "rule_based" ? "rule-based" : "LLM self-assessed"}</td>
                    <td className="font-mono">{vote.weight}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {consensus.conflicts.length > 0 && (
              <div className="rounded border border-warn/40 bg-warn/5 p-2 text-xs">
                <div className="font-medium text-warn">Conflicting agents</div>
                {consensus.conflicts.map((conflict) => (
                  <p key={conflict.agent} className="mt-1">
                    <span className="font-medium">{conflict.name}</span> ({conflict.signal}, {num(conflict.confidence, 0)}%): {conflict.reasoning}
                  </p>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted">Method: {consensus.method}</p>
          </div>
        )}
      </Card>
      <div className="grid gap-3 lg:grid-cols-2">
        {(run.results ?? []).map((result) => (
          <AgentCard key={`${result.agent}-${result.timestamp}`} result={result} />
        ))}
      </div>
    </div>
  );
}

function AgentCard({ result }: { result: AgentResult }) {
  return (
    <Card
      title={result.name}
      actions={
        <>
          <Pill tone={toneForLabel(result.signal)}>{result.signal}</Pill>
          {result.confidence !== null && <Pill>{num(result.confidence, 0)}%</Pill>}
        </>
      }
    >
      <div className="text-[11px] text-muted">
        {result.confidence_basis === "rule_based" ? "rule-based confidence" : result.confidence_basis === "llm_assessed" ? "LLM self-assessed confidence" : "no confidence"}
        {result.model ? ` · ${result.model}` : ""}
        {result.duration_s !== null ? ` · ${num(result.duration_s, 0)}s` : ""}
      </div>
      <ErrorNote error={result.error} />
      <p className="mt-2 text-xs leading-relaxed">{result.reasoning}</p>
      {result.key_levels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {result.key_levels.map((level) => (
            <Pill key={`${level.type}-${level.price}`} tone={level.type === "support" ? "bull" : level.type === "resistance" ? "bear" : "muted"} title={level.note}>
              {level.type} {num(level.price, 0)}
            </Pill>
          ))}
        </div>
      )}
      {result.risks.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[11px] text-muted">
          {result.risks.map((risk) => (
            <li key={risk}>· {risk}</li>
          ))}
        </ul>
      )}
      {result.data_sources.length > 0 && <div className="mt-2 text-[11px] text-muted">Sources: {result.data_sources.join(", ")}</div>}
      {result.warnings.length > 0 && <div className="mt-1 text-[11px] text-warn">{result.warnings.join(" · ")}</div>}
      {result.report && (
        <details className="mt-2">
          <summary className="text-xs text-accent hover:underline">Full report ▾</summary>
          <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap rounded border border-edge bg-bg p-2 font-body text-[11px] leading-relaxed">{result.report}</pre>
        </details>
      )}
    </Card>
  );
}
