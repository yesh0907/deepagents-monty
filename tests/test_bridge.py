"""Unit tests for DeepAgentBackendOS, using an in-memory stub backend.

No LangGraph runtime needed - these verify the bridge logic directly.
"""

from __future__ import annotations

from typing import cast

import pytest
from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileData,
    LsResult,
    ReadResult,
    WriteResult,
)
from pydantic_monty import Monty

from deepagents_monty import DeepAgentBackendOS


class InMemoryBackend:
    """Minimal BackendProtocol stub for direct testing."""

    def __init__(self) -> None:
        self.files: dict[str, FileData] = {}

    def read(self, path: str) -> ReadResult:
        if path in self.files:
            return ReadResult(file_data=self.files[path])
        return ReadResult(error=f"not found: {path}")

    def write(self, path: str, content: str) -> WriteResult:
        if path in self.files:
            return WriteResult(
                error=(
                    f"Cannot write to {path} because it already exists. "
                    "Read and then make an edit, or write to a new path."
                )
            )
        self.files[path] = {"content": content, "encoding": "utf-8"}
        return WriteResult(path=path)

    def edit(self, path: str, old: str, new: str, replace_all: bool = False) -> EditResult:
        fd = self.files.get(path)
        if fd is None:
            return EditResult(error=f"not found: {path}")
        count = fd["content"].count(old)
        if count == 0:
            return EditResult(error="old_string not found")
        fd["content"] = fd["content"].replace(old, new, 1 if not replace_all else -1)
        return EditResult(path=path, occurrences=count)

    def ls(self, path: str) -> LsResult:
        prefix = path.rstrip("/") + "/" if path != "/" else "/"
        entries = []
        seen_dirs: set[str] = set()
        for key in self.files:
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix) :]
            if "/" in rest:
                seen_dirs.add(rest.split("/", 1)[0])
            else:
                entries.append(
                    {
                        "path": key,
                        "is_dir": False,
                        "size": len(self.files[key]["content"]),
                    }
                )
        for d in seen_dirs:
            entries.append({"path": prefix + d + "/", "is_dir": True})
        return LsResult(entries=entries)


@pytest.fixture
def seeded_bridge() -> tuple[DeepAgentBackendOS, InMemoryBackend]:
    backend = InMemoryBackend()
    backend.files["/seed.txt"] = {"content": "hello from backend", "encoding": "utf-8"}
    return DeepAgentBackendOS(cast(BackendProtocol, backend)), backend


def test_monty_reads_backend_seeded_file(seeded_bridge):
    bridge, _ = seeded_bridge
    code = """
from pathlib import Path
Path('/seed.txt').read_text()
"""
    assert Monty(code).run(os=bridge) == "hello from backend"


def test_monty_write_visible_to_backend(seeded_bridge):
    bridge, backend = seeded_bridge
    code = """
from pathlib import Path
Path('/from_monty.txt').write_text('written by monty')
Path('/from_monty.txt').read_text()
"""
    result = Monty(code).run(os=bridge)
    assert result == "written by monty"
    assert backend.files["/from_monty.txt"]["content"] == "written by monty"


def test_monty_overwrite_via_edit_fallback(seeded_bridge):
    bridge, _ = seeded_bridge
    first = Monty(
        "from pathlib import Path\nPath('/x.txt').write_text('first')\nPath('/x.txt').read_text()"
    ).run(os=bridge)
    assert first == "first"

    # Second write overwrites; triggers the edit-fallback path
    second = Monty(
        "from pathlib import Path\nPath('/x.txt').write_text('second')\nPath('/x.txt').read_text()"
    ).run(os=bridge)
    assert second == "second"


def test_unlink_raises_permission_error(seeded_bridge):
    bridge, _ = seeded_bridge
    code = """
from pathlib import Path
try:
    Path('/seed.txt').unlink()
    msg = 'no error'
except PermissionError as e:
    msg = str(e)[:60]
msg
"""
    result = Monty(code).run(os=bridge)
    assert "Delete not supported" in result


def test_iterdir_sees_synthesized_directory(seeded_bridge):
    bridge, backend = seeded_bridge
    backend.files["/dir1/a.txt"] = {"content": "a", "encoding": "utf-8"}
    backend.files["/dir1/b.txt"] = {"content": "b", "encoding": "utf-8"}

    code = """
from pathlib import Path
sorted(str(p) for p in Path('/dir1').iterdir())
"""
    assert Monty(code).run(os=bridge) == ["/dir1/a.txt", "/dir1/b.txt"]


def test_rename_blocked(seeded_bridge):
    bridge, _ = seeded_bridge
    code = """
from pathlib import Path
try:
    Path('/seed.txt').rename('/renamed.txt')
    out = 'no error'
except PermissionError as e:
    out = 'blocked: ' + str(e)[:40]
out
"""
    assert Monty(code).run(os=bridge).startswith("blocked:")
