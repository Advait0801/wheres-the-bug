"""L3: optional small ONNX dense retriever."""

from __future__ import annotations

from typing import Any

import numpy as np

from faultloc.index import CaseIndex, FunctionIndex
from faultloc.localizers.common import query_text


class DenseLocalizer:
    name = "l3_dense"

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        # Force dependency, model-download, and runtime failures before eval starts.
        list(self._model.embed(["fault localization warmup"]))
        self._base_identity: int | None = None
        self._base_embeddings: dict[str, np.ndarray] = {}

    def _prepare_base(self, base: FunctionIndex) -> None:
        if self._base_identity == id(base):
            return
        candidates = list(base)
        vectors = self._model.embed([candidate.text for candidate in candidates])
        self._base_embeddings = {
            candidate.function_id: _normalize(np.asarray(vector, dtype=np.float32))
            for candidate, vector in zip(candidates, vectors, strict=True)
        }
        self._base_identity = id(base)

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        self._prepare_base(index.base)
        query_vector, mutated_vector = list(
            self._model.embed([query_text(case), index.override.text])
        )
        normalized_query = _normalize(np.asarray(query_vector, dtype=np.float32))
        embeddings = dict(self._base_embeddings)
        embeddings[index.overridden_id] = _normalize(
            np.asarray(mutated_vector, dtype=np.float32)
        )
        return sorted(
            index.function_ids,
            key=lambda function_id: (
                -float(np.dot(normalized_query, embeddings[function_id])),
                function_id,
            ),
        )


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm

