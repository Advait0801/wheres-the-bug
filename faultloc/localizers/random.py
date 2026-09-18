"""L0: fixed-seed random sanity floor."""

from __future__ import annotations

import hashlib
import random
from typing import Any

from faultloc.index import CaseIndex


class RandomLocalizer:
    name = "l0_random"

    def __init__(self, seed: int = 2027) -> None:
        self.seed = seed

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        digest = hashlib.sha256(
            f"{self.seed}:{case['case_id']}".encode("utf-8")
        ).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        ranking = list(index.function_ids)
        rng.shuffle(ranking)
        return ranking

