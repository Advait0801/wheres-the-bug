from __future__ import annotations

from pathlib import Path

from faultloc.harvest import _normalize_output, assign_function_splits, run_mutant
from faultloc.mutate import enumerate_mutations


def test_mutant_runs_in_copy_and_never_changes_vendored_source(tmp_path: Path) -> None:
    target = tmp_path / "target"
    package = target / "toolz"
    tests = package / "tests"
    tests.mkdir(parents=True)
    (package / "__init__.py").write_text("from .sample import add_one\n")
    source_path = package / "sample.py"
    source_path.write_text("def add_one(x):\n    return x + 1\n")
    (tests / "test_sample.py").write_text(
        "from toolz import add_one\n\ndef test_add_one():\n    assert add_one(2) == 3\n"
    )
    before = source_path.read_bytes()
    mutation = next(
        item
        for item in enumerate_mutations(target)
        if item.operator == "arithmetic_swap"
    )

    result = run_mutant(mutation, target_root=target, timeout_seconds=5)

    assert result.status == "killed"
    assert result.exception_type == "AssertionError"
    assert result.failing_test_names
    assert source_path.read_bytes() == before


def test_invalid_mutant_is_classified_without_touching_source(tmp_path: Path) -> None:
    target = tmp_path / "target"
    package = target / "toolz"
    package.mkdir(parents=True)
    source_path = package / "sample.py"
    source_path.write_text("def identity(x):\n    return x\n")
    mutation = next(
        item
        for item in enumerate_mutations(target)
        if item.operator == "return_none"
    )
    invalid = mutation.__class__(
        **{**mutation.__dict__, "mutated_source": "def broken(:\n"}
    )
    before = source_path.read_bytes()

    result = run_mutant(invalid, target_root=target)

    assert result.status == "invalid"
    assert result.exception_type == "SyntaxError"
    assert source_path.read_bytes() == before


def test_function_split_has_no_leakage() -> None:
    cases = [
        {"function_id": "pkg:a@1", "case_id": "a1"},
        {"function_id": "pkg:a@1", "case_id": "a2"},
        {"function_id": "pkg:b@2", "case_id": "b1"},
        {"function_id": "pkg:c@3", "case_id": "c1"},
        {"function_id": "pkg:d@4", "case_id": "d1"},
    ]

    counts = assign_function_splits(cases, seed=1729)

    splits_by_function: dict[str, set[str]] = {}
    for case in cases:
        splits_by_function.setdefault(case["function_id"], set()).add(case["split"])
    assert all(len(splits) == 1 for splits in splits_by_function.values())
    assert counts["dev_functions"] == counts["test_functions"] == 2


def test_normalizes_nondeterministic_pytest_output() -> None:
    output = (
        "/tmp/faultloc-mutant-abc/target/toolz/a.py object at 0x1af "
        "1 failed in 0.27s"
    )
    normalized = _normalize_output(output, Path("/tmp/faultloc-mutant-abc"))

    assert normalized == (
        "<MUTANT_ROOT>/target/toolz/a.py object at 0x<ADDR> "
        "1 failed in <TIME>s"
    )
