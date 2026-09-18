"""Ranking metrics and deterministic bootstrap confidence intervals."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Iterable, Sequence
from typing import TypeAlias


MetricRow: TypeAlias = dict[str, float | str]
MetricSummary: TypeAlias = dict[str, float]

METRIC_DIRECTIONS = {
    "top_1": "higher",
    "top_5": "higher",
    "mrr": "higher",
    "mean_rank": "lower",
    "median_rank": "lower",
    "mean_tokens_to_hit": "lower",
    "median_tokens_to_hit": "lower",
    "p50_latency_ms": "lower",
    "p95_latency_ms": "lower",
}


def reciprocal_rank(rank: int) -> float:
    if rank < 1:
        raise ValueError("rank must be at least one")
    return 1.0 / rank


def rank_of(ranking: Sequence[str], truth: str) -> int:
    try:
        return ranking.index(truth) + 1
    except ValueError as error:
        raise ValueError(f"truth {truth!r} is missing from ranking") from error


def tokens_to_hit(
    ranking: Sequence[str], truth: str, token_counts: dict[str, int]
) -> int:
    total = 0
    for function_id in ranking:
        total += token_counts[function_id]
        if function_id == truth:
            return total
    raise ValueError(f"truth {truth!r} is missing from ranking")


def summarize(rows: Sequence[MetricRow]) -> MetricSummary:
    if not rows:
        raise ValueError("cannot summarize an empty sample")
    ranks = [float(row["rank"]) for row in rows]
    token_counts = [float(row["tokens_to_hit"]) for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    return {
        "top_1": statistics.fmean(rank <= 1 for rank in ranks),
        "top_5": statistics.fmean(rank <= 5 for rank in ranks),
        "mrr": statistics.fmean(1.0 / rank for rank in ranks),
        "mean_rank": statistics.fmean(ranks),
        "median_rank": statistics.median(ranks),
        "mean_tokens_to_hit": statistics.fmean(token_counts),
        "median_tokens_to_hit": statistics.median(token_counts),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
    }


def bootstrap_summary(
    rows: Sequence[MetricRow], *, resamples: int = 1_000, seed: int = 2027
) -> dict[str, dict[str, float]]:
    if resamples < 1:
        raise ValueError("resamples must be positive")
    estimate = summarize(rows)
    rng = random.Random(seed)
    distributions = {metric: [] for metric in estimate}
    for _ in range(resamples):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        sample_summary = summarize(sample)
        for metric, value in sample_summary.items():
            distributions[metric].append(value)
    return {
        metric: {
            "estimate": value,
            "ci_low": _percentile(distributions[metric], 2.5),
            "ci_high": _percentile(distributions[metric], 97.5),
        }
        for metric, value in estimate.items()
    }


def paired_bootstrap(
    left: Sequence[MetricRow],
    right: Sequence[MetricRow],
    *,
    resamples: int = 1_000,
    seed: int = 2027,
) -> dict[str, dict[str, float | str]]:
    """Bootstrap left-minus-right deltas over matched case IDs."""
    left_by_id = {str(row["case_id"]): row for row in left}
    right_by_id = {str(row["case_id"]): row for row in right}
    if set(left_by_id) != set(right_by_id):
        raise ValueError("paired bootstrap requires identical case IDs")
    case_ids = sorted(left_by_id)
    left_ordered = [left_by_id[case_id] for case_id in case_ids]
    right_ordered = [right_by_id[case_id] for case_id in case_ids]
    left_estimate = summarize(left_ordered)
    right_estimate = summarize(right_ordered)
    distributions = {metric: [] for metric in left_estimate}
    rng = random.Random(seed)
    for _ in range(resamples):
        indices = [rng.randrange(len(case_ids)) for _ in case_ids]
        left_sample = [left_ordered[index] for index in indices]
        right_sample = [right_ordered[index] for index in indices]
        left_values = summarize(left_sample)
        right_values = summarize(right_sample)
        for metric in distributions:
            distributions[metric].append(left_values[metric] - right_values[metric])
    return {
        metric: {
            "estimate": left_estimate[metric] - right_estimate[metric],
            "ci_low": _percentile(distributions[metric], 2.5),
            "ci_high": _percentile(distributions[metric], 97.5),
            "direction": METRIC_DIRECTIONS[metric],
        }
        for metric in left_estimate
    }


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot compute percentile of an empty sample")
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight

