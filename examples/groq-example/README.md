# Groq Chat Assistant - Complete AgentEval Demo

This is a comprehensive end-to-end demo of AgentEval, featuring a simple Groq chat assistant with full SDK instrumentation, trace collection, and evaluation capabilities.

## Overview

This demo showcases:
- **Real LLM Integration**: Uses Groq's openai/gpt-oss-120b for actual chat responses
- **Complete SDK Instrumentation**: Full traces and spans for the agent workflow
- **Token & Cost Tracking**: Automatic tracking of prompt/completion tokens and costs
- **Dual Evaluation Modes**: Both local (SQLite) and remote (Postgres+Redis) evaluation
- **Gate Policy**: Configurable quality gates with regression detection
- **Realistic Dataset**: 9 test cases across multiple categories

## Prerequisites

### Required
- Python 3.10+
- Docker and Docker Compose
- Groq API key (get one at https://console.groq.com/)

### For Remote Mode
- Running PostgreSQL, Redis, and AgentEval API (via Docker Compose)

## Quick Start

### 1. Set Environment Variables

**Option A: Using .env file (recommended)**
```bash
cd C:\Users\sifeddine\Desktop\agenteval\examples\groq-example
# The .env file already contains the Groq API key
# Just update AGENTEVAL_API_KEY and AGENTEVAL_BASE_URL when you have them
```

**Option B: Using environment variables**
```bash
# Groq API key (required for the chat assistant)
export GROQ_API_KEY=your_groq_api_key_here

# AgentEval credentials (for remote mode - get these after starting the server)
export AGENTEVAL_API_KEY=your_agenteval_api_key_here
export AGENTEVAL_BASE_URL=http://localhost:8000
```

### 2. Install Dependencies

```bash
cd C:\Users\sifeddine\Desktop\agenteval\backend
pip install -e ".[sdk,cli]"
pip install groq
```

This installs the AgentEval SDK, CLI, and Groq client library.

### 3. Test the Agent (Standalone Demo)

```bash
cd C:\Users\sifeddine\Desktop\agenteval\examples\groq-example
python agent.py
```

Expected output:
```
WARNING: AGENTEVAL_API_KEY not set - running without tracing

Running chat assistant without AgentEval SDK...

Assistant: Paris
```

### 4. Start the Infrastructure (for Remote Mode)

```bash
cd C:\Users\sifeddine\Desktop\agenteval
docker compose up -d
```

This starts:
- PostgreSQL (database)
- Redis (Celery broker)
- AgentEval API (web server)
- Celery Worker (async task processing)
- Frontend (dashboard)

Wait for all services to be healthy (check with `docker compose ps`).

### 5. Create a Demo Project

```bash
# Access the API to create a project and get an API key
cd C:\Users\sifeddine\Desktop\agenteval\backend
python -m agenteval_api.seed
```

This will output something like:
```
===========================================================
Demo project created.
  project_id: 0763906d-554e-473e-bbfc-d9feeb1461e0
  api_key:    ae_live_e5TwjKqdwf3Sj7h1LeXySWc9A9_U9xRN7yd22fTOKt8
===========================================================
```

Use the `api_key` as your `AGENTEVAL_API_KEY`.

### 6. Run the Agent with Tracing

Update your `.env` file with the AgentEval credentials:
```bash
cd C:\Users\sifeddine\Desktop\agenteval\examples\groq-example
# Edit .env and add:
# AGENTEVAL_API_KEY=<key from step 5>
# AGENTEVAL_BASE_URL=http://localhost:8000
```

Then run:
```bash
python agent.py
```

Expected output:
```
Initializing AgentEval client...
Sending traced request to chat assistant...
Assistant: Paris
Flushing traces to AgentEval server...
Done! Check the dashboard to view the trace.
```

### 7. Verify Traces in Dashboard

1. Open http://localhost:8000 in your browser
2. Login with the API key from step 5
3. Navigate to the "Traces" tab
4. You should see a trace with:
   - A span of type `llm_call` named `groq_chat_completion`
   - Input: "What is the capital of France?"
   - Output: "Paris"
   - Token usage statistics
   - Cost information

## Evaluation Modes

### Local Mode (No Server Required)

Local mode uses SQLite and is perfect for development and quick iterations:

```bash
cd C:\Users\sifeddine\Desktop\agenteval
agenteval run --config examples/groq-example/agenteval.yaml --local
```

Expected output:
```
[INFO] Loading dataset from examples/groq-example/dataset.jsonl
[INFO] Loaded 9 test cases
[INFO] Running evaluation with 1 scorer: contains_check
Test case 1/9: PASS (contains: 1.0)
Test case 2/9: PASS (contains: 1.0)
...
[INFO] Evaluation complete
Score: 9/9 passed (100%)
contains: 1.00 mean
```

### Remote Mode (With Server)

Remote mode uses the full stack with PostgreSQL, Redis, and Celery:

```bash
cd C:\Users\sifeddine\Desktop\agenteval
agenteval run --config examples/groq-example/agenteval.yaml --remote
```

This will:
1. Upload the dataset to the server
2. Create a dataset version
3. Trigger an async evaluation run via Celery
4. Workers process each test case
5. Results are persisted to PostgreSQL

### Remote Mode with Gate

The gate enforces quality thresholds and fails if they're not met:

```bash
cd C:\Users\sifeddine\Desktop\agenteval
agenteval run --config examples/groq-example/agenteval.yaml --remote --gate
```

If the gate passes:
```
[INFO] Gate PASSED
[INFO] contains: 1.00 >= 0.8 ✓
```

If the gate fails:
```
[ERROR] Gate FAILED
[ERROR] contains: 0.70 < 0.8 ✗
[ERROR] Exit code: 1
```

## File Structure

```
examples/groq-example/
├── agent.py              # Main agent implementation with SDK instrumentation
├── dataset.jsonl         # 9 test cases with expected answers
├── run_for_eval.py       # CLI adapter for evaluation mode
├── run_wrapper.py        # Wrapper that sets API key for evaluation
├── agenteval.yaml        # Evaluation configuration
├── .env                  # Environment variables (GROQ_API_KEY, etc.)
└── README.md             # This file
```

## Agent Implementation Details

### Groq Integration

The agent uses the Groq Python SDK for LLM calls:

```python
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

response = groq_client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=messages,
    max_tokens=150,
    temperature=0.7,
)
```

### Tracing Instrumentation

The agent uses the AgentEval SDK to trace the complete workflow:

```python
@trace(client=client, name="groq_chat_assistant")
def _run(message: str, system: Optional[str]) -> str:
    with span(type="llm_call", name="groq_chat_completion", model=MODEL) as s:
        # ... Groq API call ...
        s.set_input(message)
        s.set_output(assistant_message)
        s.set_usage(prompt_tokens, completion_tokens, cost)
```

This creates:
- A **Trace** representing the entire agent invocation
- A **Span** of type `llm_call` for the Groq API call
- Metadata including model name, tokens, and cost

### Dataset Format

The dataset uses JSONL format (one JSON object per line):

```json
{"input": "What is the capital of France?", "expected_output": "Paris", "metadata": {"category": "geography", "difficulty": "easy"}, "tags": ["geography"]}
```

### Evaluation Configuration

The `agenteval.yaml` configures:
- **Scorers**: contains (weight 1.0, critical)
- **Gate Policy**: minimum mean scores and max regression delta
- **Critical Tags**: tags that, if failed, cause immediate gate failure

## Troubleshooting

### Issue: "GROQ_API_KEY not set"

**Solution**: Set the environment variable or add to .env:
```bash
export GROQ_API_KEY=your_groq_api_key_here
```

### Issue: "AGENTEVAL_API_KEY not set"

**Solution**: Start the server and seed a demo project:
```bash
docker compose up -d
python -m agenteval_api.seed
export AGENTEVAL_API_KEY=<key from output>
```

### Issue: "Connection refused" when running remote mode

**Solution**: Ensure the Docker services are running:
```bash
docker compose ps
docker compose up -d
```

### Issue: "ModuleNotFoundError: No module named 'groq'"

**Solution**: Install the Groq package:
```bash
pip install groq
```

### Issue: "ModuleNotFoundError: No module named 'agenteval_sdk'"

**Solution**: Install the package in development mode:
```bash
cd backend
pip install -e ".[sdk,cli]"
```

### Issue: Traces not appearing in dashboard

**Verification steps**:
1. Check that `AGENTEVAL_API_KEY` is set correctly
2. Check that `AGENTEVAL_BASE_URL` points to the correct server
3. Check the server logs: `docker compose logs api`
4. Ensure the agent calls `client.flush()` after the trace

### Issue: Gate failing unexpectedly

**Debug steps**:
1. Run without `--gate` first to see actual scores
2. Check the gate thresholds in `agenteval.yaml`
3. Review individual test case results to identify failures
4. Adjust thresholds if they're too strict for your use case

## Expected Outputs

### Standalone Agent Run (without tracing)
```
WARNING: AGENTEVAL_API_KEY not set - running without tracing

Running chat assistant without AgentEval SDK...

Assistant: Paris
```

### Standalone Agent Run (with tracing)
```
Initializing AgentEval client...
Sending traced request to chat assistant...
Assistant: Paris
Flushing traces to AgentEval server...
Done! Check the dashboard to view the trace.
```

### Local Evaluation
```
[INFO] Loading dataset from examples/groq-example/dataset.jsonl
[INFO] Loaded 9 test cases
[INFO] Running evaluation with 1 scorer: contains_check
Test case 1/9: PASS (contains: 1.0)
Test case 2/9: PASS (contains: 1.0)
...
[INFO] Evaluation complete
Score: 9/9 passed (100%)
contains: 1.00 mean
```

### Remote Evaluation
```
[INFO] Uploading dataset to server...
[INFO] Dataset version created: <version-id>
[INFO] Triggering remote evaluation run...
[INFO] Run ID: <run-id>
[INFO] Polling for completion...
[INFO] Evaluation complete: COMPLETED
Score: 9/9 passed (100%)
contains: 1.00 mean
```

### Dashboard Verification

1. **Traces Tab**:
   - Should show traces with `llm_call` spans
   - Each span shows model name (openai/gpt-oss-120b), token usage, and cost
   - Click on a trace to see detailed span information

2. **Datasets Tab**:
   - Should show the "groq-chat-assistant" dataset
   - Shows dataset versions with test case counts

3. **Eval Runs Tab**:
   - Shows evaluation runs with status, scores, and timestamps
   - Click on a run to see detailed results per test case

## CI/CD Integration

For CI/CD pipelines, use remote mode with the gate:

```yaml
# Example GitHub Actions workflow
- name: Set up Python
  uses: actions/setup-python@v4
  with:
    python-version: '3.11'

- name: Install dependencies
  run: |
    cd backend
    pip install -e ".[sdk,cli]"
    pip install groq

- name: Start infrastructure
  run: |
    docker compose up -d

- name: Seed demo project
  run: |
    cd backend
    python -m agenteval_api.seed

- name: Evaluate with AgentEval
  run: |
    export GROQ_API_KEY=${{ secrets.GROQ_API_KEY }}
    export AGENTEVAL_API_KEY=${{ secrets.AGENTEVAL_API_KEY }}
    agenteval run --config examples/groq-example/agenteval.yaml --remote --gate

- name: Teardown
  run: docker compose down
```

The gate will cause the pipeline to fail if quality thresholds aren't met.

## Next Steps

- **Modify the dataset**: Edit `dataset.jsonl` to add your own test cases
- **Add more scorers**: Configure semantic similarity, custom scorers, or LLM judges
- **Adjust gate policy**: Modify `agenteval.yaml` to set appropriate thresholds
- **Extend the agent**: Add more complex logic, RAG, or multi-step reasoning
- **Explore traces**: Use the dashboard to analyze agent behavior and identify bottlenecks
- **Try different Groq models**: Change `MODEL` to other Groq models like `llama-3.1-70b-versatile`

## Additional Resources

- [AgentEval Documentation](../../README.md)
- [SDK API Reference](../../backend/agenteval_sdk/README.md)
- [CLI Reference](../../backend/agenteval_cli/README.md)
- [Groq API Documentation](https://console.groq.com/docs)
- [Evaluation Best Practices](../../docs/evaluation-best-practices.md)
