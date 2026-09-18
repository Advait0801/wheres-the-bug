"""Evaluation harness for full-ranking fault localizers."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol, Sequence

from faultloc.index import CaseIndex, FunctionIndex, build_index
from faultloc.metrics import (
    MetricRow,
    bootstrap_summary,
    paired_bootstrap,
    rank_of,
    tokens_to_hit,
)


BOOTSTRAP_RESAMPLES = 1_000
BOOTSTRAP_SEED = 2027


class Localizer(Protocol):
    name: str

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]: ...


class StableOrderSanityLocalizer:
    """Structural smoke test, not a technique under evaluation."""

    name = "stable_order_sanity"

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        del case
        return list(index.function_ids)


def load_cases(path: Path, *, split: str = "dev") -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line]
    selected = [case for case in cases if case["split"] == split]
    return sorted(selected, key=lambda case: case["case_id"])


def evaluate_localizer(
    localizer: Localizer,
    cases: Sequence[dict[str, Any]],
    base_index: FunctionIndex,
) -> list[MetricRow]:
    rows: list[MetricRow] = []
    expected_ids = set(base_index.function_ids)
    for case in cases:
        case_index = base_index.for_case(case)
        started = time.perf_counter_ns()
        ranking = localizer.rank(case, case_index)
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        _validate_ranking(ranking, expected_ids, localizer.name)
        truth = str(case["function_id"])
        token_counts = {
            candidate.function_id: candidate.tokens for candidate in case_index
        }
        rows.append(
            {
                "case_id": str(case["case_id"]),
                "rank": float(rank_of(ranking, truth)),
                "tokens_to_hit": float(tokens_to_hit(ranking, truth, token_counts)),
                "latency_ms": latency_ms,
            }
        )
    return rows


def _validate_ranking(
    ranking: Sequence[str], expected_ids: set[str], localizer_name: str
) -> None:
    if len(ranking) != len(expected_ids):
        raise ValueError(
            f"{localizer_name} returned {len(ranking)} candidates; "
            f"expected {len(expected_ids)}"
        )
    if len(set(ranking)) != len(ranking):
        raise ValueError(f"{localizer_name} returned duplicate candidates")
    if set(ranking) != expected_ids:
        missing = sorted(expected_ids - set(ranking))
        extra = sorted(set(ranking) - expected_ids)
        raise ValueError(
            f"{localizer_name} ranking mismatch; missing={missing}, extra={extra}"
        )


def _summarize_breakdowns(
    cases: Sequence[dict[str, Any]], rows: Sequence[MetricRow]
) -> dict[str, Any]:
    by_id = {str(case["case_id"]): case for case in cases}
    groups: dict[str, dict[str, list[MetricRow]]] = {
        "exception_group": defaultdict(list),
        "exception_type": defaultdict(list),
        "operator": defaultdict(list),
    }
    for row in rows:
        case = by_id[str(row["case_id"])]
        exception = str(case["exception_type"])
        group = "AssertionError" if exception == "AssertionError" else "Other"
        groups["exception_group"][group].append(row)
        groups["exception_type"][exception].append(row)
        groups["operator"][str(case["operator"])].append(row)
    return {
        dimension: {
            name: {
                "cases": len(group_rows),
                "metrics": bootstrap_summary(
                    group_rows,
                    resamples=BOOTSTRAP_RESAMPLES,
                    seed=BOOTSTRAP_SEED,
                ),
            }
            for name, group_rows in sorted(values.items())
        }
        for dimension, values in groups.items()
    }


def evaluate(
    *,
    root: Path,
    localizers: Sequence[Localizer] | None = None,
    split: str = "dev",
    include_dense: bool = False,
    include_experiments: bool = False,
) -> dict[str, Any]:
    """Evaluate localizers and persist measured results for one split."""
    if split != "dev":
        raise ValueError("the test split is locked until the final evaluation")
    skipped_localizers: dict[str, str] = {}
    if localizers is None:
        from faultloc.localizers import build_phase4_localizers

        built, skipped_localizers = build_phase4_localizers(
            include_dense=include_dense,
            include_reverted=include_experiments,
        )
        localizers = built
    else:
        localizers = list(localizers)
    cases = load_cases(root / "data" / "cases.jsonl", split=split)
    index = build_index(root / "target")
    result_localizers: dict[str, Any] = {}
    raw_rows: dict[str, list[MetricRow]] = {}
    for localizer in localizers:
        rows = evaluate_localizer(localizer, cases, index)
        raw_rows[localizer.name] = rows
        result_localizers[localizer.name] = {
            "metrics": bootstrap_summary(
                rows, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
            ),
            "breakdowns": _summarize_breakdowns(cases, rows),
            "cases": rows,
        }

    comparisons: dict[str, Any] = {}
    names = [localizer.name for localizer in localizers]
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            comparisons[f"{left}_minus_{right}"] = paired_bootstrap(
                raw_rows[left],
                raw_rows[right],
                resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            )

    result = {
        "schema_version": 1,
        "split": split,
        "case_count": len(cases),
        "candidate_count": len(index),
        "tokenizer": index.token_counter.method,
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "paired_comparisons": True,
        },
        "localizers": result_localizers,
        "skipped_localizers": skipped_localizers,
        "comparisons": comparisons,
    }
    output_path = root / "results" / "results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(markdown_table(result))
    return result


def markdown_table(result: dict[str, Any]) -> str:
    lines = [
        "| Localizer | Top-1 | Top-5 | MRR | Mean rank | Median rank | "
        "Median tokens-to-hit | p50 ms | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, payload in result["localizers"].items():
        metrics = payload["metrics"]
        lines.append(
            "| "
            + " | ".join(
                (
                    name,
                    _format_ci(metrics["top_1"], percent=True),
                    _format_ci(metrics["top_5"], percent=True),
                    _format_ci(metrics["mrr"]),
                    _format_ci(metrics["mean_rank"]),
                    _format_ci(metrics["median_rank"]),
                    _format_ci(metrics["median_tokens_to_hit"], digits=0),
                    _format_ci(metrics["p50_latency_ms"], digits=4),
                    _format_ci(metrics["p95_latency_ms"], digits=4),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _format_ci(
    metric: dict[str, float], *, percent: bool = False, digits: int = 3
) -> str:
    scale = 100 if percent else 1
    suffix = "%" if percent else ""
    estimate = metric["estimate"] * scale
    low = metric["ci_low"] * scale
    high = metric["ci_high"] * scale
    return (
        f"{estimate:.{digits}f}{suffix} "
        f"[{low:.{digits}f}, {high:.{digits}f}]"
    )
