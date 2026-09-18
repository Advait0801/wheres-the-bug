from __future__ import annotations

import json
from pathlib import Path

import pytest

from faultloc.eval import (
    _prepare_final_evaluation,
    evaluate,
    evaluate_localizer,
    load_cases,
)
from faultloc.index import CaseIndex, build_index


ROOT = Path(__file__).resolve().parents[1]


class TruthFirst:
    name = "truth_first_test_fixture"

    def rank(self, case: dict, index: CaseIndex) -> list[str]:
        truth = case["function_id"]
        return [truth, *(item for item in index.function_ids if item != truth)]


class MissingCandidate:
    name = "missing_candidate_test_fixture"

    def rank(self, case: dict, index: CaseIndex) -> list[str]:
        del case
        return list(index.function_ids[:-1])


def test_evaluator_requires_and_scores_a_full_ranking() -> None:
    cases = load_cases(ROOT / "data" / "cases.jsonl", split="dev")[:2]
    index = build_index(ROOT / "target")

    rows = evaluate_localizer(TruthFirst(), cases, index)

    assert [row["rank"] for row in rows] == [1, 1]
    assert all(row["tokens_to_hit"] > 0 for row in rows)
    with pytest.raises(ValueError, match="expected"):
        evaluate_localizer(MissingCandidate(), cases, index)


def test_case_loader_uses_only_requested_split() -> None:
    cases = load_cases(ROOT / "data" / "cases.jsonl", split="dev")

    assert len(cases) == 187
    assert all(case["split"] == "dev" for case in cases)
    assert cases == sorted(cases, key=lambda case: case["case_id"])


def test_test_split_is_locked(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="locked"):
        evaluate(root=tmp_path, split="test")


def test_final_evaluation_archives_dev_and_refuses_a_second_run(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    dev_contents = json.dumps({"split": "dev", "case_count": 2}) + "\n"
    (results / "results.json").write_text(dev_contents)

    _prepare_final_evaluation(tmp_path)

    assert (results / "dev_results.json").read_text() == dev_contents
    (results / "test_results.json").write_text('{"split": "test"}\n')
    with pytest.raises(RuntimeError, match="already exist"):
        _prepare_final_evaluation(tmp_path)
