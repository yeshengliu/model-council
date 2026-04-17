from __future__ import annotations

from .adapters import ClaudeAdapter, CodexAdapter, GeminiAdapter, ModelAdapter
from .settings import resolve

RESEARCH_TIMEOUT_SECONDS = 240
RESEARCH_TOOLS = ["WebSearch", "WebFetch"]
RESEARCH_ORDER = ["codex", "claude"]

TIMEOUT_SECONDS = 180
CHAIRMAN_ORDER = ["codex", "claude", "gemini"]

COUNCIL: list[ModelAdapter] = []

CHAIRMAN_NAME = CHAIRMAN_ORDER[0]


def make_council() -> list[ModelAdapter]:
    settings = resolve()
    adapters = [
        ClaudeAdapter(
            timeout_seconds=TIMEOUT_SECONDS,
            model=settings["claude"]["preferred_model"],
            fallback_model=settings["claude"]["fallback_model"],
            thinking_enabled=settings["claude"]["thinking_enabled"],
        ),
        GeminiAdapter(
            timeout_seconds=TIMEOUT_SECONDS,
            model=settings["gemini"]["preferred_model"],
            fallback_model=settings["gemini"]["fallback_model"],
        ),
        CodexAdapter(
            timeout_seconds=TIMEOUT_SECONDS,
            model=settings["codex"]["preferred_model"],
            thinking_enabled=settings["codex"]["thinking_enabled"],
        ),
    ]
    active = [adapter for adapter in adapters if settings[adapter.name]["enabled"]]
    if len(active) < 2:
        raise RuntimeError("at least two active models are required")
    return active


def chairman(council: list[ModelAdapter]) -> ModelAdapter:
    for target in CHAIRMAN_ORDER:
        for a in council:
            if a.name == target:
                return a
    raise RuntimeError("no chairman candidate found")


def make_research_council() -> list[ModelAdapter]:
    settings = resolve()
    adapters_by_name = {
        "claude": ClaudeAdapter(
            timeout_seconds=RESEARCH_TIMEOUT_SECONDS,
            model=settings["claude"]["preferred_model"],
            fallback_model=settings["claude"]["fallback_model"],
            thinking_enabled=False,
            allowed_tools=RESEARCH_TOOLS,
        ),
        "codex": CodexAdapter(
            timeout_seconds=RESEARCH_TIMEOUT_SECONDS,
            model=settings["codex"]["preferred_model"],
            thinking_enabled=False,
            enable_search=True,
        ),
    }
    return [
        adapters_by_name[name]
        for name in RESEARCH_ORDER
        if name in adapters_by_name and settings[name]["enabled"]
    ]


def member_descriptions() -> list[dict]:
    settings = resolve()
    out: list[dict] = []
    for adapter in make_council():
        info = adapter.describe()
        cfg = settings[adapter.name]
        info["enabled"] = cfg["enabled"]
        info["selected_model_label"] = cfg["selected_label"]
        info["selected_model_key"] = cfg["selected_key"]
        info["thinking_enabled"] = cfg["thinking_enabled"]
        info["thinking_supported"] = cfg["thinking_supported"]
        out.append(info)
    return out
