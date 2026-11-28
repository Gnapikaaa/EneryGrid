"""Background analytics trigger service.

Provides a thin fire-and-forget wrapper around the core analytics processing
service so that telemetry ingestion endpoints can enqueue a bounded analytics
pass without blocking the HTTP response.

Design constraints:
- Uses FastAPI BackgroundTasks (no additional dependencies).
- Obtains a *fresh* database session from the session factory; the request-
  scoped session is already closed by the time the background task runs.
- Catches and logs all exceptions; never re-raises (background task errors
  must not crash the server process).
- Respects ``settings.analytics_auto_trigger``: when False, the trigger is
  a no-op, simplifying test isolation.
- Uses a bounded ``max_readings`` budget (``analytics_background_max_readings``)
  smaller than the interactive trigger to avoid starving other requests.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def trigger_analytics_for_meter(
    meter_id: uuid.UUID | None,
    facility_id: str,
    session_factory: Callable[[], "Session"],
    settings: Settings,
    actor_id: uuid.UUID,
) -> None:
    """Background task: run one bounded analytics pass for a meter or facility.

    Safe to pass to ``BackgroundTasks.add_task``; will never raise.

    Args:
        meter_id: UUID of the meter to scope the pass to, or ``None`` for a
            facility-wide pass (all active meters in the facility).
        facility_id: Facility that owns the meter (used for scoping and logging).
        session_factory: Zero-argument callable that returns a fresh Session.
            Must be the *factory* (e.g. ``build_session_factory(engine)``),
            not an already-open session.
        settings: Application settings (read ``analytics_auto_trigger`` flag and
            ``analytics_background_max_readings`` budget here).
        actor_id: UUID of the authenticated user who triggered the ingest; used
            only for audit logging.
    """
    if not settings.analytics_auto_trigger:
        logger.debug(
            "analytics_auto_trigger disabled; skipping background pass "
            "(meter_id=%s facility_id=%s)",
            meter_id,
            facility_id,
        )
        return

    db: "Session | None" = None
    try:
        from app.schemas.analytics import AnalyticsProcessRequest
        from app.services.analytics import process_analytics_batch

        db = session_factory()
        request = AnalyticsProcessRequest(
            facility_id=facility_id,
            meter_id=meter_id,
            max_readings=settings.analytics_background_max_readings,
            force_insights=False,
        )
        result = process_analytics_batch(db, request=request, settings=settings)
        logger.info(
            "Background analytics pass completed: meter_id=%s facility_id=%s "
            "readings_processed=%s anomalies=%s insights=%s actor_id=%s",
            meter_id,
            facility_id,
            result.processed_readings,
            result.anomalies_created,
            result.insights_created,
            actor_id,
        )
    except Exception:  # noqa: BLE001 — intentional broad catch; this is a background task
        logger.exception(
            "Background analytics pass FAILED: meter_id=%s facility_id=%s actor_id=%s",
            meter_id,
            facility_id,
            actor_id,
        )
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to close DB session in background analytics task "
                    "(meter_id=%s facility_id=%s)",
                    meter_id,
                    facility_id,
                )
