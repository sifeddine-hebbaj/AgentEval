import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, EvalRun } from "../api/client";
import StatusBadge from "../components/StatusBadge";

export default function EvalRuns() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);

  useEffect(() => {
    api.listEvalRuns().then(setRuns);
  }, []);

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="font-display text-2xl font-semibold mb-1">Eval Runs</h1>
      <p className="text-muted text-sm mb-6">Trigger these via the CLI (<code className="mono text-accent">agenteval run</code>), CI, or the API.</p>

      {runs === null ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : runs.length === 0 ? (
        <div className="panel p-10 text-center text-muted text-sm">
          No eval runs yet. See README "Running Your First Evaluation".
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted text-xs uppercase tracking-wide">
                <th className="text-left font-medium px-4 py-3">Status</th>
                <th className="text-right font-medium px-4 py-3">Progress</th>
                <th className="text-right font-medium px-4 py-3">Pass rate</th>
                <th className="text-right font-medium px-4 py-3">p95 latency</th>
                <th className="text-left font-medium px-4 py-3">Started</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-border/50 last:border-0 hover:bg-white/[0.03]">
                  <td className="px-4 py-3">
                    <Link to={`/eval-runs/${r.id}`} className="hover:underline">
                      <StatusBadge status={r.status} />
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {r.completed_test_cases}/{r.total_test_cases}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {r.aggregate_metrics.pass_rate != null ? `${(r.aggregate_metrics.pass_rate * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {r.aggregate_metrics.p95_latency_ms ?? "—"}ms
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{new Date(r.started_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
