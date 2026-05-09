"""External CSV helper for the data-analysis Monty eval variant."""

from __future__ import annotations

import csv
from collections.abc import Callable
from io import StringIO
from typing import Any

from deepagents.backends.protocol import BackendProtocol


def make_read_csv(backend: BackendProtocol) -> Callable[[str], list[dict[str, Any]]]:
    """Create a Monty external function that reads CSV from a Deep Agents backend."""

    def read_csv(path: str) -> list[dict[str, Any]]:
        chunks: list[str] = []
        offset = 0
        limit = 2000
        while True:
            result = backend.read(path, offset=offset, limit=limit)
            if result.error or not result.file_data:
                if offset == 0:
                    raise FileNotFoundError(path)
                break

            content_chunk = result.file_data.get("content", "")
            if not content_chunk:
                break
            chunks.append(content_chunk)

            line_count = content_chunk.count("\n")
            if not content_chunk.endswith("\n"):
                line_count += 1
            if line_count < limit:
                break
            offset += line_count

        content = "".join(chunks)
        rows: list[dict[str, Any]] = []
        for row in csv.DictReader(StringIO(content)):
            parsed: dict[str, Any] = dict(row)
            amount = parsed.get("Amount")
            if isinstance(amount, str) and amount:
                parsed["Amount"] = float(amount)
            rows.append(parsed)
        return rows

    return read_csv
