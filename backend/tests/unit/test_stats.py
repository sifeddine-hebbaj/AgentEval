from agenteval_core.stats import bootstrap_paired_delta


def test_no_difference_not_significant():
    baseline = [0.8, 0.9, 0.85, 0.82, 0.88] * 4
    new = [0.8, 0.9, 0.85, 0.82, 0.88] * 4
    result = bootstrap_paired_delta(baseline, new, iterations=500)
    assert result.significant is False
    assert result.mean_delta == 0.0


def test_clear_large_regression_is_significant():
    baseline = [0.9] * 30
    new = [0.5] * 30
    result = bootstrap_paired_delta(baseline, new, iterations=500)
    assert result.significant is True
    assert result.mean_delta < -0.3


def test_false_positive_rate_on_pure_noise_is_bounded():
    # A 95%-confidence significance test is *expected* to flag a true null
    # (no real difference) as "significant" about 5% of the time by chance
    # -- that's what "95% confidence" means. So instead of asserting a
    # single seed is never flagged (which would itself be statistically
    # incorrect and flaky), we check the false-positive rate across many
    # independent trials stays in the expected ballpark, well below the
    # rate we'd see if the function were biased/broken.
    import random

    flagged = 0
    trials = 40
    for trial_seed in range(trials):
        rng = random.Random(trial_seed)
        baseline = [0.85 + rng.uniform(-0.05, 0.05) for _ in range(40)]
        new = [0.85 + rng.uniform(-0.05, 0.05) for _ in range(40)]
        result = bootstrap_paired_delta(baseline, new, iterations=300, seed=trial_seed)
        if result.significant:
            flagged += 1

    false_positive_rate = flagged / trials
    assert false_positive_rate < 0.20  # generous margin above the ~5% expected rate


def test_mismatched_lengths_raises():
    import pytest

    with pytest.raises(ValueError):
        bootstrap_paired_delta([0.1, 0.2], [0.1])


def test_empty_input_handled_gracefully():
    result = bootstrap_paired_delta([], [])
    assert result.significant is False
    assert result.mean_delta == 0.0
