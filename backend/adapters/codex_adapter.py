from __future__ import annotations

import os
import tempfile
from typing import AsyncIterator

from .base import ModelAdapter


class CodexAdapter(ModelAdapter):
    name = "codex"
    display_name = "Codex CLI"

    def __init__(
        self,
        binary: str = "codex",
        timeout_seconds: int = 180,
        model: str | None = None,
        thinking_enabled: bool = False,
        enable_search: bool = False,
    ):
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.thinking_enabled = thinking_enabled
        self.enable_search = enable_search
        self._sandbox = os.path.join(tempfile.gettempdir(), "council-codex-sandbox")
        os.makedirs(self._sandbox, exist_ok=True)

    def describe(self) -> dict:
        thinking_desc = "Sets model_reasoning_effort=high" if self.thinking_enabled else "Default reasoning effort"
        return {
            "name": self.name,
            "display_name": self.display_name,
            "binary": self.binary,
            "runtime_model_source": "requested via --model (codex exec JSON stream does not echo the model)",
            "invocation": ["exec", "--json", "--cd <temp-sandbox>", "--sandbox read-only", "--skip-git-repo-check"],
            "options": [
                {"label": "Internet", "value": "CLI-managed; web tools may be available depending on Codex settings"},
                {"label": "Thinking mode", "value": thinking_desc},
                {"label": "Filesystem", "value": "Read-only sandbox in a temp workspace"},
            ],
        }

    async def stream_query(
        self, prompt: str, system: str | None = None
    ) -> AsyncIterator[dict]:
        full = prompt if not system else f"{system}\n\n---\n\n{prompt}"
        argv = [
            self.binary,
        ]
        if self.enable_search:
            argv.append("--search")
        argv += [
            "exec",
            "--json",
            "--cd", self._sandbox,
            "--sandbox", "read-only",
            "--skip-git-repo-check",
        ]
        if self.model:
            argv += ["--model", self.model]
            yield {"type": "meta", "runtime_model": self.model}
        if self.thinking_enabled:
            argv += ["-c", 'model_reasoning_effort="high"']
        argv.append(full)

        acc = ""
        async for ev in self._stream_ndjson(argv):
            text = _event_message(ev)
            if not text:
                continue
            # Codex emits the full assistant message in a single event. If we
            # somehow see multiple, treat each beyond the first as incremental.
            if text.startswith(acc) and len(text) > len(acc):
                delta = text[len(acc):]
                acc = text
                yield {"type": "delta", "text": delta}
            elif text and text != acc:
                acc += text
                yield {"type": "delta", "text": text}

        yield {"type": "done", "text": acc}


def _event_message(ev: dict) -> str | None:
    """Extract assistant text from a Codex exec JSON event across version shapes."""
    if ev.get("role") == "assistant" and isinstance(ev.get("content"), str):
        return ev["content"]

    msg = ev.get("msg")
    if isinstance(msg, dict):
        t = msg.get("type", "")
        if t in ("agent_message", "agent_message_delta", "assistant_message", "final_message"):
            for key in ("message", "text", "content"):
                v = msg.get(key)
                if isinstance(v, str) and v.strip():
                    return v

    item = ev.get("item")
    if isinstance(item, dict):
        item_type = item.get("type") or item.get("item_type")
        if item_type in ("assistant_message", "agent_message") and isinstance(item.get("text"), str):
            return item["text"]

    return None
