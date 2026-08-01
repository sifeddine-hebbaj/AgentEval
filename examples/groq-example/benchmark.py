#!/usr/bin/env python3
"""
Benchmark mode for comparing multiple Groq models using AgentEval CLI.

Evaluates the same dataset using 5 different Groq models with identical settings,
then generates a comparison table showing performance metrics.
"""
import os
import sys
import json
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

# Model list to benchmark
MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b", 
    "qwen/qwen3.6-27b",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]

# Groq pricing (as of 2026, approximate)
PRICING = {
    "openai/gpt-oss-20b": {"prompt": 0.0001, "completion": 0.0002},
    "openai/gpt-oss-120b": {"prompt": 0.0005, "completion": 0.001},
    "qwen/qwen3.6-27b": {"prompt": 0.0001, "completion": 0.0002},
    "llama-3.1-8b-instant": {"prompt": 0.0, "completion": 0.0},  # Free tier
    "llama-3.3-70b-versatile": {"prompt": 0.0, "completion": 0.0},  # Free tier
}


@dataclass
class BenchmarkResult:
    """Results for a single model benchmark."""
    model: str
    pass_rate: float
    exact_match_score: float
    llm_judge_score: float
    overall_score: float
    median_score: float
    p50_latency_ms: float
    p95_latency_ms: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost: float
    avg_tokens_per_request: float
    regressed_cases: int
    improved_cases: int


def update_env_model(model: str, env_path: Path):
    """Update the GROQ_MODEL in .env file."""
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    with open(env_path, 'w') as f:
        for line in lines:
            if line.startswith('GROQ_MODEL='):
                f.write(f'GROQ_MODEL={model}\n')
            else:
                f.write(line)


def parse_agenteval_output(output: str) -> Dict[str, Any]:
    """Parse the output from agenteval run command."""
    result = {
        "pass_rate": 0.0,
        "exact_match_score": 0.0,
        "llm_judge_score": 0.0,
        "overall_score": 0.0,
        "median_score": 0.0,
        "p50_latency": 0.0,
        "p95_latency": 0.0,
        "error_count": 0,
    }
    
    # Parse pass rate
    pass_rate_match = re.search(r'Pass rate:\s*(\d+\.?\d*)%', output)
    if pass_rate_match:
        result["pass_rate"] = float(pass_rate_match.group(1)) / 100
    
    # Parse exact_match score from table format
    exact_match_match = re.search(r'\|\s*exact_match\s*\|\s*(\d+\.?\d*)\s*\|', output)
    if exact_match_match:
        result["exact_match_score"] = float(exact_match_match.group(1))
        result["overall_score"] = result["exact_match_score"]
    
    # Fallback: parse any scorer score if exact_match not found
    if result["exact_match_score"] == 0.0:
        scorer_match = re.search(r'\|\s*\w+\s*\|\s*(\d+\.?\d*)\s*\|', output)
        if scorer_match:
            result["exact_match_score"] = float(scorer_match.group(1))
            result["overall_score"] = result["exact_match_score"]
    
    # Parse median score from table format
    median_score_match = re.search(r'\|\s*\w+\s*\|\s*\d+\.?\d*\s*\|\s*(\d+\.?\d*)\s*\|', output)
    if median_score_match:
        result["median_score"] = float(median_score_match.group(1))
    
    # Parse latency
    latency_match = re.search(r'p50:\s*(\d+)ms\s*p95:\s*(\d+)ms', output)
    if latency_match:
        result["p50_latency"] = float(latency_match.group(1))
        result["p95_latency"] = float(latency_match.group(2))
    
    # Parse error count
    error_match = re.search(r'Errors:\s*(\d+)', output)
    if error_match:
        result["error_count"] = int(error_match.group(1))
    
    return result


def evaluate_model_with_agenteval(model: str, config_path: Path) -> BenchmarkResult:
    """Evaluate a single model using agenteval run command."""
    print(f"\n{'='*60}")
    print(f"Evaluating model: {model}")
    print(f"{'='*60}")
    
    # Update .env with the model
    env_path = Path(__file__).parent / ".env"
    update_env_model(model, env_path)
    print(f"Updated GROQ_MODEL to: {model}")
    
    # Run agenteval command directly
    cmd = [
        "agenteval", "run",
        "--config", str(config_path),
        "--remote",
        "--gate"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    # Set up environment with the updated .env file
    env = os.environ.copy()
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parent, env=env)
    
    if result.returncode != 0:
        print(f"Error running agenteval (return code {result.returncode})")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        return BenchmarkResult(
            model=model,
            pass_rate=0.0,
            exact_match_score=0.0,
            llm_judge_score=0.0,
            overall_score=0.0,
            median_score=0.0,
            p50_latency_ms=0.0,
            p95_latency_ms=0.0,
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_tokens=0,
            total_cost=0.0,
            avg_tokens_per_request=0.0,
            regressed_cases=0,
            improved_cases=0,
        )
    
    print(result.stdout)
    
    # Parse the output
    metrics = parse_agenteval_output(result.stdout)
    
    # Calculate estimated cost based on pricing
    # Since we don't get exact token counts from the CLI output, we'll estimate
    pricing = PRICING.get(model, {"prompt": 0.0, "completion": 0.0})
    # Estimate: assume ~150 tokens per request for 100 test cases
    estimated_tokens = 15000
    estimated_cost = estimated_tokens * (pricing["prompt"] + pricing["completion"]) / 2
    
    return BenchmarkResult(
        model=model,
        pass_rate=metrics["pass_rate"],
        exact_match_score=metrics["exact_match_score"],
        llm_judge_score=metrics["llm_judge_score"],
        overall_score=metrics["overall_score"],
        median_score=metrics["median_score"],
        p50_latency_ms=metrics["p50_latency"],
        p95_latency_ms=metrics["p95_latency"],
        total_prompt_tokens=0,  # Not available in CLI output
        total_completion_tokens=0,  # Not available in CLI output
        total_tokens=estimated_tokens,  # Estimated
        total_cost=estimated_cost,  # Estimated
        avg_tokens_per_request=estimated_tokens / 100,  # Estimated
        regressed_cases=0,  # Would need baseline comparison
        improved_cases=0,  # Would need baseline comparison
    )


def print_comparison_table(results: List[BenchmarkResult]):
    """Print a formatted comparison table sorted by overall score (worst to best)."""
    # Sort by overall score (ascending = worst to best)
    sorted_results = sorted(results, key=lambda x: x.overall_score)
    
    print("\n" + "="*140)
    print("BENCHMARK LEADERBOARD - COMPARISON TABLE")
    print("="*140)
    print(f"{'Model':<30} {'Pass Rate':<12} {'Exact Match':<13} {'LLM Judge':<12} {'Overall':<10} {'P50 Latency':<12} {'P95 Latency':<12} {'Total Tokens':<14} {'Cost ($)':<10}")
    print("-"*140)
    
    for result in sorted_results:
        print(
            f"{result.model:<30} "
            f"{result.pass_rate*100:>6.1f}%     "
            f"{result.exact_match_score:>6.3f}      "
            f"{result.llm_judge_score:>6.3f}   "
            f"{result.overall_score:>6.3f}  "
            f"{result.p50_latency_ms:>8.1f}ms   "
            f"{result.p95_latency_ms:>8.1f}ms   "
            f"{result.total_tokens:>8}      "
            f"${result.total_cost:>8.4f}"
        )
    
    print("="*140)
    
    # Print detailed breakdown
    print("\nDETAILED BREAKDOWN")
    print("="*140)
    for result in sorted_results:
        print(f"\nModel: {result.model}")
        print(f"  Pass Rate: {result.pass_rate*100:.1f}%")
        print(f"  Exact Match Score: {result.exact_match_score:.3f}")
        print(f"  LLM Judge Score: {result.llm_judge_score:.3f}")
        print(f"  Overall Score: {result.overall_score:.3f}")
        print(f"  Median Score: {result.median_score:.3f}")
        print(f"  P50 Latency: {result.p50_latency_ms:.1f}ms")
        print(f"  P95 Latency: {result.p95_latency_ms:.1f}ms")
        print(f"  Total Prompt Tokens: {result.total_prompt_tokens}")
        print(f"  Total Completion Tokens: {result.total_completion_tokens}")
        print(f"  Total Tokens: {result.total_tokens}")
        print(f"  Avg Tokens/Request: {result.avg_tokens_per_request:.1f}")
        print(f"  Total Cost: ${result.total_cost:.4f}")


def save_results_to_json(results: List[BenchmarkResult], output_path: str):
    """Save benchmark results to JSON file."""
    results_dict = [asdict(r) for r in results]
    with open(output_path, 'w') as f:
        json.dump(results_dict, f, indent=2)
    print(f"\nResults saved to: {output_path}")


def main():
    """Main benchmark function."""
    # Load environment variables from the groq-example .env file
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    
    # Also load from the project root .env for AGENTEVAL_API_KEY
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")
    
    # Check for required environment variables
    agenteval_api_key = os.environ.get("AGENTEVAL_API_KEY")
    if not agenteval_api_key:
        print("Error: AGENTEVAL_API_KEY environment variable is required")
        print("Please set it in the project root .env file")
        sys.exit(1)
    
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("Error: GROQ_API_KEY environment variable is required")
        print("Please set it in the groq-example .env file")
        sys.exit(1)
    
    # Config path
    config_path = Path(__file__).parent / "agenteval.yaml"
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    
    print(f"Using config: {config_path}")
    print(f"Benchmarking {len(MODELS)} models: {', '.join(MODELS)}")
    
    # Run benchmarks
    results = []
    for model in MODELS:
        try:
            result = evaluate_model_with_agenteval(model, config_path)
            results.append(result)
        except Exception as e:
            print(f"Error evaluating {model}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Print comparison table
    print_comparison_table(results)
    
    # Save results
    output_path = Path(__file__).parent / "benchmark_results.json"
    save_results_to_json(results, output_path)
    
    print("\nBenchmark complete!")


if __name__ == "__main__":
    main()
