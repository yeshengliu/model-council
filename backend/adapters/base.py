from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..runtime import debug_dir

log = logging.getLogger(__name__)


class AdapterError(RuntimeError):
    def __init__(self, adapter: str, message: str, stderr: str = ""):
        tail = f"\n--- stderr ---\n{stderr}" if stderr else ""
        super().__init__(f"[{adapter}] {message}{tail}")
        self.adapter = adapter
        self.message = message
        self.stderr = stderr


class ModelAdapter(ABC):
    name: str
    display_name: str
    timeout_seconds: int = 180

    def describe(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "binary": getattr(self, "binary", self.name),
            "runtime_model_source": "not reported by this adapter",
            "invocation": [],
            "options": [],
        }

    @abstractmethod
    def stream_query(self, prompt: str, system: str | None = None) -> AsyncIterator[dict]:
        """Yield a stream of events:

            {"type": "delta",  "text": str}    # repeated, incremental
            {"type": "done",   "text": str}    # final authoritative full text
            {"type": "error",  "message": str} # terminal failure (may replace done)
        """
        ...

    async def query(self, prompt: str, system: str | None = None) -> str:
        chunks: list[str] = []
        final: str | None = None
        async for ev in self.stream_query(prompt, system=system):
            t = ev.get("type")
            if t == "delta":
                chunks.append(ev.get("text", ""))
            elif t == "done":
                final = ev.get("text", "")
            elif t == "error":
                raise AdapterError(self.name, ev.get("message", "unknown error"))
        return (final if final is not None else "".join(chunks)).strip()

    async def _stream_ndjson(
        self, argv: list[str], stdin_payload: str | None = None
    ) -> AsyncIterator[dict]:
        """Spawn a CLI, yield one parsed JSON object per stdout line.

        On non-zero exit, raises AdapterError with a stderr tail. Always writes
        raw stdout/stderr to data/debug/ on exit.
        """
        log.info("%s: spawning %s", self.name, " ".join(argv[:8]) + (" …" if len(argv) > 8 else ""))
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin_payload is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise AdapterError(self.name, f"CLI not found on PATH: {argv[0]}") from e

        assert proc.stdout is not None and proc.stderr is not None

        if stdin_payload is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_payload.encode())
                await proc.stdin.drain()
            finally:
                proc.stdin.close()

        stderr_buf = bytearray()

        async def drain_stderr() -> None:
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    return
                stderr_buf.extend(chunk)

        stderr_task = asyncio.create_task(drain_stderr())
        stdout_lines: list[str] = []
        start = time.monotonic()
        try:
            while True:
                if time.monotonic() - start > self.timeout_seconds:
                    proc.kill()
                    await proc.wait()
                    raise AdapterError(
                        self.name, f"CLI timed out after {self.timeout_seconds}s"
                    )
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                line_s = line.decode(errors="replace").rstrip("\r\n")
                if not line_s:
                    continue
                stdout_lines.append(line_s)
                try:
                    yield json.loads(line_s)
                except json.JSONDecodeError:
                    # Skip unparseable lines (log prefixes etc.). Kept in debug dump.
                    continue

            await proc.wait()
        finally:
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            stderr_str = stderr_buf.decode(errors="replace")
            self._dump_debug("\n".join(stdout_lines), stderr_str, proc.returncode or 0, argv)

        if proc.returncode:
            raise AdapterError(
                self.name,
                f"CLI exited with code {proc.returncode}",
                stderr=stderr_str.strip()[-2000:],
            )

    async def _stream_ndjson_with_fallback(
        self,
        primary_argv: list[str],
        fallback_argv: list[str] | None = None,
        stdin_payload: str | None = None,
    ) -> AsyncIterator[dict]:
        try:
            async for item in self._stream_ndjson(primary_argv, stdin_payload=stdin_payload):
                yield item
            return
        except AdapterError as e:
            if not fallback_argv or not _looks_like_invalid_model(str(e)):
                raise
            log.warning("%s: primary model rejected, retrying with fallback argv", self.name)
            async for item in self._stream_ndjson(fallback_argv, stdin_payload=stdin_payload):
                yield item

    def _dump_debug(self, stdout: str, stderr: str, rc: int, argv: list[str]) -> None:
        if os.getenv("COUNCIL_DEBUG", "1") == "0":
            return
        try:
            path_root = debug_dir()
            path_root.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            path = path_root / f"{self.name}-{ts}-rc{rc}.log"
            path.write_text(
                f"argv: {argv}\nrc: {rc}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
            )
            log.info("%s: debug dump at %s", self.name, path)
        except Exception as e:  # noqa: BLE001
            log.warning("failed to write debug dump: %s", e)


def _looks_like_invalid_model(message: str) -> bool:
    text = message.lower()
    needles = (
        "invalid model",
        "unknown model",
        "unsupported model",
        "model not found",
        "not a valid model",
        "unrecognized model",
    )
    return any(needle in text for needle in needles)
