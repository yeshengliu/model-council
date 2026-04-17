from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import storage
from .config import CHAIRMAN_NAME, member_descriptions
from .council import run_council_stream
from .runtime import desktop_mode, frontend_dist_dir
from .settings import (
    get_payload as get_settings_payload,
    save as save_settings,
    save_app as save_app_settings,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Model Council")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskPayload(BaseModel):
    question: str
    thread_id: str | None = None
    parent_id: str | None = None
    debate_enabled: bool = False


class SettingsPayload(BaseModel):
    settings: dict | None = None
    app_settings: dict | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "desktop_mode": desktop_mode()}


@app.get("/api/council")
def council_info():
    members = member_descriptions()
    return {
        "members": members,
        "chairman": next((member["name"] for member in members if member.get("enabled")), CHAIRMAN_NAME),
    }


@app.get("/api/settings")
def get_settings():
    return get_settings_payload()


@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    try:
        if payload.settings is not None:
            save_settings(payload.settings)
        if payload.app_settings is not None:
            save_app_settings(payload.app_settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return get_settings_payload()


@app.get("/api/conversations")
def list_conversations():
    return storage.list_summaries()


@app.get("/api/threads/{thread_id}")
def get_thread(thread_id: str):
    data = storage.load_thread(thread_id)
    if data is None:
        raise HTTPException(404, "not found")
    return data


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str):
    data = storage.load(conv_id)
    if data is None:
        raise HTTPException(404, "not found")
    return data


@app.post("/api/ask")
async def ask(payload: AskPayload):
    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "question is required")

    async def event_gen():
        async for event in run_council_stream(
            question,
            thread_id=payload.thread_id,
            parent_id=payload.parent_id,
            debate_enabled=payload.debate_enabled,
        ):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_gen())


# Serve built frontend, if present.
_FRONTEND_DIST = frontend_dist_dir()
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
