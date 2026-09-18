"""Count source functions and mutation sites in the vendored target.

The count is syntax-based and deterministic. A candidate site is one possible
location for one of the Phase 1 operator families. Counts are limited to code
inside functions and methods; tests are excluded.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target" / "toolz"


class CounterVisitor(ast.NodeVisitor):
    """Count each node once while tracking whether it is inside a function."""

    def __init__(self) -> None:
        self.function_depth = 0
        self.functions = 0
        self.sites: Counter[str] = Counter()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions += 1
        self.function_depth += 1
        self._visit_function(node)
        self.function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions += 1
        self.function_depth += 1
        self._visit_function(node)
        self.function_depth -= 1

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)
        self._count_deletable_statements(node.body)
        for statement in node.body:
            self.visit(statement)

    def generic_visit(self, node: ast.AST) -> None:
        if self.function_depth:
            if isinstance(node, ast.Compare):
                self.sites["comparison_flip"] += sum(
                    isinstance(op, (ast.Lt, ast.LtE, ast.Eq, ast.NotEq, ast.Gt, ast.GtE))
                    for op in node.ops
                )
            elif isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)
            ):
                self.sites["arithmetic_swap"] += 1
            elif isinstance(node, ast.Constant) and type(node.value) is int:
                self.sites["integer_off_by_one"] += 1
            elif isinstance(node, ast.BoolOp):
                self.sites["boolean_operator_swap"] += 1
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                self.sites["remove_not"] += 1
            elif isinstance(node, ast.Return) and node.value is not None:
                self.sites["return_none"] += 1
            elif isinstance(node, ast.Constant) and type(node.value) is bool:
                self.sites["boolean_constant_swap"] += 1

            if isinstance(node, ast.Slice):
                for bound in (node.lower, node.upper):
                    if bound is not None and not (
                        isinstance(bound, ast.Constant) and type(bound.value) is int
                    ):
                        self.sites["slice_bound_off_by_one"] += 1

            for _, value in ast.iter_fields(node):
                if isinstance(value, list) and value and all(
                    isinstance(item, ast.stmt) for item in value
                ):
                    self._count_deletable_statements(value)

        super().generic_visit(node)

    def _count_deletable_statements(self, statements: list[ast.stmt]) -> None:
        if len(statements) <= 1:
            return
        start = 1 if _is_docstring(statements[0]) else 0
        self.sites["statement_deletion"] += len(statements) - start


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def source_files() -> list[Path]:
    return sorted(
        path
        for path in TARGET.rglob("*.py")
        if "tests" not in path.relative_to(TARGET).parts
    )


def main() -> None:
    visitor = CounterVisitor()
    files = source_files()
    for path in files:
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))

    print(f"source_files={len(files)}")
    print(f"functions={visitor.functions}")
    for operator, count in sorted(visitor.sites.items()):
        print(f"{operator}={count}")
    print(f"candidate_mutation_sites={sum(visitor.sites.values())}")


if __name__ == "__main__":
    main()
