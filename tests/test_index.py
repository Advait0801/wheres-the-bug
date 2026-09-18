from __future__ import annotations

import json
from pathlib import Path

from faultloc.index import build_index


ROOT = Path(__file__).resolve().parents[1]


def test_indexes_every_production_function_with_unique_ids() -> None:
    index = build_index(ROOT / "target")

    assert len(index) == 155
    assert len(set(index.function_ids)) == len(index)
    assert index.token_counter.method == "tiktoken:cl100k_base"
    assert all(candidate.tokens > 0 for candidate in index)
    assert all("tests" not in candidate.file.split("/") for candidate in index)


def test_case_index_swaps_only_mutated_function() -> None:
    case = json.loads((ROOT / "data" / "cases.jsonl").read_text().splitlines()[0])
    index = build_index(ROOT / "target")
    case_index = index.for_case(case)
    truth = case["function_id"]

    assert index.get(truth).source == case["original_function_source"]
    assert case_index.get(truth).source == case["mutated_function_source"]
    assert index.get(truth).source != case_index.get(truth).source
    unchanged_id = next(function_id for function_id in index.function_ids if function_id != truth)
    assert case_index.get(unchanged_id) is index.get(unchanged_id)

