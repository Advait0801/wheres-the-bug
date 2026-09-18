"""Shared query construction and code-aware tokenization."""

from __future__ import annotations

import re
from typing import Any


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def code_tokens(text: str) -> list[str]:
    """Keep identifiers while adding lowercase snake/camel components."""
    tokens: list[str] = []
    for match in IDENTIFIER_RE.finditer(text):
        raw = match.group(0)
        lowered = raw.lower()
        tokens.append(lowered)
        snake_parts = [part for part in raw.split("_") if part]
        for snake_part in snake_parts:
            camel_parts = [part for part in CAMEL_BOUNDARY_RE.split(snake_part) if part]
            tokens.extend(part.lower() for part in camel_parts)
    return tokens


def query_text(case: dict[str, Any]) -> str:
    failing_source = "\n".join(
        str(test.get("source", "")) for test in case.get("failing_tests", [])
    )
    return "\n".join(
        (
            str(case.get("exception_type") or ""),
            str(case.get("exception_message") or ""),
            str(case.get("traceback_text") or ""),
            failing_source,
        )
    )

