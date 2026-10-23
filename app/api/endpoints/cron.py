import hmac

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.services.resync import resync_all

router = APIRouter(tags=["Cron"])


def _authorized(request: Request) -> None:
    expected = settings.CRON_SECRET or ""
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not set")
    header = request.headers.get("authorization") or ""
    provided = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid cron secret")


@router.api_route("/cron/resync", methods=["GET", "POST"])
async def cron_resync(request: Request) -> dict:
    """Rebuild every account. Vercel Cron uses GET; a system cron can POST."""
    _authorized(request)
    return await resync_all()
