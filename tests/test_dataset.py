from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_committed_cases_match_harvest_summary_and_do_not_leak_functions() -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "data" / "cases.jsonl").read_text().splitlines()
    ]
    mutants = [
        json.loads(line)
        for line in (ROOT / "data" / "mutants.jsonl").read_text().splitlines()
    ]
    summary = json.loads((ROOT / "data" / "harvest_summary.json").read_text())

    assert len(cases) == summary["cases"] == summary["counts"]["killed"]
    assert len(mutants) == summary["selected_mutants"]
    outcome_counts = Counter(item["status"] for item in mutants)
    assert {
        status: outcome_counts[status] for status in summary["counts"]
    } == summary["counts"]
    assert len({case["case_id"] for case in cases}) == len(cases)

    splits_by_function: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        splits_by_function[case["function_id"]].add(case["split"])
        assert case["diff"]
        assert case["traceback_text"]
        assert case["failing_tests"]
        assert case["original_function_source"]
        assert case["mutated_function_source"]
        assert case["original_function_source"] != case["mutated_function_source"]
        assert "faultloc-mutant-" not in case["traceback_text"]
        assert all(test["source"] for test in case["failing_tests"])
    assert all(len(splits) == 1 for splits in splits_by_function.values())
