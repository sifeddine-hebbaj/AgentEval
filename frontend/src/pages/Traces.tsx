import { useEffect, useState } from "react";
import { api, TraceDetail, TraceSummary } from "../api/client";
import StatusBadge from "../components/StatusBadge";

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString();
}

function SpanRow({ span, depth }: { span: TraceDetail["spans"][number]; depth: number }) {
  const typeColor: Record<string, string> = {
    llm_call: "text-accent",
    tool_call: "text-warn",
    retrieval: "text-pass",
    custom: "text-muted",
  };
  return (
    <div
      className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0"
      style={{ paddingLeft: `${depth * 20}px` }}
    >
      <span className={`mono text-xs w-20 shrink-0 ${typeColor[span.span_type] || "text-muted"}`}>
        {span.span_type}
      </span>
      <span className="text-sm flex-1 truncate">{span.name || "(unnamed span)"}</span>
      {span.model_name && <span className="mono text-xs text-muted">{span.model_name}</span>}
      <span className="mono text-xs text-muted w-24 text-right">
        {span.prompt_tokens + span.completion_tokens} tok
      </span>
      <span className="mono text-xs text-muted w-16 text-right">${span.cost.toFixed(4)}</span>
      <StatusBadge status={span.status} />
    </div>
  );
}

function buildTree(spans: TraceDetail["spans"]) {
  const byParent = new Map<string | null, TraceDetail["spans"]>();
  for (const s of spans) {
    const key = s.parent_span_id;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(s);
  }
  const ordered: { span: TraceDetail["spans"][number]; depth: number }[] = [];
  function walk(parentId: string | null, depth: number) {
    for (const s of byParent.get(parentId) || []) {
      ordered.push({ span: s, depth });
      walk(s.id, depth + 1);
    }
  }
  walk(null, 0);
  return ordered;
}

function TraceDrawer({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [trace, setTrace] = useState<TraceDetail | null>(null);

  useEffect(() => {
    api.getTrace(traceId).then(setTrace);
  }, [traceId]);

  const tree = trace ? buildTree(trace.spans) : [];

  return (
    <div className="fixed inset-0 bg-black/50 flex justify-end z-50" onClick={onClose}>
      <div className="w-[640px] h-full bg-panel border-l border-border overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg font-semibold">Trace detail</h2>
          <button onClick={onClose} className="text-muted hover:text-[#E6EDF3]">✕</button>
        </div>
        {!trace ? (
          <p className="text-muted text-sm">Loading…</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 mb-6 text-sm">
              <div>
                <div className="text-muted text-xs">Environment</div>
                <div className="mono">{trace.environment}</div>
              </div>
              <div>
                <div className="text-muted text-xs">Status</div>
                <StatusBadge status={trace.status} />
              </div>
              <div>
                <div className="text-muted text-xs">Total tokens</div>
                <div className="mono">{trace.total_tokens}</div>
              </div>
              <div>
                <div className="text-muted text-xs">Total cost</div>
                <div className="mono">${trace.total_cost.toFixed(4)}</div>
              </div>
              <div>
                <div className="text-muted text-xs">Duration</div>
                <div className="mono">{trace.duration_ms ?? "—"}ms</div>
              </div>
              <div>
                <div className="text-muted text-xs">Started</div>
                <div className="mono text-xs">{fmtDate(trace.started_at)}</div>
              </div>
            </div>
            <h3 className="text-sm font-medium mb-2 text-muted uppercase tracking-wide">Span waterfall</h3>
            <div className="panel p-2">
              {tree.length === 0 ? (
                <p className="text-muted text-sm p-3">No spans recorded for this trace.</p>
              ) : (
                tree.map(({ span, depth }) => <SpanRow key={span.id} span={span} depth={depth} />)
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Traces() {
  const [traces, setTraces] = useState<TraceSummary[] | null>(null);
  const [envFilter, setEnvFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.listTraces(envFilter || undefined).then(setTraces);
  }, [envFilter]);

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold">Traces</h1>
          <p className="text-muted text-sm mt-1">Every ingested agent run, newest first.</p>
        </div>
        <select className="input" value={envFilter} onChange={(e) => setEnvFilter(e.target.value)}>
          <option value="">All environments</option>
          <option value="development">development</option>
          <option value="staging">staging</option>
          <option value="production">production</option>
        </select>
      </div>

      {traces === null ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : traces.length === 0 ? (
        <div className="panel p-10 text-center">
          <p className="text-muted text-sm">
            No traces yet. Instrument an agent with the SDK and call{" "}
            <code className="mono text-accent">client.flush()</code>, or run{" "}
            <code className="mono text-accent">python examples/example-support-agent/agent.py</code>.
          </p>
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted text-xs uppercase tracking-wide">
                <th className="text-left font-medium px-4 py-3">Environment</th>
                <th className="text-left font-medium px-4 py-3">Status</th>
                <th className="text-right font-medium px-4 py-3">Tokens</th>
                <th className="text-right font-medium px-4 py-3">Cost</th>
                <th className="text-right font-medium px-4 py-3">Duration</th>
                <th className="text-left font-medium px-4 py-3">Started</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-border/50 last:border-0 hover:bg-white/[0.03] cursor-pointer"
                  onClick={() => setSelected(t.id)}
                >
                  <td className="px-4 py-3 mono text-xs">{t.environment}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">{t.total_tokens}</td>
                  <td className="px-4 py-3 text-right mono text-xs">${t.total_cost.toFixed(4)}</td>
                  <td className="px-4 py-3 text-right mono text-xs">{t.duration_ms ?? "—"}ms</td>
                  <td className="px-4 py-3 text-xs text-muted">{fmtDate(t.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && <TraceDrawer traceId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
