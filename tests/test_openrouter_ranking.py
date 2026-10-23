import asyncio

import pytest
from pydantic import ValidationError

from app.core.settings import UserSettings
from app.models.profile import TasteProfile
from app.services.openrouter import _parse_chat_json, kind_for
from app.services.ranking import (
    apply_id_order,
    clean_title,
    model_ranking,
    name_row,
    order_from_scores,
    ranking_active,
    rerank_catalog,
    title_from_choice,
)
from app.services.row_generator import RowGeneratorService


def _items():
    return [
        {"id": "tt1", "type": "movie", "name": "One", "genres": ["Thriller"], "description": "A heist."},
        {"id": "tt2", "type": "movie", "name": "Two", "genres": ["Drama"], "description": "A family."},
        {"id": "tt3", "type": "movie", "name": "Three", "genres": ["Comedy"], "description": "A joke."},
    ]


def test_legacy_gemini_settings_still_load():
    settings = UserSettings.model_validate(
        {
            "catalogs": [],
            "gemini_api_key": "old-gemini-key",
            "llm": {"provider": "gemini", "api_key": "sk-old", "model": "gemini-2.5-flash"},
        }
    )
    assert not hasattr(settings, "gemini_api_key")
    assert not hasattr(settings, "llm")


def test_kind_for_routes_decision_models_and_leaves_text_models_on_chat():
    catalog = {
        "typesafe/jev-1.14": ["decisions"],
        "~typesafe/jev-latest": ["decisions"],
        "typesafe/jev-router": ["text"],
        "openai/gpt-4o-mini": ["text"],
    }
    assert kind_for("typesafe/jev-1.14", catalog) == "decisions"
    assert kind_for("typesafe/jev-latest", catalog) == "decisions"
    assert kind_for("typesafe/jev-router", catalog) == "chat"
    assert kind_for("openai/gpt-4o-mini", catalog) == "chat"
    assert kind_for("typesafe/jev-1.14", None) == "chat"
    assert kind_for("missing/model", catalog) == "chat"


def test_apply_id_order_drops_invented_ids_and_keeps_the_rest():
    merged, dropped = apply_id_order(_items(), ["nope", "tt3", "tt3", "tt1"])
    assert [item["id"] for item in merged] == ["tt3", "tt1", "tt2"]
    assert dropped == 2


def test_apply_id_order_falls_back_when_nothing_matches():
    original = _items()
    merged, dropped = apply_id_order(original, ["made-up"])
    assert merged is original
    assert dropped == 1


def test_order_from_scores_ignores_bad_answers_and_breaks_ties_with_scored_order():
    indexed = [("c0", "tt1"), ("c1", "tt2"), ("c2", "tt3")]
    answers = {
        "c0": {"type": "score", "score": 1.0},
        "c1": {"type": "noul", "noul": 0.9},
        "c2": {"type": "score", "score": True},
        "invented": {"type": "score", "score": 5},
    }
    assert order_from_scores(indexed, answers) == ["tt1"]

    tied = {
        "c0": {"type": "score", "score": 2},
        "c1": {"type": "score", "score": 2},
        "c2": {"type": "score", "score": 3},
    }
    assert order_from_scores(indexed, tied) == ["tt3", "tt1", "tt2"]


def test_title_choice_rejects_none_and_unknown_options():
    options = {"standard": "Because you watched Inception", "more": "More like Inception"}
    assert title_from_choice({"title": {"type": "choice", "choice": "more"}}, options, "fallback") == (
        "More like Inception"
    )
    assert title_from_choice({"title": {"type": "choice", "choice": "none"}}, options, "fallback") == "fallback"
    assert title_from_choice({"title": {"type": "score", "score": 1}}, options, "fallback") == "fallback"


def test_clean_title_requires_the_seed_and_rejects_blank_or_long_text():
    assert clean_title("  More like Inception  ", "Because you watched Inception", must_contain="Inception") == (
        "More like Inception"
    )
    assert clean_title("Great films", "Because you watched Inception", must_contain="Inception") == (
        "Because you watched Inception"
    )
    assert clean_title("   ", "Top Picks for You") == "Top Picks for You"
    assert clean_title("x" * 81, "Top Picks for You") == "Top Picks for You"


def test_parse_chat_json_reads_fenced_content_and_rejects_a_list():
    body = {"choices": [{"message": {"content": '```json\n{"ordered_ids": ["tt1"]}\n```'}}]}
    assert _parse_chat_json(body) == {"ordered_ids": ["tt1"]}
    assert _parse_chat_json({"choices": [{"message": {"content": "[1, 2]"}}]}) is None
    parts = {"choices": [{"message": {"content": [{"text": '{"title": "Heist Nights"}'}]}}]}
    assert _parse_chat_json(parts) == {"title": "Heist Nights"}


def test_rank_schema_rejects_a_missing_list():
    from app.services.ranking import _RankOut

    with pytest.raises(ValidationError):
        _RankOut.model_validate({"title": "nope"})


def _enable(monkeypatch):
    monkeypatch.setattr("app.services.openrouter.settings.OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("app.services.openrouter.settings.OPENROUTER_MODEL", "typesafe/jev-1.14")


def test_rerank_uses_decision_scores_and_drops_unknown_answer_keys(monkeypatch):
    _enable(monkeypatch)

    async def kind():
        return "decisions"

    async def decide(state, questions):
        assert set(questions) == {"c0", "c1", "c2"}
        assert "invented" not in state["candidates"]
        return {
            "model": "typesafe/jev-1.14-20261014",
            "answers": {
                "c0": {"type": "score", "score": 0.2},
                "c1": {"type": "score", "score": 2.4},
                "c2": {"type": "score", "score": 1.1},
                "c9": {"type": "score", "score": 9},
            },
        }

    monkeypatch.setattr("app.services.openrouter.model_kind", kind)
    monkeypatch.setattr("app.services.openrouter.decide", decide)

    async def run():
        with model_ranking():
            assert ranking_active()
            return await rerank_catalog(_items(), "watchly.rec", None, "movie")

    ranked = asyncio.run(run())
    assert [item["id"] for item in ranked] == ["tt2", "tt3", "tt1"]


def test_rerank_chat_drops_invented_ids_and_falls_back_on_invalid_json(monkeypatch):
    _enable(monkeypatch)

    async def kind():
        return "chat"

    async def chat(system, user, schema):
        assert "tt1" in user and "tt9" not in user
        return {"ordered_ids": ["tt9", "tt2", "tt1"]}

    monkeypatch.setattr("app.services.openrouter.model_kind", kind)
    monkeypatch.setattr("app.services.openrouter.chat_json", chat)

    async def run():
        with model_ranking():
            return await rerank_catalog(_items(), "watchly.theme.1", None, "movie")

    ranked = asyncio.run(run())
    assert [item["id"] for item in ranked] == ["tt2", "tt1", "tt3"]

    async def bad(system, user, schema):
        return {"nope": True}

    monkeypatch.setattr("app.services.openrouter.chat_json", bad)

    async def fallback():
        with model_ranking():
            return await rerank_catalog(_items(), "watchly.item.1", None, "movie")

    assert asyncio.run(fallback()) == _items()


def test_rerank_falls_back_when_the_model_errors(monkeypatch):
    _enable(monkeypatch)

    async def kind():
        return "chat"

    async def chat(system, user, schema):
        raise TimeoutError("slow")

    monkeypatch.setattr("app.services.openrouter.model_kind", kind)
    monkeypatch.setattr("app.services.openrouter.chat_json", chat)

    async def run():
        with model_ranking():
            return await rerank_catalog(_items(), "watchly.rec", None, "movie")

    assert asyncio.run(run()) == _items()


def test_request_path_does_not_rank_even_when_openrouter_is_configured(monkeypatch):
    _enable(monkeypatch)

    async def boom(*args, **kwargs):
        raise AssertionError("model called outside a resync")

    monkeypatch.setattr("app.services.openrouter.model_kind", boom)
    assert asyncio.run(rerank_catalog(_items(), "watchly.rec", None, "movie")) == _items()
    assert asyncio.run(name_row("because", "Because you watched Inception", seed_title="Inception")) == (
        "Because you watched Inception"
    )


def test_decision_name_must_contain_the_seed(monkeypatch):
    _enable(monkeypatch)

    async def kind():
        return "decisions"

    async def decide(state, questions):
        return {"model": "typesafe/jev-1.14", "answers": {"title": {"type": "choice", "choice": "more"}}}

    monkeypatch.setattr("app.services.openrouter.model_kind", kind)
    monkeypatch.setattr("app.services.openrouter.decide", decide)

    async def run():
        with model_ranking():
            return await name_row("because", "Because you watched Inception", seed_title="Inception")

    assert asyncio.run(run()) == "More like Inception"


def test_chat_name_falls_back_when_the_seed_is_missing(monkeypatch):
    _enable(monkeypatch)

    async def kind():
        return "chat"

    async def chat(system, user, schema):
        return {"title": "Movies you might like"}

    monkeypatch.setattr("app.services.openrouter.model_kind", kind)
    monkeypatch.setattr("app.services.openrouter.chat_json", chat)

    async def run():
        with model_ranking():
            return await name_row("because", "Because you watched Inception", seed_title="Inception")

    assert asyncio.run(run()) == "Because you watched Inception"


def test_row_generator_does_not_call_the_model_outside_a_resync(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("model called")

    monkeypatch.setattr("app.services.openrouter.decide", boom)
    monkeypatch.setattr("app.services.openrouter.chat_json", boom)
    service = RowGeneratorService.__new__(RowGeneratorService)

    async def no_keywords(self, ids):
        return {}

    monkeypatch.setattr(RowGeneratorService, "_resolve_keyword_names", no_keywords)
    profile = TasteProfile(genre_scores={28: 5.0, 53: 3.0, 18: 2.0})
    rows = asyncio.run(service.generate_rows(profile, "movie"))
    assert rows
    assert all(row.title and row.id.startswith("watchly.theme.") for row in rows)


def test_user_settings_ignore_removed_llm_field_on_construct_from_dict():
    dumped = UserSettings(catalogs=[]).model_dump()
    assert "llm" not in dumped
    assert "gemini_api_key" not in dumped
