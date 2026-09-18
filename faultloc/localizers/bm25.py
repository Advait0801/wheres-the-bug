"""L2: BM25 over code-aware function chunks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rank_bm25 import BM25Okapi

from faultloc.index import CaseIndex
from faultloc.localizers.common import code_tokens, query_text


class BM25Localizer:
    name = "l2_bm25"

    def __init__(
        self,
        *,
        name: str = "l2_bm25",
        query_builder: Callable[[dict[str, Any]], str] = query_text,
    ) -> None:
        self.name = name
        self.query_builder = query_builder

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        candidates = list(index)
        corpus = [code_tokens(candidate.text) for candidate in candidates]
        model = BM25Okapi(corpus)
        scores = model.get_scores(code_tokens(self.query_builder(case)))
        scored = zip(candidates, scores, strict=True)
        return [
            candidate.function_id
            for candidate, _ in sorted(
                scored,
                key=lambda item: (-float(item[1]), item[0].function_id),
            )
        ]
