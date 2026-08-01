"""AgentEval CLI.

Exit code contract (see SRS section 10.3):
  0 = gate passed
  1 = gate failed (regression / threshold breach)
  2 = infrastructure/config error (never conflated with a real gate failure)
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from agenteval_cli.config import AgentEvalConfig
from agenteval_cli.gate import evaluate_gate
from agenteval_core.engine import EvalEngine
from agenteval_core.scorers import registry as core_registry
from agenteval_sdk.local_repository import SQLiteEvalResultRepository

# Load environment variables from .env file
load_dotenv()

app = typer.Typer(add_completion=False, help="AgentEval: agent evaluation & regression testing CLI")
console = Console()


def _get_api_client():
    """Get HTTP client for API interactions."""
    api_key = os.environ.get("AGENTEVAL_API_KEY")
    base_url = os.environ.get("AGENTEVAL_BASE_URL", "http://localhost:8000")
    if not api_key:
        console.print("[red]AGENTEVAL_API_KEY environment variable is required for remote mode[/red]")
        raise typer.Exit(code=2)
    return httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}), api_key


def _load_dataset(path: str):
    from agenteval_core.models import Dataset

    if path.endswith(".jsonl"):
        return Dataset.from_jsonl(path)
    if path.endswith(".csv"):
        return Dataset.from_csv(path)
    raise typer.BadParameter(f"Unsupported dataset format: {path} (expected .jsonl or .csv)")


def _make_runner(runner_spec: str):
    """runner_spec is either a shell command (invoked with the test-case
    input piped on stdin, expects JSON-encoded output on stdout) or a
    Python import path 'module:function'.
    """
    if ":" in runner_spec and not runner_spec.strip().startswith(("python ", "./", "/")):
        module_name, func_name = runner_spec.split(":", 1)
        try:
            module = importlib.import_module(module_name)
            return getattr(module, func_name)
        except (ImportError, AttributeError) as exc:
            console.print(f"[red]Could not load runner '{runner_spec}': {exc}[/red]")
            raise typer.Exit(code=2)

    def shell_runner(input_value):
        # Set environment variables for the subprocess
        env = os.environ.copy()
        mistral_key = os.environ.get('MISTRAL_API_KEY')
        if not mistral_key:
            raise ValueError("MISTRAL_API_KEY environment variable is not set")
        env['MISTRAL_API_KEY'] = mistral_key
        result = subprocess.run(
            runner_spec, shell=True, input=json.dumps(input_value), capture_output=True, text=True, timeout=60, env=env
        )
        if result.returncode != 0:
            raise RuntimeError(f"runner exited {result.returncode}: {result.stderr.strip()[:500]}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.strip()

    return shell_runner


def _build_scorers(config: AgentEvalConfig) -> list:
    scorers = []
    for sc in config.scorers:
        try:
            scorer = core_registry.create(sc.type, **sc.config)
            # Use the config name for scoring keys to match gate expectations
            scorer.name = sc.name
            scorers.append(scorer)
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2)
    return scorers


def _build_scorers_for_remote(config: AgentEvalConfig) -> list:
    """Build scorers for remote evaluation - use scorer_type as name for consistency"""
    scorers = []
    for sc in config.scorers:
        try:
            scorer = core_registry.create(sc.type, **sc.config)
            # Use scorer_type as name for consistency with server-side scoring
            scorer.name = sc.type
            scorers.append(scorer)
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2)
    return scorers


def _map_scorer_names(aggregate: dict, config: AgentEvalConfig) -> dict:
    """Map scorer_type names back to config names for gate evaluation"""
    name_map = {sc.type: sc.name for sc in config.scorers}
    mapped_aggregate = aggregate.copy()
    
    # Map mean_scores
    if "mean_scores" in mapped_aggregate:
        mapped_aggregate["mean_scores"] = {
            name_map.get(k, k): v for k, v in mapped_aggregate["mean_scores"].items()
        }
    
    # Map median_scores
    if "median_scores" in mapped_aggregate:
        mapped_aggregate["median_scores"] = {
            name_map.get(k, k): v for k, v in mapped_aggregate["median_scores"].items()
        }
    
    return mapped_aggregate


def _render_results_table(aggregate: dict) -> None:
    table = Table(title="Evaluation Results")
    table.add_column("Scorer")
    table.add_column("Mean Score", justify="right")
    table.add_column("Median Score", justify="right")
    for name, value in aggregate.get("mean_scores", {}).items():
        median = aggregate.get("median_scores", {}).get(name, "-")
        table.add_row(name, f"{value:.3f}", f"{median}")
    console.print(table)
    console.print(
        f"Pass rate: [bold]{aggregate.get('pass_rate', 0):.1%}[/bold]  |  "
        f"Errors: {aggregate.get('error_count', 0)}  |  "
        f"p50: {aggregate.get('p50_latency_ms', 0)}ms  p95: {aggregate.get('p95_latency_ms', 0)}ms"
    )


def _run_remote_evaluation(config: AgentEvalConfig, dataset, scorers, runner):
    """Execute remote evaluation via AgentEval API."""
    client, _api_key = _get_api_client()

    # 1. Run the agent locally to get outputs (similar to local mode)
    console.print("[cyan]Step 1: Running agent locally to generate outputs...[/cyan]")
    # Use scorers with scorer_type names for consistency with server
    remote_scorers = _build_scorers_for_remote(config)
    repo = SQLiteEvalResultRepository()
    engine = EvalEngine(repo, remote_scorers)
    try:
        summary = engine.run(dataset, runner)
    except Exception as exc:
        console.print(f"[red]Agent execution failed: {exc}[/red]")
        raise typer.Exit(code=2)
    
    # Collect the actual outputs from the run summary
    precomputed_outputs = {}
    run_results = repo.get_run_results(summary.id)
    for result in run_results:
        precomputed_outputs[str(result.test_case_id)] = result.actual_output
    
    console.print(f"[green]Generated {len(precomputed_outputs)} agent outputs[/green]")
    
    # 2. Get project_id from first dataset (API key is project-scoped)
    console.print("[cyan]Step 2: Getting project from first dataset...[/cyan]")
    datasets_response = client.get("/v1/datasets")
    datasets_response.raise_for_status()
    datasets = datasets_response.json()
    
    if not datasets:
        console.print("[red]No datasets found. Please run: python -m agenteval_api.seed[/red]")
        raise typer.Exit(code=2)
    
    # Extract project_id from the first dataset
    project_id = datasets[0]["project_id"]
    console.print(f"[green]Project ID: {project_id}[/green]")
    
    # 3. Get or create dataset
    console.print("[cyan]Step 3: Getting/creating dataset...[/cyan]")
    dataset_id = None
    for ds in datasets:
        if ds["name"] == config.project:
            dataset_id = ds["id"]
            break
    
    if not dataset_id:
        console.print(f"[cyan]Creating new dataset: {config.project}[/cyan]")
        dataset_response = client.post(
            "/v1/datasets",
            json={"project_id": project_id, "name": config.project, "description": f"Dataset for {config.project}"}
        )
        dataset_response.raise_for_status()
        dataset_data = dataset_response.json()
        dataset_id = dataset_data["id"]
    
    console.print(f"[green]Dataset ID: {dataset_id}[/green]")
    
    # 4. Create or reuse dataset version
    console.print("[cyan]Step 4: Checking for existing dataset version with same test cases...[/cyan]")
    test_cases = [{"input": tc.input, "expected_output": tc.expected_output} for tc in dataset.test_cases]
    
    # Get existing versions to check for matching test cases
    versions_response = client.get(f"/v1/datasets/{dataset_id}/versions")
    versions_response.raise_for_status()
    versions_data = versions_response.json()
    
    dataset_version_id = None
    for version in versions_data:
        # Fetch version details to compare test cases
        version_detail_response = client.get(f"/v1/datasets/{dataset_id}/versions/{version['id']}")
        version_detail_response.raise_for_status()
        version_detail = version_detail_response.json()
        
        # Compare test cases
        existing_test_cases = version_detail.get("test_cases", [])
        if len(existing_test_cases) == len(test_cases):
            # Check if test cases match
            match = True
            for i, tc in enumerate(test_cases):
                if i >= len(existing_test_cases):
                    match = False
                    break
                if existing_test_cases[i]["input"] != tc["input"] or existing_test_cases[i]["expected_output"] != tc["expected_output"]:
                    match = False
                    break
            
            if match:
                dataset_version_id = version["id"]
                console.print(f"[green]Reusing existing dataset version: {dataset_version_id}[/green]")
                break
    
    if dataset_version_id is None:
        # Create new dataset version if no matching one exists
        console.print("[cyan]Creating new dataset version...[/cyan]")
        version_response = client.post(
            f"/v1/datasets/{dataset_id}/versions",
            json={"test_cases": test_cases}
        )
        version_response.raise_for_status()
        version_data = version_response.json()
        dataset_version_id = version_data["id"]
        console.print(f"[green]Created new dataset version: {dataset_version_id}[/green]")
    
    console.print(f"[green]Dataset Version ID: {dataset_version_id}[/green]")
    
    # Fetch the created dataset version to get the actual test case IDs
    version_detail_response = client.get(f"/v1/datasets/{dataset_id}/versions/{dataset_version_id}")
    version_detail_response.raise_for_status()
    version_detail = version_detail_response.json()
    
    # Map local test case indices to server test case IDs
    server_test_case_ids = [tc["id"] for tc in version_detail["test_cases"]]
    
    # Rebuild precomputed_outputs with server test case IDs
    local_outputs = list(precomputed_outputs.values())
    precomputed_outputs_server = {}
    for i, server_id in enumerate(server_test_case_ids):
        if i < len(local_outputs):
            precomputed_outputs_server[str(server_id)] = local_outputs[i]
    
    console.print(f"[green]Mapped {len(precomputed_outputs_server)} outputs to server test case IDs[/green]")
    
    # 5. Create a simple eval suite with basic scorer
    console.print("[cyan]Step 5: Creating eval suite...[/cyan]")
    # For simplicity, create a single scorer and suite
    sc = config.scorers[0]
    
    # Determine the correct output_type based on scorer type
    # Boolean scorers: contains, exact_match, regex_match, json_schema_valid
    # Numeric scorers: levenshtein_similarity
    boolean_scorers = {"contains", "exact_match", "regex_match", "json_schema_valid"}
    output_type = "boolean" if sc.type in boolean_scorers else "numeric"
    
    # Use the scorer type as the name to match the registry key
    scorer_name = sc.type  # Use type (e.g., "contains") instead of config name (e.g., "contains_check")
    
    # Check for existing scorer with same configuration to enable baseline comparison
    console.print("[cyan]Checking for existing scorer with same configuration...[/cyan]")
    scorers_response = client.get(
        "/v1/scorers",
        params={"project_id": project_id}
    )
    scorers_response.raise_for_status()
    scorers_data = scorers_response.json()
    
    console.print(f"[yellow]Looking for scorer with: type={sc.type}, name={scorer_name}, output_type={output_type}, config={sc.config or {}}[/yellow]")
    console.print(f"[yellow]Found {len(scorers_data)} existing scorers[/yellow]")
    
    scorer_version_id = None
    for i, scorer in enumerate(scorers_data):
        console.print(f"[yellow]Scorer {i}: id={scorer.get('id')}, type={scorer.get('scorer_type')}, name={scorer.get('name')}, output_type={scorer.get('output_type')}, config={scorer.get('config')}[/yellow]")
        # Check if this scorer has the same type, name, and config
        type_match = scorer.get("scorer_type") == sc.type
        # Be lenient about name matching since it might be None in some cases
        name_match = scorer.get("name") == scorer_name or scorer.get("name") is None
        output_type_match = scorer.get("output_type") == output_type
        config_match = scorer.get("config") == (sc.config or {})
        
        console.print(f"[yellow]  - type_match={type_match}, name_match={name_match}, output_type_match={output_type_match}, config_match={config_match}[/yellow]")
        
        if type_match and name_match and output_type_match and config_match:
            scorer_version_id = scorer["id"]
            console.print(f"[green]Reusing existing scorer version: {scorer_version_id}[/green]")
            break
    
    if scorer_version_id is None:
        # Create new scorer if no matching one exists
        scorer_response = client.post(
            "/v1/scorers",
            json={
                "project_id": project_id,
                "name": scorer_name,
                "scorer_type": sc.type,
                "config": sc.config or {},
                "output_type": output_type
            }
        )
        scorer_response.raise_for_status()
        scorer_data = scorer_response.json()
        console.print(f"[green]Created new scorer: {scorer_data}[/green]")
        scorer_version_id = scorer_data["id"]  # The POST returns the version ID directly
    
    console.print(f"[yellow]Final scorer_version_id for eval suite lookup: {scorer_version_id}[/yellow]")
    
    # Check for existing eval suite with same scorer configuration to enable baseline comparison
    console.print("[cyan]Checking for existing eval suite with same configuration...[/cyan]")
    suites_response = client.get(
        "/v1/eval-suites",
        params={"project_id": project_id}
    )
    suites_response.raise_for_status()
    suites_data = suites_response.json()
    
    console.print(f"[yellow]Looking for eval suite with scorer_version_ids=[{scorer_version_id}][/yellow]")
    console.print(f"[yellow]Found {len(suites_data)} existing eval suites[/yellow]")
    
    suite_id = None
    for i, suite in enumerate(suites_data):
        suite_scorer_ids = suite.get("scorer_version_ids", [])
        console.print(f"[yellow]Suite {i}: id={suite.get('id')}, scorer_version_ids={suite_scorer_ids}[/yellow]")
        # Check if this suite has the same scorer configuration
        if len(suite_scorer_ids) == 1 and suite_scorer_ids[0] == scorer_version_id:
            suite_id = suite["id"]
            console.print(f"[green]Reusing existing eval suite: {suite_id}[/green]")
            break
    
    if suite_id is None:
        # Create new eval suite if no matching one exists
        suite_response = client.post(
            "/v1/eval-suites",
            json={
                "project_id": project_id,
                "name": config.project,
                "scorer_version_ids": [scorer_version_id],
                "critical_scorer_version_ids": [scorer_version_id] if sc.is_critical else []
            }
        )
        suite_response.raise_for_status()
        suite_data = suite_response.json()
        suite_id = suite_data["id"]
        console.print(f"[green]Created new eval suite: {suite_id}[/green]")
    
    console.print(f"[green]Eval Suite ID: {suite_id}[/green]")
    
    # 6. Trigger evaluation run with precomputed outputs
    console.print("[cyan]Step 6: Triggering evaluation run with precomputed outputs...[/cyan]")
    run_response = client.post(
        "/v1/eval-runs",
        json={
            "dataset_version_id": dataset_version_id,
            "eval_suite_id": suite_id,
            "precomputed_outputs": precomputed_outputs_server
        }
    )
    run_response.raise_for_status()
    run_data = run_response.json()
    run_id = run_data["id"]
    console.print(f"[green]Run ID: {run_id}[/green]")
    
    # 7. Poll for completion
    console.print("[cyan]Step 7: Polling for completion...[/cyan]")
    with Progress() as progress:
        task = progress.add_task("[cyan]Waiting for evaluation to complete...", total=None)
        
        while True:
            status_response = client.get(f"/v1/eval-runs/{run_id}")
            status_response.raise_for_status()
            run_data = status_response.json()
            status = run_data["status"]
            
            if status.lower() in ["completed", "failed"]:
                progress.update(task, completed=True)
                break
            
            progress.update(task, description=f"[cyan]Status: {status} ({run_data['completed_test_cases']}/{run_data['total_test_cases']})")
            time.sleep(2)
    
    console.print(f"[green]Evaluation completed with status: {status}[/green]")
    
    # 8. Get results
    console.print("[cyan]Step 8: Fetching results...[/cyan]")
    results_response = client.get(f"/v1/eval-runs/{run_id}/results")
    results_response.raise_for_status()
    results = results_response.json()
    
    # Convert to aggregate metrics format
    aggregate = run_data.get("aggregate_metrics", {})
    
    # Map scorer names from scorer_type back to config names for gate evaluation
    aggregate = _map_scorer_names(aggregate, config)
    
    console.print(f"[green]Fetched {len(results)} test case results[/green]")
    
    return aggregate, None


@app.command()
def run(
    config_path: str = typer.Option("agenteval.yaml", "--config", "-c", help="Path to agenteval.yaml"),
    dataset_override: str | None = typer.Option(None, "--dataset", help="Override dataset path from config"),
    local: bool = typer.Option(True, "--local/--remote", help="Run fully locally (SQLite) vs. against a server"),
    gate: bool = typer.Option(False, "--gate", help="Apply gate policy and exit non-zero on failure"),
    report_file: str | None = typer.Option(None, "--report-file", help="Write a JSON report to this path"),
) -> None:
    """Run an evaluation against a dataset using the scorers/gate policy
    defined in agenteval.yaml.
    """
    if not Path(config_path).exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        raise typer.Exit(code=2)

    try:
        config = AgentEvalConfig.from_yaml(config_path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    dataset_path = dataset_override or config.dataset
    try:
        dataset = _load_dataset(dataset_path)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]Could not load dataset: {exc}[/red]")
        raise typer.Exit(code=2)

    scorers = _build_scorers(config)
    if not scorers:
        console.print("[red]No scorers configured in agenteval.yaml[/red]")
        raise typer.Exit(code=2)

    runner = _make_runner(config.runner)

    if local:
        repo = SQLiteEvalResultRepository()
        engine = EvalEngine(repo, scorers)
        try:
            summary = engine.run(dataset, runner)
        except Exception as exc:  # infra-level failure (e.g. runner totally broken), not a gate failure
            console.print(f"[red]Evaluation run failed to execute: {exc}[/red]")
            raise typer.Exit(code=2)
        aggregate = summary.aggregate_metrics
        diff = None
    else:
        console.print("[cyan]Running remote evaluation...[/cyan]")
        try:
            aggregate, diff = _run_remote_evaluation(config, dataset, scorers, runner)
        except Exception as exc:
            console.print(f"[red]Remote evaluation failed: {exc}[/red]")
            raise typer.Exit(code=2)

    _render_results_table(aggregate)

    report = {"aggregate_metrics": aggregate, "config": config.model_dump()}
    if report_file:
        Path(report_file).write_text(json.dumps(report, indent=2, default=str))
        console.print(f"Report written to {report_file}")

    if not gate:
        return

    decision = evaluate_gate(aggregate, config.gate, diff)
    for reason in decision.reasons:
        style = "green" if decision.passed else "red"
        console.print(f"[{style}]- {reason}[/{style}]")

    if decision.passed:
        console.print("[bold green]GATE PASSED[/bold green]")
        raise typer.Exit(code=0)
    else:
        console.print("[bold red]GATE FAILED[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def scorers() -> None:
    """List all registered built-in scorers."""
    for name in core_registry.names():
        console.print(f"  - {name}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
