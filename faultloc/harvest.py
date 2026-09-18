"""Execute deterministic mutations in isolated copies and harvest killed cases."""

from __future__ import annotations

import ast
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from faultloc.mutate import Mutation, enumerate_mutations, sample_mutations


DEFAULT_SEED = 1729
DEFAULT_MAX_MUTANTS = 400
DEFAULT_MAX_PER_FUNCTION = 4
DEFAULT_TIMEOUT_SECONDS = 20.0
OUTPUT_LIMIT = 24_000


@dataclass(frozen=True)
class MutantResult:
    mutation_id: str
    status: str
    duration_seconds: float
    returncode: int | None
    output: str
    exception_type: str | None = None
    exception_message: str | None = None
    failing_test_names: tuple[str, ...] = ()


def run_mutant(
    mutation: Mutation,
    *,
    target_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> MutantResult:
    """Run one mutant in a temporary copy; never write to ``target_root``."""
    started = time.perf_counter()
    try:
        compile(mutation.mutated_source, mutation.file, "exec")
    except (SyntaxError, ValueError) as error:
        return MutantResult(
            mutation_id=mutation.mutation_id,
            status="invalid",
            duration_seconds=time.perf_counter() - started,
            returncode=None,
            output=f"{type(error).__name__}: {error}",
            exception_type=type(error).__name__,
            exception_message=str(error),
        )

    with tempfile.TemporaryDirectory(prefix="faultloc-mutant-") as temp_dir:
        copied_target = Path(temp_dir) / "target"
        shutil.copytree(target_root, copied_target)
        mutated_path = copied_target / mutation.file
        mutated_path.write_text(mutation.mutated_source, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(copied_target)
        env["PYTHONHASHSEED"] = "0"
        test_paths = [
            copied_target / "toolz" / "tests",
            copied_target / "toolz" / "sandbox" / "tests",
        ]
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=long",
            *(path.relative_to(temp_dir).as_posix() for path in test_paths if path.is_dir()),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            partial = _normalize_output(
                _combine_output(error.stdout, error.stderr), Path(temp_dir)
            )
            return MutantResult(
                mutation_id=mutation.mutation_id,
                status="timeout",
                duration_seconds=time.perf_counter() - started,
                returncode=None,
                output=partial,
            )

    output = _normalize_output(
        _combine_output(completed.stdout, completed.stderr), Path(temp_dir)
    )
    status = "survived" if completed.returncode == 0 else "killed"
    exception_type, exception_message = _parse_exception(output)
    return MutantResult(
        mutation_id=mutation.mutation_id,
        status=status,
        duration_seconds=time.perf_counter() - started,
        returncode=completed.returncode,
        output=output,
        exception_type=exception_type,
        exception_message=exception_message,
        failing_test_names=tuple(_failing_test_names(output)),
    )


def _combine_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value

    return text(stdout) + text(stderr)


def _normalize_output(output: str, temp_root: Path) -> str:
    output = output.replace(str(temp_root), "<MUTANT_ROOT>")
    output = re.sub(
        r"[^\s'\"{}]*faultloc-mutant-[^/\s'\"{}]*",
        "<MUTANT_ROOT>",
        output,
    )
    output = re.sub(r"0x[0-9a-fA-F]+", "0x<ADDR>", output)
    return re.sub(r"(?<=\bin )\d+(?:\.\d+)?s\b", "<TIME>s", output)


def _parse_exception(output: str) -> tuple[str | None, str | None]:
    matches = re.findall(
        r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt))(?::\s*(.*))?$",
        output,
        flags=re.MULTILINE,
    )
    if matches:
        exception_type, message = matches[-1]
        return exception_type.rsplit(".", 1)[-1], message.strip()
    assertion_lines = re.findall(r"^E\s+(assert\b.*)$", output, flags=re.MULTILINE)
    if assertion_lines:
        return "AssertionError", assertion_lines[-1].strip()
    if "ERROR collecting" in output:
        return "CollectionError", "pytest failed while collecting tests"
    return None, None


def _failing_test_names(output: str) -> list[str]:
    names = re.findall(
        r"^(?:FAILED|ERROR)\s+(target/[^\s]+)", output, flags=re.MULTILINE
    )
    return sorted(dict.fromkeys(names))


def _test_source(target_root: Path, node_id: str) -> str:
    path_text, *parts = node_id.split("::")
    path = Path(path_text)
    if path.is_absolute():
        try:
            relative = path.relative_to(target_root)
        except ValueError:
            return ""
    else:
        marker = "target/"
        normalized = path.as_posix()
        relative = Path(normalized.split(marker, 1)[-1]) if marker in normalized else path
    source_path = target_root / relative
    if not source_path.is_file():
        return ""
    source = source_path.read_text(encoding="utf-8")
    if not parts:
        return source
    wanted = re.sub(r"\[.*\]$", "", parts[-1])
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == wanted:
            return ast.get_source_segment(source, node) or ""
    return ""


def _function_source(source: str, function_id: str) -> str:
    function_part = function_id.split(":", 1)[1]
    wanted, line_text = function_part.rsplit("@", 1)
    wanted_line = int(line_text)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    functions: dict[tuple[str, int], ast.FunctionDef | ast.AsyncFunctionDef] = {}

    class Finder(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def _visit_function(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            qualified = ".".join((*self.scope, node.name))
            functions.setdefault((qualified, node.lineno), node)
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

    Finder().visit(tree)
    node = functions.get((wanted, wanted_line))
    return ast.get_source_segment(source, node) or "" if node is not None else ""


def _case_record(
    mutation: Mutation, result: MutantResult, target_root: Path
) -> dict[str, Any]:
    failing_tests = [
        {"name": name, "source": _test_source(target_root, name)}
        for name in result.failing_test_names
    ]
    return {
        "case_id": f"case-{mutation.mutation_id}",
        "function_id": mutation.function.function_id,
        "function_qualified_name": mutation.function.qualified_name,
        "file": mutation.file,
        "line_start": mutation.function.line_start,
        "line_end": mutation.function.line_end,
        "operator": mutation.operator,
        "diff": mutation.diff,
        "original_function_source": _function_source(
            mutation.source, mutation.function.function_id
        ),
        "mutated_function_source": _function_source(
            mutation.mutated_source, mutation.function.function_id
        ),
        "exception_type": result.exception_type,
        "exception_message": result.exception_message,
        "traceback_text": result.output,
        "failing_tests": failing_tests,
        "pytest_output": result.output[:OUTPUT_LIMIT],
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True) + "\n")


def assign_function_splits(
    cases: list[dict[str, Any]], *, seed: int
) -> dict[str, int]:
    """Assign a deterministic half-by-function dev/test split in place."""
    function_ids = sorted({str(case["function_id"]) for case in cases})
    random.Random(seed).shuffle(function_ids)
    dev_functions = set(function_ids[: (len(function_ids) + 1) // 2])
    for case in cases:
        case["split"] = "dev" if case["function_id"] in dev_functions else "test"
    return {
        "dev_functions": len(dev_functions),
        "test_functions": len(function_ids) - len(dev_functions),
        "dev_cases": sum(case["split"] == "dev" for case in cases),
        "test_cases": sum(case["split"] == "test" for case in cases),
    }


def harvest(
    *,
    root: Path,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    max_per_function: int = DEFAULT_MAX_PER_FUNCTION,
    seed: int = DEFAULT_SEED,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Generate the committed benchmark cases and return its measured summary."""
    target_root = root / "target"
    all_mutations = enumerate_mutations(target_root)
    selected = sample_mutations(
        all_mutations,
        limit=max_mutants,
        max_per_function=max_per_function,
        seed=seed,
    )
    outcomes: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    started = time.perf_counter()
    for index, mutation in enumerate(selected, start=1):
        result = run_mutant(
            mutation, target_root=target_root, timeout_seconds=timeout_seconds
        )
        counts[result.status] += 1
        outcomes.append(
            {
                "mutation_id": mutation.mutation_id,
                "function_id": mutation.function.function_id,
                "file": mutation.file,
                "operator": mutation.operator,
                "status": result.status,
            }
        )
        if result.status == "killed":
            cases.append(_case_record(mutation, result, target_root))
        print(
            f"[{index:03d}/{len(selected):03d}] {result.status:<8} "
            f"{mutation.function.function_id} {mutation.operator}",
            flush=True,
        )

    ordered_cases = sorted(cases, key=lambda item: item["case_id"])
    split_counts = assign_function_splits(ordered_cases, seed=seed)
    ordered_outcomes = sorted(outcomes, key=lambda item: item["mutation_id"])
    _write_jsonl(root / "data" / "cases.jsonl", ordered_cases)
    _write_jsonl(root / "data" / "mutants.jsonl", ordered_outcomes)
    summary = {
        "seed": seed,
        "timeout_seconds": timeout_seconds,
        "max_mutants": max_mutants,
        "max_per_function": max_per_function,
        "enumerated_unique_mutants": len(all_mutations),
        "selected_mutants": len(selected),
        "functions_represented": len(
            {mutation.function.function_id for mutation in selected}
        ),
        "counts": {status: counts.get(status, 0) for status in (
            "killed", "survived", "timeout", "invalid"
        )},
        "cases": len(ordered_cases),
        "split": split_counts,
    }
    summary_path = root / "data" / "harvest_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"harvest_elapsed_seconds={time.perf_counter() - started:.3f}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary
