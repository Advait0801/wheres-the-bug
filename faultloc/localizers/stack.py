"""L1: traceback library frames, deepest first."""

from __future__ import annotations

import re
from typing import Any

from faultloc.index import CaseIndex, FunctionChunk


PYTEST_FRAME_RE = re.compile(
    r"^(?P<path>[^\s:]*toolz/[^\s:]+\.py):(?P<line>\d+):",
    flags=re.MULTILINE,
)
PYTHON_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>[^"]*toolz/[^"]+\.py)", line (?P<line>\d+)',
    flags=re.MULTILINE,
)


class StackFrameLocalizer:
    name = "l1_stack"

    def rank(self, case: dict[str, Any], index: CaseIndex) -> list[str]:
        candidates_by_file: dict[str, list[FunctionChunk]] = {}
        for candidate in index:
            candidates_by_file.setdefault(candidate.file, []).append(candidate)

        frames = _library_frames(str(case.get("traceback_text") or ""))
        ranked: list[str] = []
        seen: set[str] = set()
        for file, line in reversed(frames):
            matches = [
                candidate
                for candidate in candidates_by_file.get(file, [])
                if candidate.line_start <= line <= candidate.line_end
            ]
            matches.sort(
                key=lambda candidate: (
                    candidate.line_end - candidate.line_start,
                    -candidate.line_start,
                    candidate.function_id,
                )
            )
            for candidate in matches[:1]:
                if candidate.function_id not in seen:
                    ranked.append(candidate.function_id)
                    seen.add(candidate.function_id)
        ranked.extend(
            function_id for function_id in index.function_ids if function_id not in seen
        )
        return ranked


def _library_frames(traceback_text: str) -> list[tuple[str, int]]:
    located: list[tuple[int, str, int]] = []
    for pattern in (PYTEST_FRAME_RE, PYTHON_FRAME_RE):
        for match in pattern.finditer(traceback_text):
            path = match.group("path").replace("\\", "/")
            if "/tests/" in f"/{path}" or "site-packages" in path:
                continue
            toolz_start = path.rfind("toolz/")
            if toolz_start < 0:
                continue
            located.append(
                (match.start(), path[toolz_start:], int(match.group("line")))
            )
    located.sort(key=lambda item: item[0])
    return [(file, line) for _, file, line in located]
