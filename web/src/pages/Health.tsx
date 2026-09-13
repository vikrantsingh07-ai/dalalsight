import { useApp } from "../context/AppContext";
import { ago, istTime, num } from "../lib/format";
import { useApi, useEvents } from "../lib/hooks";
import type { HealthReport, TimelineEntry } from "../lib/types";
import { toneForStatus } from "../lib/tones";
import { Button, Card, Empty, ErrorNote, PageHeader, Pill, Spinner, Table } from "../components/ui";

export default function Health() {
  const { status } = useApp();
  const report = useApi<HealthReport>("/api/health", { interval: 15_000 });
  const timeline = useApi<TimelineEntry[]>("/api/timeline?limit=150", { interval: 60_000 });
  useEvents(["timeline"], (message) => {
    const entry = message.data as TimelineEntry;
    timeline.setData((list) => [entry, ...(list ?? [])].slice(0, 150));
  });
  const data = report.data;
  const ai = data?.components.find((c) => c.name === "AI model");

  return (
    <div className="space-y-3">
      <PageHeader title="System health" subtitle={data ? `Checked ${istTime(data.generated_at, { seconds: true })}` : undefined}>
        {data && (
          <Pill tone={toneForStatus(data.overall)} className="px-2 py-1 text-xs">
            overall {data.overall}
          </Pill>
        )}
        <Button onClick={report.reload}>Re-check</Button>
        {report.loading && <Spinner label="Checking" />}
      </PageHeader>
      <ErrorNote error={report.error} />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-3">
          <Card title="Components" bodyClass="p-0">
            <Table>
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Status</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {(data?.components ?? []).map((component) => (
                  <tr key={component.name}>
                    <td className="whitespace-nowrap">{component.name}</td>
                    <td>
                      <Pill tone={toneForStatus(component.status)}>{component.status}</Pill>
                    </td>
                    <td className="text-[11px] text-muted">
                      {component.detail}
                      {component.latency_ms !== undefined && component.latency_ms !== null && ` · ${num(component.latency_ms, 0)} ms`}
                      {component.last_success && ` · last success ${ago(component.last_success)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          {ai?.models && (
            <Card title="AI models">
              <Table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Role</th>
                    <th>Usable</th>
                    <th>State</th>
                  </tr>
                </thead>
                <tbody>
                  {ai.models.map((model) => (
                    <tr key={model.model}>
                      <td className="font-mono">{model.model}</td>
                      <td>{model.role}</td>
                      <td>
                        <Pill tone={model.usable ? "bull" : "bear"}>{model.usable ? "yes" : "no"}</Pill>
                      </td>
                      <td className="text-muted">{model.state}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {status && (
                <p className="mt-2 text-[11px] text-muted">
                  Active: {status.ai.active_model ?? "none"} · last used: {status.ai.last_model_used ?? "none yet"} · calls today {status.ai.calls_today}/{status.ai.daily_budget}
                  {status.ai.last_error ? ` · last error: ${status.ai.last_error}` : ""}
                </p>
              )}
            </Card>
          )}
          <Card title="Recent errors" bodyClass="p-0">
            {data && data.recent_errors.length === 0 ? (
              <div className="p-3">
                <Empty>No errors logged.</Empty>
              </div>
            ) : (
              <Table>
                <tbody>
                  {(data?.recent_errors ?? []).map((row) => (
                    <tr key={row.id}>
                      <td className="whitespace-nowrap text-muted">{istTime(row.ts, { date: true, seconds: true })}</td>
                      <td>
                        <Pill tone="bear">{row.source}</Pill>
                      </td>
                      <td className="text-xs">{row.message}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
        <Card title="Activity timeline" bodyClass="max-h-[760px] overflow-y-auto p-2">
          {timeline.data?.length === 0 && <Empty>No activity yet.</Empty>}
          <ol className="space-y-1.5">
            {(timeline.data ?? []).map((entry) => (
              <li key={entry.id} className="border-l-2 border-edge pl-2 text-xs">
                <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted">
                  <span className="font-mono">{istTime(entry.ts, { date: true, seconds: true })}</span>
                  <Pill>{entry.kind}</Pill>
                  {entry.symbol && <span className="font-mono">{entry.symbol}</span>}
                </div>
                <div className="leading-snug">{entry.message}</div>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </div>
  );
}
