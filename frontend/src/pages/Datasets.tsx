import { FormEvent, useEffect, useState } from "react";
import { api, Dataset, DatasetVersion } from "../api/client";

export default function Datasets() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, DatasetVersion[]>>({});
  const [newName, setNewName] = useState("");
  const [projectId, setProjectId] = useState("");

  function refresh() {
    api.listDatasets().then(setDatasets);
  }

  useEffect(refresh, []);

  async function toggleExpand(id: string) {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    if (!versions[id]) {
      const v = await api.listDatasetVersions(id);
      setVersions((prev) => ({ ...prev, [id]: v }));
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim() || !projectId.trim()) return;
    await api.createDataset(projectId.trim(), newName.trim());
    setNewName("");
    refresh();
  }

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="font-display text-2xl font-semibold mb-1">Datasets</h1>
      <p className="text-muted text-sm mb-6">Versioned collections of test cases used for regression evaluation.</p>

      <form onSubmit={handleCreate} className="panel p-4 mb-6 flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs text-muted mb-1">Project ID</label>
          <input className="input w-full mono text-xs" value={projectId} onChange={(e) => setProjectId(e.target.value)} placeholder="uuid" />
        </div>
        <div className="flex-1">
          <label className="block text-xs text-muted mb-1">Dataset name</label>
          <input className="input w-full" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="support-qa" />
        </div>
        <button type="submit" className="btn-primary">
          Create dataset
        </button>
      </form>

      {datasets === null ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : datasets.length === 0 ? (
        <div className="panel p-10 text-center text-muted text-sm">
          No datasets yet. Create one above, or import via{" "}
          <code className="mono text-accent">agenteval_core.Dataset.from_jsonl(...)</code>.
        </div>
      ) : (
        <div className="space-y-2">
          {datasets.map((d) => (
            <div key={d.id} className="panel">
              <button
                onClick={() => toggleExpand(d.id)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/[0.02]"
              >
                <div>
                  <div className="font-medium text-sm">{d.name}</div>
                  {d.description && <div className="text-xs text-muted mt-0.5">{d.description}</div>}
                </div>
                <span className="text-muted text-xs mono">{expanded === d.id ? "▲" : "▼"}</span>
              </button>
              {expanded === d.id && (
                <div className="border-t border-border px-4 py-3">
                  <div className="text-xs text-muted uppercase tracking-wide mb-2">Version history</div>
                  {(versions[d.id] || []).map((v) => (
                    <div key={v.id} className="flex items-center justify-between py-1.5 text-sm">
                      <span className="mono text-accent">v{v.version_number}</span>
                      <span className="text-muted text-xs">{v.test_case_count} test cases</span>
                      <span className="mono text-xs text-muted">{v.id.slice(0, 8)}</span>
                    </div>
                  ))}
                  {(versions[d.id] || []).length === 0 && (
                    <p className="text-muted text-xs">
                      No versions yet — create one via <code className="mono text-accent">POST /v1/datasets/{d.id}/versions</code>.
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
