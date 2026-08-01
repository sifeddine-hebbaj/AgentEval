import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Traces from "./pages/Traces";
import Datasets from "./pages/Datasets";
import EvalRuns from "./pages/EvalRuns";
import EvalRunDetail from "./pages/EvalRunDetail";
import Trends from "./pages/Trends";
import ResultsDashboard from "./pages/ResultsDashboard";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!api.hasApiKey()) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/traces" element={<Traces />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/eval-runs" element={<EvalRuns />} />
        <Route path="/eval-runs/:runId" element={<EvalRunDetail />} />
        <Route path="/results" element={<ResultsDashboard />} />
        <Route path="/trends" element={<Trends />} />
        <Route path="/" element={<Navigate to="/traces" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/traces" replace />} />
    </Routes>
  );
}
