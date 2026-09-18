"""Function-level source index with cheap per-mutant overlays."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class FunctionChunk:
    """One candidate function presented to a fault localizer."""

    function_id: str
    qualified_name: str
    file: str
    line_start: int
    line_end: int
    source: str
    text: str
    tokens: int


class TokenCounter:
    """Count source tokens with cl100k_base, with a documented fallback."""

    def __init__(self) -> None:
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
            self.method = "tiktoken:cl100k_base"
        except (ImportError, OSError):
            self._encoding = None
            self.method = "chars/4"

    def count(self, text: str) -> int:
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return max(1, (len(text) + 3) // 4)


class FunctionIndex:
    """Immutable original index; a case swaps only its mutated function."""

    def __init__(
        self, candidates: Iterable[FunctionChunk], token_counter: TokenCounter
    ) -> None:
        ordered = sorted(candidates, key=lambda candidate: candidate.function_id)
        self._candidates = tuple(ordered)
        self._by_id = {candidate.function_id: candidate for candidate in ordered}
        if len(self._by_id) != len(self._candidates):
            raise ValueError("function IDs must be unique")
        self.token_counter = token_counter

    @property
    def function_ids(self) -> tuple[str, ...]:
        return tuple(candidate.function_id for candidate in self._candidates)

    def get(self, function_id: str) -> FunctionChunk:
        return self._by_id[function_id]

    def __iter__(self) -> Iterator[FunctionChunk]:
        return iter(self._candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    def for_case(self, case: dict[str, Any]) -> "CaseIndex":
        function_id = str(case["function_id"])
        original = self.get(function_id)
        mutated_source = str(case["mutated_function_source"])
        mutated = replace(
            original,
            source=mutated_source,
            text=_chunk_text(original.qualified_name, mutated_source),
            tokens=self.token_counter.count(mutated_source),
        )
        return CaseIndex(self, function_id, mutated)


class CaseIndex:
    """A read-only view replacing exactly one original candidate chunk."""

    def __init__(
        self, base: FunctionIndex, overridden_id: str, override: FunctionChunk
    ) -> None:
        self.base = base
        self.overridden_id = overridden_id
        self.override = override

    @property
    def function_ids(self) -> tuple[str, ...]:
        return self.base.function_ids

    def get(self, function_id: str) -> FunctionChunk:
        if function_id == self.overridden_id:
            return self.override
        return self.base.get(function_id)

    def __iter__(self) -> Iterator[FunctionChunk]:
        for candidate in self.base:
            yield self.override if candidate.function_id == self.overridden_id else candidate

    def __len__(self) -> int:
        return len(self.base)


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, source: str, relative_file: str, counter: TokenCounter) -> None:
        self.source = source
        self.relative_file = relative_file
        self.module = _module_name(relative_file)
        self.counter = counter
        self.scope: list[str] = []
        self.chunks: list[FunctionChunk] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join((*self.scope, node.name))
        qualified_name = f"{self.module}.{qualified}"
        function_source = ast.get_source_segment(self.source, node) or ast.unparse(node)
        self.chunks.append(
            FunctionChunk(
                function_id=f"{self.module}:{qualified}@{node.lineno}",
                qualified_name=qualified_name,
                file=self.relative_file,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                source=function_source,
                text=_chunk_text(qualified_name, function_source),
                tokens=self.counter.count(function_source),
            )
        )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _module_name(relative_file: str) -> str:
    parts = list(Path(relative_file).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _chunk_text(qualified_name: str, source: str) -> str:
    # The source already contains the signature, docstring, and body.
    return f"{qualified_name}\n{source}"


def build_index(target_root: Path) -> FunctionIndex:
    """Index every production function and method in the vendored package."""
    counter = TokenCounter()
    chunks: list[FunctionChunk] = []
    package = target_root / "toolz"
    files = sorted(
        path
        for path in package.rglob("*.py")
        if "tests" not in path.relative_to(package).parts
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        relative_file = path.relative_to(target_root).as_posix()
        visitor = _FunctionVisitor(source, relative_file, counter)
        visitor.visit(ast.parse(source, filename=relative_file))
        chunks.extend(visitor.chunks)
    return FunctionIndex(chunks, counter)

