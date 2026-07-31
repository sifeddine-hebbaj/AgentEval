"""Gate policy evaluation: pure function, no I/O, no rendering.

Kept deliberately separate from CLI output formatting (main.py) so this
same decision logic can be reused by the GitHub Action's PR-comment
renderer without duplicating the policy rules (see roadmap Task 1.5's
"compute vs render" note).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agenteval_cli.config import GateConfig


@dataclass
class GateDecision:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_gate(aggregate_metrics: dict, gate: GateConfig, diff: dict | None = None) -> GateDecision:
    reasons: list[str] = []
    passed = True

    mean_scores = aggregate_metrics.get("mean_scores", {})
    for scorer_name, min_score in gate.min_mean_score.items():
        actual = mean_scores.get(scorer_name)
        if actual is None:
            reasons.append(f"scorer '{scorer_name}' produced no scores (all errored?)")
            passed = False
        elif actual < min_score:
            reasons.append(f"'{scorer_name}' mean score {actual:.3f} is below required minimum {min_score:.3f}")
            passed = False

    if gate.max_p95_latency_ms is not None:
        p95 = aggregate_metrics.get("p95_latency_ms", 0)
        if p95 > gate.max_p95_latency_ms:
            reasons.append(f"p95 latency {p95}ms exceeds budget {gate.max_p95_latency_ms}ms")
            passed = False

    if diff is not None:
        significance = diff.get("significance", {})
        for scorer_name, sig in significance.items():
            delta = sig.get("mean_delta", 0)
            if sig.get("significant") and delta < -abs(gate.max_regression_delta):
                reasons.append(
                    f"significant regression in '{scorer_name}': delta={delta:.3f} "
                    f"(p={sig.get('p_value_approx')})"
                )
                passed = False

        for case in diff.get("regressed_cases", []):
            if case.get("tag") in gate.critical_tags:
                reasons.append(
                    f"critical-tagged test case '{case.get('test_case_id')}' regressed on "
                    f"'{case.get('scorer')}'"
                )
                passed = False

    if not reasons:
        reasons.append("all thresholds satisfied, no significant regressions detected")

    if gate.mode == "warn":
        return GateDecision(passed=True, reasons=reasons + (["(warn mode: not blocking)"] if not passed else []))

    return GateDecision(passed=passed, reasons=reasons)
