"""Exercise the backend without the frontend.

Usage:
    uv run python scripts/test_backend.py adapters        # probe each CLI once
    uv run python scripts/test_backend.py council "question here"
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters import AdapterError, ClaudeAdapter, CodexAdapter, GeminiAdapter
from backend.council import run_council_stream


async def probe_one(adapter, prompt: str) -> None:
    name = adapter.name
    print(f"\n=== {name} ===")
    try:
        text = await adapter.query(prompt)
        print(f"[ok] {len(text)} chars")
        print(text[:500] + ("…" if len(text) > 500 else ""))
    except AdapterError as e:
        print(f"[FAIL] {e}")
    except Exception as e:
        print(f"[CRASH] {type(e).__name__}: {e}")


async def probe_all() -> None:
    prompt = "In one short sentence: what is 2+2?"
    for ad in (ClaudeAdapter(), GeminiAdapter(), CodexAdapter()):
        await probe_one(ad, prompt)


async def full_council(question: str) -> None:
    print(f"\n=== Council run: {question!r} ===\n")
    async for ev in run_council_stream(question):
        # Truncate long text fields so the stream is readable.
        ev_copy = dict(ev)
        for k in ("text", "error"):
            if k in ev_copy and isinstance(ev_copy[k], str) and len(ev_copy[k]) > 300:
                ev_copy[k] = ev_copy[k][:300] + "…"
        print(json.dumps(ev_copy, indent=2))
        print("---")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "adapters":
        asyncio.run(probe_all())
    elif cmd == "council":
        question = sys.argv[2] if len(sys.argv) > 2 else "In one short sentence: what is 2+2?"
        asyncio.run(full_council(question))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
