import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function Login() {
  const [apiKey, setApiKey] = useState("");
  const navigate = useNavigate();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    api.setApiKey(apiKey.trim());
    navigate("/traces");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="font-display text-2xl font-semibold tracking-tight">
            Agent<span className="text-accent">Eval</span>
          </div>
          <p className="text-muted text-sm mt-1">agent evaluation & regression testing console</p>
        </div>
        <form onSubmit={handleSubmit} className="panel p-6 space-y-4">
          <div>
            <label className="block text-xs text-muted mb-1.5">Project API Key</label>
            <input
              autoFocus
              type="password"
              className="input w-full mono"
              placeholder="ae_live_..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <button type="submit" className="btn-primary w-full">
            Connect
          </button>
          <p className="text-xs text-muted leading-relaxed">
            Create a key via <code className="mono text-accent">POST /v1/api-keys</code> (see README
            "Quickstart"), or run <code className="mono text-accent">make seed</code> for a demo key.
          </p>
        </form>
      </div>
    </div>
  );
}
