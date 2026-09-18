"""L4: reciprocal-rank fusion of stack, BM25, and optional dense rankings."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from faultloc.index import CaseIndex


class _Ranker(Protocol):
    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]: ...


class HybridLocalizer:
    name = "l4_hybrid"

    def __init__(
        self,
        *,
        stack: _Ranker,
        bm25: _Ranker,
        dense: _Ranker | None = None,
        k: int = 60,
    ) -> None:
        self.components = [stack, bm25, *([dense] if dense is not None else [])]
        self.k = k

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        rankings = [component.rank(case, index) for component in self.components]
        return reciprocal_rank_fusion(rankings, index.function_ids, k=self.k)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], candidates: Sequence[str], *, k: int = 60
) -> list[str]:
    scores = {candidate: 0.0 for candidate in candidates}
    for ranking in rankings:
        for rank, candidate in enumerate(ranking, start=1):
            scores[candidate] += 1.0 / (k + rank)
    return sorted(candidates, key=lambda candidate: (-scores[candidate], candidate))

