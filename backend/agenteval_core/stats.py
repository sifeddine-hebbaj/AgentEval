"""Statistical significance testing for regression detection.

A naive "new mean < old mean" check on LLM-judge scores is noisy: LLM
outputs (and judge scores) are non-deterministic, so small deltas are
often sampling noise, not real regressions. We use a paired bootstrap
on the per-test-case score deltas to decide whether an observed drop
is likely real (see SRS section 9.4).
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class SignificanceResult:
    mean_delta: float
    ci_low: float
    ci_high: float
    significant: bool
    p_value_approx: float


def bootstrap_paired_delta(
    baseline_scores: list[float],
    new_scores: list[float],
    iterations: int = 1000,
    confidence: float = 0.95,
    seed: int | None = 42,
) -> SignificanceResult:
    """baseline_scores and new_scores must be aligned by test case
    (same index = same test case) and the same length.
    """
    if len(baseline_scores) != len(new_scores):
        raise ValueError("baseline_scores and new_scores must be the same length (paired)")
    n = len(baseline_scores)
    if n == 0:
        return SignificanceResult(0.0, 0.0, 0.0, False, 1.0)

    deltas = [new_scores[i] - baseline_scores[i] for i in range(n)]
    observed_mean = sum(deltas) / n

    rng = random.Random(seed)
    resampled_means: list[float] = []
    for _ in range(iterations):
        sample = [deltas[rng.randrange(n)] for _ in range(n)]
        resampled_means.append(sum(sample) / n)

    resampled_means.sort()
    lower_idx = int((1 - confidence) / 2 * iterations)
    upper_idx = int((1 - (1 - confidence) / 2) * iterations) - 1
    ci_low = resampled_means[max(0, lower_idx)]
    ci_high = resampled_means[min(iterations - 1, upper_idx)]

    significant = not (ci_low <= 0.0 <= ci_high)
    # Approximate two-sided p-value: fraction of bootstrap means on the
    # opposite side of zero from the observed mean, doubled.
    if observed_mean >= 0:
        p_approx = 2 * (sum(1 for m in resampled_means if m <= 0) / iterations)
    else:
        p_approx = 2 * (sum(1 for m in resampled_means if m >= 0) / iterations)
    p_approx = min(1.0, p_approx)

    return SignificanceResult(
        mean_delta=round(observed_mean, 4),
        ci_low=round(ci_low, 4),
        ci_high=round(ci_high, 4),
        significant=significant,
        p_value_approx=round(p_approx, 4),
    )
