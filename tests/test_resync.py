import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints.cron import cron_resync
from app.core.config import settings
from app.services.catalog_updater import catalog_updater
from app.services.ranking import ranking_active
from app.services.redis_service import redis_service
from app.services.resync import resync_all, scheduler_enabled
from app.services.token_store import token_store


class _Request:
    def __init__(self, authorization: str | None):
        self.headers = {} if authorization is None else {"authorization": authorization}


def test_scheduler_runs_on_a_long_lived_process_only(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_UPDATE_CATALOGS", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.delenv("VERCEL", raising=False)
    assert scheduler_enabled() is True

    monkeypatch.setenv("VERCEL", "1")
    assert scheduler_enabled() is False

    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "vercel")
    assert scheduler_enabled() is False

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "AUTO_UPDATE_CATALOGS", False)
    assert scheduler_enabled() is False


def test_resync_refreshes_stored_accounts_and_drops_missing_ones(monkeypatch):
    calls = []
    forgotten = []

    async def tokens():
        return ["keep", "gone"]

    async def get_user(token):
        if token == "gone":
            return None
        return {"settings": {"catalogs": []}}

    async def refresh(token, credentials, update_timestamp=True):
        calls.append(token)
        return True

    async def forget(token):
        forgotten.append(token)

    async def lock(*args, **kwargs):
        return True

    async def delete(key):
        return True

    monkeypatch.setattr(token_store, "list_account_tokens", tokens)
    monkeypatch.setattr(token_store, "get_user_data", get_user)
    monkeypatch.setattr(token_store, "forget_account", forget)
    monkeypatch.setattr(catalog_updater, "refresh_catalogs_for_credentials", refresh)
    monkeypatch.setattr(redis_service, "set_nx", lock)
    monkeypatch.setattr(redis_service, "delete", delete)

    summary = asyncio.run(resync_all())
    assert summary == {"status": "ok", "refreshed": 1, "failed": 0}
    assert calls == ["keep"]
    assert forgotten == ["gone"]


def test_resync_reports_busy_when_the_lock_is_held(monkeypatch):
    async def lock(*args, **kwargs):
        return False

    deleted = []

    async def delete(key):
        deleted.append(key)
        return True

    monkeypatch.setattr(redis_service, "set_nx", lock)
    monkeypatch.setattr(redis_service, "delete", delete)

    summary = asyncio.run(resync_all())
    assert summary["status"] == "busy"
    assert deleted == []


def test_refresh_enables_model_ranking(monkeypatch):
    seen = {}

    class Bundle:
        async def close(self):
            pass

    async def stop(bundle, credentials, token):
        seen["on"] = ranking_active()
        raise RuntimeError("stop")

    monkeypatch.setattr("app.services.catalog_updater.StremioBundle", Bundle)
    monkeypatch.setattr("app.services.catalog_updater.auth_service.resolve_auth_key_with_bundle", stop)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "openai/gpt-4o-mini")

    ok = asyncio.run(catalog_updater.refresh_catalogs_for_credentials("tok", {"settings": {"catalogs": []}}))
    assert seen["on"] is True
    assert ok is False
    assert ranking_active() is False


def test_cron_requires_the_bearer_secret(monkeypatch):
    monkeypatch.setattr("app.api.endpoints.cron.settings.CRON_SECRET", None)
    with pytest.raises(HTTPException) as missing:
        asyncio.run(cron_resync(_Request("Bearer secret")))
    assert missing.value.status_code == 503

    monkeypatch.setattr("app.api.endpoints.cron.settings.CRON_SECRET", "secret")
    with pytest.raises(HTTPException) as wrong:
        asyncio.run(cron_resync(_Request("Bearer nope")))
    assert wrong.value.status_code == 401

    async def summary():
        return {"status": "ok", "refreshed": 1, "failed": 0}

    monkeypatch.setattr("app.api.endpoints.cron.resync_all", summary)
    assert asyncio.run(cron_resync(_Request("Bearer secret")))["refreshed"] == 1
