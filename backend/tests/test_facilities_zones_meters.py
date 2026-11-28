from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import threading
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    AnomalySeverity,
    AnomalyStatus,
    BaselineStatus,
    CostEstimateStatus,
    HealthStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
    TariffPeriod,
    UserRole,
)
from app.core.database import build_session_factory, get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import (
    Anomaly,
    EnergyInsight,
    Facility,
    Meter,
    MeterCalibrationAudit,
    TelemetryReading,
    User,
    Zone,
)
from app.schemas.facility import (
    FacilityCreate,
    FacilityUpdate,
    MeterCreate,
    MeterUpdate,
    ZoneCreate,
    ZoneUpdate,
)
from app.services import facilities as facility_service
from app.services import meters as meter_service
from app.services import zones as zone_service
from app.services.exceptions import ConflictError, PermissionDeniedError


def _build_test_client(test_settings: Settings, db_session: Session) -> TestClient:
    app = create_app(test_settings)

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _create_user_with_token(
    db: Session,
    settings: Settings,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    is_active: bool = True,
) -> tuple[User, str]:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password("GridStrongPass#2026"),
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token, _ = create_access_token(user_id=user.id, role=role, settings=settings)
    return user, token


def _facility_payload(
    *,
    facility_id: str = "plant-pune-01",
    code: str = "PNQ-01",
    name: str = "Pune Manufacturing Plant",
) -> dict[str, object]:
    return {
        "id": facility_id,
        "code": code,
        "name": name,
        "location": "Pune, India",
        "timezone": "Asia/Kolkata",
        "currency_code": "INR",
        "contracted_demand_kw": "1500.00",
        "off_peak_tariff_rate": "6.1000",
        "mid_peak_tariff_rate": "8.4000",
        "peak_tariff_rate": "11.8000",
    }


def _zone_payload(
    facility_id: str,
    *,
    slug: str = "hvac-cooling",
    name: str = "HVAC & Cooling",
    primary_meter_code: str = "MTR-HVAC-01",
) -> dict[str, object]:
    return {
        "facility_id": facility_id,
        "slug": slug,
        "name": name,
        "primary_meter_code": primary_meter_code,
        "share_pct": "34.50",
        "status": "Nominal",
    }


def _meter_payload(
    facility_id: str,
    zone_id: str | uuid.UUID,
    *,
    meter_code: str = "MTR-HVAC-01",
    equipment_name: str = "Centrifugal Chiller 1",
) -> dict[str, object]:
    return {
        "facility_id": facility_id,
        "zone_id": str(zone_id),
        "meter_code": meter_code,
        "equipment_name": equipment_name,
        "rated_kw": "420.00",
        "nominal_interval_seconds": 900,
        "current_kw": "255.25",
        "power_factor": "0.962",
        "thd_pct": "2.15",
        "status": "Nominal",
        "last_calibrated_at": "2026-10-15",
    }


def test_unauthenticated_requests_rejected_on_all_crud_endpoints(
    test_settings: Settings, db_session: Session
) -> None:
    random_uuid = str(uuid.uuid4())
    with _build_test_client(test_settings, db_session) as client:
        for method, path in (
            ("GET", "/api/v1/facilities"),
            ("POST", "/api/v1/facilities"),
            ("GET", "/api/v1/facilities/fac-1"),
            ("PATCH", "/api/v1/facilities/fac-1"),
            ("POST", "/api/v1/facilities/fac-1/deactivate"),
            ("DELETE", "/api/v1/facilities/fac-1"),
            ("GET", "/api/v1/zones"),
            ("POST", "/api/v1/zones"),
            ("GET", f"/api/v1/zones/{random_uuid}"),
            ("PATCH", f"/api/v1/zones/{random_uuid}"),
            ("POST", f"/api/v1/zones/{random_uuid}/deactivate"),
            ("DELETE", f"/api/v1/zones/{random_uuid}"),
            ("GET", "/api/v1/meters"),
            ("POST", "/api/v1/meters"),
            ("GET", f"/api/v1/meters/{random_uuid}"),
            ("PATCH", f"/api/v1/meters/{random_uuid}"),
            ("POST", f"/api/v1/meters/{random_uuid}/deactivate"),
            ("DELETE", f"/api/v1/meters/{random_uuid}"),
        ):
            response = client.request(method, path)
            assert response.status_code == 401, f"Expected 401 for {method} {path}"


def test_rbac_matrix_facility_manager_strictly_readonly_and_engineer_meter_update_only(
    test_settings: Settings, db_session: Session
) -> None:
    admin, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="admin@energygrid.example",
        full_name="Grid Admin",
        role=UserRole.ADMIN,
    )
    manager, manager_token = _create_user_with_token(
        db_session,
        test_settings,
        email="manager@energygrid.example",
        full_name="Facility Manager",
        role=UserRole.FACILITY_MANAGER,
    )
    engineer, engineer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="engineer@energygrid.example",
        full_name="Utility Engineer",
        role=UserRole.UTILITY_ENGINEER,
    )
    viewer, viewer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="viewer@energygrid.example",
        full_name="Grid Viewer",
        role=UserRole.VIEWER,
    )

    with _build_test_client(test_settings, db_session) as client:
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        fac_resp = client.post(
            "/api/v1/facilities", headers=admin_headers, json=_facility_payload()
        )
        assert fac_resp.status_code == 201
        fac_id = fac_resp.json()["id"]

        zone_resp = client.post(
            "/api/v1/zones", headers=admin_headers, json=_zone_payload(fac_id)
        )
        assert zone_resp.status_code == 201
        zone_id = zone_resp.json()["id"]

        meter_resp = client.post(
            "/api/v1/meters",
            headers=admin_headers,
            json=_meter_payload(fac_id, zone_id),
        )
        assert meter_resp.status_code == 201
        meter_id = meter_resp.json()["id"]

        # All authenticated roles have read access
        for token in (admin_token, manager_token, engineer_token, viewer_token):
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/facilities", headers=headers).status_code == 200
            assert client.get(f"/api/v1/facilities/{fac_id}", headers=headers).status_code == 200
            assert client.get("/api/v1/zones", headers=headers).status_code == 200
            assert client.get(f"/api/v1/zones/{zone_id}", headers=headers).status_code == 200
            assert client.get("/api/v1/meters", headers=headers).status_code == 200
            assert client.get(f"/api/v1/meters/{meter_id}", headers=headers).status_code == 200

        # facility_manager and viewer are strictly read-only on HTTP endpoints
        for ro_token in (manager_token, viewer_token):
            headers = {"Authorization": f"Bearer {ro_token}"}
            assert (
                client.post(
                    "/api/v1/facilities",
                    headers=headers,
                    json=_facility_payload(facility_id="plant-ro", code="RO-01"),
                ).status_code
                == 403
            )
            assert (
                client.patch(
                    f"/api/v1/facilities/{fac_id}",
                    headers=headers,
                    json={"name": "Blocked Rename"},
                ).status_code
                == 403
            )
            assert (
                client.post(f"/api/v1/facilities/{fac_id}/deactivate", headers=headers).status_code
                == 403
            )
            assert client.delete(f"/api/v1/facilities/{fac_id}", headers=headers).status_code == 403

            assert (
                client.post(
                    "/api/v1/zones",
                    headers=headers,
                    json=_zone_payload(fac_id, slug="ro-zone", primary_meter_code="MTR-RO"),
                ).status_code
                == 403
            )
            assert (
                client.patch(
                    f"/api/v1/zones/{zone_id}",
                    headers=headers,
                    json={"name": "Blocked Zone Rename"},
                ).status_code
                == 403
            )
            assert client.post(f"/api/v1/zones/{zone_id}/deactivate", headers=headers).status_code == 403
            assert client.delete(f"/api/v1/zones/{zone_id}", headers=headers).status_code == 403

            assert (
                client.post(
                    "/api/v1/meters",
                    headers=headers,
                    json=_meter_payload(fac_id, zone_id, meter_code="MTR-RO-01"),
                ).status_code
                == 403
            )
            assert (
                client.patch(
                    f"/api/v1/meters/{meter_id}",
                    headers=headers,
                    json={"current_kw": "100.00"},
                ).status_code
                == 403
            )
            assert (
                client.post(f"/api/v1/meters/{meter_id}/deactivate", headers=headers).status_code
                == 403
            )
            assert client.delete(f"/api/v1/meters/{meter_id}", headers=headers).status_code == 403

        # utility_engineer can PATCH meters only; all other mutations forbidden
        eng_headers = {"Authorization": f"Bearer {engineer_token}"}
        eng_patch_meter = client.patch(
            f"/api/v1/meters/{meter_id}",
            headers=eng_headers,
            json={"status": "Warning", "current_kw": "312.40"},
        )
        assert eng_patch_meter.status_code == 200
        assert eng_patch_meter.json()["status"] == "Warning"
        assert eng_patch_meter.json()["current_kw"] == "312.40"

        for method, path, body in (
            ("POST", "/api/v1/facilities", _facility_payload(facility_id="plant-eng", code="ENG-01")),
            ("PATCH", f"/api/v1/facilities/{fac_id}", {"name": "Blocked"}),
            ("POST", f"/api/v1/facilities/{fac_id}/deactivate", None),
            ("DELETE", f"/api/v1/facilities/{fac_id}", None),
            ("POST", "/api/v1/zones", _zone_payload(fac_id, slug="eng-zone", primary_meter_code="M-E")),
            ("PATCH", f"/api/v1/zones/{zone_id}", {"name": "Blocked"}),
            ("POST", f"/api/v1/zones/{zone_id}/deactivate", None),
            ("DELETE", f"/api/v1/zones/{zone_id}", None),
            ("POST", "/api/v1/meters", _meter_payload(fac_id, zone_id, meter_code="MTR-ENG-NEW")),
            ("POST", f"/api/v1/meters/{meter_id}/deactivate", None),
            ("DELETE", f"/api/v1/meters/{meter_id}", None),
        ):
            resp = client.request(method, path, headers=eng_headers, json=body)
            assert resp.status_code == 403, f"Expected 403 for utility_engineer {method} {path}"

    # Verify service-layer dual authorization directly (bypassing FastAPI routes)
    zone_uuid = uuid.UUID(zone_id)
    meter_uuid = uuid.UUID(meter_id)
    for forbidden_actor in (manager, viewer):
        with pytest.raises(PermissionDeniedError):
            facility_service.create_facility(
                db_session,
                actor=forbidden_actor,
                payload=FacilityCreate(**_facility_payload(facility_id="svc-fac", code="SVC-01")),  # type: ignore[arg-type]
            )
        with pytest.raises(PermissionDeniedError):
            facility_service.update_facility(
                db_session,
                actor=forbidden_actor,
                facility_id=fac_id,
                payload=FacilityUpdate(name="Blocked"),
            )
        with pytest.raises(PermissionDeniedError):
            facility_service.deactivate_facility(db_session, actor=forbidden_actor, facility_id=fac_id)
        with pytest.raises(PermissionDeniedError):
            facility_service.delete_facility(db_session, actor=forbidden_actor, facility_id=fac_id)

        with pytest.raises(PermissionDeniedError):
            zone_service.create_zone(
                db_session,
                actor=forbidden_actor,
                payload=ZoneCreate(**_zone_payload(fac_id, slug="svc-zone")),  # type: ignore[arg-type]
            )
        with pytest.raises(PermissionDeniedError):
            zone_service.update_zone(
                db_session,
                actor=forbidden_actor,
                zone_id=zone_uuid,
                payload=ZoneUpdate(name="Blocked"),
            )
        with pytest.raises(PermissionDeniedError):
            zone_service.deactivate_zone(db_session, actor=forbidden_actor, zone_id=zone_uuid)
        with pytest.raises(PermissionDeniedError):
            zone_service.delete_zone(db_session, actor=forbidden_actor, zone_id=zone_uuid)

        with pytest.raises(PermissionDeniedError):
            meter_service.register_meter(
                db_session,
                actor=forbidden_actor,
                payload=MeterCreate(**_meter_payload(fac_id, zone_uuid, meter_code="MTR-SVC-01")),  # type: ignore[arg-type]
            )
        with pytest.raises(PermissionDeniedError):
            meter_service.update_meter(
                db_session,
                actor=forbidden_actor,
                meter_id=meter_uuid,
                payload=MeterUpdate(current_kw=Decimal("10.00")),
            )
        with pytest.raises(PermissionDeniedError):
            meter_service.deactivate_meter(db_session, actor=forbidden_actor, meter_id=meter_uuid)
        with pytest.raises(PermissionDeniedError):
            meter_service.delete_meter(db_session, actor=forbidden_actor, meter_id=meter_uuid)

    with pytest.raises(PermissionDeniedError):
        facility_service.update_facility(
            db_session, actor=engineer, facility_id=fac_id, payload=FacilityUpdate(name="No")
        )
    with pytest.raises(PermissionDeniedError):
        meter_service.deactivate_meter(db_session, actor=engineer, meter_id=meter_uuid)

    # Admin service call succeeds
    updated = meter_service.update_meter(
        db_session,
        actor=admin,
        meter_id=meter_uuid,
        payload=MeterUpdate(status=HealthStatus.NOMINAL),
    )
    assert updated.status == HealthStatus.NOMINAL


def test_crud_validation_filtering_pagination_and_no_n_plus_one(
    test_settings: Settings, db_session: Session, db_engine: Engine
) -> None:
    _, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="crud.admin@energygrid.example",
        full_name="CRUD Admin",
        role=UserRole.ADMIN,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    with _build_test_client(test_settings, db_session) as client:
        # Validation rejects invalid currency, timezone, and extra fields
        bad_currency = client.post(
            "/api/v1/facilities",
            headers=headers,
            json={**_facility_payload(), "currency_code": "XYZ"},
        )
        assert bad_currency.status_code == 422

        bad_tz = client.post(
            "/api/v1/facilities",
            headers=headers,
            json={**_facility_payload(), "timezone": "Mars/Olympus"},
        )
        assert bad_tz.status_code == 422

        # Create 3 facilities, 2 zones each (6 total), 2 meters in first zone
        zone_ids_by_fac: dict[str, list[str]] = {}
        for idx in range(1, 4):
            fac_id = f"fac-grid-0{idx}"
            resp = client.post(
                "/api/v1/facilities",
                headers=headers,
                json=_facility_payload(
                    facility_id=fac_id,
                    code=f"GRD-0{idx}",
                    name=f"Grid Campus {idx}",
                ),
            )
            assert resp.status_code == 201
            zone_ids_by_fac[fac_id] = []
            for z_idx in range(1, 3):
                z_resp = client.post(
                    "/api/v1/zones",
                    headers=headers,
                    json=_zone_payload(
                        fac_id,
                        slug=f"zone-{z_idx}",
                        name=f"Zone {idx}-{z_idx}",
                        primary_meter_code=f"MTR-{idx}-{z_idx}-A",
                    ),
                )
                assert z_resp.status_code == 201
                zone_ids_by_fac[fac_id].append(z_resp.json()["id"])

        # Duplicate facility ID or code -> 409
        assert (
            client.post(
                "/api/v1/facilities",
                headers=headers,
                json=_facility_payload(facility_id="fac-grid-01", code="GRD-99"),
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/facilities",
                headers=headers,
                json=_facility_payload(facility_id="fac-grid-99", code="GRD-01"),
            ).status_code
            == 409
        )

        # Zone under missing facility -> 404; duplicate slug in same facility -> 409
        assert (
            client.post(
                "/api/v1/zones",
                headers=headers,
                json=_zone_payload("missing-fac"),
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/zones",
                headers=headers,
                json=_zone_payload("fac-grid-01", slug="zone-1"),
            ).status_code
            == 409
        )

        # Cross-facility zone/meter mismatch -> 400
        assert (
            client.post(
                "/api/v1/meters",
                headers=headers,
                json=_meter_payload(
                    "fac-grid-01",
                    zone_ids_by_fac["fac-grid-02"][0],
                    meter_code="MTR-CROSS-BAD",
                ),
            ).status_code
            == 400
        )

        # Register 3 meters across facilities
        m1 = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(
                "fac-grid-01",
                zone_ids_by_fac["fac-grid-01"][0],
                meter_code="MTR-01-A",
            ),
        )
        assert m1.status_code == 201
        m2 = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(
                "fac-grid-01",
                zone_ids_by_fac["fac-grid-01"][1],
                meter_code="MTR-01-B",
            ),
        )
        assert m2.status_code == 201
        m3 = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(
                "fac-grid-02",
                zone_ids_by_fac["fac-grid-02"][0],
                meter_code="MTR-02-A",
            ),
        )
        assert m3.status_code == 201

        # Pagination bounds check
        assert client.get("/api/v1/facilities?page_size=101", headers=headers).status_code == 422
        assert client.get("/api/v1/facilities?page=0", headers=headers).status_code == 422

        page1 = client.get("/api/v1/facilities?page=1&page_size=2", headers=headers)
        assert page1.status_code == 200
        body1 = page1.json()
        assert body1["total"] == 3
        assert body1["pages"] == 2
        assert [item["id"] for item in body1["items"]] == ["fac-grid-01", "fac-grid-02"]
        assert body1["items"][0]["zone_count"] == 2
        assert body1["items"][0]["meter_count"] == 2

        page2 = client.get("/api/v1/facilities?page=2&page_size=2", headers=headers)
        assert page2.status_code == 200
        assert [item["id"] for item in page2.json()["items"]] == ["fac-grid-03"]

        # Zone and meter filtering
        z_filtered = client.get("/api/v1/zones?facility_id=fac-grid-01", headers=headers)
        assert z_filtered.status_code == 200
        assert z_filtered.json()["total"] == 2

        m_filtered = client.get(
            f"/api/v1/meters?facility_id=fac-grid-01&zone_id={zone_ids_by_fac['fac-grid-01'][0]}",
            headers=headers,
        )
        assert m_filtered.status_code == 200
        assert m_filtered.json()["total"] == 1
        assert m_filtered.json()["items"][0]["meter_code"] == "MTR-01-A"

        # Constant query count check (no N+1) on list endpoints
        sql_statements: list[str] = []

        def _count_queries(_conn, _cursor, statement, _params, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
            if statement.lstrip().upper().startswith("SELECT"):
                sql_statements.append(statement)

        event.listen(db_engine, "before_cursor_execute", _count_queries)
        try:
            sql_statements.clear()
            assert client.get("/api/v1/facilities?page=1&page_size=20", headers=headers).status_code == 200
            # Expect: user lookup (auth), count, select facilities, grouped zones, grouped meters = 5 max
            assert len(sql_statements) <= 5

            sql_statements.clear()
            assert client.get("/api/v1/zones?page=1&page_size=20", headers=headers).status_code == 200
            # Expect: user lookup (auth), count, select zones, grouped meters = 4 max
            assert len(sql_statements) <= 4
        finally:
            event.remove(db_engine, "before_cursor_execute", _count_queries)


def test_soft_deactivation_cascade_protection_and_historical_preservation(
    test_settings: Settings, db_session: Session
) -> None:
    admin, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="history.admin@energygrid.example",
        full_name="History Admin",
        role=UserRole.ADMIN,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    with _build_test_client(test_settings, db_session) as client:
        fac_id = "fac-hist-01"
        assert (
            client.post(
                "/api/v1/facilities",
                headers=headers,
                json=_facility_payload(facility_id=fac_id, code="HST-01"),
            ).status_code
            == 201
        )
        z1_resp = client.post(
            "/api/v1/zones",
            headers=headers,
            json=_zone_payload(fac_id, slug="z-primary", primary_meter_code="MTR-HIST-01"),
        )
        assert z1_resp.status_code == 201
        z1_id = z1_resp.json()["id"]

        z2_resp = client.post(
            "/api/v1/zones",
            headers=headers,
            json=_zone_payload(fac_id, slug="z-secondary", primary_meter_code="MTR-HIST-02"),
        )
        assert z2_resp.status_code == 201
        z2_id = z2_resp.json()["id"]

        m_hist_resp = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(fac_id, z1_id, meter_code="MTR-HIST-01"),
        )
        assert m_hist_resp.status_code == 201
        m_hist_id = uuid.UUID(m_hist_resp.json()["id"])

        m_clean_resp = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(fac_id, z2_id, meter_code="MTR-CLEAN-02"),
        )
        assert m_clean_resp.status_code == 201
        m_clean_id = uuid.UUID(m_clean_resp.json()["id"])

        # Seed telemetry, anomaly, calibration audit on m_hist_id, plus energy insight on z1_id
        t_end = datetime(2026, 11, 10, 10, 15, tzinfo=UTC)
        reading = TelemetryReading(
            facility_id=fac_id,
            zone_id=uuid.UUID(z1_id),
            meter_id=m_hist_id,
            interval_start=t_end - timedelta(seconds=900),
            recorded_at=t_end,
            interval_seconds=900,
            actual_kw=Decimal("310.00"),
            energy_kwh=Decimal("77.5000"),
            baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
            power_factor=Decimal("0.950"),
            tariff_period=TariffPeriod.PEAK.value,
        )
        db_session.add(reading)
        db_session.flush()

        anomaly = Anomaly(
            event_code="EVT-HIST-01",
            facility_id=fac_id,
            zone_id=uuid.UUID(z1_id),
            meter_id=m_hist_id,
            reading_id=reading.id,
            detected_at=t_end,
            severity=AnomalySeverity.HIGH.value,
            status=AnomalyStatus.OPEN.value,
            z_score=Decimal("3.40"),
            actual_kw=Decimal("310.00"),
            expected_kw=Decimal("210.00"),
            deviation_pct=Decimal("47.62"),
            duration_min=15,
            estimated_waste_kwh=Decimal("25.00"),
            estimated_cost=Decimal("295.00"),
            signature="Compressor spike",
            recommendation="Inspect intake valve",
            waveform=[210.0, 310.0],
            baseline_waveform=[210.0, 210.0],
        )
        audit = MeterCalibrationAudit(
            meter_id=m_hist_id,
            audited_by_user_id=admin.id,
            audited_on=date(2026, 11, 1),
            notes="Annual NIST traceable clamp audit",
        )
        insight = EnergyInsight(
            facility_id=fac_id,
            zone_id=uuid.UUID(z1_id),
            rule_code=InsightRuleCode.THERMAL_CORRELATED_LOAD.value,
            dedupe_key=(
                f"{InsightRuleCode.THERMAL_CORRELATED_LOAD.value}"
                f":facility={fac_id}:zone={z1_id}:meter=none"
            ),
            title="Stagger Chiller Staging",
            category=InsightCategory.HVAC_THERMAL.value,
            summary="Delay secondary chiller lead-lag threshold by 12 minutes.",
            monthly_kwh_savings=Decimal("2400.00"),
            annual_cost_savings=Decimal("240000.00"),
            payback_months=Decimal("2.00"),
            cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
            savings_basis=InsightSavingsBasis.ESTIMATED_EXCESS_AVOIDANCE.value,
            priority=InsightPriority.HIGH.value,
            status=InsightStatus.RECOMMENDED.value,
        )
        db_session.add_all([anomaly, audit, insight])
        db_session.commit()

        # Cannot reassign m_hist_id to another zone while telemetry/anomalies exist
        assert (
            client.patch(
                f"/api/v1/meters/{m_hist_id}",
                headers=headers,
                json={"zone_id": z2_id},
            ).status_code
            == 409
        )

        # Clean meter CAN be reassigned to another active zone in same facility
        assert (
            client.patch(
                f"/api/v1/meters/{m_clean_id}",
                headers=headers,
                json={"zone_id": z1_id},
            ).status_code
            == 200
        )
        # Move m_clean_id back to z2_id then delete it (zero historical records -> 204)
        assert (
            client.patch(
                f"/api/v1/meters/{m_clean_id}",
                headers=headers,
                json={"zone_id": z2_id},
            ).status_code
            == 200
        )
        assert client.delete(f"/api/v1/meters/{m_clean_id}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/meters/{m_clean_id}", headers=headers).status_code == 404

        # Hard-deleting m_hist_id blocked with 409; history preserved
        assert client.delete(f"/api/v1/meters/{m_hist_id}", headers=headers).status_code == 409

        # Cannot deactivate zone or facility while active child resources exist
        assert client.post(f"/api/v1/zones/{z1_id}/deactivate", headers=headers).status_code == 409
        assert client.post(f"/api/v1/facilities/{fac_id}/deactivate", headers=headers).status_code == 409

        # Soft-deactivate m_hist_id -> 200 and preserves telemetry, anomaly, and audit
        deact_meter = client.post(f"/api/v1/meters/{m_hist_id}/deactivate", headers=headers)
        assert deact_meter.status_code == 200
        assert deact_meter.json()["is_active"] is False
        assert deact_meter.json()["deactivated_at"] is not None

        # Duplicate deactivation rejected cleanly
        assert client.post(f"/api/v1/meters/{m_hist_id}/deactivate", headers=headers).status_code == 409

        assert db_session.query(TelemetryReading).filter_by(meter_id=m_hist_id).count() == 1
        assert db_session.query(Anomaly).filter_by(meter_id=m_hist_id).count() == 1
        assert db_session.query(MeterCalibrationAudit).filter_by(meter_id=m_hist_id).count() == 1

        # Cannot register new meter under deactivated zone
        assert client.post(f"/api/v1/zones/{z1_id}/deactivate", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/v1/meters",
                headers=headers,
                json=_meter_payload(fac_id, z1_id, meter_code="MTR-AFTER-Z-DEACT"),
            ).status_code
            == 409
        )

        # Deactivate z2 (empty) and facility
        assert client.post(f"/api/v1/zones/{z2_id}/deactivate", headers=headers).status_code == 200
        deact_fac = client.post(f"/api/v1/facilities/{fac_id}/deactivate", headers=headers)
        assert deact_fac.status_code == 200
        assert deact_fac.json()["is_active"] is False

        # Cannot create zone under deactivated facility
        assert (
            client.post(
                "/api/v1/zones",
                headers=headers,
                json=_zone_payload(fac_id, slug="z-after-deact"),
            ).status_code
            == 409
        )

        # Hard-delete facility MUST be blocked even when zones are inactive (prevents CASCADE wipeout!)
        assert client.delete(f"/api/v1/facilities/{fac_id}", headers=headers).status_code == 409
        assert db_session.get(Zone, uuid.UUID(z1_id)) is not None

        # Hard-delete zone with inactive meter/insight blocked with 409; empty zone z2 deletes with 204
        assert client.delete(f"/api/v1/zones/{z1_id}", headers=headers).status_code == 409
        assert client.delete(f"/api/v1/zones/{z2_id}", headers=headers).status_code == 204


def test_delete_meter_blocked_individually_by_calibration_audit(
    test_settings: Settings, db_session: Session
) -> None:
    admin, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="audit.guard@energygrid.example",
        full_name="Audit Guard",
        role=UserRole.ADMIN,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    with _build_test_client(test_settings, db_session) as client:
        fac_id = "fac-audit-guard"
        client.post(
            "/api/v1/facilities",
            headers=headers,
            json=_facility_payload(facility_id=fac_id, code="AUD-01"),
        )
        z_id = client.post(
            "/api/v1/zones", headers=headers, json=_zone_payload(fac_id)
        ).json()["id"]
        m_id = client.post(
            "/api/v1/meters",
            headers=headers,
            json=_meter_payload(fac_id, z_id, meter_code="MTR-AUD-ONLY"),
        ).json()["id"]

        db_session.add(
            MeterCalibrationAudit(
                meter_id=uuid.UUID(m_id),
                audited_by_user_id=admin.id,
                audited_on=date(2026, 11, 5),
                notes="Calibration certificate only",
            )
        )
        db_session.commit()

        assert client.delete(f"/api/v1/meters/{m_id}", headers=headers).status_code == 409


def test_concurrent_parent_deactivation_and_child_creation_stays_consistent(
    test_settings: Settings, db_session: Session, db_engine: Engine
) -> None:
    admin, _ = _create_user_with_token(
        db_session,
        test_settings,
        email="concurrency.admin@energygrid.example",
        full_name="Concurrency Admin",
        role=UserRole.ADMIN,
    )
    admin_id = admin.id
    session_factory = build_session_factory(db_engine)

    # 1. Race deactivate_facility vs create_zone across several runs
    for run_idx in range(4):
        fac_id = f"fac-race-{run_idx}"
        facility_service.create_facility(
            db_session,
            actor=admin,
            payload=FacilityCreate(**_facility_payload(facility_id=fac_id, code=f"RC-{run_idx}")),  # type: ignore[arg-type]
        )

        barrier = threading.Barrier(2)

        def _deactivate_fac() -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                barrier.wait(timeout=5)
                try:
                    facility_service.deactivate_facility(s, actor=actor_row, facility_id=fac_id)
                    return "deactivated"
                except ConflictError:
                    return "conflict"
            finally:
                s.close()

        def _create_child_zone(idx: int = run_idx) -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                barrier.wait(timeout=5)
                try:
                    zone_service.create_zone(
                        s,
                        actor=actor_row,
                        payload=ZoneCreate(**_zone_payload(fac_id, slug=f"race-zone-{idx}")),  # type: ignore[arg-type]
                    )
                    return "created"
                except ConflictError:
                    return "conflict"
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_deact = pool.submit(_deactivate_fac)
            f_create = pool.submit(_create_child_zone)
            deact_outcome = f_deact.result(timeout=10)
            create_outcome = f_create.result(timeout=10)

        assert {deact_outcome, create_outcome} in (
            {"deactivated", "conflict"},
            {"conflict", "created"},
        )

        db_session.expire_all()
        fac_row = db_session.get(Facility, fac_id)
        assert fac_row is not None
        active_zones = int(
            db_session.scalar(
                select(func.count(Zone.id)).where(
                    Zone.facility_id == fac_id, Zone.is_active.is_(True)
                )
            )
            or 0
        )
        # Critical invariant: never an active child zone under an inactive facility
        assert not (fac_row.is_active is False and active_zones > 0)

    # 2. Race deactivate_zone vs register_meter
    for run_idx in range(4):
        fac_id = f"fac-zrace-{run_idx}"
        facility_service.create_facility(
            db_session,
            actor=admin,
            payload=FacilityCreate(**_facility_payload(facility_id=fac_id, code=f"ZR-{run_idx}")),  # type: ignore[arg-type]
        )
        created_zone = zone_service.create_zone(
            db_session,
            actor=admin,
            payload=ZoneCreate(**_zone_payload(fac_id, slug=f"zrace-{run_idx}")),  # type: ignore[arg-type]
        )
        zone_id = created_zone.id

        barrier = threading.Barrier(2)

        def _deactivate_zone(z_id: uuid.UUID = zone_id) -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                barrier.wait(timeout=5)
                try:
                    zone_service.deactivate_zone(s, actor=actor_row, zone_id=z_id)
                    return "deactivated"
                except ConflictError:
                    return "conflict"
            finally:
                s.close()

        def _register_child_meter(
            f_id: str = fac_id, z_id: uuid.UUID = zone_id, idx: int = run_idx
        ) -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                barrier.wait(timeout=5)
                try:
                    meter_service.register_meter(
                        s,
                        actor=actor_row,
                        payload=MeterCreate(
                            **_meter_payload(f_id, z_id, meter_code=f"MTR-ZR-{idx}")  # type: ignore[arg-type]
                        ),
                    )
                    return "created"
                except ConflictError:
                    return "conflict"
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_deact = pool.submit(_deactivate_zone)
            f_reg = pool.submit(_register_child_meter)
            deact_outcome = f_deact.result(timeout=10)
            reg_outcome = f_reg.result(timeout=10)

        assert {deact_outcome, reg_outcome} in (
            {"deactivated", "conflict"},
            {"conflict", "created"},
        )

        db_session.expire_all()
        zone_row = db_session.get(Zone, zone_id)
        assert zone_row is not None
        active_meters = int(
            db_session.scalar(
                select(func.count(Meter.id)).where(
                    Meter.zone_id == zone_id, Meter.is_active.is_(True)
                )
            )
            or 0
        )
        # Critical invariant: never an active meter under an inactive zone
        assert not (zone_row.is_active is False and active_meters > 0)
