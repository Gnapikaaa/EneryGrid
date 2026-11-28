from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
import threading
import uuid

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import Settings
from app.core.constants import (
    AnomalySeverity,
    AnomalyStatus,
    BaselineStatus,
    CostEstimateStatus,
    Environment,
    HealthStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
    UserRole,
)
from app.core.database import build_session_factory, get_db
from app.main import create_app
from app.models.anomaly import Anomaly
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.analytics import AnalyticsCursor, AnalyticsProcessRequest
from app.services import analytics as analytics_service
from app.services import anomalies as anomaly_service
from app.services import insights as insight_service
from app.services.exceptions import ConflictError, ValidationFailureError


def _unit_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url="postgresql+psycopg://postgres:pass@localhost:5432/test",
    )


def _dummy_user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}@energygrid.test",
        full_name=role.value.title(),
        password_hash="not-used",
        role=role.value,
        is_active=True,
    )


def test_analytics_request_validation_and_cursor_rules() -> None:
    meter_id = uuid.uuid4()
    ts = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    # Valid cursor & bounded request
    valid = AnalyticsProcessRequest(
        meter_id=meter_id,
        max_readings=500,
        cursor=AnalyticsCursor(
            last_meter_id=meter_id,
            last_recorded_at=ts,
            last_reading_id=42,
        ),
    )
    assert valid.cursor is not None
    assert valid.cursor.last_reading_id == 42

    # Partial cursor (missing fields) rejected by strict schema
    with pytest.raises(ValidationError):
        AnalyticsProcessRequest.model_validate(
            {
                "cursor": {
                    "last_meter_id": str(meter_id),
                    "last_recorded_at": ts.isoformat(),
                }
            }
        )

    # Naive timestamps rejected
    with pytest.raises(ValidationError):
        AnalyticsCursor(
            last_meter_id=meter_id,
            last_recorded_at=datetime(2026, 11, 19, 12, 0),
            last_reading_id=1,
        )

    with pytest.raises(ValidationError):
        AnalyticsProcessRequest(
            start_at=datetime(2026, 11, 19, 12, 0),
        )

    # start_at > end_at rejected
    with pytest.raises(ValidationError):
        AnalyticsProcessRequest(
            start_at=ts,
            end_at=ts - timedelta(hours=1),
        )

    # retry_exhausted mutually exclusive with reprocess & retry_insufficient
    with pytest.raises(ValidationError):
        AnalyticsProcessRequest(retry_exhausted=True, reprocess=True)

    with pytest.raises(ValidationError):
        AnalyticsProcessRequest(retry_exhausted=True, retry_insufficient=True)


def test_analytics_api_rbac_and_http_validation() -> None:
    settings = _unit_settings()
    app = create_app(settings)

    class _UnusedSession:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(
                f"DB method '{name}' should not be called when auth or validation fails."
            )

    def _no_db():
        yield _UnusedSession()

    app.dependency_overrides[get_db] = _no_db
    client = TestClient(app)

    # Unauthenticated calls -> 401 across analytics, anomalies, insights
    assert client.post("/api/v1/analytics/process", json={}).status_code == 401
    assert client.get("/api/v1/anomalies").status_code == 401
    assert client.get("/api/v1/insights").status_code == 401

    sample_id = uuid.uuid4()
    for role in (UserRole.FACILITY_MANAGER, UserRole.VIEWER):
        app.dependency_overrides[get_current_user] = lambda r=role: _dummy_user(r)
        assert client.post("/api/v1/analytics/process", json={}).status_code == 403
        assert (
            client.post(f"/api/v1/anomalies/{sample_id}/acknowledge", json={}).status_code == 403
        )
        assert (
            client.post(f"/api/v1/anomalies/{sample_id}/investigate", json={}).status_code == 403
        )
        assert (
            client.post(
                f"/api/v1/anomalies/{sample_id}/resolve",
                json={"note": "Resolved"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/anomalies/{sample_id}/reopen",
                json={"note": "Reopened"},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/insights/{sample_id}",
                json={"status": "In Progress"},
            ).status_code
            == 403
        )

    # Utility engineer fails FastAPI 422 on invalid combinations before DB access
    app.dependency_overrides[get_current_user] = lambda: _dummy_user(UserRole.UTILITY_ENGINEER)
    r1 = client.post(
        "/api/v1/analytics/process",
        json={"retry_exhausted": True, "reprocess": True},
    )
    assert r1.status_code == 422

    r2 = client.post(
        "/api/v1/analytics/process",
        json={"retry_exhausted": True, "retry_insufficient": True},
    )
    assert r2.status_code == 422

    r3 = client.post(
        "/api/v1/analytics/process",
        json={"cursor": {"last_meter_id": str(sample_id)}},
    )
    assert r3.status_code == 422

    # Confirm all 12 Phase 2E route+method endpoints are exposed in OpenAPI
    openapi_paths = app.openapi()["paths"]
    actual_routes = {
        (method.upper(), path)
        for path, ops in openapi_paths.items()
        for method in ops
    }
    expected_routes = {
        ("POST", "/api/v1/analytics/process"),
        ("GET", "/api/v1/anomalies"),
        ("GET", "/api/v1/anomalies/{anomaly_id}"),
        ("GET", "/api/v1/anomalies/{anomaly_id}/history"),
        ("POST", "/api/v1/anomalies/{anomaly_id}/acknowledge"),
        ("POST", "/api/v1/anomalies/{anomaly_id}/investigate"),
        ("POST", "/api/v1/anomalies/{anomaly_id}/resolve"),
        ("POST", "/api/v1/anomalies/{anomaly_id}/reopen"),
        ("GET", "/api/v1/insights"),
        ("GET", "/api/v1/insights/{insight_id}"),
        ("GET", "/api/v1/insights/{insight_id}/history"),
        ("PATCH", "/api/v1/insights/{insight_id}"),
    }
    assert expected_routes.issubset(actual_routes)


def _seed_meter_history(
    db: Session,
    *,
    fac_id: str = "FAC-CONC",
    spike_last: bool = True,
) -> tuple[User, Facility, Zone, Meter]:
    actor = User(
        email=f"eng-{uuid.uuid4().hex[:8]}@energygrid.test",
        full_name="Grid Engineer",
        password_hash="hash",
        role=UserRole.UTILITY_ENGINEER.value,
        is_active=True,
    )
    fac = Facility(
        id=fac_id,
        code=fac_id[:6],
        name="Concurrency Plant",
        location="Austin, TX",
        timezone="UTC",
        currency_code="USD",
        contracted_demand_kw=Decimal("500.00"),
        off_peak_tariff_rate=Decimal("0.0500"),
        mid_peak_tariff_rate=Decimal("0.1000"),
        peak_tariff_rate=Decimal("0.2000"),
    )
    zone = Zone(
        facility_id=fac.id,
        slug="z1",
        name="Z1",
        primary_meter_code="M-C1",
        share_pct=Decimal("100.00"),
        status=HealthStatus.NOMINAL.value,
    )
    db.add_all([actor, fac, zone])
    db.flush()

    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_code="M-C1",
        equipment_name="Compressor C1",
        rated_kw=Decimal("300.00"),
        power_factor=Decimal("0.940"),
        thd_pct=Decimal("2.00"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 11, 1),
    )
    db.add(meter)
    db.flush()

    # 15 consecutive weekdays at 14:00 UTC + 1 target spike at day 16
    day_cursor = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)
    weekdays_added = 0
    while weekdays_added < 16:
        if day_cursor.weekday() < 5:
            is_last = spike_last and weekdays_added == 15
            kw = Decimal("220.00") if is_last else Decimal("100.00") + Decimal(weekdays_added % 3)
            db.add(
                TelemetryReading(
                    facility_id=fac.id,
                    zone_id=zone.id,
                    meter_id=meter.id,
                    interval_start=day_cursor - timedelta(seconds=900),
                    recorded_at=day_cursor,
                    interval_seconds=900,
                    actual_kw=kw,
                    energy_kwh=kw * Decimal("0.25"),
                    baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
                    power_factor=Decimal("0.940"),
                    tariff_period=TariffPeriod.PEAK.value,
                )
            )
            weekdays_added += 1
        day_cursor += timedelta(days=1)

    db.commit()
    return actor, fac, zone, meter


def test_db_analytics_cursor_pagination_and_tampered_cursor(
    db_session: Session, test_settings: Settings
) -> None:
    actor, fac, _zone, meter = _seed_meter_history(db_session, fac_id="FAC-CUR")

    # Tampered cursor -> ValidationFailureError (422)
    with pytest.raises(ValidationFailureError):
        analytics_service.process_analytics_batch(
            db_session,
            actor=actor,
            payload=AnalyticsProcessRequest(
                meter_id=meter.id,
                cursor=AnalyticsCursor(
                    last_meter_id=meter.id,
                    last_recorded_at=datetime(2026, 10, 12, 14, 0, tzinfo=UTC),
                    last_reading_id=99999999,
                ),
            ),
            settings=test_settings,
        )

    # First bounded page (max_readings=8)
    page1 = analytics_service.process_analytics_batch(
        db_session,
        actor=actor,
        payload=AnalyticsProcessRequest(meter_id=meter.id, max_readings=8, include_insights=False),
        settings=test_settings,
    )
    assert page1.processed_readings == 8
    assert page1.has_more is True
    assert page1.remaining_eligible_readings == 8
    assert page1.next_cursor is not None

    # Second bounded page picks up cleanly at next_cursor
    page2 = analytics_service.process_analytics_batch(
        db_session,
        actor=actor,
        payload=AnalyticsProcessRequest(
            meter_id=meter.id,
            max_readings=10,
            include_insights=False,
            cursor=page1.next_cursor,
        ),
        settings=test_settings,
    )
    assert page2.processed_readings == 8
    assert page2.has_more is False
    assert page2.remaining_eligible_readings == 0
    assert page2.next_cursor is None
    assert page2.anomalies_created == 1

    # Reprocess mode paginates over previously processed readings without skipping
    re1 = analytics_service.process_analytics_batch(
        db_session,
        actor=actor,
        payload=AnalyticsProcessRequest(
            meter_id=meter.id,
            reprocess=True,
            max_readings=10,
            include_insights=False,
        ),
        settings=test_settings,
    )
    assert re1.processed_readings == 10
    assert re1.has_more is True
    assert re1.remaining_eligible_readings == 6
    assert re1.next_cursor is not None

    re2 = analytics_service.process_analytics_batch(
        db_session,
        actor=actor,
        payload=AnalyticsProcessRequest(
            meter_id=meter.id,
            reprocess=True,
            max_readings=10,
            include_insights=False,
            cursor=re1.next_cursor,
        ),
        settings=test_settings,
    )
    assert re2.processed_readings == 6
    assert re2.has_more is False
    assert re2.anomalies_created == 0
    assert re2.anomalies_unchanged == 1


def test_db_concurrent_analytics_batches_with_barrier(
    db_engine: Engine, db_session: Session, test_settings: Settings
) -> None:
    actor, _fac, _zone, meter = _seed_meter_history(db_session, fac_id="FAC-BAR")
    actor_id = actor.id
    meter_id = meter.id

    SessionLocal = build_session_factory(db_engine)
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker() -> None:
        session = SessionLocal()
        try:
            worker_actor = session.get(User, actor_id)
            assert worker_actor is not None
            barrier.wait(timeout=10)
            summary = analytics_service.process_analytics_batch(
                session,
                actor=worker_actor,
                payload=AnalyticsProcessRequest(meter_id=meter_id, include_insights=True),
                settings=test_settings,
            )
            results.append(summary.anomalies_created)
        except Exception as exc:
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker), threading.Thread(target=_worker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors
    assert sorted(results) == [0, 1]
    anomaly_count = int(
        db_session.scalar(select(func.count(Anomaly.id)).where(Anomaly.meter_id == meter_id)) or 0
    )
    assert anomaly_count == 1


def test_db_concurrent_anomaly_ack_and_insight_reactivation_with_barrier(
    db_engine: Engine, db_session: Session
) -> None:
    actor, fac, zone, meter = _seed_meter_history(db_session, fac_id="FAC-RACE")
    t = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    reading = db_session.scalar(
        select(TelemetryReading).where(TelemetryReading.meter_id == meter.id).limit(1)
    )
    assert reading is not None

    anomaly = Anomaly(
        event_code=f"EG-{reading.id}",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=reading.id,
        detected_at=t,
        severity=AnomalySeverity.HIGH.value,
        status=AnomalyStatus.OPEN.value,
        z_score=Decimal("3.00"),
        actual_kw=Decimal("220.00"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("120.00"),
        duration_min=15,
        estimated_waste_kwh=Decimal("30.00"),
        estimated_cost=Decimal("6.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        signature="Spike",
        recommendation="Inspect",
        waveform=[220.0],
        baseline_waveform=[100.0],
    )
    dedupe_key = f"LOW_POWER_FACTOR:facility={fac.id}:zone={zone.id}:meter={meter.id}"
    ins_impl = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code=InsightRuleCode.LOW_POWER_FACTOR.value,
        dedupe_key=dedupe_key,
        title="Impl",
        category=InsightCategory.POWER_QUALITY.value,
        summary="Impl",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE.value,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.IMPLEMENTED.value,
    )
    ins_active = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code=InsightRuleCode.LOW_POWER_FACTOR.value,
        dedupe_key=dedupe_key,
        title="Active",
        category=InsightCategory.POWER_QUALITY.value,
        summary="Active",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE.value,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.RECOMMENDED.value,
    )
    db_session.add_all([anomaly, ins_impl, ins_active])
    db_session.commit()

    SessionLocal = build_session_factory(db_engine)
    barrier = threading.Barrier(2)
    ack_outcomes: list[str] = []

    def _race_ack() -> None:
        session = SessionLocal()
        try:
            worker_actor = session.get(User, actor.id)
            assert worker_actor is not None
            barrier.wait(timeout=10)
            anomaly_service.acknowledge_anomaly(
                session, actor=worker_actor, anomaly_id=anomaly.id, note="Ack"
            )
            ack_outcomes.append("ok")
        except ConflictError:
            ack_outcomes.append("conflict")
        finally:
            session.close()

    t1 = threading.Thread(target=_race_ack)
    t2 = threading.Thread(target=_race_ack)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert sorted(ack_outcomes) == ["conflict", "ok"]

    # Concurrent attempt to update active insight while reactivating implemented insight
    react_outcomes: list[str] = []
    barrier2 = threading.Barrier(2)

    def _update_active() -> None:
        session = SessionLocal()
        try:
            worker_actor = session.get(User, actor.id)
            assert worker_actor is not None
            barrier2.wait(timeout=10)
            insight_service.update_insight_status(
                session,
                actor=worker_actor,
                insight_id=ins_active.id,
                new_status=InsightStatus.IN_PROGRESS,
            )
            react_outcomes.append("active_progressed")
        finally:
            session.close()

    def _try_reactivate() -> None:
        session = SessionLocal()
        try:
            worker_actor = session.get(User, actor.id)
            assert worker_actor is not None
            barrier2.wait(timeout=10)
            insight_service.update_insight_status(
                session,
                actor=worker_actor,
                insight_id=ins_impl.id,
                new_status=InsightStatus.RECOMMENDED,
            )
            react_outcomes.append("unexpected_reactivate")
        except ConflictError:
            react_outcomes.append("reactivate_conflict")
        finally:
            session.close()

    t3 = threading.Thread(target=_update_active)
    t4 = threading.Thread(target=_try_reactivate)
    t3.start()
    t4.start()
    t3.join(timeout=15)
    t4.join(timeout=15)
    assert sorted(react_outcomes) == ["active_progressed", "reactivate_conflict"]
