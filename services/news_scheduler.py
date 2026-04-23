"""APScheduler background job — keeps the Qdrant news index fresh.

Runs in a daemon thread inside the FastAPI process (no external service needed).

Schedule
--------
  First run  : 60 seconds after server start   (lets uvicorn fully initialise)
  Subsequent : every 7 days

Usage (from server.py)
----------------------
    from services.news_scheduler import start_scheduler, stop_scheduler

    @app.on_event("startup")
    async def on_startup():
        start_scheduler()

    @app.on_event("shutdown")
    async def on_shutdown():
        stop_scheduler()
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Job
# ══════════════════════════════════════════════════════════════════════════════

def _run_ingest() -> None:
    """Scheduled job body — runs both RAG ingest (Qdrant) and CAG preprocessing (KV cache)."""
    import os
    logger.info("[scheduler] Starting scheduled news ingest (RAG + CAG)…")
    try:
        from services.news_rag import ingest_news_articles
        api_key = os.environ.get("GROQ_API_KEY", "")
        count = ingest_news_articles(force=True, api_key=api_key)
        logger.info(f"[scheduler] News ingest complete — {count} chunks in Qdrant + KV cache updated")
    except Exception as e:
        logger.error(f"[scheduler] News ingest failed: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
# Lifecycle
# ══════════════════════════════════════════════════════════════════════════════

def start_scheduler() -> None:
    """Start the background scheduler (idempotent — safe to call multiple times)."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.debug("[scheduler] Already running — skipping start")
        return

    _scheduler = BackgroundScheduler(timezone="UTC", daemon=True)

    first_run = datetime.now(timezone.utc) + timedelta(seconds=60)

    _scheduler.add_job(
        _run_ingest,
        trigger="interval",
        weeks=1,
        id="news_ingest",
        next_run_time=first_run,
        misfire_grace_time=300,   # allow up to 5 min late if server was busy
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"[scheduler] Started — first news ingest at "
        f"{first_run.strftime('%H:%M:%S UTC')}, then every 7 days"
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler on server exit."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] Stopped")
