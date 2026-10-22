import asyncio

from app.api.endpoints.oauth import _pkce_challenge
from app.services.trakt import trakt_service


def test_pkce_challenge_matches_rfc7636_vector():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert _pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_token_requests_omit_secret_for_pkce_apps(monkeypatch):
    bodies = []

    async def fake_post(url, json=None, **kwargs):
        bodies.append(json)
        return {}

    monkeypatch.setattr(trakt_service.client, "post", fake_post)
    monkeypatch.setattr("app.services.trakt.settings.TRAKT_CLIENT_ID", "cid")

    monkeypatch.setattr("app.services.trakt.settings.TRAKT_CLIENT_SECRET", None)
    asyncio.run(trakt_service.exchange_code("code", "https://x/cb", "verifier"))
    asyncio.run(trakt_service.refresh_token("rt", "https://x/cb"))
    assert bodies[0]["code_verifier"] == "verifier"
    assert all("client_secret" not in b for b in bodies)

    bodies.clear()
    monkeypatch.setattr("app.services.trakt.settings.TRAKT_CLIENT_SECRET", "sec")
    asyncio.run(trakt_service.exchange_code("code", "https://x/cb", "verifier"))
    asyncio.run(trakt_service.refresh_token("rt", "https://x/cb"))
    assert all(b["client_secret"] == "sec" for b in bodies)
