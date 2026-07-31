"""AgentEval CLI.

Exit code contract (see SRS section 10.3):
  0 = gate passed
  1 = gate failed (regression / threshold breach)
  2 = infrastructure/config error (never conflated with a real gate failure)
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from agenteval_cli.config import AgentEvalConfig
from agenteval_cli.gate import evaluate_gate
from agenteval_core.engine import EvalEngine
from agenteval_core.scorers import registry as core_registry
from agenteval_sdk.local_repository import SQLiteEvalResultRepository

app = typer.Typer(add_completion=False, help="AgentEval: agent evaluation & regression testing CLI")
console = Console()


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
        result = subprocess.run(
            runner_spec, shell=True, input=json.dumps(input_value), capture_output=True, text=True, timeout=60
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
            scorers.append(core_registry.create(sc.type, **sc.config))
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2)
    return scorers


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


@app.command()
def run(
    config_path: str = typer.Option("agenteval.yaml", "--config", "-c", help="Path to agenteval.yaml"),
    dataset_override: Optional[str] = typer.Option(None, "--dataset", help="Override dataset path from config"),
    local: bool = typer.Option(True, "--local/--remote", help="Run fully locally (SQLite) vs. against a server"),
    gate: bool = typer.Option(False, "--gate", help="Apply gate policy and exit non-zero on failure"),
    report_file: Optional[str] = typer.Option(None, "--report-file", help="Write a JSON report to this path"),
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
        console.print(
            "[yellow]--remote mode requires a running AgentEval API; see README 'CI/CD Integration' "
            "section for the full remote-gate workflow (trigger + poll + diff).[/yellow]"
        )
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
