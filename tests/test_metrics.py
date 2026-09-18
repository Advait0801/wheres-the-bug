from __future__ import annotations

import pytest

from faultloc.metrics import (
    bootstrap_summary,
    paired_bootstrap,
    rank_of,
    reciprocal_rank,
    summarize,
    tokens_to_hit,
)


def _row(case_id: str, rank: int, tokens: int, latency: float) -> dict[str, float | str]:
    return {
        "case_id": case_id,
        "rank": float(rank),
        "tokens_to_hit": float(tokens),
        "latency_ms": latency,
    }


def test_known_ranks_produce_known_metrics() -> None:
    rows = [
        _row("a", 1, 10, 1.0),
        _row("b", 2, 30, 2.0),
        _row("c", 10, 100, 9.0),
    ]

    metrics = summarize(rows)

    assert metrics["top_1"] == pytest.approx(1 / 3)
    assert metrics["top_5"] == pytest.approx(2 / 3)
    assert metrics["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 10) / 3)
    assert metrics["mean_rank"] == pytest.approx(13 / 3)
    assert metrics["median_rank"] == 2
    assert metrics["mean_tokens_to_hit"] == pytest.approx(140 / 3)
    assert metrics["median_tokens_to_hit"] == 30
    assert metrics["p50_latency_ms"] == 2
    assert metrics["p95_latency_ms"] == pytest.approx(8.3)


def test_rank_and_tokens_to_hit_include_the_true_function() -> None:
    ranking = ["a", "b", "c"]

    assert rank_of(ranking, "b") == 2
    assert tokens_to_hit(ranking, "b", {"a": 10, "b": 20, "c": 30}) == 30
    with pytest.raises(ValueError):
        rank_of(ranking, "missing")


def test_bootstrap_is_reproducible_and_paired() -> None:
    left = [_row("a", 1, 10, 1), _row("b", 2, 20, 2), _row("c", 3, 30, 3)]
    right = [_row("a", 2, 20, 2), _row("b", 3, 30, 3), _row("c", 4, 40, 4)]

    first = bootstrap_summary(left, resamples=100, seed=7)
    second = bootstrap_summary(left, resamples=100, seed=7)
    comparison = paired_bootstrap(left, right, resamples=100, seed=7)

    assert first == second
    assert comparison["mean_rank"]["estimate"] == -1
    assert comparison["mean_tokens_to_hit"]["estimate"] == -10
    assert comparison["mrr"]["estimate"] > 0


def _assert_reciprocal_rank_contract(metric) -> None:
    assert metric(1) == 1
    assert metric(2) == 0.5
    assert metric(10) == 0.1


def test_deliberately_mutated_metric_is_caught() -> None:
    """Mutation check: the classic off-by-one denominator must fail."""

    def broken_reciprocal_rank(rank: int) -> float:
        return 1 / (rank + 1)

    _assert_reciprocal_rank_contract(reciprocal_rank)
    with pytest.raises(AssertionError):
        _assert_reciprocal_rank_contract(broken_reciprocal_rank)

