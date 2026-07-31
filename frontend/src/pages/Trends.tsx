import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { api, TrendPoint } from "../api/client";

const COLORS = ["#4FD1C5", "#D4A72C", "#F85149", "#3FB950", "#8B98A5"];

export default function Trends() {
  const [trends, setTrends] = useState<TrendPoint[] | null>(null);

  useEffect(() => {
    api.getTrends().then(setTrends);
  }, []);

  if (trends === null) return <div className="p-8 text-muted text-sm">Loading…</div>;

  const scorerNames = Array.from(new Set(trends.flatMap((t) => Object.keys(t.mean_scores))));
  const chartData = trends.map((t, i) => ({
    idx: i + 1,
    ...t.mean_scores,
    pass_rate: t.pass_rate,
  }));
  const latencyData = trends.map((t, i) => ({ idx: i + 1, p50: t.p50_latency_ms, p95: t.p95_latency_ms }));

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="font-display text-2xl font-semibold mb-1">Trends</h1>
      <p className="text-muted text-sm mb-6">Score and latency history across completed eval runs.</p>

      {trends.length === 0 ? (
        <div className="panel p-10 text-center text-muted text-sm">
          No completed eval runs yet — trends appear once you have at least two.
        </div>
      ) : (
        <>
          <div className="panel p-5 mb-6">
            <h3 className="text-sm font-medium mb-4 text-muted uppercase tracking-wide">Mean score per scorer</h3>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#232B33" />
                <XAxis dataKey="idx" stroke="#8B98A5" fontSize={12} />
                <YAxis domain={[0, 1]} stroke="#8B98A5" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12181F", border: "1px solid #232B33" }} />
                <Legend />
                {scorerNames.map((name, i) => (
                  <Line key={name} type="monotone" dataKey={name} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="panel p-5">
            <h3 className="text-sm font-medium mb-4 text-muted uppercase tracking-wide">Latency (ms)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#232B33" />
                <XAxis dataKey="idx" stroke="#8B98A5" fontSize={12} />
                <YAxis stroke="#8B98A5" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12181F", border: "1px solid #232B33" }} />
                <Legend />
                <Line type="monotone" dataKey="p50" stroke="#4FD1C5" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="p95" stroke="#F85149" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
