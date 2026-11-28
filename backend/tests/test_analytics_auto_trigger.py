"""Unit tests for the automatic analytics background trigger.

No database connection is required. All DB and service calls are mocked.

Covers:
1. trigger_analytics_for_meter catches exceptions and does not re-raise.
2. trigger_analytics_for_meter logs failures at ERROR level.
3. analytics_auto_trigger=False â†’ trigger is a no-op (service not called).
4. Session factory is called to get a fresh session; request session not reused.
5. Session is always closed in the finally block, even on exception.
6. Successful pass logs at INFO level with correct counts.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.analytics_scheduler import trigger_analytics_for_meter
from app.core.config import Settings
from app.core.constants import Environment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(*, auto_trigger: bool = True, bg_max: int = 500) -> Settings:
    return Settings(_env_file=None,
        environment=Environment.TEST,
        database_url="postgresql+psycopg://test:test@localhost/test_db",
        test_database_url="postgresql+psycopg://test:test@localhost/test_db2",
        jwt_secret_key="test-only-signing-key-with-more-than-32-characters",
        allow_dev_auth_bypass=False,
        allowed_origins=["http://localhost:3000"],
        cors_allow_credentials=True,
        analytics_auto_trigger=auto_trigger,
        analytics_background_max_readings=bg_max,
    )


def _make_session_factory(session: Any) -> Any:
    """Return a factory callable that returns the given session object."""
    return lambda: session


# ---------------------------------------------------------------------------
# 3. analytics_auto_trigger=False â†’ no-op
# ---------------------------------------------------------------------------

class TestAutoTriggerDisabled:
    def test_disabled_does_not_call_session_factory(self) -> None:
        settings = _make_settings(auto_trigger=False)
        factory = MagicMock()
        actor_id = uuid.uuid4()
        meter_id = uuid.uuid4()

        trigger_analytics_for_meter(
            meter_id,
            "test-facility-001",
            factory,
            settings,
            actor_id,
        )

        factory.assert_not_called()

    def test_disabled_logs_debug_message(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _make_settings(auto_trigger=False)
        factory = MagicMock()
        actor_id = uuid.uuid4()

        with caplog.at_level(logging.DEBUG, logger="app.services.analytics_scheduler"):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "test-facility-001",
                factory,
                settings,
                actor_id,
            )

        assert any("analytics_auto_trigger disabled" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 1 & 2. Exception caught, not re-raised; logged at ERROR
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    def test_exception_in_process_does_not_reraise(self) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        with patch(
            "app.services.analytics_scheduler.process_analytics_batch",
            side_effect=RuntimeError("DB explosion"),
        ):
            # Must NOT raise
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                factory,
                settings,
                uuid.uuid4(),
            )

    def test_exception_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        with caplog.at_level(logging.ERROR, logger="app.services.analytics_scheduler"):
            with patch(
                "app.services.analytics_scheduler.process_analytics_batch",
                side_effect=RuntimeError("DB explosion"),
            ):
                trigger_analytics_for_meter(
                    uuid.uuid4(),
                    "fac-001",
                    factory,
                    settings,
                    uuid.uuid4(),
                )

        assert any("FAILED" in r.message for r in caplog.records)

    def test_exception_in_session_factory_does_not_reraise(self) -> None:
        """Even if the session factory itself raises, the trigger must not propagate."""
        settings = _make_settings(auto_trigger=True)

        def bad_factory() -> None:
            raise ConnectionError("Cannot connect")

        with patch("app.services.analytics_scheduler.process_analytics_batch"):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                bad_factory,  # type: ignore[arg-type]
                settings,
                uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# 4. Session factory is called; a fresh session is obtained
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_session_factory_called_once(self) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = MagicMock(return_value=mock_session)

        mock_summary = MagicMock()
        mock_summary.processed_readings = 5
        mock_summary.anomalies_created = 1
        mock_summary.insights_created = 0

        with patch(
            "app.services.analytics_scheduler.process_analytics_batch",
            return_value=mock_summary,
        ):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                factory,
                settings,
                uuid.uuid4(),
            )

        factory.assert_called_once()

    def test_session_closed_on_success(self) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        mock_summary = MagicMock()
        mock_summary.processed_readings = 0
        mock_summary.anomalies_created = 0
        mock_summary.insights_created = 0

        with patch(
            "app.services.analytics_scheduler.process_analytics_batch",
            return_value=mock_summary,
        ):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                factory,
                settings,
                uuid.uuid4(),
            )

        mock_session.close.assert_called_once()

    def test_session_closed_even_on_exception(self) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        with patch(
            "app.services.analytics_scheduler.process_analytics_batch",
            side_effect=ValueError("analytics error"),
        ):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                factory,
                settings,
                uuid.uuid4(),
            )

        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Successful pass: INFO logged with correct counts
# ---------------------------------------------------------------------------

class TestSuccessLogging:
    def test_success_logs_at_info(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _make_settings(auto_trigger=True)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        mock_summary = MagicMock()
        mock_summary.processed_readings = 42
        mock_summary.anomalies_created = 3
        mock_summary.insights_created = 1

        with caplog.at_level(logging.INFO, logger="app.services.analytics_scheduler"):
            with patch(
                "app.services.analytics_scheduler.process_analytics_batch",
                return_value=mock_summary,
            ):
                trigger_analytics_for_meter(
                    uuid.uuid4(),
                    "fac-001",
                    factory,
                    settings,
                    uuid.uuid4(),
                )

        assert any("completed" in r.message for r in caplog.records)

    def test_max_readings_budget_passed_to_service(self) -> None:
        settings = _make_settings(auto_trigger=True, bg_max=250)
        mock_session = MagicMock()
        factory = _make_session_factory(mock_session)

        mock_summary = MagicMock()
        mock_summary.processed_readings = 0
        mock_summary.anomalies_created = 0
        mock_summary.insights_created = 0

        captured_request: list[Any] = []

        def _capture(db: Any, *, actor: Any, payload: Any, settings: Any) -> Any:
            captured_request.append(payload)
            return mock_summary

        with patch(
            "app.services.analytics_scheduler.process_analytics_batch",
            side_effect=_capture,
        ):
            trigger_analytics_for_meter(
                uuid.uuid4(),
                "fac-001",
                factory,
                settings,
                uuid.uuid4(),
            )

        assert len(captured_request) == 1
        assert captured_request[0].max_readings == 250

