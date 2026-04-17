from __future__ import annotations

from typing import AsyncIterator

from .base import ModelAdapter


class GeminiAdapter(ModelAdapter):
    name = "gemini"
    display_name = "Gemini CLI"

    def __init__(
        self,
        binary: str = "gemini",
        timeout_seconds: int = 180,
        model: str | None = None,
        fallback_model: str | None = None,
    ):
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.fallback_model = fallback_model

    def describe(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "binary": self.binary,
            "runtime_model_source": "reported by Gemini init event",
            "invocation": ["-p <prompt>", "--output-format stream-json"],
            "options": [
                {"label": "Internet", "value": "CLI-managed; may use built-in search/tool calls"},
                {"label": "Thinking mode", "value": "CLI-managed; wrapper does not force a reasoning tier"},
                {"label": "Filesystem", "value": "CLI-managed by local Gemini CLI behavior"},
            ],
        }

    async def stream_query(
        self, prompt: str, system: str | None = None
    ) -> AsyncIterator[dict]:
        full = prompt if not system else f"{system}\n\n---\n\n{prompt}"
        argv = [
            self.binary,
            "-p", full,
            "--output-format", "stream-json",
        ]
        if self.model:
            argv += ["--model", self.model]

        fallback_argv = list(argv)
        if self.model and self.fallback_model and self.fallback_model != self.model:
            idx = fallback_argv.index("--model")
            fallback_argv[idx + 1] = self.fallback_model
        else:
            fallback_argv = None

        acc = ""
        async for ev in self._stream_ndjson_with_fallback(argv, fallback_argv=fallback_argv):
            t = ev.get("type")
            if t == "init" and ev.get("model"):
                yield {"type": "meta", "runtime_model": ev["model"]}

            if t == "message" and ev.get("role") == "assistant":
                content = ev.get("content")
                if not isinstance(content, str) or not content:
                    continue
                # When Gemini marks delta=true, each event is an incremental
                # chunk. Otherwise it may send a cumulative string.
                if ev.get("delta") is True or not acc:
                    acc += content
                    yield {"type": "delta", "text": content}
                elif content.startswith(acc):
                    chunk = content[len(acc):]
                    if chunk:
                        acc = content
                        yield {"type": "delta", "text": chunk}
                else:
                    acc += content
                    yield {"type": "delta", "text": content}

            elif t == "result":
                stats_models = ((ev.get("stats") or {}).get("models") or {})
                if isinstance(stats_models, dict) and stats_models:
                    yield {"type": "meta", "runtime_model": next(iter(stats_models.keys()))}
                if ev.get("status") and ev.get("status") != "success":
                    yield {"type": "error", "message": f"gemini status: {ev.get('status')}"}
                    return
                yield {"type": "done", "text": acc}
                return

            elif t == "error":
                err = ev.get("error") or ev.get("message") or "unknown error"
                if isinstance(err, dict):
                    err = err.get("message") or str(err)
                yield {"type": "error", "message": str(err)}
                return

        yield {"type": "done", "text": acc}
