from __future__ import annotations

import json
from pathlib import Path

import faultloc.localizers as localizer_package
from faultloc.index import build_index
from faultloc.localizers import build_baseline_localizers, build_phase4_localizers
from faultloc.localizers.bm25 import BM25Localizer
from faultloc.localizers.common import code_tokens
from faultloc.localizers.hybrid import reciprocal_rank_fusion
from faultloc.localizers.improvements import (
    RoutingLocalizer,
    TestCallBM25Localizer,
    clean_query_text,
    extract_called_function_ids,
)
from faultloc.localizers.random import RandomLocalizer
from faultloc.localizers.stack import StackFrameLocalizer


ROOT = Path(__file__).resolve().parents[1]


def _first_dev_case() -> dict:
    return next(
        json.loads(line)
        for line in (ROOT / "data" / "cases.jsonl").read_text().splitlines()
        if json.loads(line)["split"] == "dev"
    )


def test_random_is_case_deterministic_and_returns_full_ranking() -> None:
    case = _first_dev_case()
    index = build_index(ROOT / "target").for_case(case)
    localizer = RandomLocalizer(seed=17)

    first = localizer.rank(case, index)
    second = localizer.rank(case, index)

    assert first == second
    assert len(first) == len(index)
    assert set(first) == set(index.function_ids)


def test_stack_ranks_deepest_library_frame_first() -> None:
    base = build_index(ROOT / "target")
    case = _first_dev_case()
    case["traceback_text"] = """\
target/toolz/functoolz.py:21:
target/toolz/itertoolz.py:313: TypeError
target/toolz/tests/test_itertoolz.py:10: in test_take
"""
    index = base.for_case(case)

    ranking = StackFrameLocalizer().rank(case, index)

    assert ranking[0].startswith("toolz.itertoolz:take@")
    assert ranking[1].startswith("toolz.functoolz:identity@")
    assert len(ranking) == len(base)


def test_code_tokenization_and_bm25_are_deterministic() -> None:
    assert code_tokens("HTTPServer foo_bar") == [
        "httpserver",
        "http",
        "server",
        "foo_bar",
        "foo",
        "bar",
    ]
    case = _first_dev_case()
    index = build_index(ROOT / "target").for_case(case)
    localizer = BM25Localizer()

    first = localizer.rank(case, index)
    second = localizer.rank(case, index)

    assert first == second
    assert len(first) == len(index)
    assert set(first) == set(index.function_ids)


def test_rrf_uses_stable_tie_breaks() -> None:
    candidates = ("a", "b", "c")
    rankings = [("a", "b", "c"), ("c", "b", "a")]

    assert reciprocal_rank_fusion(rankings, candidates, k=60) == ["a", "c", "b"]


def test_default_factory_builds_l0_l1_l2_and_l4() -> None:
    localizers, skipped = build_baseline_localizers(include_dense=False)

    assert [localizer.name for localizer in localizers] == [
        "l0_random",
        "l1_stack",
        "l2_bm25",
        "l4_hybrid",
    ]
    assert skipped == {}


def test_dense_failure_is_reported_and_hybrid_still_runs(monkeypatch) -> None:
    class FailingDense:
        def __init__(self) -> None:
            raise OSError("model unavailable")

    monkeypatch.setattr(localizer_package, "DenseLocalizer", FailingDense)

    localizers, skipped = build_baseline_localizers(include_dense=True)

    assert [localizer.name for localizer in localizers] == [
        "l0_random",
        "l1_stack",
        "l2_bm25",
        "l4_hybrid",
    ]
    assert skipped == {"l3_dense": "OSError: model unavailable"}


def test_test_call_extraction_resolves_import_alias_and_boosts_call() -> None:
    case = _first_dev_case()
    case["failing_tests"] = [
        {
            "name": "test_sample.py::test_take",
            "source": "from toolz import take as grab\n\ndef test_take():\n    assert grab(2, range(3))\n",
        }
    ]
    index = build_index(ROOT / "target").for_case(case)
    called = extract_called_function_ids(case, index)
    take_id = next(
        function_id
        for function_id in index.function_ids
        if function_id.startswith("toolz.itertoolz:take@")
    )

    class ReverseRanker:
        def rank(self, case, index):
            return list(reversed(index.function_ids))

    ranking = TestCallBM25Localizer(bm25=ReverseRanker()).rank(case, index)

    assert take_id in called
    assert ranking[0] == take_id


def test_router_uses_stack_only_for_non_assertion_with_library_frame() -> None:
    case = _first_dev_case()
    index = build_index(ROOT / "target").for_case(case)

    class MarkerRanker:
        def __init__(self, reverse: bool) -> None:
            self.reverse = reverse

        def rank(self, case, index):
            ranking = list(index.function_ids)
            return list(reversed(ranking)) if self.reverse else ranking

    stack = MarkerRanker(reverse=True)
    fallback = MarkerRanker(reverse=False)
    router = RoutingLocalizer(stack=stack, assertion_fallback=fallback)
    case["exception_type"] = "TypeError"
    case["traceback_text"] = "target/toolz/itertoolz.py:313: TypeError"
    assert router.rank(case, index) == list(reversed(index.function_ids))

    case["exception_type"] = "AssertionError"
    assert router.rank(case, index) == list(index.function_ids)


def test_clean_query_removes_paths_and_pytest_boilerplate() -> None:
    case = {
        "exception_type": "TypeError",
        "exception_message": "bad value",
        "traceback_text": (
            "target/toolz/functoolz.py:20: TypeError\n"
            "FAILED target/toolz/tests/test_x.py::test_x\n"
            "=== 1 failed in <TIME>s ===\n"
            "E TypeError: bad value\n"
        ),
        "failing_tests": [{"source": "assert identity(1) == 1"}],
    }

    cleaned = clean_query_text(case)

    assert ".py" not in cleaned
    assert "FAILED" not in cleaned
    assert "TypeError" in cleaned
    assert "identity" in cleaned


def test_phase4_factory_adds_three_pre_registered_attempts() -> None:
    localizers, skipped = build_phase4_localizers(
        include_dense=False, include_reverted=True
    )

    assert [localizer.name for localizer in localizers][-3:] == [
        "a5_test_calls",
        "a6_router",
        "a7_clean_bm25",
    ]
    assert skipped == {}


def test_reverted_query_cleanup_is_not_in_default_factory() -> None:
    localizers, _ = build_phase4_localizers(include_dense=False)

    assert "a5_test_calls" in [localizer.name for localizer in localizers]
    assert "a6_router" in [localizer.name for localizer in localizers]
    assert "a7_clean_bm25" not in [localizer.name for localizer in localizers]
