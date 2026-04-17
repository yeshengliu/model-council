from __future__ import annotations

from typing import AsyncIterator

from .base import ModelAdapter


class ClaudeAdapter(ModelAdapter):
    name = "claude"
    display_name = "Claude Code"

    def __init__(
        self,
        binary: str = "claude",
        timeout_seconds: int = 180,
        model: str | None = None,
        fallback_model: str | None = None,
        thinking_enabled: bool = False,
        allowed_tools: list[str] | None = None,
    ):
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.fallback_model = fallback_model
        self.thinking_enabled = thinking_enabled
        self.allowed_tools = allowed_tools

    def describe(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "binary": self.binary,
            "runtime_model_source": "reported by Claude init event",
            "invocation": ["-p", "--no-session-persistence", "--output-format stream-json", "--verbose", "--include-partial-messages"],
            "options": [
                {"label": "Internet", "value": "CLI-managed; wrapper does not explicitly disable web/tool use"},
                {"label": "Thinking mode", "value": "CLI-managed; wrapper does not force a reasoning mode"},
                {"label": "Filesystem", "value": "CLI-managed by local Claude Code defaults"},
            ],
        }

    async def stream_query(
        self, prompt: str, system: str | None = None
    ) -> AsyncIterator[dict]:
        argv = [
            self.binary,
            "-p",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if self.model:
            argv += ["--model", self.model]
        if self.thinking_enabled:
            argv += ["--effort", "high"]
        if self.allowed_tools is not None:
            argv += ["--allowedTools", ",".join(self.allowed_tools)]
        if system:
            argv += ["--append-system-prompt", system]

        fallback_argv = list(argv)
        if self.model and self.fallback_model and self.fallback_model != self.model:
            idx = fallback_argv.index("--model")
            fallback_argv[idx + 1] = self.fallback_model
        else:
            fallback_argv = None

        acc = ""
        async for ev in self._stream_ndjson_with_fallback(
            argv,
            fallback_argv=fallback_argv,
            stdin_payload=prompt,
        ):
            t = ev.get("type")
            if t == "system" and ev.get("subtype") == "init" and ev.get("model"):
                yield {"type": "meta", "runtime_model": ev["model"]}
            if t == "stream_event":
                se = ev.get("event") or {}
                if se.get("type") == "content_block_delta":
                    delta = se.get("delta") or {}
                    text = delta.get("text") or ""
                    if text:
                        acc += text
                        yield {"type": "delta", "text": text}
            elif t == "assistant":
                msg = ev.get("message") or {}
                for c in msg.get("content") or []:
                    if c.get("type") == "text":
                        text = c.get("text") or ""
                        if text and text != acc:
                            # Some versions emit full message blocks; diff against
                            # the accumulator so we don't double-render when
                            # deltas also came through.
                            if text.startswith(acc):
                                text = text[len(acc):]
                            if text:
                                acc += text
                                yield {"type": "delta", "text": text}
            elif t == "result":
                if ev.get("is_error"):
                    yield {"type": "error", "message": ev.get("result") or "unknown error"}
                    return
                final = ev.get("result") or acc
                yield {"type": "done", "text": final}
                return

        # Stream ended without a result event — treat accumulated text as final.
        yield {"type": "done", "text": acc}
