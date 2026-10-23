from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator

from app.models.profile import TasteProfile
from app.services import openrouter
from app.services.tmdb.genre import movie_genres, series_genres

RowKind = Literal["top", "because", "theme"]

_on: ContextVar[bool] = ContextVar("watchly_model_ranking", default=False)

DECISION_CAP = 12
CHAT_CAP = 20

_SCORE_CRITERIA = [
    "A poor fit for this viewer's taste on this row",
    "A weak fit",
    "A reasonable fit",
    "A strong fit",
    "An excellent fit they would want on this row",
]

_NAME_SYSTEM = (
    "You name one Stremio recommendation row. Reply with JSON only, "
    'of the form {"title": "..."} . Two to six words, no quotes inside the title, no explanation.'
)
_RANK_SYSTEM = (
    "You order recommendation candidates for one row. Reply with JSON only, "
    'of the form {"ordered_ids": ["id", ...]}. Use only ids from the list, best fit first.'
)

_NAME_SCHEMA = {
    "name": "row_title",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    },
}
_RANK_SCHEMA = {
    "name": "row_order",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ordered_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["ordered_ids"],
    },
}


@contextmanager
def model_ranking() -> Iterator[None]:
    reset = _on.set(True)
    try:
        yield
    finally:
        _on.reset(reset)


def ranking_active() -> bool:
    return _on.get() and openrouter.openrouter_configured()


class _TitleOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str


class _RankOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ordered_ids: list[str]

    @field_validator("ordered_ids", mode="before")
    @classmethod
    def _as_strings(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("ordered_ids")
        return [str(item).strip() for item in value if str(item).strip()]


def taste_line(profile: TasteProfile | None, content_type: str) -> str:
    if profile is None:
        return ""
    genres = movie_genres if content_type == "movie" else series_genres
    names = [genres.get(genre_id, "") for genre_id, _score in profile.get_top_genres(3)]
    names = [name for name in names if name]
    if not names:
        return ""
    return "Favours " + ", ".join(names)


def clean_title(raw: str | None, fallback: str, *, must_contain: str | None = None) -> str:
    title = " ".join((raw or "").split())
    if not title or len(title) > 80:
        return fallback
    if must_contain and must_contain.casefold() not in title.casefold():
        return fallback
    return title


def is_default_top_name(name: str | None) -> bool:
    return (name or "").strip().casefold() == "top picks for you"


def row_kind(catalog_id: str) -> RowKind | None:
    if catalog_id == "watchly.rec":
        return "top"
    if catalog_id.startswith(("watchly.item.", "watchly.loved.", "watchly.watched.")):
        return "because"
    if catalog_id.startswith("watchly.theme."):
        return "theme"
    return None


def apply_id_order(items: list[dict[str, Any]], ordered_ids: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Model order first. Ids that were not in `items` are dropped, not added.

    Candidates the model omitted keep their scored order after the ones it named,
    so a short answer still fills the row.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        cid = str(item.get("id") or "").strip()
        if cid and cid not in by_id:
            by_id[cid] = item
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    dropped = 0
    for raw in ordered_ids:
        cid = raw.strip()
        if cid in by_id and cid not in seen:
            picked.append(by_id[cid])
            seen.add(cid)
        else:
            dropped += 1
    if not picked:
        return items, dropped
    rest = [item for item in items if str(item.get("id") or "").strip() not in seen]
    return picked + rest, dropped


def order_from_scores(indexed: list[tuple[str, str]], answers: dict[str, Any]) -> list[str]:
    """`indexed` is (question key, candidate id) in the scored order, which breaks ties."""
    scored: list[tuple[float, int, str]] = []
    for index, (key, cid) in enumerate(indexed):
        answer = answers.get(key)
        if not isinstance(answer, dict) or answer.get("type") != "score":
            continue
        score = answer.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        scored.append((float(score), index, cid))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [cid for _score, _index, cid in scored]


def title_from_choice(answers: dict[str, Any], options: dict[str, str], fallback: str) -> str:
    answer = answers.get("title")
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return fallback
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice == "none" or choice not in options:
        return fallback
    return options[choice]


def title_options(kind: RowKind, fallback: str, seed_title: str | None, taste: str) -> dict[str, str]:
    options = {"standard": fallback}
    genre = ""
    if taste.lower().startswith("favours "):
        genre = taste.split(",", 1)[0].removeprefix("Favours ").strip()
    if kind == "top" and genre:
        options["genre"] = f"{genre} for You"
        options["more"] = f"More {genre}"
    elif kind == "because" and seed_title:
        options["more"] = f"More like {seed_title}"
    elif kind == "theme":
        words = fallback.split()
        if len(words) >= 3:
            short = " ".join(words[:3])
            if short.casefold() != fallback.casefold():
                options["short"] = short
    return options


def _candidate_brief(item: dict[str, Any]) -> dict[str, str]:
    genres = item.get("genres") or []
    genre_text = ", ".join(genre for genre in genres if isinstance(genre, str)) if isinstance(genres, list) else ""
    overview = " ".join(str(item.get("description") or "").split())[:240]
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("name") or ""),
        "year": str(item.get("releaseInfo") or ""),
        "genres": genre_text[:80],
        "overview": overview,
    }


def _window(items: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    picked = []
    for item in items:
        if str(item.get("id") or "").strip():
            picked.append(item)
        if len(picked) >= cap:
            break
    return picked


async def name_row(
    kind: RowKind,
    fallback: str,
    *,
    seed_title: str | None = None,
    taste: str = "",
) -> str:
    if not ranking_active():
        return fallback
    try:
        api = await openrouter.model_kind()
        if api == "decisions":
            raw, resolved = await _name_with_decisions(kind, fallback, seed_title, taste)
        else:
            raw, resolved = await _name_with_chat(kind, fallback, seed_title, taste)
        title = clean_title(raw, fallback, must_contain=seed_title)
    except Exception as exc:
        logger.warning(f"OpenRouter title fell back for {kind}: {type(exc).__name__}")
        return fallback
    if title != fallback:
        logger.info(f"OpenRouter named {kind} via {api} model={resolved}")
    return title


async def rerank_catalog(
    items: list[dict[str, Any]],
    catalog_id: str,
    profile: TasteProfile | None,
    content_type: str,
) -> list[dict[str, Any]]:
    kind = row_kind(catalog_id)
    if not items or kind is None or not ranking_active():
        return items
    try:
        api = await openrouter.model_kind()
        window = _window(items, DECISION_CAP if api == "decisions" else CHAT_CAP)
        if len(window) < 2:
            return items
        taste = taste_line(profile, content_type)
        if api == "decisions":
            ordered, resolved = await _rank_with_decisions(kind, taste, window)
        else:
            ordered, resolved = await _rank_with_chat(kind, taste, window)
    except Exception as exc:
        logger.warning(f"OpenRouter ranking fell back to scoring for {catalog_id}: {type(exc).__name__}")
        return items
    if not ordered:
        logger.warning(f"OpenRouter ranking fell back to scoring for {catalog_id}")
        return items
    merged, dropped = apply_id_order(items, ordered)
    if merged is items:
        logger.warning(f"OpenRouter ranking fell back to scoring for {catalog_id}")
        return items
    logger.info(f"OpenRouter ranked {catalog_id} via {api} model={resolved} dropped={dropped}")
    return merged


async def _name_with_chat(kind: RowKind, fallback: str, seed_title: str | None, taste: str) -> tuple[str | None, str]:
    lines = [f"Row kind: {kind}.", f"Fallback title: {fallback}."]
    if taste:
        lines.append(f"Viewer: {taste}.")
    if seed_title:
        lines.append(f"The title must contain this exact text: {seed_title}.")
    lines.append("Do not invent a movie or series that was not given to you.")
    data = await openrouter.chat_json(_NAME_SYSTEM, "\n".join(lines), _NAME_SCHEMA)
    if not data:
        return None, openrouter.configured_model()
    try:
        return _TitleOut.model_validate(data).title, openrouter.configured_model()
    except ValueError:
        return None, openrouter.configured_model()


async def _name_with_decisions(
    kind: RowKind, fallback: str, seed_title: str | None, taste: str
) -> tuple[str | None, str]:
    options = title_options(kind, fallback, seed_title, taste)
    state: dict[str, Any] = {"row": kind, "viewer": taste or "No taste summary", "titles": options}
    if seed_title:
        state["seed_title"] = seed_title
    criteria = {key: f"The title in `titles.{key}`." for key in options}
    criteria["none"] = "None of these titles fit the row."
    data = await openrouter.decide(
        state,
        {
            "title": {
                "type": "choice",
                "instructions": "Which title should this row use?",
                "criteria": criteria,
            }
        },
    )
    if not data:
        return None, openrouter.configured_model()
    return title_from_choice(data["answers"], options, fallback), str(
        data.get("model") or openrouter.configured_model()
    )


async def _rank_with_chat(kind: RowKind, taste: str, window: list[dict[str, Any]]) -> tuple[list[str], str]:
    lines = [f"Row kind: {kind}."]
    if taste:
        lines.append(f"Viewer: {taste}.")
    lines.append("Candidates:")
    for item in window:
        brief = _candidate_brief(item)
        lines.append(
            f"- id: {brief['id']} | {brief['title']} | {brief['year']} | {brief['genres']} | {brief['overview']}"
        )
    data = await openrouter.chat_json(_RANK_SYSTEM, "\n".join(lines), _RANK_SCHEMA)
    if not data:
        return [], openrouter.configured_model()
    try:
        return _RankOut.model_validate(data).ordered_ids, openrouter.configured_model()
    except ValueError:
        return [], openrouter.configured_model()


async def _rank_with_decisions(kind: RowKind, taste: str, window: list[dict[str, Any]]) -> tuple[list[str], str]:
    indexed: list[tuple[str, str]] = []
    candidates: dict[str, dict[str, str]] = {}
    for index, item in enumerate(window):
        key = f"c{index}"
        brief = _candidate_brief(item)
        indexed.append((key, brief["id"]))
        candidates[key] = brief
    questions = {
        key: {
            "type": "score",
            "instructions": f"How well does `candidates.{key}` fit this viewer on this row?",
            "criteria": _SCORE_CRITERIA,
        }
        for key, _cid in indexed
    }
    data = await openrouter.decide(
        {"row": kind, "viewer": taste or "No taste summary", "candidates": candidates},
        questions,
    )
    if not data:
        return [], openrouter.configured_model()
    return order_from_scores(indexed, data["answers"]), str(data.get("model") or openrouter.configured_model())
