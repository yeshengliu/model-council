from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, AsyncIterator

from . import storage
from .adapters import AdapterError, ModelAdapter
from .config import chairman, make_council, make_research_council
from .prompts import (
    COUNCIL_SYSTEM,
    RESEARCH_SYSTEM,
    debate_referee_prompt,
    debate_rebuttal_prompt,
    debate_synthesis_prompt,
    peer_review_prompt,
    research_prompt,
    synthesis_prompt,
    wrap_with_followup_context,
    wrap_with_research,
)
from .settings import load_app

_SENTINEL = object()
MAX_DEBATE_ROUNDS = 3


def _is_rate_limited(message: str | None) -> bool:
    if not message:
        return False
    text = message.lower()
    return any(token in text for token in ("rate limit", "rate-limited", "hit your limit", "too many requests", "quota"))


def _anonymize(members: list[ModelAdapter]) -> dict[str, str]:
    letters = [chr(ord("A") + i) for i in range(len(members))]
    random.shuffle(letters)
    return {m.name: letters[i] for i, m in enumerate(members)}


def _parse_referee_summary(text: str) -> dict[str, Any]:
    decision = "STOP"
    focus_points: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.lower().startswith("decision:"):
            decision = "CONTINUE" if "continue" in line.lower() else "STOP"
        elif line.startswith("- "):
            focus_points.append(line[2:].strip())
    return {
        "decision": decision,
        "focus_points": focus_points[:3],
        "text": text,
    }


async def _pump_one(
    adapter: ModelAdapter,
    prompt: str,
    stage: str,
    queue: asyncio.Queue,
    system: str = COUNCIL_SYSTEM,
) -> None:
    """Run one adapter's streaming call; push its events onto the shared queue."""
    await queue.put({"type": "model_started", "stage": stage, "model": adapter.name})
    acc = ""
    final_text: str | None = None
    error: str | None = None
    try:
        async for ev in adapter.stream_query(prompt, system=system):
            t = ev.get("type")
            if t == "delta":
                chunk = ev.get("text") or ""
                if chunk:
                    acc += chunk
                    await queue.put({
                        "type": "delta",
                        "stage": stage,
                        "model": adapter.name,
                        "text": chunk,
                    })
            elif t == "meta":
                await queue.put({
                    "type": "model_meta",
                    "stage": stage,
                    "model": adapter.name,
                    **{k: v for k, v in ev.items() if k != "type"},
                })
            elif t == "done":
                final_text = ev.get("text") or acc
            elif t == "error":
                error = ev.get("message") or "unknown error"
    except AdapterError as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001
        error = f"{adapter.name}: unexpected error: {e!r}"

    await queue.put({
        "type": "__model_done__",
        "stage": stage,
        "model": adapter.name,
        "display_name": adapter.display_name,
        "text": final_text if error is None else None,
        "error": error,
    })


async def _run_stage(
    stage: str,
    tasks: list[tuple[ModelAdapter, str]],
    system: str = COUNCIL_SYSTEM,
) -> AsyncIterator[dict[str, Any]]:
    """Run N adapter streams concurrently, yield interleaved events.

    Yields model_started / delta events live, then a terminal __model_done__
    event per model (stripped to the caller as it pleases).
    """
    queue: asyncio.Queue = asyncio.Queue()
    pumps = [asyncio.create_task(_pump_one(a, p, stage, queue, system=system)) for a, p in tasks]

    remaining = len(tasks)
    try:
        while remaining > 0:
            ev = await queue.get()
            if ev.get("type") == "__model_done__":
                remaining -= 1
            yield ev
    finally:
        for t in pumps:
            if not t.done():
                t.cancel()
        for t in pumps:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


async def run_council_stream(
    question: str,
    thread_id: str | None = None,
    parent_id: str | None = None,
    debate_enabled: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    conv_id = str(uuid.uuid4())
    members = make_council()
    anon = _anonymize(members)
    chair = chairman(members)
    parent_run = storage.load(parent_id) if parent_id else None
    effective_thread_id = thread_id or conv_id
    prior_runs = storage.list_runs_for_thread(effective_thread_id) if thread_id else []
    turn_index = len(prior_runs)
    contextual_question = wrap_with_followup_context(question, parent_run)

    conversation: dict[str, Any] = {
        "id": conv_id,
        "thread_id": effective_thread_id,
        "parent_id": parent_id,
        "turn_index": turn_index,
        "is_followup": bool(parent_id),
        "created_at": storage.now_iso(),
        "question": question,
        "chairman": chair.name,
        "anonymization": anon,
        "runtime_models": {},
        "research": {},
        "answers": {},
        "reviews": {},
        "debate_enabled": debate_enabled,
        "debate": {
            "rounds": [],
            "referee_summaries": [],
            "stopped_reason": None,
        },
        "synthesis": None,
    }

    yield {
        "type": "start",
        "id": conv_id,
        "members": [
            {"name": m.name, "display_name": m.display_name, "label": anon[m.name]}
            for m in members
        ],
        "chairman": chair.name,
        "question": question,
        "thread_id": effective_thread_id,
        "parent_id": parent_id,
        "turn_index": turn_index,
        "is_followup": bool(parent_id),
        "debate_enabled": debate_enabled,
    }

    # ---- Stage 0: optional web research ----
    research_blocks: list[tuple[str, str]] = []
    if load_app().get("research_enabled"):
        yield {"type": "stage", "stage": "research", "status": "started"}
        research_members = make_research_council()
        async for ev in _run_stage(
            "research",
            [(adapter, research_prompt(contextual_question)) for adapter in research_members],
            system=RESEARCH_SYSTEM,
        ):
            if ev.get("type") == "model_meta":
                if ev.get("runtime_model"):
                    conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
                yield ev
            elif ev.get("type") == "__model_done__":
                name = ev["model"]
                display_name = ev["display_name"]
                if ev.get("error"):
                    conversation["research"][name] = {
                        "display_name": display_name,
                        "error": ev["error"],
                    }
                    yield {
                        "type": "research",
                        "model": name,
                        "display_name": display_name,
                        "error": ev["error"],
                    }
                else:
                    text = ev.get("text") or ""
                    conversation["research"][name] = {
                        "display_name": display_name,
                        "text": text,
                    }
                    research_blocks.append((display_name, text))
                    yield {
                        "type": "research",
                        "model": name,
                        "display_name": display_name,
                        "text": text,
                    }
            else:
                yield ev
        yield {"type": "stage", "stage": "research", "status": "done"}

    combined_research = "\n\n".join(
        f"### {display_name}\n{text.strip()}" for display_name, text in research_blocks if text.strip()
    )
    grounded_question = wrap_with_research(contextual_question, combined_research or None)

    # ---- Stage 1: fan-out ----
    yield {"type": "stage", "stage": "fanout", "status": "started"}
    tasks = [(a, grounded_question) for a in members]
    async for ev in _run_stage("fanout", tasks):
        if ev.get("type") == "model_meta":
            if ev.get("runtime_model"):
                conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
            yield ev
        elif ev.get("type") == "__model_done__":
            name = ev["model"]
            display_name = ev["display_name"]
            if ev.get("error"):
                conversation["answers"][name] = {
                    "display_name": display_name,
                    "label": anon[name],
                    "error": ev["error"],
                }
                yield {
                    "type": "answer",
                    "model": name,
                    "display_name": display_name,
                    "label": anon[name],
                    "error": ev["error"],
                }
            else:
                text = ev.get("text") or ""
                conversation["answers"][name] = {
                    "display_name": display_name,
                    "label": anon[name],
                    "text": text,
                }
                yield {
                    "type": "answer",
                    "model": name,
                    "display_name": display_name,
                    "label": anon[name],
                    "text": text,
                }
        else:
            yield ev
    yield {"type": "stage", "stage": "fanout", "status": "done"}

    referee_texts: list[str] = []
    if debate_enabled:
        yield {"type": "stage", "stage": "review", "status": "started"}
        focus_points: list[str] = []
        stopped_reason = "max rounds reached"
        for round_index in range(1, MAX_DEBATE_ROUNDS + 1):
            yield {"type": "debate_round_started", "round": round_index}
            round_tasks: list[tuple[ModelAdapter, str]] = []
            for debater in members:
                own_entry = conversation["answers"].get(debater.name, {})
                own_answer = own_entry.get("text") or f"(no response — {own_entry.get('error', 'unknown error')})"
                others: list[tuple[str, str]] = []
                for other in members:
                    if other.name == debater.name:
                        continue
                    if round_index == 1:
                        entry = conversation["answers"].get(other.name, {})
                    else:
                        previous_round = conversation["debate"]["rounds"][-1]["responses"]
                        entry = previous_round.get(other.name, {})
                    body = entry.get("text") or f"(no response — {entry.get('error', 'unknown error')})"
                    others.append((other.display_name, body))
                round_tasks.append((debater, debate_rebuttal_prompt(grounded_question, own_answer, others, focus_points or None)))

            round_responses: dict[str, Any] = {}
            async for ev in _run_stage("review", round_tasks):
                if ev.get("type") == "model_meta":
                    if ev.get("runtime_model"):
                        conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
                    yield ev
                elif ev.get("type") == "__model_done__":
                    name = ev["model"]
                    display_name = ev["display_name"]
                    if ev.get("error"):
                        round_responses[name] = {"display_name": display_name, "error": ev["error"]}
                    else:
                        round_responses[name] = {"display_name": display_name, "text": ev.get("text") or ""}
                    yield {
                        "type": "debate_turn",
                        "round": round_index,
                        "model": name,
                        "display_name": display_name,
                        "text": round_responses[name].get("text"),
                        "error": round_responses[name].get("error"),
                    }
                else:
                    yield ev

            conversation["debate"]["rounds"].append({
                "round_index": round_index,
                "focus_points": focus_points,
                "responses": round_responses,
            })
            yield {"type": "debate_round_done", "round": round_index}

            ref_tasks = [(chair, debate_referee_prompt(
                grounded_question,
                [(m.display_name, conversation["answers"][m.name].get("text") or "(no response)") for m in members],
                conversation["debate"]["rounds"],
            ))]
            referee_text = ""
            async for ev in _run_stage("review", ref_tasks):
                if ev.get("type") == "model_meta":
                    if ev.get("runtime_model"):
                        conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
                    yield ev
                elif ev.get("type") == "__model_done__":
                    referee_text = ev.get("text") or ev.get("error") or ""
                else:
                    yield ev
            parsed = _parse_referee_summary(referee_text)
            referee_texts.append(referee_text)
            conversation["debate"]["referee_summaries"].append({
                "round_index": round_index,
                "decision": parsed["decision"],
                "focus_points": parsed["focus_points"],
                "text": referee_text,
            })
            yield {
                "type": "debate_referee",
                "round": round_index,
                "decision": parsed["decision"],
                "focus_points": parsed["focus_points"],
                "text": referee_text,
            }
            focus_points = parsed["focus_points"]
            if parsed["decision"] != "CONTINUE":
                stopped_reason = f"referee stopped after round {round_index}"
                break
        conversation["debate"]["stopped_reason"] = stopped_reason
        yield {"type": "stage", "stage": "review", "status": "done"}
    else:
        # ---- Stage 2: peer review ----
        yield {"type": "stage", "stage": "review", "status": "started"}
        review_tasks: list[tuple[ModelAdapter, str]] = []
        for reviewer in members:
            others: list[tuple[str, str]] = []
            for a in members:
                if a.name == reviewer.name:
                    continue
                entry = conversation["answers"].get(a.name, {})
                body = entry.get("text") or f"(no response — {entry.get('error', 'unknown error')})"
                others.append((anon[a.name], body))
            review_tasks.append((reviewer, peer_review_prompt(grounded_question, others)))

        async for ev in _run_stage("review", review_tasks):
            if ev.get("type") == "model_meta":
                if ev.get("runtime_model"):
                    conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
                yield ev
            elif ev.get("type") == "__model_done__":
                name = ev["model"]
                display_name = ev["display_name"]
                if ev.get("error"):
                    conversation["reviews"][name] = {"display_name": display_name, "error": ev["error"]}
                    yield {
                        "type": "review",
                        "reviewer": name,
                        "display_name": display_name,
                        "error": ev["error"],
                    }
                else:
                    text = ev.get("text") or ""
                    conversation["reviews"][name] = {"display_name": display_name, "text": text}
                    yield {
                        "type": "review",
                        "reviewer": name,
                        "display_name": display_name,
                        "text": text,
                    }
            else:
                yield ev
        yield {"type": "stage", "stage": "review", "status": "done"}

    # ---- Stage 3: synthesis ----
    yield {"type": "stage", "stage": "synthesis", "status": "started"}

    named_answers = [
        (m.display_name, conversation["answers"][m.name].get("text") or "(no response)")
        for m in members
    ]
    if debate_enabled:
        synth_prompt = debate_synthesis_prompt(
            grounded_question,
            named_answers,
            conversation["debate"]["rounds"],
            referee_texts,
        )
    else:
        named_reviews = [
            (m.display_name, conversation["reviews"][m.name].get("text") or "(no review)")
            for m in members
        ]
        synth_prompt = synthesis_prompt(grounded_question, named_answers, named_reviews)

    synthesis_candidates = [chair] + [member for member in members if member.name != chair.name]
    active_chair = chair

    for index, candidate in enumerate(synthesis_candidates):
        active_chair = candidate
        async for ev in _run_stage("synthesis", [(candidate, synth_prompt)]):
            if ev.get("type") == "model_meta":
                if ev.get("runtime_model"):
                    conversation["runtime_models"][ev["model"]] = ev["runtime_model"]
                yield ev
                continue
            if ev.get("type") != "__model_done__":
                yield ev
                continue

            error = ev.get("error")
            if error and _is_rate_limited(error) and index < len(synthesis_candidates) - 1:
                replacement = synthesis_candidates[index + 1]
                yield {
                    "type": "chairman_fallback",
                    "from": candidate.name,
                    "to": replacement.name,
                    "reason": error,
                }
                break

            if error:
                conversation["synthesis"] = {"chairman": candidate.name, "error": error}
                yield {"type": "synthesis", "chairman": candidate.name, "error": error}
            else:
                text = ev.get("text") or ""
                conversation["synthesis"] = {"chairman": candidate.name, "text": text}
                yield {"type": "synthesis", "chairman": candidate.name, "text": text}
            break
        else:
            continue

        if conversation["synthesis"] is not None:
            break

    if conversation["synthesis"] is None:
        conversation["synthesis"] = {
            "chairman": active_chair.name,
            "error": "synthesis ended without a final result",
        }
        yield {
            "type": "synthesis",
            "chairman": active_chair.name,
            "error": "synthesis ended without a final result",
        }
    yield {"type": "stage", "stage": "synthesis", "status": "done"}

    path = storage.save(conversation)
    yield {"type": "done", "id": conv_id, "thread_id": effective_thread_id, "path": str(path)}
