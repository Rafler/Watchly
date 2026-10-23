import asyncio
import os
import time

from loguru import logger

from app.core.config import settings
from app.core.constants import RESYNC_LOCK_KEY
from app.core.security import redact_token
from app.services.catalog_updater import catalog_updater
from app.services.redis_service import redis_service
from app.services.token_store import token_store

RESYNC_LOCK_TTL_SECONDS = 2 * 60 * 60
_START_DELAY_SECONDS = 30


def scheduler_enabled() -> bool:
    """In-process loop for a long-running server. Vercel has no process to keep it."""
    if not settings.AUTO_UPDATE_CATALOGS:
        return False
    if settings.APP_ENV == "vercel" or os.getenv("VERCEL"):
        return False
    return True


async def resync_all() -> dict[str, int | str]:
    if not await redis_service.set_nx(RESYNC_LOCK_KEY, "1", RESYNC_LOCK_TTL_SECONDS):
        logger.info("Resync already running")
        return {"status": "busy", "refreshed": 0, "failed": 0}

    refreshed = 0
    failed = 0
    try:
        for token in await token_store.list_account_tokens():
            credentials = await token_store.get_user_data(token)
            if not credentials:
                await token_store.forget_account(token)
                continue
            try:
                ok = await catalog_updater.refresh_catalogs_for_credentials(token, credentials)
            except Exception as exc:
                logger.warning(f"[{redact_token(token)}] Resync failed: {type(exc).__name__}")
                failed += 1
                continue
            if ok:
                refreshed += 1
            else:
                failed += 1
        logger.info(f"Resync finished: refreshed={refreshed} failed={failed}")
        return {"status": "ok", "refreshed": refreshed, "failed": failed}
    finally:
        await redis_service.delete(RESYNC_LOCK_KEY)


async def resync_loop() -> None:
    await asyncio.sleep(min(_START_DELAY_SECONDS, settings.CATALOG_REFRESH_INTERVAL_SECONDS))
    while True:
        started = time.monotonic()
        try:
            await resync_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily resync failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(settings.CATALOG_REFRESH_INTERVAL_SECONDS - elapsed, 60))


def main() -> None:
    print(asyncio.run(resync_all()))


if __name__ == "__main__":
    main()
