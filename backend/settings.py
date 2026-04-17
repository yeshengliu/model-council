from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .runtime import settings_path

SETTINGS_META: dict[str, Any] = {
    "claude": {
        "display_name": "Claude Code",
        "models": [
            {
                "key": "sonnet",
                "label": "Sonnet (claude-sonnet-4-6)",
                "preferred_model": "claude-sonnet-4-6",
                "fallback_model": "sonnet",
            },
            {
                "key": "opus",
                "label": "Opus (claude-opus-4-6)",
                "preferred_model": "claude-opus-4-6",
                "fallback_model": "opus",
            },
        ],
        "thinking": {
            "supported": True,
            "label": "Thinking",
            "description": "Uses Claude effort high when enabled.",
        },
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "models": [
            {
                "key": "pro",
                "label": "Pro (gemini-3-pro-preview)",
                "preferred_model": "gemini-3-pro-preview",
                "fallback_model": "gemini-2.5-pro",
            },
            {
                "key": "flash",
                "label": "Flash (gemini-3-flash-preview)",
                "preferred_model": "gemini-3-flash-preview",
                "fallback_model": "gemini-2.5-flash",
            },
        ],
        "thinking": {
            "supported": False,
            "label": "Thinking",
            "description": "Gemini manages reasoning internally; Pro models reason by default.",
            "auto_on_model_keys": ["pro"],
            "auto_on_text": "Thinking mode enabled",
            "auto_off_text": "Managed by Gemini CLI",
        },
    },
    "codex": {
        "display_name": "Codex CLI",
        "models": [
            {
                "key": "gpt_5_4",
                "label": "GPT-5.4 (gpt-5.4)",
                "preferred_model": "gpt-5.4",
                "fallback_model": None,
            },
            {
                "key": "gpt_5_3_codex",
                "label": "GPT-5.3 Codex (gpt-5.3-codex)",
                "preferred_model": "gpt-5.3-codex",
                "fallback_model": None,
            },
        ],
        "thinking": {
            "supported": True,
            "label": "Thinking",
            "description": "Sets model_reasoning_effort=high via 'codex exec -c'.",
        },
    },
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "claude": {"enabled": True, "default_model": "sonnet", "thinking_enabled": True},
    "gemini": {"enabled": True, "default_model": "flash"},
    "codex": {"enabled": True, "default_model": "gpt_5_4", "thinking_enabled": False},
}

APP_SETTINGS_META: dict[str, Any] = {
    "research_enabled": {
        "label": "Ground with live web research",
        "description": "Before the council answers, Claude and Codex run web research in parallel and share the findings into the later council stages.",
    },
}

DEFAULT_APP_SETTINGS: dict[str, Any] = {
    "research_enabled": True,
}


def _ensure_parent() -> None:
    settings_path().parent.mkdir(parents=True, exist_ok=True)


def _read_raw() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def load() -> dict[str, Any]:
    data = deepcopy(DEFAULT_SETTINGS)
    raw = _read_raw()
    for name, section in data.items():
        incoming = raw.get(name)
        if not isinstance(incoming, dict):
            continue
        section.update(incoming)
    return sanitize(data)


def load_app() -> dict[str, Any]:
    data = deepcopy(DEFAULT_APP_SETTINGS)
    raw = _read_raw().get("app")
    if isinstance(raw, dict):
        data.update(raw)
    return sanitize_app(data)


def save(settings: dict[str, Any], app_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = sanitize(settings)
    normalized_app = sanitize_app(app_settings) if app_settings is not None else load_app()
    _ensure_parent()
    payload = dict(normalized)
    payload["app"] = normalized_app
    settings_path().write_text(json.dumps(payload, indent=2))
    return normalized


def save_app(app_settings: dict[str, Any]) -> dict[str, Any]:
    current = load()
    save(current, app_settings)
    return load_app()


def sanitize(settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(DEFAULT_SETTINGS)
    for cli, defaults in out.items():
        current = settings.get(cli, {})
        model_keys = {item["key"] for item in SETTINGS_META[cli]["models"]}
        out[cli]["enabled"] = bool(current.get("enabled", defaults["enabled"]))
        selected = current.get("default_model")
        if selected in model_keys:
            out[cli]["default_model"] = selected
        if "thinking_enabled" in defaults:
            out[cli]["thinking_enabled"] = bool(current.get("thinking_enabled", defaults["thinking_enabled"]))
    enabled_count = sum(1 for section in out.values() if section.get("enabled"))
    if enabled_count < 2:
        raise ValueError("at least two models must remain enabled")
    return out


def sanitize_app(app_settings: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(DEFAULT_APP_SETTINGS)
    for key in out:
        if key in app_settings:
            out[key] = bool(app_settings[key])
    return out


def get_payload() -> dict[str, Any]:
    return {
        "settings": load(),
        "options": deepcopy(SETTINGS_META),
        "app_settings": load_app(),
        "app_options": deepcopy(APP_SETTINGS_META),
    }


def resolve(settings: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    current = sanitize(settings or load())
    resolved: dict[str, dict[str, Any]] = {}
    for cli, section in current.items():
        meta = SETTINGS_META[cli]
        choice = next(item for item in meta["models"] if item["key"] == section["default_model"])
        resolved[cli] = {
            "enabled": bool(section.get("enabled", True)),
            "display_name": meta["display_name"],
            "selected_key": choice["key"],
            "selected_label": choice["label"],
            "preferred_model": choice["preferred_model"],
            "fallback_model": choice.get("fallback_model"),
            "thinking_enabled": bool(section.get("thinking_enabled", False)) if meta["thinking"]["supported"] else False,
            "thinking_supported": bool(meta["thinking"]["supported"]),
        }
    return resolved
