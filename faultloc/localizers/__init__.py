"""Baseline fault localizers."""

from __future__ import annotations

from typing import Any

from faultloc.localizers.bm25 import BM25Localizer
from faultloc.localizers.dense import DenseLocalizer
from faultloc.localizers.hybrid import HybridLocalizer
from faultloc.localizers.improvements import (
    CleanBM25Localizer,
    RoutingLocalizer,
    TestCallBM25Localizer,
)
from faultloc.localizers.random import RandomLocalizer
from faultloc.localizers.stack import StackFrameLocalizer


def build_baseline_localizers(
    *, include_dense: bool = False
) -> tuple[list[Any], dict[str, str]]:
    """Build L0-L4, gracefully omitting the optional dense model."""
    random_localizer = RandomLocalizer()
    stack_localizer = StackFrameLocalizer()
    bm25_localizer = BM25Localizer()
    localizers: list[Any] = [random_localizer, stack_localizer, bm25_localizer]
    skipped: dict[str, str] = {}
    dense_localizer = None
    if include_dense:
        try:
            dense_localizer = DenseLocalizer()
            localizers.append(dense_localizer)
        except Exception as error:  # optional dependency/model availability
            skipped["l3_dense"] = f"{type(error).__name__}: {error}"
            print(f"Skipping l3_dense: {skipped['l3_dense']}")
    localizers.append(
        HybridLocalizer(
            stack=stack_localizer,
            bm25=bm25_localizer,
            dense=dense_localizer,
        )
    )
    return localizers, skipped


def build_phase4_localizers(
    *, include_dense: bool = False, include_reverted: bool = False
) -> tuple[list[Any], dict[str, str]]:
    localizers, skipped = build_baseline_localizers(include_dense=include_dense)
    stack = next(localizer for localizer in localizers if localizer.name == "l1_stack")
    bm25 = next(localizer for localizer in localizers if localizer.name == "l2_bm25")
    test_calls = TestCallBM25Localizer(bm25=bm25)
    router = RoutingLocalizer(stack=stack, assertion_fallback=test_calls)
    localizers.extend((test_calls, router))
    if include_reverted:
        localizers.append(CleanBM25Localizer())
    return localizers, skipped


__all__ = [
    "BM25Localizer",
    "DenseLocalizer",
    "HybridLocalizer",
    "CleanBM25Localizer",
    "RoutingLocalizer",
    "TestCallBM25Localizer",
    "RandomLocalizer",
    "StackFrameLocalizer",
    "build_baseline_localizers",
    "build_phase4_localizers",
]
