# Example: Support Agent

A minimal, fully working agent used to demo AgentEval end-to-end.

## Run it standalone

```bash
cd examples/example-support-agent
python agent.py
```

## Evaluate it locally (no server required)

```bash
cd ../../backend
pip install -e ".[cli]"
agenteval run --config ../examples/example-support-agent/agenteval.yaml --local --gate
```

## Send a real trace to a running AgentEval server

```bash
export AGENTEVAL_API_KEY=ae_live_...   # from `make seed`
python agent.py
```

Then open the dashboard's Traces page to see the instrumented run,
including its retrieval and "LLM call" spans.
