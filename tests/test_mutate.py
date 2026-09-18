from __future__ import annotations

import ast
from pathlib import Path

from faultloc.mutate import enumerate_mutations, sample_mutations


def _target(tmp_path: Path, source: str) -> Path:
    target = tmp_path / "target"
    package = target / "toolz"
    package.mkdir(parents=True)
    (package / "sample.py").write_text(source, encoding="utf-8")
    return target


def test_enumerates_supported_single_site_mutations(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        """\
def choose(x, flag=True):
    values = [1, 2, 3]
    if flag and not x < 2:
        return values[:x + 1]
    return False
""",
    )

    mutations = enumerate_mutations(target)
    operators = {mutation.operator for mutation in mutations}

    assert {
        "arithmetic_swap",
        "boolean_constant_swap",
        "boolean_operator_swap",
        "comparison_flip",
        "integer_off_by_one",
        "remove_not",
        "return_none",
        "slice_bound_off_by_one",
        "statement_deletion",
    } <= operators
    assert len({mutation.mutated_source for mutation in mutations}) == len(mutations)
    for mutation in mutations:
        ast.parse(mutation.mutated_source)
        assert mutation.function.function_id == "toolz.sample:choose@1"
        assert mutation.diff


def test_sampling_is_deterministic_and_capped_by_function(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        """\
def first(x):
    if x == 1:
        return x + 1
    return 2

def second(x):
    if x != 3:
        return x - 1
    return 4
""",
    )
    mutations = enumerate_mutations(target)

    first = sample_mutations(mutations, limit=6, max_per_function=3, seed=17)
    second = sample_mutations(mutations, limit=6, max_per_function=3, seed=17)

    assert [item.mutation_id for item in first] == [item.mutation_id for item in second]
    counts: dict[str, int] = {}
    for mutation in first:
        counts[mutation.function.function_id] = (
            counts.get(mutation.function.function_id, 0) + 1
        )
    assert max(counts.values()) <= 3
    assert set(counts) == {"toolz.sample:first@1", "toolz.sample:second@6"}
