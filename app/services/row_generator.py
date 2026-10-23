"""
Dynamic Row Generator Service.

Generates 3 personalized catalog rows from a user's taste profile:
- Row 1 (Core): Strongest preferences
- Row 2 (Blend): Mixed preferences with variety
- Row 3 (Rising Star): Emerging/exploratory interests
"""

import asyncio
import random
from typing import Any

from loguru import logger
from pydantic import BaseModel

from app.models.profile import TasteProfile
from app.services.ranking import name_row, taste_line
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb.service import TMDBService, get_tmdb_service

GOLD_END = 3
SILVER_START = 3
SILVER_END = 10

ROLE_ANCHOR = "a"
ROLE_FLAVOR = "f"
ROLE_FALLBACK = "b"

AXIS_GENRE = "g"
AXIS_KEYWORD = "k"
AXIS_COUNTRY = "ct"
AXIS_RUNTIME = "r"
AXIS_CREATOR = "cr"


class RowDefinition(BaseModel):
    """A dynamic catalog row with an ID (encodes TMDB params) and a display title."""

    title: str
    id: str


# --- ID building (format must match theme_based.py parser) ---


def build_row_id(axes: list[tuple[str, str, Any]]) -> str:
    """Build row ID from axes. Each axis is (role, axis_type, value).

    Example output: watchly.theme.a:g28.f:k1234.b:rshort
    """
    parts = ["watchly.theme"]
    sorted_axes = sorted(axes, key=lambda x: (x[0], x[1], str(x[2])))
    for role, axis_type, value in sorted_axes:
        if isinstance(value, (list, tuple)):
            value = "-".join(str(v) for v in value)
        parts.append(f"{role}:{axis_type}{value}")
    return ".".join(parts)


# --- Display helpers ---


def _genre_name(genre_id: int, content_type: str) -> str:
    genre_map = movie_genres if content_type == "movie" else series_genres
    return genre_map.get(genre_id, "Movies" if content_type == "movie" else "Series")


def _country_adjective(code: str) -> str | None:
    adjs = COUNTRY_ADJECTIVES.get(code, [])
    return random.choice(adjs) if adjs else None


def _keyword_display(name: str) -> str:
    return name.strip().replace("-", " ").replace("_", " ").title()


def _runtime_modifier(bucket: str) -> str | None:
    return {"short": "Short & Sweet", "long": "Epic"}.get(bucket)


def _pick(items: list, start: int, end: int, exclude: set | None = None) -> Any | None:
    """Pick a random item from items[start:end], excluding IDs in `exclude`."""
    pool = items[start:end]
    if exclude:
        pool = [x for x in pool if x[0] not in exclude]
    return random.choice(pool) if pool else None


def _build_core_row(
    genres: list[tuple[int, float]],
    keywords: list[tuple[int, float]],
    runtimes: list[tuple[str, float]],
    keyword_names: dict[int, str],
    content_type: str,
    used_genres: set[int],
    used_keywords: set[int],
) -> tuple[list[tuple[str, str, Any]], str] | None:
    axes: list[tuple[str, str, Any]] = []
    title_parts: list[str] = []

    g = _pick(genres, 0, GOLD_END, used_genres)
    if not g:
        return None
    axes.append((ROLE_ANCHOR, AXIS_GENRE, g[0]))
    title_parts.append(_genre_name(g[0], content_type))
    used_genres.add(g[0])

    for _ in range(random.randint(1, 2)):
        k = _pick(keywords, 0, GOLD_END, used_keywords)
        if k and k[0] in keyword_names:
            axes.append((ROLE_FLAVOR, AXIS_KEYWORD, k[0]))
            title_parts.append(_keyword_display(keyword_names[k[0]]))
            used_keywords.add(k[0])

    if runtimes:
        rt = random.choice(runtimes[:2])
        axes.append((ROLE_FALLBACK, AXIS_RUNTIME, rt[0]))
        mod = _runtime_modifier(rt[0])
        if mod:
            title_parts.insert(0, mod)

    return (axes, " ".join(title_parts))


def _build_blend_row(
    genres: list[tuple[int, float]],
    countries: list[tuple[str, float]],
    content_type: str,
    used_genres: set[int],
) -> tuple[list[tuple[str, str, Any]], str] | None:
    axes: list[tuple[str, str, Any]] = []
    title_parts: list[str] = []

    g = _pick(genres, 0, GOLD_END, used_genres)
    if not g:
        return None
    axes.append((ROLE_ANCHOR, AXIS_GENRE, g[0]))
    title_parts.append(_genre_name(g[0], content_type))
    used_genres.add(g[0])

    use_country = random.choice([True, False])
    if use_country and countries:
        c = _pick(countries, 0, SILVER_END)
        if c:
            axes.append((ROLE_FLAVOR, AXIS_COUNTRY, c[0]))
            adj = _country_adjective(c[0])
            if adj:
                title_parts.insert(0, adj)
    else:
        other = [gx for gx in genres if gx[0] != g[0]]
        sg = _pick(other, 0, SILVER_END) if other else None
        if sg:
            axes.append((ROLE_FLAVOR, AXIS_GENRE, sg[0]))
            title_parts.append(_genre_name(sg[0], content_type))

    return (axes, " ".join(title_parts))


def _build_rising_row(
    genres: list[tuple[int, float]],
    keywords: list[tuple[int, float]],
    countries: list[tuple[str, float]],
    keyword_names: dict[int, str],
    content_type: str,
    used_genres: set[int],
    used_keywords: set[int],
) -> tuple[list[tuple[str, str, Any]], str] | None:
    axes: list[tuple[str, str, Any]] = []
    title_parts: list[str] = []

    k = _pick(keywords, SILVER_START, SILVER_END, used_keywords)
    if not k or k[0] not in keyword_names:
        return None
    axes.append((ROLE_ANCHOR, AXIS_KEYWORD, k[0]))
    title_parts.append(_keyword_display(keyword_names[k[0]]))
    used_keywords.add(k[0])

    g = _pick(genres, SILVER_START, SILVER_END, used_genres)
    if g:
        axes.append((ROLE_FLAVOR, AXIS_GENRE, g[0]))
        title_parts.append(_genre_name(g[0], content_type))

    if countries:
        c = _pick(countries, 0, SILVER_END)
        if c:
            axes.append((ROLE_FALLBACK, AXIS_COUNTRY, c[0]))

    return (axes, " ".join(title_parts))


def build_fallback_rows(
    genres: list[tuple[int, float]],
    keywords: list[tuple[int, float]],
    countries: list[tuple[str, float]],
    runtimes: list[tuple[str, float]],
    keyword_names: dict[int, str],
    content_type: str,
) -> list[tuple[list[tuple[str, str, Any]], str]]:
    """Build up to 3 rows as (axes, fallback_title) tuples."""
    rows: list[tuple[list[tuple[str, str, Any]], str]] = []
    used_genres: set[int] = set()
    used_keywords: set[int] = set()

    r1 = _build_core_row(genres, keywords, runtimes, keyword_names, content_type, used_genres, used_keywords)
    if r1:
        rows.append(r1)

    r2 = _build_blend_row(genres, countries, content_type, used_genres)
    if r2:
        rows.append(r2)

    r3 = _build_rising_row(genres, keywords, countries, keyword_names, content_type, used_genres, used_keywords)
    if r3:
        rows.append(r3)

    return rows[:3]


class RowGeneratorService:
    """Generates dynamic, personalized row definitions from a taste profile."""

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or get_tmdb_service()

    async def generate_rows(self, profile: TasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """Up to 3 rows from the profile. A resync may replace the template title."""
        genres = profile.get_top_genres(limit=5)
        keywords = profile.get_top_keywords(limit=10)
        countries = profile.get_top_countries(limit=2)
        runtimes = sorted(profile.runtime_bucket_scores.items(), key=lambda x: x[1], reverse=True)

        keyword_names = await self._resolve_keyword_names([kid for kid, _ in keywords])
        rows = build_fallback_rows(genres, keywords, countries, runtimes, keyword_names, content_type)
        taste = taste_line(profile, content_type)
        titled = [
            RowDefinition(title=await name_row("theme", fallback, taste=taste), id=build_row_id(axes))
            for axes, fallback in rows
        ]
        logger.info(f"Generated {len(titled)} rows for {content_type}")
        return titled

    # --- Helpers ---

    async def _resolve_keyword_names(self, keyword_ids: list[int]) -> dict[int, str]:
        results = await asyncio.gather(
            *[self._get_keyword_name(kid) for kid in keyword_ids],
            return_exceptions=True,
        )
        return {kid: name for kid, name in zip(keyword_ids, results) if isinstance(name, str) and name}

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service.get_keyword_details(keyword_id)
            return data.get("name")
        except Exception:
            return None
