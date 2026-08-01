import { useEffect, useState } from "react";
import { api, EvalRun, EvalResultOut, ScoreOut } from "../api/client";
import StatusBadge from "../components/StatusBadge";

type TestCaseResult = EvalResultOut & {
  input: string;
  expected_output: string;
  actual_output: string;
  passed: boolean;
};

function scorePassed(score: ScoreOut): boolean {
  if (score.error) return false;
  if (score.boolean_value !== null) return score.boolean_value;
  if (score.numeric_value !== null) return score.numeric_value >= 0.5;
  if (score.category_value) {
    return ["pass", "true", "correct", "yes"].includes(score.category_value.toLowerCase());
  }
  return false;
}

function testCasePassed(result: Pick<EvalResultOut, "status" | "scores">): boolean {
  if (result.status === "error") return false;
  if (result.scores.length === 0) return false;
  return result.scores.every(scorePassed);
}

function formatScoreValue(score: ScoreOut): string {
  if (score.error) return "err";
  if (score.numeric_value !== null) return score.numeric_value.toFixed(2);
  if (score.boolean_value !== null) return score.boolean_value ? "pass" : "fail";
  if (score.category_value) return score.category_value;
  return "—";
}

function ScoreCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel p-4">
      <div className="text-xs text-muted uppercase tracking-wide mb-1">{label}</div>
      <div className="font-display text-xl font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function PassBadge({ passed }: { passed: boolean }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono border ${
        passed ? "text-pass border-pass/30 bg-pass/10" : "text-fail border-fail/30 bg-fail/10"
      }`}
    >
      {passed ? "PASS" : "FAIL"}
    </span>
  );
}

export default function ResultsDashboard() {
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [results, setResults] = useState<TestCaseResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadEvalRuns();
  }, []);

  const loadEvalRuns = async () => {
    try {
      setLoading(true);
      const runs = await api.listEvalRuns();
      setEvalRuns(runs);
      if (runs.length > 0) {
        await loadRunResults(runs[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load evaluation runs");
    } finally {
      setLoading(false);
    }
  };

  const loadRunResults = async (runId: string) => {
    try {
      setLoading(true);
      const [runDetails, runResults] = await Promise.all([
        api.getEvalRun(runId),
        api.getEvalRunResults(runId),
      ]);

      setSelectedRun(runDetails);

      const transformedResults: TestCaseResult[] = runResults.map((result) => ({
        ...result,
        input:
          typeof result.test_case_input === "string"
            ? result.test_case_input
            : JSON.stringify(result.test_case_input),
        expected_output:
          typeof result.test_case_expected_output === "string"
            ? result.test_case_expected_output
            : JSON.stringify(result.test_case_expected_output),
        actual_output:
          typeof result.actual_output === "string"
            ? result.actual_output
            : JSON.stringify(result.actual_output),
        passed: testCasePassed(result),
      }));

      setResults(transformedResults);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run results");
    } finally {
      setLoading(false);
    }
  };

  const passedCount = results.filter((r) => r.passed).length;
  const avgLatency = results.reduce((sum, r) => sum + (r.latency_ms || 0), 0) / results.length || 0;
  const aggregatePassRate = selectedRun?.aggregate_metrics.pass_rate;
  const passRate =
    aggregatePassRate != null
      ? aggregatePassRate * 100
      : results.length > 0
        ? (passedCount / results.length) * 100
        : 0;
  const passedDisplay =
    aggregatePassRate != null && selectedRun
      ? Math.round(aggregatePassRate * selectedRun.total_test_cases)
      : passedCount;
  const totalDisplay = selectedRun?.total_test_cases ?? results.length;
  const gatePassed = (aggregatePassRate ?? 0) >= 0.8;

  if (loading && evalRuns.length === 0) {
    return <div className="p-8 text-muted text-sm">Loading evaluation results…</div>;
  }

  if (error) {
    return (
      <div className="p-8 max-w-5xl">
        <div className="panel p-4 border-fail/30">
          <div className="text-fail text-sm">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-display text-2xl font-semibold">Results</h1>
        <button onClick={loadEvalRuns} className="btn-ghost text-xs">
          Refresh
        </button>
      </div>
      <p className="text-muted text-sm mb-6">
        Per-test-case outcomes, scores, and AI responses for completed eval runs.
      </p>

      {/* Evaluation Run Selector */}
      <div className="panel p-4 mb-6">
        <label className="block text-xs text-muted uppercase tracking-wide mb-2">
          Evaluation Run
        </label>
        <select
          value={selectedRun?.id || ""}
          onChange={(e) => loadRunResults(e.target.value)}
          className="input w-full"
        >
          {evalRuns.map((run) => (
            <option key={run.id} value={run.id}>
              {run.id.slice(0, 8)} — {run.status} ({run.completed_test_cases}/{run.total_test_cases})
            </option>
          ))}
        </select>
      </div>

      {/* Summary Metrics */}
      {selectedRun && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
          <ScoreCard
            label="Pass Rate"
            value={`${passRate.toFixed(1)}%`}
            sub={`${passedDisplay}/${totalDisplay} passed`}
          />
          <ScoreCard
            label="Avg Latency"
            value={`${avgLatency.toFixed(0)}ms`}
            sub="per request"
          />
          <div className="panel p-4">
            <div className="text-xs text-muted uppercase tracking-wide mb-1">Status</div>
            <StatusBadge status={selectedRun.status.toLowerCase()} />
            <div className="text-xs text-muted mt-2">
              {selectedRun.completed_test_cases}/{selectedRun.total_test_cases} cases
            </div>
          </div>
          <div className="panel p-4">
            <div className="text-xs text-muted uppercase tracking-wide mb-1">Gate Status</div>
            <div className={`font-display text-xl font-semibold ${gatePassed ? "text-pass" : "text-fail"}`}>
              {gatePassed ? "PASSED" : "FAILED"}
            </div>
            <div className="text-xs text-muted mt-0.5">Threshold: 80%</div>
          </div>
        </div>
      )}

      {/* Detailed Results Table */}
      <h3 className="text-sm font-medium mb-2 text-muted uppercase tracking-wide">
        Test Case Results
      </h3>
      <div className="panel overflow-hidden mb-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted text-xs uppercase tracking-wide">
                <th className="text-left font-medium px-4 py-3">Status</th>
                <th className="text-left font-medium px-4 py-3">Input</th>
                <th className="text-left font-medium px-4 py-3">Expected</th>
                <th className="text-left font-medium px-4 py-3">AI Response</th>
                <th className="text-left font-medium px-4 py-3">Score</th>
                <th className="text-right font-medium px-4 py-3">Latency</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr
                  key={result.test_case_id}
                  className="border-b border-border/50 last:border-0 hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3">
                    <PassBadge passed={result.passed} />
                  </td>
                  <td className="px-4 py-3 text-sm max-w-xs truncate">{result.input}</td>
                  <td className="px-4 py-3 text-sm text-muted max-w-xs truncate">
                    {result.expected_output}
                  </td>
                  <td className="px-4 py-3 text-sm max-w-md">
                    <div className="truncate" title={result.actual_output}>
                      {result.actual_output}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {result.scores.length > 0 && (
                      <div className="flex flex-col gap-1">
                        {result.scores.map((score, sIdx) => (
                          <div key={sIdx} className="mono">
                            <span className="text-muted">{score.scorer_name}:</span>{" "}
                            <span className={scorePassed(score) ? "text-pass" : "text-fail"}>
                              {formatScoreValue(score)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs text-muted">
                    {result.latency_ms ? `${result.latency_ms.toFixed(0)}ms` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AI Response Details */}
      {results.length > 0 && (
        <>
          <h3 className="text-sm font-medium mb-2 text-muted uppercase tracking-wide">
            AI Response Details
          </h3>
          <div className="space-y-3">
            {results.map((result, index) => (
              <div key={result.test_case_id} className="panel p-4">
                <div className="flex justify-between items-start mb-3">
                  <span className="text-sm font-medium">Test Case {index + 1}</span>
                  <PassBadge passed={result.passed} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-muted uppercase tracking-wide mb-1">Input</div>
                    <div>{result.input}</div>
                  </div>
                  <div>
                    <div className="text-xs text-muted uppercase tracking-wide mb-1">
                      Expected Output
                    </div>
                    <div>{result.expected_output}</div>
                  </div>
                  <div className="md:col-span-2">
                    <div className="text-xs text-muted uppercase tracking-wide mb-1">
                      AI Response
                    </div>
                    <div className="bg-base border border-border rounded-md p-3 text-sm">
                      {result.actual_output}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted uppercase tracking-wide mb-1">Latency</div>
                    <div className="mono text-xs">
                      {result.latency_ms ? `${result.latency_ms.toFixed(0)}ms` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted uppercase tracking-wide mb-1">Scores</div>
                    <div className="space-y-1">
                      {result.scores.map((score, sIdx) => (
                        <div key={sIdx} className="flex justify-between text-xs">
                          <span className="text-muted">{score.scorer_name}</span>
                          <span className={`mono ${scorePassed(score) ? "text-pass" : "text-fail"}`}>
                            {formatScoreValue(score)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
