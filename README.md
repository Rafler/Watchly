# Watchly

Fork of [TimilsinaBimal/Watchly](https://github.com/TimilsinaBimal/Watchly) (MIT). The upstream license and copyright in [LICENSE](LICENSE) are unchanged.

<div align="center">

<!-- Premium Badge Collection -->
[![Version](https://img.shields.io/github/v/release/timilsinabimal/watchly?style=for-the-badge&logo=semver&color=6366f1)](https://github.com/timilsinabimal/watchly/releases)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/timilsinabimal/watchly?style=for-the-badge&color=f59e0b&logo=github)](https://github.com/timilsinabimal/watchly/stargazers)

</div>
<br/>

**Watchly** is a Stremio catalog addon that fills your Stremio home with personalized movie and series recommendations built from your own watch history. It reads what you've watched, rated, and loved — from **Stremio, Trakt, Simkl, MDBList, or Nuvio** — builds a numerical taste profile from it, and serves a set of recommendation rows ("Top Picks for You", "Because you watched …", genre and keyword catalogs, and more) using metadata from [TMDB](https://www.themoviedb.org/).

Everything is configured through a web page; you paste the resulting manifest URL into Stremio once. A daily resync rebuilds the rows. When `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are set, that resync asks the model to order and name Top Picks, "Because you watched", and theme rows. Catalog requests serve the cache and do not call the model.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Catalogs](#catalogs)
- [Watch history sources](#watch-history-sources)
- [Personalization](#personalization)
- [Screenshots](#screenshots)
- [Installation (Docker)](#installation-docker)
- [Unraid](#unraid)
- [Choose a Redis](#choose-a-redis)
- [Deploy on Vercel](#deploy-on-vercel)
- [Configuration reference](#configuration-reference)
- [OpenRouter](#openrouter)
- [Daily resync](#daily-resync)
- [Optional integrations](#optional-integrations)
- [Development](#development)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Funding & support](#funding--support)
- [Acknowledgements](#acknowledgements)

## Features

- **Personalized recommendations** — a taste profile (top genres, keywords, directors, cast, eras, countries, runtime) is built from your history and drives every catalog row.
- **Five history sources** — use your **Stremio** library, or your **Trakt**, **Simkl**, **MDBList** or **Nuvio** account. Ratings, watches, loves, and rewatches are all understood.
- **Multiple catalog types** — Top Picks, "Because you watched/loved", dynamic genre & keyword rows, recommendations from your recurring directors and actors, and "based on everything you loved/liked".
- **Fine-grained personalization** — discovery style (mainstream → hidden gems), release-year window, excluded genres (separately for movies and series), display language, and per-catalog enable/rename/shuffle controls.
- **Poster ratings overlay** — optionally overlay IMDb/TMDb-style ratings on posters via [RatingPosterDB](https://ratingposterdb.com/), Top Posters, or a custom template.
- **Bring your own keys** — supply your own TMDB or Simkl API key, or rely on the server's.
- **Secure by design** — credentials are encrypted at rest in Redis and never appear in the manifest URL, which carries only a short opaque token.
- **Daily resync** — a long-running process rebuilds catalogs on a schedule. On Vercel, a cron calls a protected endpoint. Either way the home page reads the cache.
- **Fast** — aggressive Redis caching of profiles, libraries, and rendered catalogs keeps responses quick.

## How it works

1. You open the `/configure` page and connect a history source (Stremio login, Trakt/Simkl via OAuth, or an MDBList API key). Your credentials are encrypted and stored in Redis under a short opaque **token**. That token is embedded in your personal manifest URL.
2. Watchly fetches your watch history from the configured source and converts it into a source-agnostic library — ratings ≥ 9 count as *loved*, 7–8.9 as *liked*, the rest as *watched*.
3. From that library it builds a **taste profile**: a numerical fingerprint of your preferences across genres, keywords, people, eras, countries, and runtime.
4. The daily resync runs the recommendation engines: candidates come from TMDB (and Simkl where available), are scored against your profile, capped for diversity, and enriched with metadata. If OpenRouter is configured, the model then reorders Top Picks, "Because you watched", and theme rows and may rename them. Anything else — a timeout, invalid JSON, an id the model invented — keeps the scored order and the existing title. The result is cached.
5. When Stremio requests a catalog, Watchly returns that cache. A cold cache (nothing stored yet) is built with the scored order on that request and does not call the model.

Each user's state is keyed entirely on their token. You can switch history sources at any time; the library and profile are rebuilt from the new source.

## Catalogs

You choose which of these to enable on the configure page. Each can be toggled per content type (movies / series), renamed, hidden from the home page, or shuffled.

| Catalog | ID | What it shows |
| --- | --- | --- |
| **Top Picks for You** | `watchly.rec` | Your strongest personalized recommendations, combining profile-driven TMDB discovery with picks seeded from your library. |
| **Because you watched / loved** | `watchly.item` | Titles similar to one recent item. The seed is chosen at random from your 3 most-recent loved + 3 most-recent watched items; the row title becomes "Because you loved *X*" or "Because you watched *X*" accordingly. |
| **Genre & Keyword Catalogs** | `watchly.theme` | Dynamic, Netflix-style rows built from your favorite genres, keywords, and countries (e.g. "American Horror", "Based on a Novel"). Up to ~4 rows each for movies and series, varying with your history. |
| **From your favourite Creators** | `watchly.creators` | Recommendations from directors and lead actors who recur across multiple items in your library — not one-offs. |
| **Based on what you loved** | `watchly.all.loved` | Recommendations drawn from your entire set of loved items. |
| **Based on what you liked** | `watchly.liked.all` | Recommendations drawn from your entire set of liked items. |

## Watch history sources

Watchly works for users who keep their library in different places. Pick one source per install:

- **Stremio** — uses your Stremio library directly (requires a Stremio email/password or auth key).
- **Trakt** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.
- **Simkl** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.
- **MDBList** — paste your API key from [mdblist.com/preferences](https://mdblist.com/preferences/) on the configure page; Watchly reads your watched history and ratings. Needs no server-side setup.
- **Nuvio** — sign in to Nuvio on the configure page (the password goes from your browser to Nuvio, not to Watchly); Watchly reads the watched list of the profile you choose, one Watchly instance per profile if you want. Needs no server-side setup.

A single install uses exactly one source at a time. Switching sources rebuilds your library and profile from the new account.

## Personalization

All of these are set on the configure page and stored with your token:

- **Discovery style** — `mainstream`, `balanced`, `gems` (highly rated, less popular), or `all`. Controls the quality/popularity band candidates must fall in.
- **Release-year range** — restrict recommendations to a year window (default 1970–present).
- **Excluded genres** — hide genres you don't want, configured separately for movies and series.
- **Display language** — catalog titles and metadata are translated to your chosen language.
- **Sorting order** — show movies first, series first, or the default interleaving.
- **Poster ratings** — overlay ratings on posters via RPDB, Top Posters, or a custom URL template.
- **Per-catalog controls** — enable/disable, movie-only or series-only, hide from home, shuffle, and rename most catalogs.

## Screenshots

<img src="./app/static/screenshots/homepage.png" alt="Top Picks" width="800"/>

Find more screenshots [here](./app/static/screenshots/).

## Installation (Docker)

Docker is the recommended way to self-host. Watchly requires a **Redis** instance; a server **TMDB API key** is optional but recommended.

1. **Create a `docker-compose.yml`:**

   ```yaml
   services:
     redis:
       image: redis:7-alpine
       container_name: watchly-redis
       restart: unless-stopped
       volumes:
         - redis_data:/data

     watchly:
       image: ghcr.io/timilsinabimal/watchly:latest
       container_name: watchly
       restart: unless-stopped
       ports:
         - "8000:8000"
       env_file:
         - .env
       depends_on:
         - redis

   volumes:
     redis_data:
   ```

2. **Create a `.env` file** (see the [configuration reference](#configuration-reference) for all options):

   ```env
   # Required
   TOKEN_SALT=generate_a_long_random_secret
   HOST_NAME=https://your-public-addon-url

   # Optional, recommended
   TMDB_API_KEY=your_tmdb_api_key_here

   # Redis (matches the compose service name)
   REDIS_URL=redis://redis:6379/0

   # Optional — rank and name rows on the daily resync (see "OpenRouter")
   # OPENROUTER_API_KEY=
   # OPENROUTER_MODEL=typesafe/jev-1.14

   # Optional — enable Trakt / Simkl (see "Optional integrations")
   # TRAKT_CLIENT_ID=
   # TRAKT_CLIENT_SECRET=   # only for legacy (non-PKCE) Trakt apps
   # SIMKL_CLIENT_ID=
   # SIMKL_CLIENT_SECRET=
   ```

   `HOST_NAME` must be the public URL where the addon is reachable. It is used to build OAuth callback URLs and the manifest URL, so it has to match what Stremio (and Trakt/Simkl) will see.

3. **Start it:**

   ```bash
   docker-compose up -d
   ```

4. **Configure and install:**
   Open `http://localhost:8000/configure` (or your `HOST_NAME`), connect a history source, pick your catalogs, and paste the generated manifest URL into Stremio.

### Unraid

A Community Applications-style template lives at [`unraid/watchly.xml`](unraid/watchly.xml).

1. Install **Redis** from Community Applications (any Redis container works).
2. On the **Docker** tab, click **Add Container**, switch to advanced view, and set the template URL to
   `https://raw.githubusercontent.com/TimilsinaBimal/Watchly/main/unraid/watchly.xml` — or add
   `https://github.com/TimilsinaBimal/Watchly` under *Template Repositories* and pick **Watchly** from the template list.
3. Fill in the required fields: TMDB API key, a long random token salt, the Redis URL from step 1
   (e.g. `redis://YOUR-UNRAID-IP:6379/0`), and the host name your Stremio clients will reach the addon on.
4. Start the container and open the WebUI to configure your catalogs.

## Choose a Redis

Watchly keeps every account, cache and rendered row in Redis, so it needs one it can reach on every request.

- **Docker: run Redis next to Watchly.** The `redis:7-alpine` service in the compose file above costs nothing, has no command or connection limits, and never gets deleted for being idle.
- **Vercel: use [Upstash](https://upstash.com/pricing/redis).** Its free plan fits a small instance, TLS is always on, and a free database that sits idle is archived and can be restored rather than deleted.

Roughly how much a user costs: serving a cached row takes about 3 commands (alias lookup, warm-up check, catalog read), so a home screen of ~10 rows plus the manifest is ~35. Each row is rebuilt once a day, about 10 more commands per row. A user who opens Stremio a few times a day comes to about 150–250 commands, or 5–8K a month.

| | Upstash free | Redis Cloud free (Deploy button) | Docker Redis |
| --- | --- | --- | --- |
| Commands | 500K / month (~60–100 users) | 100 ops/sec | no limit |
| Data | 256 MB | 30 MB | your disk |
| Connections | not published | 30 | no limit |
| TLS | always on (`rediss://`) | not available on free | local network |
| Idle database | archived after 30 days, restorable | deleted after 14 days without commands | never |
| Next step up | pay as you go, $0.20 per 100K commands | paid plans from $5 / month | — |

Sources: [Upstash pricing](https://upstash.com/docs/redis/overall/pricing), [Upstash FAQ](https://upstash.com/docs/redis/help/faq), [Redis Cloud Essentials limits](https://redis.io/docs/latest/operate/rc/subscriptions/view-essentials-subscription/essentials-plan-details/), [Redis Cloud TLS](https://redis.io/docs/latest/operate/rc/security/database-security/tls-ssl/), [Redis pricing](https://redis.io/pricing/). Checked September 2026; confirm current limits before you pick.

Redis Cloud's free plan is the weaker fit on Vercel: each function instance opens up to `REDIS_MAX_CONNECTIONS` (20) connections, so two instances can exhaust its 30, and a home screen requests every row at once, which a few users together can push past 100 ops/sec. It is fine for trying Watchly out; switch to Upstash before you share the instance.

### Set up Upstash

1. In the [Upstash console](https://console.upstash.com), create a Redis database. Pick the region nearest your Vercel functions; new Vercel projects run in `iad1` (Washington, D.C.), so AWS `us-east-1` is the usual choice.
2. Open the database's **Connect** section and copy the `rediss://default:<password>@<host>:<port>` URL from the redis-cli snippet. Don't use the REST URL and token (`UPSTASH_REDIS_REST_*`, `KV_REST_API_*`): they are for Upstash's HTTP API, which Watchly's Redis client can't speak.
3. In Vercel, open **Settings → Environment Variables** and set `REDIS_URL` to that URL.
4. Redeploy from the **Deployments** tab.

The `rediss://` scheme turns on TLS, and redis-py handles it with no extra settings.

### Redis Cloud (Deploy button)

The Deploy button's **Redis** store creates a free Redis Cloud database and adds `REDIS_URL` to the project for you. On the free plan, set `REDIS_MAX_CONNECTIONS=10` so two instances stay under its 30-connection limit, and remember that the database is deleted after 14 days with no commands.

## Deploy on Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FTimilsinaBimal%2FWatchly&project-name=watchly&repository-name=watchly&env=TOKEN_SALT,HOST_NAME&envDescription=A%20long%20random%20TOKEN_SALT%20and%20HOST_NAME%20set%20to%20https%3A%2F%2F%3Cproject-name%3E.vercel.app.%20TMDB_API_KEY%20is%20optional%20but%20recommended%3B%20add%20it%20later%20under%20Settings%20%3E%20Environment%20Variables.&envLink=https%3A%2F%2Fgithub.com%2FTimilsinaBimal%2FWatchly%23deploy-on-vercel&stores=%5B%7B%22type%22%3A%22integration%22%2C%22integrationSlug%22%3A%22redis%22%2C%22productSlug%22%3A%22redis%22%7D%5D)

Vercel detects the FastAPI app with no extra config and runs it on Python 3.12, the version `pyproject.toml` and `.python-version` pin. A running instance also serves this guide at `/self-host`.

1. Click the button and pick a project name.
2. Accept the **Redis** store to try Watchly on a free Redis Cloud database; it adds `REDIS_URL` to the project. For an instance you'll keep, skip it and [set up Upstash](#set-up-upstash) instead (see [Choose a Redis](#choose-a-redis)).
3. Fill in `TOKEN_SALT` (for example `openssl rand -hex 32`) and `HOST_NAME` (`https://<project-name>.vercel.app`), then deploy. `TMDB_API_KEY` is optional but recommended: add it under **Settings → Environment Variables** (see [Configuration reference](#configuration-reference)).
4. If the production domain Vercel assigned differs from your `HOST_NAME`, fix it under **Settings → Environment Variables**.
5. Redeploy from the **Deployments** tab; environment variable changes only apply to new deployments.
6. Open `https://<your-domain>/configure` and set up your catalogs.

Leave `APP_ENV` unset: the `production` default refuses to start with the placeholder `TOKEN_SALT`.

**Limits.** Vercel does not keep a process alive between requests, so the in-process resync loop does not start there (`VERCEL` is set, or `APP_ENV=vercel`). [`vercel.json`](vercel.json) schedules `GET /cron/resync` every day at 06:00 UTC. Set `CRON_SECRET`; Vercel sends it as `Authorization: Bearer <CRON_SECRET>`. Without that variable the endpoint returns 503.

- The setup warm-up may not finish. The configure page falls back to "Setup is taking a while", and the first home screen builds its rows as Stremio requests them, with the scored order and no model call.
- A catalog request never rebuilds a cached row and never calls OpenRouter. Until the cron has run once, a cold row is the scored list.
- The cron runs inside a function with the platform's request limit (5 minutes by default). One personal library fits. A resync that is killed leaves the Redis lock until it expires (2 hours) and finishes on the next run.
- Docker runs the same rebuild in-process and does not depend on that limit.

## Configuration reference

All settings are environment variables. Only `TOKEN_SALT` and `HOST_NAME` are strictly required, plus a reachable Redis.

### Required

| Variable | Description |
| --- | --- |
| `TMDB_API_KEY` | Optional, recommended. Each user enters their own TMDB key on the configure page; this server key is the fallback. Without it the configure page offers English only, and accounts saved before the page asked for a key have none to use. |
| `TOKEN_SALT` | Secret used to derive the encryption key for stored credentials. **Set a long random value** — the default `change-me` is insecure. |
| `HOST_NAME` | Public base URL of the addon (used for manifest and OAuth callback URLs). |

### Redis

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL. Redis is required. |
| `REDIS_MAX_CONNECTIONS` | `20` | Max Redis connections per process. |
| `REDIS_CONNECTIONS_THRESHOLD` | `100` | Background Redis-heavy jobs back off above this many total clients. |
| `REDIS_TOKEN_KEY` | `watchly:token:` | Key prefix for stored user tokens. |

### Optional integrations

| Variable | Default | Description |
| --- | --- | --- |
| `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET` | — | Trakt OAuth app credentials; enable Trakt as a history source. The secret is only needed for legacy apps — PKCE apps (the Trakt default now) have none. |
| `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET` | — | Simkl OAuth app credentials; enable Simkl as a history source. |

### Tuning & behavior

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port. |
| `ADDON_ID` | `com.bimal.watchly` | Stremio addon ID in the manifest. |
| `ADDON_NAME` | `Watchly` | Display name in the manifest. |
| `APP_ENV` | `production` | `development`, `production`, or `vercel`. |
| `TOKEN_TTL_SECONDS` | `0` | Token expiry in seconds; `0` = never expire. |
| `AUTO_UPDATE_CATALOGS` | `true` | Run the in-process daily resync on a long-running server. Has no effect on Vercel. |
| `CATALOG_REFRESH_INTERVAL_SECONDS` | `86400` | How often that loop rebuilds every account (24 h). |
| `CATALOG_CACHE_TTL` | `60` | `Cache-Control` max-age, in seconds, that Stremio may reuse a catalog response for. |
| `CATALOG_STALE_TTL` | `604800` | Soft-expiration fallback for cached catalogs (7 d). |
| `RECOMMENDATION_SOURCE_ITEMS_LIMIT` | `10` | Number of library items used to seed recommendations. |
| `LIBRARY_ITEMS_LIMIT` | `20` | Library item cap used in parts of the pipeline. |
| `ANNOUNCEMENT_HTML` | `""` | Optional HTML banner shown on the configure page. |
| `ALLOW_SIGNUPS` | `true` | Set to `false` to lock the instance to existing accounts; new signups are rejected. |

### OpenRouter and cron

| Variable | Default | Description |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Server key for [OpenRouter](https://openrouter.ai/). Never put it in the configure page or a URL. |
| `OPENROUTER_MODEL` | — | Model id, for example `typesafe/jev-1.14` or `openai/gpt-4o-mini`. Both this and the key must be set or rows stay on the built-in scores. |
| `CRON_SECRET` | — | Bearer secret for `GET` and `POST /cron/resync`. Unset, the endpoint returns 503. |

## OpenRouter

One key and one model id, both read from the environment. The configure page does not collect a model key.

The resync still builds candidates with Watchly's engines. The model only reorders and names three families: Top Picks (`watchly.rec`), "Because you watched / loved" (`watchly.item`), and theme rows (`watchly.theme`). Creators, loved, liked, and rewatch rows stay on the scored order. A returned id that was not in the candidate list is dropped. If the call times out, errors, or comes back as something other than the expected JSON, that row keeps the scored order and its existing title, and that result is what gets cached.

**Picking a model.** Any id from the [models list](https://openrouter.ai/models) works. Decision models such as `typesafe/jev-1.14` are not on the default list: `GET /api/v1/models` omits them. They show up for `output_modalities=decisions` and for `output_modalities=all`. `typesafe/jev-router` is a text model, not a decision model. Pin a versioned id (`typesafe/jev-1.14`). An alias such as `~typesafe/jev-latest` can move to another build.

Watchly reads `output_modalities` with `output_modalities=all` and sends a decision-only model to `POST /api/alpha/decisions`. Those models do not write titles. The row name is a choice among titles the server already built (the current name, a shorter theme name, "More like {seed}", or none). A chat model uses `POST /api/v1/chat/completions` with a JSON schema. If the models list cannot be loaded, the id is sent to chat completions; a decision model fails that call and the row falls back to scores.

**Cost.** A resync makes about two calls per enabled Top Picks, Because-you-watched, and theme row, per movies and series, per account: one to name the row and one to order it. Opening Stremio does not call the model. Decision calls report `usage.cost` in USD on the Decisions API; chat models bill as normal completions. The price is whatever `OPENROUTER_MODEL` costs that day — check the model page. Leave both variables unset and nothing is billed.

## Daily resync

Catalog rows are rebuilt on a schedule, then served from Redis until the next rebuild.

- **Docker or any long-running process.** On startup, if `AUTO_UPDATE_CATALOGS` is true and the process is not on Vercel, a loop rebuilds every account. It waits 30 seconds after boot, then repeats every `CATALOG_REFRESH_INTERVAL_SECONDS` (default 24 hours). A Redis lock (`watchly:resync:lock`, 2 hours) keeps two loops from overlapping.
- **Vercel Cron or system cron.** `GET` or `POST /cron/resync` with `Authorization: Bearer <CRON_SECRET>` runs the same rebuild. [`vercel.json`](vercel.json) schedules it daily at 06:00 UTC. Vercel sends the `CRON_SECRET` env var as that bearer token. A system cron is the same request:

  ```bash
  curl -fsS -H "Authorization: Bearer $CRON_SECRET" https://your-public-addon-url/cron/resync
  ```

- **One-shot.** From a checkout with the same environment and a reachable Redis:

  ```bash
  uv run python -m app.services.resync
  ```

  It prints `{"status": "ok", "refreshed": N, "failed": M}` or `{"status": "busy", ...}` when a resync is already running.

Accounts are listed from a Redis set written when an account is saved. The first resync on an install from before that set scans stored tokens once and fills the set. Catalog requests do not scan.

## Optional integrations

These are only needed if you want the corresponding feature; Watchly runs fine with just TMDB + Redis.

- **Trakt** — create an API app at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications). Set the redirect URI to `HOST_NAME/auth/trakt/callback` and put the client ID in `TRAKT_CLIENT_ID`. New Trakt apps use PKCE and are not issued a secret; set `TRAKT_CLIENT_SECRET` only if your app has one.
- **Simkl** — create an app at [simkl.com/settings/developer](https://simkl.com/settings/developer). Set the redirect URI to `HOST_NAME/auth/simkl/callback` and put the credentials in `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET`.
- **Poster ratings (RPDB)** — users enter their own [RatingPosterDB](https://ratingposterdb.com/) key on the configure page; no server config required. Row naming is the server OpenRouter model, described above.

## Development

Dependencies are managed with [uv](https://github.com/astral-sh/uv); a `requirements.txt` is kept in sync for non-uv environments. **Python 3.12+** is required, and a running Redis is needed for most functionality.

```bash
# Clone
git clone https://github.com/TimilsinaBimal/Watchly.git
cd Watchly

# Install dependencies
uv sync

# Run the dev server (auto-reload)
uv run main.py --dev
# or
uvicorn app.core.app:app --reload
```

Create a `.env` with at least `TOKEN_SALT`, `HOST_NAME`, and `REDIS_URL` before running. `TMDB_API_KEY` is optional but recommended. Add `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` when you want the daily resync to rank rows. The configure UI is served at `/configure`.

### Tests, linting, formatting

```bash
# Tests (pytest is installed into the venv on demand)
PYTHONPATH=. uv run --with pytest pytest tests/
PYTHONPATH=. uv run --with pytest pytest tests/test_catalog_endpoint.py -v

# Lint / format (also enforced by pre-commit on commit)
pre-commit run --all-files
black .      # line length 120, py312
isort .      # black profile
flake8 .     # config in setup.cfg
```

## Architecture

Watchly is a FastAPI service that speaks the Stremio addon protocol. The request flow for every authenticated endpoint is:

1. **`app/services/context.py:load_user_context`** — decrypts the token, parses settings, resolves auth, and builds the `LibraryCollection` from the configured `watch_history_source`.
2. **`app/services/recommendation/catalog_service.py`** — routes the catalog ID to a recommendation engine (Top Picks, theme, item, creators, all-loved/liked).
3. The engine's results pass through metadata enrichment, poster-ratings overlay, translation, and serialization into a Stremio catalog.

The taste-profile pipeline lives in `app/services/profile/`, all external HTTP goes through `app/core/base_client.py:BaseClient` (retries, timeouts, structured errors), and Redis (`app/services/user_cache.py`, `app/services/redis_service.py`) is the source of truth for user state.

### Project layout

```
app/
  api/            # FastAPI routers: manifest, catalog, tokens, oauth, dashboard, validation, health …
  core/           # app setup, config/settings, base HTTP client, security, constants
  models/         # Pydantic models (library, profile, …)
  services/
    profile/      # taste-profile builder
    recommendation/ # catalog routing + per-type engines, scoring, diversity, filtering
    poster_ratings/ # RPDB / Top Posters / custom overlays
    stremio/      # Stremio library + auth
    tmdb/         # TMDB client, genres, countries
    …             # trakt, simkl, openrouter, ranking, resync, translation, caching, catalog updater
  static/, templates/  # the configure UI and dashboard
```

### Key endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /configure` | Web UI for setup and catalog selection. |
| `GET /{token}/manifest.json` | Per-user Stremio manifest. |
| `GET /{token}/catalog/{type}/{id}.json` | Catalog data for a content type and catalog ID. |
| `POST /tokens/` | Create a token from submitted credentials/settings. |
| `GET /auth/trakt`, `GET /auth/simkl` | OAuth start; `/callback` variants complete the flow. |
| `GET /{token}/dashboard/data` | User dashboard data. |
| `GET /health`, `GET /stats` | Readiness probe and usage stats. |
| `GET` or `POST /cron/resync` | Rebuild every account. Requires `Authorization: Bearer <CRON_SECRET>`. |

## Contributing

Contributions of all sizes are welcome!

- **Small bug fixes & improvements** — open a Pull Request directly.
- **Major features & refactors** — please [open an issue](https://github.com/TimilsinaBimal/Watchly/issues) first to discuss the approach. This keeps your work aligned with the project's direction and saves you time.

## Funding & support

If you find Watchly useful, please consider supporting the project:
- [Buy me Mo:Mo](https://buymemomo.com/timilsinabimal)

## Bug reports

Found a bug or have a feature request? Please [open an issue](https://github.com/TimilsinaBimal/Watchly/issues) on GitHub.

## Contributors

Thank you to everyone who has contributed to the project!

<a href="https://github.com/TimilsinaBimal/watchly/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=TimilsinaBimal/watchly" />
</a>

## Acknowledgements

Special thanks to **[The Movie Database (TMDB)](https://www.themoviedb.org/)** for the rich metadata that powers Watchly's recommendations, and to **Trakt** and **Simkl** for their history APIs.
