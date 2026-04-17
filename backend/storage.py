from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime import conversations_dir


def _ensure_root() -> None:
    conversations_dir().mkdir(parents=True, exist_ok=True)


def save(conversation: dict[str, Any]) -> Path:
    _ensure_root()
    path = conversations_dir() / f"{conversation['id']}.json"
    path.write_text(json.dumps(conversation, indent=2))
    return path


def load(conv_id: str) -> dict[str, Any] | None:
    path = conversations_dir() / f"{conv_id}.json"
    if not path.exists():
        return None
    return _normalize_run(json.loads(path.read_text()))


def list_summaries() -> list[dict[str, Any]]:
    _ensure_root()
    threads: dict[str, dict[str, Any]] = {}
    for p in conversations_dir().glob("*.json"):
        try:
            data = _normalize_run(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
        thread_id = data["thread_id"]
        summary = threads.setdefault(thread_id, {
            "id": thread_id,
            "title": data.get("question", "")[:200],
            "latest_question": data.get("question", "")[:200],
            "updated_at": data.get("created_at"),
            "created_at": data.get("created_at"),
            "turn_count": 0,
            "_first_turn": data.get("turn_index", 0),
            "_latest_turn": data.get("turn_index", 0),
        })
        turn_index = data.get("turn_index", 0)
        summary["turn_count"] += 1
        if turn_index < summary["_first_turn"]:
            summary["_first_turn"] = turn_index
            summary["title"] = data.get("question", "")[:200]
            summary["created_at"] = data.get("created_at")
        if turn_index >= summary["_latest_turn"]:
            summary["_latest_turn"] = turn_index
            summary["latest_question"] = data.get("question", "")[:200]
            summary["updated_at"] = data.get("created_at")
    out = sorted(
        ({
            "id": item["id"],
            "title": item["title"],
            "latest_question": item["latest_question"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "turn_count": item["turn_count"],
        } for item in threads.values()),
        key=lambda item: item.get("updated_at") or "",
        reverse=True,
    )
    return out


def load_thread(thread_id: str) -> dict[str, Any] | None:
    _ensure_root()
    runs = list_runs_for_thread(thread_id)
    if not runs:
        singleton = load(thread_id)
        if singleton is None:
            return None
        runs = [singleton]
    runs_desc = sorted(runs, key=lambda run: (run.get("turn_index", 0), run.get("created_at") or ""), reverse=True)
    latest = runs_desc[0]
    first = min(runs_desc, key=lambda run: (run.get("turn_index", 0), run.get("created_at") or ""))
    return {
        "id": thread_id,
        "title": first.get("question", "")[:200],
        "created_at": first.get("created_at"),
        "updated_at": latest.get("created_at"),
        "turn_count": len(runs_desc),
        "runs": runs_desc,
    }


def list_runs_for_thread(thread_id: str) -> list[dict[str, Any]]:
    _ensure_root()
    runs: list[dict[str, Any]] = []
    for p in conversations_dir().glob("*.json"):
        try:
            data = _normalize_run(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
        if data.get("thread_id") == thread_id:
            runs.append(data)
    runs.sort(key=lambda run: (run.get("turn_index", 0), run.get("created_at") or ""))
    return runs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_run(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "id": "",
            "thread_id": "",
            "parent_id": None,
            "turn_index": 0,
        }
    run_id = str(data.get("id", ""))
    out = dict(data)
    out.setdefault("thread_id", run_id)
    out.setdefault("parent_id", None)
    out.setdefault("turn_index", 0)
    out.setdefault("is_followup", bool(out.get("parent_id")))
    return out
