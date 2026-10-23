import asyncio
import time

import pytest

from app.core.settings import UserSettings
from app.services.recommendation import catalog_service as cs_module
from app.services.recommendation.catalog_service import catalog_service

TOKEN = "tok_swr"
FRESH = {"metas": [{"id": "tt-fresh", "type": "movie", "name": "Fresh"}]}
STALE = {"metas": [{"id": "tt-stale", "type": "movie", "name": "Stale"}]}


@pytest.fixture
def harness(monkeypatch):
    state = {"cached": None, "age": 0, "builds": 0}

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data(token):
        return {"settings": UserSettings(catalogs=[], watch_history_source="stremio").model_dump()}

    async def fake_get_catalog(token, content_type, catalog_id):
        if state["cached"] is None:
            return None
        return dict(state["cached"]), int(time.time()) - state["age"]

    async def fake_load_context(token, require_auth=True):
        class Ctx:
            token = TOKEN

            async def close(self):
                pass

        return Ctx()

    async def fake_build(ctx, content_type, catalog_id, headers):
        state["builds"] += 1
        return dict(FRESH), headers

    async def model_must_not_run(*args, **kwargs):
        raise AssertionError("catalog request called OpenRouter")

    monkeypatch.setattr(cs_module.token_store, "resolve_alias", fake_resolve_alias)
    monkeypatch.setattr(cs_module.token_store, "get_user_data", fake_get_user_data)
    monkeypatch.setattr(cs_module.user_cache, "get_catalog", fake_get_catalog)
    monkeypatch.setattr(cs_module, "load_user_context", fake_load_context)
    monkeypatch.setattr(catalog_service, "_build_catalog", fake_build)
    monkeypatch.setattr("app.services.openrouter.chat_json", model_must_not_run)
    monkeypatch.setattr("app.services.openrouter.decide", model_must_not_run)
    monkeypatch.setattr("app.services.openrouter.load_catalog", model_must_not_run)
    return state


def get(content_type="movie", catalog_id="watchly.rec"):
    return asyncio.run(catalog_service.get_catalog(TOKEN, content_type, catalog_id))


def test_fresh_cache_is_served_without_building(harness):
    harness["cached"] = FRESH
    harness["age"] = 60

    data, _headers = get()

    assert data["metas"][0]["id"] == "tt-fresh"
    assert harness["builds"] == 0


def test_stale_cache_is_served_without_a_rebuild(harness):
    """A catalog request never rebuilds. The daily resync does, including the model call."""
    harness["cached"] = STALE
    harness["age"] = 10**6

    data, _headers = get()

    assert data["metas"][0]["id"] == "tt-stale"
    assert harness["builds"] == 0


def test_cold_cache_builds_on_the_request(harness):
    harness["cached"] = None

    data, _headers = get()

    assert data["metas"][0]["id"] == "tt-fresh"
    assert harness["builds"] == 1


def test_client_cache_window_stays_short(harness):
    harness["cached"] = FRESH
    harness["age"] = 60

    _, headers = get()

    assert "max-age=60," in headers["Cache-Control"]
    assert "stale-while-revalidate=3600" in headers["Cache-Control"]
