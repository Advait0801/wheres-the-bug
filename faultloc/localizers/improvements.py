"""Pre-registered Phase 4 improvement experiments."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from typing import Any, Protocol

from faultloc.index import CaseIndex
from faultloc.localizers.bm25 import BM25Localizer
from faultloc.localizers.stack import _library_frames


class _Ranker(Protocol):
    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]: ...


class TestCallBM25Localizer:
    """A5: put directly called library functions ahead of BM25's remainder."""

    __test__ = False
    name = "a5_test_calls"

    def __init__(self, bm25: _Ranker | None = None) -> None:
        self.bm25 = bm25 or BM25Localizer()

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        baseline = self.bm25.rank(case, index)
        called = extract_called_function_ids(case, index)
        return [
            *(function_id for function_id in baseline if function_id in called),
            *(function_id for function_id in baseline if function_id not in called),
        ]


class RoutingLocalizer:
    """A6: route runtime exceptions to stack and other cases to A5."""

    name = "a6_router"

    def __init__(self, *, stack: _Ranker, assertion_fallback: _Ranker) -> None:
        self.stack = stack
        self.assertion_fallback = assertion_fallback

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        has_frame = bool(_library_frames(str(case.get("traceback_text") or "")))
        if case.get("exception_type") != "AssertionError" and has_frame:
            return self.stack.rank(case, index)
        return self.assertion_fallback.rank(case, index)


class CleanBM25Localizer(BM25Localizer):
    """A7: BM25 after removing pytest and path boilerplate."""

    def __init__(self) -> None:
        super().__init__(name="a7_clean_bm25", query_builder=clean_query_text)


def extract_called_function_ids(
    case: dict[str, Any], index: CaseIndex
) -> set[str]:
    names: set[str] = set()
    for test in case.get("failing_tests", []):
        source = str(test.get("source") or "")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    aliases[alias.asname or alias.name] = alias.name.rsplit(".", 1)[-1]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called_name = _called_name(node.func)
            if called_name:
                names.add(aliases.get(called_name, called_name).rsplit(".", 1)[-1])

    by_name: dict[str, set[str]] = defaultdict(set)
    for candidate in index:
        parts = candidate.qualified_name.split(".")
        by_name[parts[-1]].add(candidate.function_id)
        if parts[-1] == "__init__" and len(parts) > 1:
            by_name[parts[-2]].add(candidate.function_id)
    return {function_id for name in names for function_id in by_name.get(name, set())}


def _called_name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


PATH_RE = re.compile(
    r"(?:[A-Za-z]:)?(?:[^\s:'\"]+[/\\])+[^\s:'\"]+\.py(?::\d+)?"
)
SUMMARY_RE = re.compile(
    r"^(?:FAILED\s|ERROR\s|short test summary|warnings summary|\d+ (?:failed|passed|errors?))|^(?:=+|_+|-{3,})$",
    flags=re.IGNORECASE,
)


def clean_query_text(case: dict[str, Any]) -> str:
    cleaned_traceback: list[str] = []
    for line in str(case.get("traceback_text") or "").splitlines():
        stripped = line.strip()
        if not stripped or SUMMARY_RE.match(stripped):
            continue
        cleaned = PATH_RE.sub(" ", line)
        cleaned_traceback.append(" ".join(cleaned.split()))
    failing_source = "\n".join(
        str(test.get("source", "")) for test in case.get("failing_tests", [])
    )
    return "\n".join(
        (
            str(case.get("exception_type") or ""),
            str(case.get("exception_message") or ""),
            "\n".join(cleaned_traceback),
            failing_source,
        )
    )
