import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, EvalResultOut, EvalRun, EvalRunDiff } from "../api/client";
import StatusBadge from "../components/StatusBadge";

function ScoreCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel p-4">
      <div className="text-xs text-muted uppercase tracking-wide mb-1">{label}</div>
      <div className="font-display text-xl font-semibold mono">{value}</div>
    </div>
  );
}

export default function EvalRunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<EvalRun | null>(null);
  const [results, setResults] = useState<EvalResultOut[] | null>(null);
  const [diff, setDiff] = useState<EvalRunDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    if (!runId) return;
    api.getEvalRun(runId).then(setRun);
    api.getEvalRunResults(runId).then(setResults);
  }, [runId]);

  async function loadDiff() {
    if (!runId) return;
    setShowDiff(true);
    try {
      const d = await api.getEvalRunDiff(runId);
      setDiff(d);
      setDiffError(null);
    } catch (e) {
      setDiffError(e instanceof Error ? e.message : "Could not load diff.");
    }
  }

  async function markBaseline() {
    if (!runId) return;
    await api.setBaseline(runId);
    alert("This run is now the baseline for its dataset + suite.");
  }

  if (!run) return <div className="p-8 text-muted text-sm">Loading…</div>;

  const meanScores = run.aggregate_metrics.mean_scores || {};

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-2xl font-semibold">Eval Run</h1>
        <div className="flex gap-2">
          <button onClick={markBaseline} className="btn-ghost text-xs">
            Set as baseline
          </button>
          <button onClick={loadDiff} className="btn-primary text-xs">
            Compare to baseline
          </button>
        </div>
      </div>
      <p className="mono text-xs text-muted mb-6">{run.id}</p>

      <div className="grid grid-cols-4 gap-3 mb-6">
        <ScoreCard label="Status" value={run.status} />
        <ScoreCard label="Pass rate" value={run.aggregate_metrics.pass_rate != null ? `${(run.aggregate_metrics.pass_rate * 100).toFixed(0)}%` : "—"} />
        <ScoreCard label="p50 / p95 latency" value={`${run.aggregate_metrics.p50_latency_ms ?? "—"} / ${run.aggregate_metrics.p95_latency_ms ?? "—"}ms`} />
        <ScoreCard label="Errors" value={String(run.aggregate_metrics.error_count ?? 0)} />
      </div>

      <div className="flex gap-3 mb-6">
        {Object.entries(meanScores).map(([name, value]) => (
          <div key={name} className="panel px-4 py-3 flex-1">
            <div className="text-xs text-muted">{name}</div>
            <div className="font-display text-lg font-semibold mono text-accent">{value.toFixed(3)}</div>
          </div>
        ))}
      </div>

      {showDiff && (
        <div className="panel p-4 mb-6">
          <h3 className="text-sm font-medium mb-3 text-muted uppercase tracking-wide">Baseline diff</h3>
          {diffError ? (
            <p className="text-warn text-sm">{diffError}</p>
          ) : !diff ? (
            <p className="text-muted text-sm">Loading…</p>
          ) : (
            <>
              <div className="flex gap-4 mb-4">
                {Object.entries(diff.significance).map(([scorer, sig]) => (
                  <div key={scorer} className="text-sm">
                    <span className="text-muted">{scorer}: </span>
                    <span className={sig.mean_delta < 0 ? "text-fail" : "text-pass"}>
                      {sig.mean_delta >= 0 ? "+" : ""}
                      {sig.mean_delta.toFixed(3)}
                    </span>
                    <span className="text-muted text-xs ml-1">
                      {sig.significant ? "(significant)" : "(not statistically significant)"}
                    </span>
                  </div>
                ))}
              </div>
              {diff.regressed_cases.length === 0 ? (
                <p className="text-pass text-sm">No regressed test cases vs. baseline.</p>
              ) : (
                <div className="space-y-1">
                  {diff.regressed_cases.map((c, i) => (
                    <div key={i} className="flex items-center gap-3 border-l-2 border-fail pl-3 py-1 text-sm">
                      <span className="mono text-xs text-muted">{c.test_case_id.slice(0, 8)}</span>
                      <span className="text-muted">{c.scorer}</span>
                      <span className="mono text-xs">
                        {c.baseline_score?.toFixed(3)} → <span className="text-fail">{c.new_score?.toFixed(3)}</span>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      <h3 className="text-sm font-medium mb-2 text-muted uppercase tracking-wide">Per-test-case results</h3>
      <div className="panel overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-xs uppercase tracking-wide">
              <th className="text-left font-medium px-4 py-3">Test case</th>
              <th className="text-left font-medium px-4 py-3">Status</th>
              <th className="text-left font-medium px-4 py-3">Scores</th>
              <th className="text-right font-medium px-4 py-3">Latency</th>
            </tr>
          </thead>
          <tbody>
            {(results || []).map((r) => (
              <tr key={r.id} className="border-b border-border/50 last:border-0">
                <td className="px-4 py-3 mono text-xs">{r.test_case_id.slice(0, 8)}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-4 py-3 text-xs">
                  {r.scores.map((s) => (
                    <span key={s.scorer_name} className="mono mr-3">
                      {s.scorer_name}=
                      <span className={s.error ? "text-fail" : "text-accent"}>
                        {s.error ? "err" : s.numeric_value?.toFixed(2) ?? String(s.boolean_value)}
                      </span>
                    </span>
                  ))}
                </td>
                <td className="px-4 py-3 text-right mono text-xs">{r.latency_ms ?? "—"}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
