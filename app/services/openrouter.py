import json
import time
from typing import Any, Literal

import httpx
from loguru import logger

from app.core.base_client import BaseClient
from app.core.config import settings

ModelKind = Literal["decisions", "chat"]

# Decision models are missing from the default models list. This filter returns
# them and the chat models together, so one lookup can classify any id.
_MODELS_PATH = "/api/v1/models"
_CATALOG_TTL_SECONDS = 6 * 60 * 60
_catalog: tuple[float, dict[str, list[str]]] | None = None


def configured_model() -> str:
    return (settings.OPENROUTER_MODEL or "").strip()


def openrouter_configured() -> bool:
    return bool((settings.OPENROUTER_API_KEY or "").strip() and configured_model())


def kind_for(model: str, catalog: dict[str, list[str]] | None) -> ModelKind:
    """Decisions API when the catalog says this id does not speak text.

    `None` means the catalog could not be loaded. Chat is the fallback so a
    failed lookup still tries the completion the operator named; a decision-only
    model then fails that call and ranking falls back to scores.
    """
    if catalog is None:
        return "chat"
    mods = catalog.get(model)
    if mods is None and not model.startswith("~"):
        mods = catalog.get(f"~{model}")
    if not mods:
        return "chat"
    if "decisions" in mods and "text" not in mods:
        return "decisions"
    return "chat"


class _Client(BaseClient):
    def __init__(self) -> None:
        super().__init__(
            base_url="https://openrouter.ai",
            timeout=20.0,
            max_retries=2,
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.HOST_NAME,
                "X-Title": settings.ADDON_NAME,
            },
        )


def _modalities(entry: dict[str, Any]) -> list[str]:
    architecture = entry.get("architecture") or {}
    mods = architecture.get("output_modalities") or []
    return [mod for mod in mods if isinstance(mod, str)]


async def load_catalog() -> dict[str, list[str]] | None:
    global _catalog
    now = time.monotonic()
    if _catalog and now - _catalog[0] < _CATALOG_TTL_SECONDS:
        return _catalog[1]
    if not openrouter_configured():
        return None
    client = _Client()
    try:
        payload = await client.get(_MODELS_PATH, params={"output_modalities": "all"})
    except httpx.HTTPStatusError as exc:
        logger.warning(f"OpenRouter model list failed: HTTP {exc.response.status_code}")
        return None
    except httpx.RequestError as exc:
        logger.warning(f"OpenRouter model list failed: {type(exc).__name__}")
        return None
    finally:
        await client.close()

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    indexed = {
        entry["id"]: _modalities(entry)
        for entry in data
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    _catalog = (now, indexed)
    return indexed


def reset_catalog_cache() -> None:
    global _catalog
    _catalog = None


async def model_kind() -> ModelKind:
    model = configured_model()
    catalog = await load_catalog()
    kind = kind_for(model, catalog)
    if catalog is not None and model not in catalog and f"~{model}" not in catalog:
        logger.warning(f"OpenRouter model {model} was not in the catalog; using chat completions")
    return kind


async def chat_json(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    structured = {
        "model": configured_model(),
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    data = await _post("/api/v1/chat/completions", structured)
    parsed = _parse_chat_json(data) if isinstance(data, dict) else None
    if parsed is not None:
        return parsed
    if data is not None:
        return None
    plain = await _post("/api/v1/chat/completions", {"model": configured_model(), "messages": messages})
    if not isinstance(plain, dict):
        return None
    return _parse_chat_json(plain)


async def decide(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any] | None:
    data = await _post(
        "/api/alpha/decisions",
        {"model": configured_model(), "state": state, "questions": questions},
    )
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        return None
    return data


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    client = _Client()
    try:
        payload = await client.post(path, json=body)
    except httpx.HTTPStatusError as exc:
        logger.warning(f"OpenRouter {path} failed: HTTP {exc.response.status_code}")
        return None
    except httpx.RequestError as exc:
        logger.warning(f"OpenRouter {path} failed: {type(exc).__name__}")
        return None
    finally:
        await client.close()
    return payload if isinstance(payload, dict) else None


def _parse_chat_json(data: dict[str, Any]) -> dict[str, Any] | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
