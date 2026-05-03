"""Monty AbstractOS <-> Deep Agents BackendProtocol bridge.

See `DeepAgentBackendOS` for the full design discussion.
"""

from __future__ import annotations

import base64
import contextvars
from pathlib import PurePosixPath
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from pydantic_monty import AbstractOS, StatResult


class DeepAgentBackendOS(AbstractOS):
    """Projects a Deep Agents BackendProtocol as a Monty virtual filesystem.

    Monty code does ``Path('/x').read_text()``; that routes here, which routes
    into the backend (state, store, etc). Writes inside Monty become state
    updates visible to every other tool using the same backend.

    Threading note
    --------------
    Monty's VM calls these ``path_*`` methods from a worker thread, not the
    caller's async thread. LangGraph's ``StateBackend`` looks up state via a
    ``ContextVar`` that's only set on the caller's thread. We capture the
    current ``contextvars.Context`` at construction time and replay every
    backend call inside that context, so ``StateBackend`` sees the right
    LangGraph config (``CONFIG_KEY_READ`` / ``CONFIG_KEY_SEND``).

    Sync-only by design
    -------------------
    This bridge calls backend methods **synchronously**. All built-in Deep
    Agents backends (``StateBackend``, ``StoreBackend``, ``FilesystemBackend``,
    ``CompositeBackend``) expose sync methods and are the expected pairing.

    Monty intentionally separates two host-callback channels:

    1. ``AbstractOS`` (what we use here) — synchronous, for OS-level
       operations (``pathlib``, ``os``, ``datetime``). Called directly from
       Monty's worker thread. Fast, no suspension.

    2. ``external_functions`` — natively supports async coroutine functions
       via Monty's suspend/resume model. The VM pauses at each external
       call, control returns to the host's event loop, and the VM is
       resumed once the result is ready.

    If you need to front a genuinely async-only backend (e.g. a remote
    S3/Postgres-style service with no sync API), do **not** try to drive
    it through ``AbstractOS``. Attempting to bridge back to an asyncio
    loop from Monty's worker thread deadlocks: Monty's PyO3 Future pins
    the main Python thread while awaiting its worker, so a coroutine
    scheduled on the main loop via ``run_coroutine_threadsafe`` never
    runs. A dedicated-loop-thread workaround exists but pays a ~3-4s
    first-call PyO3/tokio warmup cost, and it's not the canonical
    Monty pattern.

    The idiomatic alternative is a complementary middleware that exposes
    the backend as ``external_functions``::

        external_functions = {
            "read_file":  async def read_file(path): ...,
            "write_file": async def write_file(path, content): ...,
            "ls":         async def ls(path): ...,
        }

    The LLM-facing ergonomics change — ``await read_file('/x')`` instead
    of ``Path('/x').read_text()`` — but async works natively with zero
    thread-bridging.
    """

    def __init__(self, backend: BackendProtocol):
        self._b = backend
        # Snapshot contextvars so backend calls from Monty's worker thread
        # still see the graph's config (CONFIG_KEY_READ / SEND).
        self._ctx = contextvars.copy_context()

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Invoke a sync backend method inside the captured LangGraph context."""
        sync_fn = getattr(self._b, method_name)
        return self._ctx.run(sync_fn, *args, **kwargs)

    # ---- environment / path normalization (no-op for our purposes) -----

    def get_environ(self) -> dict[str, str]:
        return {}

    def getenv(self, key: str, default: str | None = None) -> str | None:
        return default

    def path_absolute(self, path: PurePosixPath) -> str:
        return str(path)

    def path_resolve(self, path: PurePosixPath) -> str:
        return str(path)

    def path_is_symlink(self, path: PurePosixPath) -> bool:
        return False

    # ---- existence / type checks ---------------------------------------

    def path_is_file(self, path: PurePosixPath) -> bool:
        r = self._call("read", str(path))
        return r.error is None

    def path_is_dir(self, path: PurePosixPath) -> bool:
        # A directory "exists" iff the backend's ls returns non-empty entries
        # under that prefix. Root is always a dir.
        p = str(path)
        if p in ("/", ""):
            return True
        r = self._call("ls", p)
        return r.error is None and bool(r.entries)

    def path_exists(self, path: PurePosixPath) -> bool:
        return self.path_is_file(path) or self.path_is_dir(path)

    # ---- reads ---------------------------------------------------------

    def path_read_bytes(self, path: PurePosixPath) -> bytes:
        r = self._call("read", str(path))
        if r.error:
            raise FileNotFoundError(str(path))
        fd = r.file_data or {}
        content, encoding = fd.get("content", ""), fd.get("encoding", "utf-8")
        if encoding == "base64":
            return base64.b64decode(content)
        return content.encode("utf-8")

    def path_read_text(self, path: PurePosixPath) -> str:
        return self.path_read_bytes(path).decode("utf-8")

    def path_iterdir(self, path: PurePosixPath) -> list[PurePosixPath]:
        r = self._call("ls", str(path))
        if r.error:
            raise FileNotFoundError(str(path))
        return [PurePosixPath(entry["path"]) for entry in (r.entries or [])]

    # ---- writes --------------------------------------------------------

    def _write_with_overwrite(self, path_str: str, content: str) -> None:
        """``backend.write`` refuses to overwrite; fall back to edit if needed."""
        r = self._call("write", path_str, content)
        if r.error and "already exists" in r.error:
            existing = self._call("read", path_str)
            if existing.error or not existing.file_data:
                raise OSError(f"write failed: {r.error}")
            old = existing.file_data.get("content", "")
            if old == content:
                return  # no-op overwrite
            edit_result = self._call("edit", path_str, old, content, False)
            if edit_result.error:
                raise OSError(f"overwrite failed: {edit_result.error}")
        elif r.error:
            raise OSError(r.error)

    def path_write_bytes(self, path: PurePosixPath, data: bytes) -> int:
        # StateBackend.write currently accepts only str. Encode binary via
        # base64; for v0.1 we error loudly so the caller sees the limit.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotImplementedError(
                "binary writes not yet supported by this bridge (StateBackend.write is str-only)"
            ) from exc
        self._write_with_overwrite(str(path), text)
        return len(data)

    def path_write_text(self, path: PurePosixPath, data: str) -> int:
        self._write_with_overwrite(str(path), data)
        return len(data)

    # ---- stat ----------------------------------------------------------

    def path_stat(self, path: PurePosixPath) -> StatResult:
        if self.path_is_file(path):
            r = self._call("read", str(path))
            content = (r.file_data or {}).get("content", "")
            return StatResult.file_stat(size=len(content))
        if self.path_is_dir(path):
            return StatResult.dir_stat()
        raise FileNotFoundError(str(path))

    # ---- unsupported mutations (by design) -----------------------------

    def path_mkdir(self, path: PurePosixPath, parents: bool, exist_ok: bool) -> None:
        return  # no-op: dirs are implicit in a flat namespace

    def path_unlink(self, path: PurePosixPath) -> None:
        raise PermissionError(
            f"Delete not supported: this filesystem is append-only. "
            f"Overwrite {path} with empty content instead."
        )

    def path_rmdir(self, path: PurePosixPath) -> None:
        raise PermissionError(
            "Delete not supported: directories are implicit and cannot be removed."
        )

    def path_rename(self, path: PurePosixPath, target: PurePosixPath) -> None:
        raise PermissionError(f"Rename not supported: read {path} and write to {target}.")
