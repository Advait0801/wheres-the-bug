"""Deterministic, single-site source mutations for the vendored target."""

from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


COMPARISON_SWAPS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
}
ARITHMETIC_SWAPS: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.FloorDiv,
    ast.FloorDiv: ast.Mult,
}


@dataclass(frozen=True)
class FunctionInfo:
    """Stable identity and source extent for one function or method."""

    function_id: str
    qualified_name: str
    file: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class Mutation:
    """One textual replacement implementing one semantic AST mutation."""

    mutation_id: str
    function: FunctionInfo
    operator: str
    file: str
    start: int
    end: int
    original: str
    replacement: str
    source: str
    mutated_source: str

    @property
    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.source.splitlines(keepends=True),
                self.mutated_source.splitlines(keepends=True),
                fromfile=f"a/{self.file}",
                tofile=f"b/{self.file}",
                n=3,
            )
        )


@dataclass(frozen=True)
class _Candidate:
    function: FunctionInfo
    operator: str
    start: int
    end: int
    replacement: str


class _Offsets:
    def __init__(self, source: str) -> None:
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.starts: list[int] = []
        offset = 0
        for line in self.lines:
            self.starts.append(offset)
            offset += len(line)

    def span(self, node: ast.AST) -> tuple[int, int]:
        if not hasattr(node, "end_lineno") or node.end_lineno is None:
            raise ValueError(f"node has no source extent: {node!r}")
        start = self.starts[node.lineno - 1] + node.col_offset
        end = self.starts[node.end_lineno - 1] + node.end_col_offset
        return start, end

    def deletion_span(self, node: ast.stmt) -> tuple[int, int]:
        start, end = self.span(node)
        line_start = self.starts[node.lineno - 1]
        before = self.source[line_start:start]
        line_end = (
            self.starts[node.end_lineno]
            if node.end_lineno < len(self.lines)
            else len(self.source)
        )
        after = self.source[end:line_end]
        if before.strip() == "" and after.strip() == "":
            return line_start, line_end
        return start, end


class _CandidateVisitor(ast.NodeVisitor):
    def __init__(self, source: str, relative_file: str) -> None:
        self.source = source
        self.relative_file = relative_file
        self.offsets = _Offsets(source)
        self.module = _module_name(relative_file)
        self.scope: list[str] = []
        self.function_stack: list[FunctionInfo] = []
        self.candidates: list[_Candidate] = []

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
        function = FunctionInfo(
            function_id=f"{self.module}:{qualified}@{node.lineno}",
            qualified_name=f"{self.module}.{qualified}",
            file=self.relative_file,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
        )
        self.scope.append(node.name)
        self.function_stack.append(function)
        self._visit_body(node.body)
        self.function_stack.pop()
        self.scope.pop()

    def _visit_body(self, statements: list[ast.stmt]) -> None:
        if len(statements) > 1:
            for index, statement in enumerate(statements):
                if index == 0 and _is_docstring(statement):
                    continue
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                start, end = self.offsets.deletion_span(statement)
                self._add("statement_deletion", start, end, "")
        for statement in statements:
            self.visit(statement)

    def generic_visit(self, node: ast.AST) -> None:
        if not self.function_stack:
            return super().generic_visit(node)

        if isinstance(node, ast.Compare):
            for index, operator in enumerate(node.ops):
                replacement_type = COMPARISON_SWAPS.get(type(operator))
                if replacement_type is None:
                    continue
                changed = copy.deepcopy(node)
                changed.ops[index] = replacement_type()
                self._replace_node("comparison_flip", node, changed)

        elif isinstance(node, ast.BinOp):
            replacement_type = ARITHMETIC_SWAPS.get(type(node.op))
            if replacement_type is not None:
                changed = copy.deepcopy(node)
                changed.op = replacement_type()
                self._replace_node("arithmetic_swap", node, changed)

        elif isinstance(node, ast.Constant) and type(node.value) is int:
            for delta in (-1, 1):
                changed = ast.Constant(value=node.value + delta)
                self._replace_node("integer_off_by_one", node, changed)

        elif isinstance(node, ast.BoolOp):
            changed = copy.deepcopy(node)
            changed.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self._replace_node("boolean_operator_swap", node, changed)

        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self._replace_node("remove_not", node, node.operand)

        elif isinstance(node, ast.Return) and node.value is not None:
            changed = copy.deepcopy(node)
            changed.value = ast.Constant(value=None)
            self._replace_node("return_none", node, changed)

        elif isinstance(node, ast.Constant) and type(node.value) is bool:
            self._replace_node(
                "boolean_constant_swap", node, ast.Constant(value=not node.value)
            )

        if isinstance(node, ast.Slice):
            for bound in (node.lower, node.upper):
                if bound is None or (
                    isinstance(bound, ast.Constant) and type(bound.value) is int
                ):
                    continue
                for delta in (-1, 1):
                    changed = ast.BinOp(
                        left=copy.deepcopy(bound),
                        op=ast.Add() if delta == 1 else ast.Sub(),
                        right=ast.Constant(value=1),
                    )
                    self._replace_node("slice_bound_off_by_one", bound, changed)

        for _, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(
                isinstance(item, ast.stmt) for item in value
            ):
                self._visit_body(value)
            elif isinstance(value, ast.AST):
                self.visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)

    def _replace_node(self, operator: str, old: ast.AST, new: ast.AST) -> None:
        start, end = self.offsets.span(old)
        self._add(operator, start, end, ast.unparse(ast.fix_missing_locations(new)))

    def _add(self, operator: str, start: int, end: int, replacement: str) -> None:
        self.candidates.append(
            _Candidate(
                function=self.function_stack[-1],
                operator=operator,
                start=start,
                end=end,
                replacement=replacement,
            )
        )


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _module_name(relative_file: str) -> str:
    path = Path(relative_file)
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def discover_source_files(target_root: Path) -> list[Path]:
    """Return sorted production Python sources under ``target_root/toolz``."""
    package = target_root / "toolz"
    return sorted(
        path
        for path in package.rglob("*.py")
        if "tests" not in path.relative_to(package).parts
    )


def enumerate_mutations(target_root: Path) -> list[Mutation]:
    """Enumerate and source-deduplicate every supported single-site mutation."""
    mutations: list[Mutation] = []
    seen_sources: set[tuple[str, str]] = set()
    for path in discover_source_files(target_root):
        relative_file = path.relative_to(target_root).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_file)
        visitor = _CandidateVisitor(source, relative_file)
        visitor.visit(tree)
        for candidate in sorted(
            visitor.candidates,
            key=lambda item: (
                item.function.function_id,
                item.start,
                item.end,
                item.operator,
                item.replacement,
            ),
        ):
            mutated = (
                source[: candidate.start]
                + candidate.replacement
                + source[candidate.end :]
            )
            source_hash = hashlib.sha256(mutated.encode()).hexdigest()
            dedupe_key = (relative_file, source_hash)
            if dedupe_key in seen_sources:
                continue
            seen_sources.add(dedupe_key)
            identity = "|".join(
                (
                    relative_file,
                    candidate.function.function_id,
                    candidate.operator,
                    str(candidate.start),
                    str(candidate.end),
                    candidate.replacement,
                )
            )
            mutation_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
            mutations.append(
                Mutation(
                    mutation_id=mutation_id,
                    function=candidate.function,
                    operator=candidate.operator,
                    file=relative_file,
                    start=candidate.start,
                    end=candidate.end,
                    original=source[candidate.start : candidate.end],
                    replacement=candidate.replacement,
                    source=source,
                    mutated_source=mutated,
                )
            )
    return sorted(mutations, key=lambda item: item.mutation_id)


def sample_mutations(
    mutations: Iterable[Mutation],
    *,
    limit: int,
    max_per_function: int,
    seed: int,
) -> list[Mutation]:
    """Round-robin sample across functions with a deterministic per-function cap."""
    if limit < 1 or max_per_function < 1:
        raise ValueError("limit and max_per_function must be positive")
    groups: dict[str, list[Mutation]] = defaultdict(list)
    for mutation in mutations:
        groups[mutation.function.function_id].append(mutation)

    rng = random.Random(seed)
    function_ids = sorted(groups)
    rng.shuffle(function_ids)
    for function_id in function_ids:
        groups[function_id].sort(key=lambda item: item.mutation_id)
        rng.shuffle(groups[function_id])
        del groups[function_id][max_per_function:]

    selected: list[Mutation] = []
    for round_index in range(max_per_function):
        for function_id in function_ids:
            group = groups[function_id]
            if round_index < len(group):
                selected.append(group[round_index])
                if len(selected) == limit:
                    return selected
    return selected
