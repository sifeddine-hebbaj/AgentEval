/**
 * Typed API client. Mirrors backend/agenteval_api/schemas/schemas.py.
 *
 * NOTE: these types are hand-maintained to keep this reference dashboard
 * dependency-light. For a larger team, wire up `openapi-typescript`
 * against the backend's /openapi.json (see README "Extending the
 * Frontend") so these can never silently drift from the server.
 */

const BASE_URL = "";

export type TraceSummary = {
  id: string;
  environment: string;
  status: string;
  total_tokens: number;
  total_cost: number;
  duration_ms: number | null;
  started_at: string;
  ended_at: string | null;
};

export type SpanOut = {
  id: string;
  parent_span_id: string | null;
  span_type: string;
  name: string;
  input: unknown;
  output: unknown;
  model_name: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number;
  status: string;
  error_message: string | null;
  started_at: string;
  ended_at: string | null;
};

export type TraceDetail = TraceSummary & { spans: SpanOut[]; metadata: Record<string, unknown> };

export type Dataset = { id: string; name: string; description: string; created_at: string };
export type DatasetVersion = {
  id: string;
  dataset_id: string;
  version_number: number;
  test_case_count: number;
  created_at: string;
};

export type EvalRun = {
  id: string;
  status: string;
  total_test_cases: number;
  completed_test_cases: number;
  aggregate_metrics: {
    mean_scores?: Record<string, number>;
    median_scores?: Record<string, number>;
    pass_rate?: number;
    error_count?: number;
    p50_latency_ms?: number;
    p95_latency_ms?: number;
  };
  started_at: string;
  completed_at: string | null;
};

export type ScoreOut = {
  scorer_name: string;
  numeric_value: number | null;
  boolean_value: boolean | null;
  category_value: string | null;
  rationale: string | null;
  error: string | null;
};

export type EvalResultOut = {
  id: string;
  test_case_id: string;
  test_case_input: unknown;
  test_case_expected_output: unknown;
  actual_output: unknown;
  status: string;
  latency_ms: number | null;
  scores: ScoreOut[];
};

export type RegressedCase = {
  test_case_id: string;
  scorer: string;
  baseline_score: number | null;
  new_score: number | null;
};

export type SignificanceEntry = {
  mean_delta: number;
  ci_low: number;
  ci_high: number;
  significant: boolean;
  p_value_approx: number;
};

export type EvalRunDiff = {
  run_id: string;
  baseline_id: string;
  aggregate_delta: Record<string, number>;
  regressed_cases: RegressedCase[];
  improved_cases: RegressedCase[];
  significance: Record<string, SignificanceEntry>;
};

export type TrendPoint = {
  run_id: string;
  completed_at: string | null;
  mean_scores: Record<string, number>;
  pass_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

function getAuth(): { apiKey: string } {
  const apiKey = localStorage.getItem("agenteval_api_key") || "";
  return { apiKey };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { apiKey } = getAuth();
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  setApiKey(key: string) {
    localStorage.setItem("agenteval_api_key", key);
  },
  clearApiKey() {
    localStorage.removeItem("agenteval_api_key");
  },
  hasApiKey() {
    return !!localStorage.getItem("agenteval_api_key");
  },

  listTraces: (environment?: string) =>
    request<TraceSummary[]>(`/v1/traces${environment ? `?environment=${environment}` : ""}`),
  getTrace: (id: string) => request<TraceDetail>(`/v1/traces/${id}`),

  listDatasets: () => request<Dataset[]>("/v1/datasets"),
  createDataset: (project_id: string, name: string, description = "") =>
    request<Dataset>("/v1/datasets", { method: "POST", body: JSON.stringify({ project_id, name, description }) }),
  listDatasetVersions: (datasetId: string) =>
    request<DatasetVersion[]>(`/v1/datasets/${datasetId}/versions`),
  createDatasetVersion: (datasetId: string, testCases: unknown[]) =>
    request<DatasetVersion>(`/v1/datasets/${datasetId}/versions`, {
      method: "POST",
      body: JSON.stringify({ test_cases: testCases }),
    }),

  listEvalRuns: () => request<EvalRun[]>("/v1/eval-runs"),
  getEvalRun: (id: string) => request<EvalRun>(`/v1/eval-runs/${id}`),
  getEvalRunResults: (id: string) => request<EvalResultOut[]>(`/v1/eval-runs/${id}/results`),
  getEvalRunDiff: (id: string, baseline?: string) =>
    request<EvalRunDiff>(`/v1/eval-runs/${id}/diff${baseline ? `?baseline=${baseline}` : ""}`),
  setBaseline: (id: string) => request<void>(`/v1/eval-runs/${id}/set-baseline`, { method: "POST" }),

  getTrends: () => request<TrendPoint[]>("/v1/metrics/trends"),
};

export { ApiError };
