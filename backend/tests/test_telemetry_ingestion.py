from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import io
import threading
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    BaselineStatus,
    HealthStatus,
    QualityFlag,
    TelemetrySource,
    UserRole,
)
from app.core.database import build_session_factory, get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import Facility, Meter, TelemetryReading, User, Zone
from app.schemas.telemetry import (
    TelemetryBulkIngestRequest,
    TelemetryReadingCreate,
)
from app.services import meters as meter_service
from app.services import telemetry as telemetry_service
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
) -> tuple[User, str]:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password("TelemetryPass#2026"),
        role=role.value,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token, _ = create_access_token(user_id=user.id, role=role, settings=settings)
    return user, token


def _seed_facility_zone_meter(
    db: Session,
    *,
    facility_id: str = "fac-tel-01",
    facility_code: str = "TEL-01",
    zone_slug: str = "chiller-plant",
    meter_code: str = "MTR-TEL-01",
    rated_kw: Decimal = Decimal("400.00"),
    nominal_interval_seconds: int = 900,
    is_active: bool = True,
) -> tuple[Facility, Zone, Meter]:
    facility = db.get(Facility, facility_id)
    if facility is None:
        facility = Facility(
            id=facility_id,
            code=facility_code,
            name=f"Facility {facility_code}",
            location="Pune, India",
            timezone="Asia/Kolkata",
            currency_code="INR",
            contracted_demand_kw=Decimal("1500.00"),
            off_peak_tariff_rate=Decimal("6.0000"),
            mid_peak_tariff_rate=Decimal("8.5000"),
            peak_tariff_rate=Decimal("11.5000"),
            is_active=True,
        )
        db.add(facility)
        db.flush()

    zone = db.scalar(
        select(Zone).where(Zone.facility_id == facility_id, Zone.slug == zone_slug)
    )
    if zone is None:
        zone = Zone(
            facility_id=facility.id,
            slug=zone_slug,
            name=f"Zone {zone_slug}",
            primary_meter_code=meter_code,
            share_pct=Decimal("40.00"),
            status=HealthStatus.NOMINAL.value,
            is_active=True,
        )
        db.add(zone)
        db.flush()

    meter = Meter(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_code=meter_code,
        equipment_name=f"Equipment {meter_code}",
        rated_kw=rated_kw,
        nominal_interval_seconds=nominal_interval_seconds,
        current_kw=Decimal("150.00"),
        power_factor=Decimal("0.950"),
        thd_pct=Decimal("2.10"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 10, 1),
        is_active=is_active,
        deactivated_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC) if not is_active else None,
    )
    db.add(meter)
    db.commit()
    db.refresh(meter)
    return facility, zone, meter


def test_telemetry_rbac_and_unauthenticated_access(
    test_settings: Settings, db_session: Session
) -> None:
    _facility, _zone, meter = _seed_facility_zone_meter(db_session)
    _admin, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="tel.admin@energygrid.example",
        full_name="Telemetry Admin",
        role=UserRole.ADMIN,
    )
    manager, manager_token = _create_user_with_token(
        db_session,
        test_settings,
        email="tel.manager@energygrid.example",
        full_name="Telemetry Manager",
        role=UserRole.FACILITY_MANAGER,
    )
    _engineer, engineer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="tel.engineer@energygrid.example",
        full_name="Telemetry Engineer",
        role=UserRole.UTILITY_ENGINEER,
    )
    viewer, viewer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="tel.viewer@energygrid.example",
        full_name="Telemetry Viewer",
        role=UserRole.VIEWER,
    )

    reading_body = {
        "meter_id": str(meter.id),
        "recorded_at": "2026-11-10T09:15:00Z",
        "actual_kw": "200.00",
        "power_factor": "0.960",
    }
    csv_bytes = (
        b"meter_code,recorded_at,actual_kw,power_factor\n"
        b"MTR-TEL-01,2026-11-10T09:30:00Z,210.00,0.960\n"
    )

    with _build_test_client(test_settings, db_session) as client:
        # Unauthenticated -> 401
        assert client.get("/api/v1/telemetry/readings").status_code == 401
        assert client.post("/api/v1/telemetry/readings", json=reading_body).status_code == 401
        assert (
            client.post(
                "/api/v1/telemetry/readings/bulk",
                json={"readings": [reading_body]},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/telemetry/readings/upload",
                files={"file": ("readings.csv", csv_bytes, "text/csv")},
            ).status_code
            == 401
        )

        # facility_manager and viewer are read-only
        for ro_token in (manager_token, viewer_token):
            headers = {"Authorization": f"Bearer {ro_token}"}
            assert client.get("/api/v1/telemetry/readings", headers=headers).status_code == 200
            assert (
                client.post(
                    "/api/v1/telemetry/readings", headers=headers, json=reading_body
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/telemetry/readings/bulk",
                    headers=headers,
                    json={"readings": [reading_body]},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/api/v1/telemetry/readings/upload",
                    headers=headers,
                    files={"file": ("readings.csv", csv_bytes, "text/csv")},
                ).status_code
                == 403
            )

        # utility_engineer and admin have ingestion access
        eng_headers = {"Authorization": f"Bearer {engineer_token}"}
        assert (
            client.post(
                "/api/v1/telemetry/readings", headers=eng_headers, json=reading_body
            ).status_code
            == 201
        )

        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        bulk_resp = client.post(
            "/api/v1/telemetry/readings/bulk",
            headers=admin_headers,
            json={
                "readings": [
                    {
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-10T09:45:00Z",
                        "actual_kw": "220.00",
                        "power_factor": "0.955",
                    }
                ]
            },
        )
        assert bulk_resp.status_code == 200
        assert bulk_resp.json()["inserted_count"] == 1

    # Direct service-layer RBAC check
    payload_obj = TelemetryReadingCreate(**reading_body)  # type: ignore[arg-type]
    bulk_obj = TelemetryBulkIngestRequest(readings=[reading_body])
    for ro_actor in (manager, viewer):
        with pytest.raises(PermissionDeniedError):
            telemetry_service.ingest_reading(
                db_session, actor=ro_actor, payload=payload_obj, settings=test_settings
            )
        with pytest.raises(PermissionDeniedError):
            telemetry_service.ingest_bulk_readings(
                db_session, actor=ro_actor, payload=bulk_obj, settings=test_settings
            )
        with pytest.raises(PermissionDeniedError):
            telemetry_service.ingest_csv_bytes(
                db_session,
                actor=ro_actor,
                csv_stream=io.BytesIO(csv_bytes),
                settings=test_settings,
            )


def test_single_ingestion_validation_energy_tolerance_overload_and_meter_unchanged(
    test_settings: Settings, db_session: Session
) -> None:
    facility, zone, active_meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-single-01",
        facility_code="SNG-01",
        meter_code="MTR-SNG-01",
        rated_kw=Decimal("400.00"),
    )
    _f2, zone2, other_meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-single-02",
        facility_code="SNG-02",
        zone_slug="lighting",
        meter_code="MTR-SNG-02",
    )
    _, _, inactive_meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-single-01",
        facility_code="SNG-01",
        zone_slug="chiller-plant",
        meter_code="MTR-SNG-INACTIVE",
        is_active=False,
    )
    _, engineer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="single.eng@energygrid.example",
        full_name="Single Engineer",
        role=UserRole.UTILITY_ENGINEER,
    )
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # Custom settings proving 3x overload factor is configurable, not hardcoded
    strict_settings = test_settings.model_copy(
        update={"telemetry_max_overload_factor": Decimal("1.5")}
    )

    with _build_test_client(strict_settings, db_session) as client:
        # 1. Valid reading with omitted energy_kwh (calculated = 200 * 900 / 3600 = 50.0000)
        #    and offset timestamp (+05:30 IST -> 03:45:00Z = 09:15 IST -> Peak)
        r1 = client.post(
            "/api/v1/telemetry/readings",
            headers=headers,
            json={
                "meter_code": active_meter.meter_code,
                "recorded_at": "2026-11-10T09:15:00+05:30",
                "actual_kw": "200.00",
                "power_factor": "0.960",
            },
        )
        assert r1.status_code == 201
        body1 = r1.json()
        assert body1["energy_kwh"] == "50.0000"
        assert body1["recorded_at"] == "2026-11-10T03:45:00Z"
        assert body1["interval_start"] == "2026-11-10T03:30:00Z"
        assert body1["interval_seconds"] == 900
        assert body1["tariff_period"] == "Peak"
        assert body1["baseline_status"] == BaselineStatus.INSUFFICIENT_HISTORY.value
        assert body1["baseline_kw"] is None
        assert body1["std_dev_kw"] is None
        assert body1["z_score"] is None

        # Verify meters.current_kw and meters.status were NOT modified by ingestion
        db_session.expire_all()
        reloaded_meter = db_session.get(Meter, active_meter.id)
        assert reloaded_meter is not None
        assert reloaded_meter.current_kw == Decimal("150.00")
        assert reloaded_meter.status == HealthStatus.NOMINAL.value

        # 2. Explicitly supplied energy_kwh within tolerance (51.2500 vs expected 50.0000)
        #    is preserved verbatim without overwriting
        r2 = client.post(
            "/api/v1/telemetry/readings",
            headers=headers,
            json={
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:00:00Z",
                "actual_kw": "200.00",
                "energy_kwh": "51.2500",
                "power_factor": "0.960",
            },
        )
        assert r2.status_code == 201
        assert r2.json()["energy_kwh"] == "51.2500"

        # 3. Supplied energy_kwh outside tolerance (65.0000 vs expected 50.0000) -> 422
        r_bad_energy = client.post(
            "/api/v1/telemetry/readings",
            headers=headers,
            json={
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00Z",
                "actual_kw": "200.00",
                "energy_kwh": "65.0000",
                "power_factor": "0.960",
            },
        )
        assert r_bad_energy.status_code == 422

        # 4. Configurable overload limit (1.5x * 400 = 600 kW; 650 kW rejected) -> 422
        r_overload = client.post(
            "/api/v1/telemetry/readings",
            headers=headers,
            json={
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00Z",
                "actual_kw": "650.00",
                "power_factor": "0.960",
            },
        )
        assert r_overload.status_code == 422

        # 5. Duplicate timestamp -> 409; overlapping interval -> 409
        assert (
            client.post(
                "/api/v1/telemetry/readings",
                headers=headers,
                json={
                    "meter_id": str(active_meter.id),
                    "recorded_at": "2026-11-10T04:00:00Z",
                    "actual_kw": "200.00",
                    "power_factor": "0.960",
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/telemetry/readings",
                headers=headers,
                json={
                    "meter_id": str(active_meter.id),
                    "recorded_at": "2026-11-10T03:55:00Z",
                    "actual_kw": "200.00",
                    "power_factor": "0.960",
                },
            ).status_code
            == 409
        )

        # 6. Inactive meter -> 409; unknown meter -> 404; facility/zone mismatch -> 400
        assert (
            client.post(
                "/api/v1/telemetry/readings",
                headers=headers,
                json={
                    "meter_id": str(inactive_meter.id),
                    "recorded_at": "2026-11-10T04:15:00Z",
                    "actual_kw": "100.00",
                    "power_factor": "0.960",
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/telemetry/readings",
                headers=headers,
                json={
                    "meter_id": str(uuid.uuid4()),
                    "recorded_at": "2026-11-10T04:15:00Z",
                    "actual_kw": "100.00",
                    "power_factor": "0.960",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/telemetry/readings",
                headers=headers,
                json={
                    "meter_id": str(active_meter.id),
                    "facility_id": facility.id,
                    "zone_id": str(zone2.id),  # belongs to fac-single-02, not active_meter
                    "recorded_at": "2026-11-10T04:15:00Z",
                    "actual_kw": "100.00",
                    "power_factor": "0.960",
                },
            ).status_code
            == 400
        )

        # 7. Naive timestamp, future timestamp, negative kW, bad power factor,
        #    mismatched interval_start -> 422
        for bad_payload in (
            {
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00",  # naive
                "actual_kw": "100.00",
                "power_factor": "0.950",
            },
            {
                "meter_id": str(active_meter.id),
                "recorded_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "actual_kw": "100.00",
                "power_factor": "0.950",
            },
            {
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00Z",
                "actual_kw": "-10.00",
                "power_factor": "0.950",
            },
            {
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00Z",
                "actual_kw": "100.00",
                "power_factor": "1.050",
            },
            {
                "meter_id": str(active_meter.id),
                "recorded_at": "2026-11-10T04:15:00Z",
                "interval_start": "2026-11-10T04:05:00Z",
                "interval_seconds": 900,
                "actual_kw": "100.00",
                "power_factor": "0.950",
            },
        ):
            assert (
                client.post(
                    "/api/v1/telemetry/readings",
                    headers=headers,
                    json=bad_payload,
                ).status_code
                == 422
            )

        # 8. Gap-bounded reading up to 7200s allowed when quality_flag='gap_bounded'
        gap_resp = client.post(
            "/api/v1/telemetry/readings",
            headers=headers,
            json={
                "meter_id": str(other_meter.id),
                "recorded_at": "2026-11-10T06:00:00Z",
                "interval_seconds": 3600,
                "actual_kw": "120.00",
                "power_factor": "0.940",
                "quality_flag": "gap_bounded",
            },
        )
        assert gap_resp.status_code == 201
        assert gap_resp.json()["energy_kwh"] == "120.0000"
        assert gap_resp.json()["interval_start"] == "2026-11-10T05:00:00Z"


def test_bulk_ingestion_partial_success_vs_atomic_rollback(
    test_settings: Settings, db_session: Session
) -> None:
    _f, _z, meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-bulk-01",
        facility_code="BLK-01",
        meter_code="MTR-BLK-01",
    )
    _, admin_token = _create_user_with_token(
        db_session,
        test_settings,
        email="bulk.admin@energygrid.example",
        full_name="Bulk Admin",
        role=UserRole.ADMIN,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    with _build_test_client(test_settings, db_session) as client:
        # 1. Default atomic=false (partial success) keeps valid rows and isolates duplicates,
        #    overlaps, invalid measurements, and unknown meters
        partial_resp = client.post(
            "/api/v1/telemetry/readings/bulk",
            headers=headers,
            json={
                "readings": [
                    {
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:15:00Z",
                        "actual_kw": "180.00",
                        "power_factor": "0.950",
                    },
                    {
                        # Intra-batch duplicate of item 0
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:15:00Z",
                        "actual_kw": "185.00",
                        "power_factor": "0.950",
                    },
                    {
                        # Overlapping [01:10, 01:25) with item 0 [01:00, 01:15)
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:25:00Z",
                        "actual_kw": "190.00",
                        "power_factor": "0.950",
                    },
                    {
                        # Invalid negative kW
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:30:00Z",
                        "actual_kw": "-5.00",
                        "power_factor": "0.950",
                    },
                    {
                        # Valid contiguous interval [01:15, 01:30)
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:30:00Z",
                        "actual_kw": "200.00",
                        "energy_kwh": "50.5000",
                        "power_factor": "0.960",
                    },
                    {
                        # Unknown meter
                        "meter_code": "MTR-DOES-NOT-EXIST",
                        "recorded_at": "2026-11-11T01:45:00Z",
                        "actual_kw": "100.00",
                        "power_factor": "0.950",
                    },
                ]
            },
        )
        assert partial_resp.status_code == 200
        summary = partial_resp.json()
        assert summary["atomic"] is False
        assert summary["total_received"] == 6
        assert summary["inserted_count"] == 2
        assert summary["duplicate_count"] == 1
        assert summary["overlap_count"] == 1
        assert summary["failed_count"] == 2
        assert len(summary["inserted_ids"]) == 2
        assert [err["row_index"] for err in summary["errors"]] == [1, 2, 3, 5]
        assert [err["code"] for err in summary["errors"]] == [
            "duplicate_reading",
            "overlapping_interval",
            "validation_error",
            "not_found",
        ]

        assert (
            db_session.scalar(
                select(func.count(TelemetryReading.id)).where(
                    TelemetryReading.meter_id == meter.id
                )
            )
            == 2
        )

        # 2. atomic=true rolls back ALL rows in batch if any row fails
        atomic_fail_resp = client.post(
            "/api/v1/telemetry/readings/bulk",
            headers=headers,
            json={
                "atomic": True,
                "readings": [
                    {
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T02:00:00Z",
                        "actual_kw": "210.00",
                        "power_factor": "0.950",
                    },
                    {
                        # Duplicate against earlier persisted row 01:30Z
                        "meter_code": meter.meter_code,
                        "recorded_at": "2026-11-11T01:30:00Z",
                        "actual_kw": "200.00",
                        "power_factor": "0.950",
                    },
                ],
            },
        )
        assert atomic_fail_resp.status_code == 409

        # Confirm 02:00Z row was rolled back too
        db_session.expire_all()
        assert (
            db_session.scalar(
                select(func.count(TelemetryReading.id)).where(
                    TelemetryReading.meter_id == meter.id
                )
            )
            == 2
        )

        # 3. Bulk max limit check
        small_bulk_settings = test_settings.model_copy(
            update={"telemetry_max_bulk_items": 2}
        )
        with _build_test_client(small_bulk_settings, db_session) as capped_client:
            too_many = capped_client.post(
                "/api/v1/telemetry/readings/bulk",
                headers=headers,
                json={
                    "readings": [
                        {
                            "meter_code": meter.meter_code,
                            "recorded_at": f"2026-11-11T0{h}:00:00Z",
                            "actual_kw": "100.00",
                            "power_factor": "0.950",
                        }
                        for h in (3, 4, 5)
                    ]
                },
            )
            assert too_many.status_code == 413


def test_csv_upload_partial_atomic_malformed_and_size_row_limits(
    test_settings: Settings, db_session: Session
) -> None:
    _f, _z, meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-csv-01",
        facility_code="CSV-01",
        meter_code="MTR-CSV-01",
    )
    _, engineer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="csv.eng@energygrid.example",
        full_name="CSV Engineer",
        role=UserRole.UTILITY_ENGINEER,
    )
    headers = {"Authorization": f"Bearer {engineer_token}"}

    # Includes UTF-8 BOM, valid rows, explicit energy_kwh within tolerance, bad timestamp, duplicate
    mixed_csv = (
        "\ufeffmeter_code,recorded_at,actual_kw,energy_kwh,power_factor,ambient_temp_c\n"
        "MTR-CSV-01,2026-11-12T08:15:00Z,200.00,50.7500,0.960,24.50\n"
        "MTR-CSV-01,not-a-timestamp,200.00,,0.960,24.50\n"
        "MTR-CSV-01,2026-11-12T08:15:00Z,205.00,,0.960,24.50\n"
        "MTR-CSV-01,2026-11-12T08:30:00Z,240.00,,0.955,25.00\n"
    ).encode("utf-8")

    with _build_test_client(test_settings, db_session) as client:
        # 1. Partial CSV import succeeds on valid rows and reports 1-based line numbers
        resp = client.post(
            "/api/v1/telemetry/readings/upload",
            headers=headers,
            files={"file": ("telemetry.csv", mixed_csv, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["atomic"] is False
        assert body["total_received"] == 4
        assert body["inserted_count"] == 2
        assert body["duplicate_count"] == 1
        assert body["failed_count"] == 1
        assert [err["row_number"] for err in body["errors"]] == [3, 4]

        stored = list(
            db_session.scalars(
                select(TelemetryReading)
                .where(TelemetryReading.meter_id == meter.id)
                .order_by(TelemetryReading.recorded_at.asc())
            ).all()
        )
        assert len(stored) == 2
        assert stored[0].energy_kwh == Decimal("50.7500")
        assert stored[0].source == TelemetrySource.CSV_IMPORT.value
        assert stored[1].energy_kwh == Decimal("60.0000")

        # 2. Atomic CSV import rolls back valid rows if a subsequent row fails
        atomic_csv = (
            b"meter_code,recorded_at,actual_kw,power_factor\n"
            b"MTR-CSV-01,2026-11-12T09:00:00Z,160.00,0.950\n"
            b"MTR-CSV-01,2026-11-12T09:15:00Z,99999.00,0.950\n"
        )
        atomic_resp = client.post(
            "/api/v1/telemetry/readings/upload?atomic=true",
            headers=headers,
            files={"file": ("atomic.csv", atomic_csv, "text/csv")},
        )
        assert atomic_resp.status_code == 422
        assert (
            db_session.scalar(
                select(func.count(TelemetryReading.id)).where(
                    TelemetryReading.meter_id == meter.id
                )
            )
            == 2
        )

        # 3. Missing required header or empty file -> 422
        assert (
            client.post(
                "/api/v1/telemetry/readings/upload",
                headers=headers,
                files={"file": ("bad_headers.csv", b"meter_code,recorded_at\n", "text/csv")},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/telemetry/readings/upload",
                headers=headers,
                files={"file": ("empty.csv", b"", "text/csv")},
            ).status_code
            == 422
        )

    # 4. Enforce streaming byte limit and row limit cleanly without persisting partial rows
    capped_settings = test_settings.model_copy(
        update={
            "telemetry_max_csv_upload_bytes": 1024,
            "telemetry_max_csv_upload_rows": 3,
        }
    )
    with _build_test_client(capped_settings, db_session) as capped_client:
        # Exceeds 3-row limit while still under 1024 bytes
        four_row_csv = (
            b"meter_code,recorded_at,actual_kw,power_factor\n"
            b"MTR-CSV-01,2026-11-12T10:00:00Z,150.00,0.950\n"
            b"MTR-CSV-01,2026-11-12T10:15:00Z,150.00,0.950\n"
            b"MTR-CSV-01,2026-11-12T10:30:00Z,150.00,0.950\n"
            b"MTR-CSV-01,2026-11-12T10:45:00Z,150.00,0.950\n"
        )
        assert len(four_row_csv) < 1024
        row_cap_resp = capped_client.post(
            "/api/v1/telemetry/readings/upload",
            headers=headers,
            files={"file": ("too_many_rows.csv", four_row_csv, "text/csv")},
        )
        assert row_cap_resp.status_code == 413

        # Exceeds 1024-byte limit
        oversized_csv = b"meter_code,recorded_at,actual_kw,power_factor\n" + (
            b"MTR-CSV-01,2026-11-12T11:00:00Z,150.00,0.950\n" * 30
        )
        assert len(oversized_csv) > 1024
        byte_cap_resp = capped_client.post(
            "/api/v1/telemetry/readings/upload",
            headers=headers,
            files={"file": ("too_big.csv", oversized_csv, "text/csv")},
        )
        assert byte_cap_resp.status_code == 413

        # Still only the 2 original rows exist
        assert (
            db_session.scalar(
                select(func.count(TelemetryReading.id)).where(
                    TelemetryReading.meter_id == meter.id
                )
            )
            == 2
        )


def test_query_telemetry_readings_filters_and_pagination(
    test_settings: Settings, db_session: Session
) -> None:
    fac1, zone1, m1 = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-qry-01",
        facility_code="QRY-01",
        zone_slug="z1",
        meter_code="MTR-QRY-01",
    )
    fac2, zone2, m2 = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-qry-02",
        facility_code="QRY-02",
        zone_slug="z2",
        meter_code="MTR-QRY-02",
    )
    admin, _ = _create_user_with_token(
        db_session,
        test_settings,
        email="qry.admin@energygrid.example",
        full_name="Query Admin",
        role=UserRole.ADMIN,
    )
    _, viewer_token = _create_user_with_token(
        db_session,
        test_settings,
        email="qry.viewer@energygrid.example",
        full_name="Query Viewer",
        role=UserRole.VIEWER,
    )

    for ts, m, qf, src in (
        ("2026-11-13T08:00:00Z", m1, QualityFlag.VALID, TelemetrySource.METER_FEED),
        ("2026-11-13T08:15:00Z", m1, QualityFlag.GAP_BOUNDED, TelemetrySource.CSV_IMPORT),
        ("2026-11-13T08:30:00Z", m1, QualityFlag.VALID, TelemetrySource.METER_FEED),
        ("2026-11-13T08:45:00Z", m2, QualityFlag.VALID, TelemetrySource.SIMULATION),
    ):
        telemetry_service.ingest_reading(
            db_session,
            actor=admin,
            payload=TelemetryReadingCreate(
                meter_id=m.id,
                recorded_at=datetime.fromisoformat(ts),
                actual_kw=Decimal("180.00"),
                power_factor=Decimal("0.950"),
                quality_flag=qf,
                source=src,
            ),
            settings=test_settings,
        )

    headers = {"Authorization": f"Bearer {viewer_token}"}
    with _build_test_client(test_settings, db_session) as client:
        # Filter by facility, zone, meter, date range, quality_flag, source
        by_fac = client.get(
            f"/api/v1/telemetry/readings?facility_id={fac1.id}&page=1&page_size=2",
            headers=headers,
        )
        assert by_fac.status_code == 200
        body = by_fac.json()
        assert body["total"] == 3
        assert body["pages"] == 2
        # Ordered newest first
        assert [item["recorded_at"] for item in body["items"]] == [
            "2026-11-13T08:30:00Z",
            "2026-11-13T08:15:00Z",
        ]

        by_zone_range = client.get(
            f"/api/v1/telemetry/readings?zone_id={zone1.id}&start_at=2026-11-13T08:10:00Z&end_at=2026-11-13T08:20:00Z",
            headers=headers,
        )
        assert by_zone_range.status_code == 200
        assert by_zone_range.json()["total"] == 1
        assert by_zone_range.json()["items"][0]["quality_flag"] == "gap_bounded"

        by_meter_src = client.get(
            f"/api/v1/telemetry/readings?meter_id={m2.id}&source=simulation",
            headers=headers,
        )
        assert by_meter_src.status_code == 200
        assert by_meter_src.json()["total"] == 1
        assert by_meter_src.json()["items"][0]["facility_id"] == fac2.id
        assert by_meter_src.json()["items"][0]["zone_id"] == str(zone2.id)

        # Invalid date range rejected
        bad_range = client.get(
            "/api/v1/telemetry/readings?start_at=2026-11-14T00:00:00Z&end_at=2026-11-13T00:00:00Z",
            headers=headers,
        )
        assert bad_range.status_code == 422


def test_concurrent_telemetry_ingestion_and_meter_deactivation(
    test_settings: Settings, db_session: Session, db_engine: Engine
) -> None:
    admin, _ = _create_user_with_token(
        db_session,
        test_settings,
        email="race.admin@energygrid.example",
        full_name="Race Admin",
        role=UserRole.ADMIN,
    )
    admin_id = admin.id
    session_factory = build_session_factory(db_engine)

    # 1. Concurrent identical timestamp ingestion -> exactly 1 succeeds, 1 raises ConflictError
    _, _, dup_meter = _seed_facility_zone_meter(
        db_session,
        facility_id="fac-tel-race",
        facility_code="TRC-01",
        meter_code="MTR-TRC-DUP",
    )
    dup_meter_id = dup_meter.id
    barrier_dup = threading.Barrier(2)

    def _ingest_same_ts() -> str:
        s = session_factory()
        try:
            actor_row = s.get(User, admin_id)
            assert actor_row is not None
            payload = TelemetryReadingCreate(
                meter_id=dup_meter_id,
                recorded_at=datetime(2026, 11, 15, 10, 15, tzinfo=UTC),
                actual_kw=Decimal("200.00"),
                power_factor=Decimal("0.950"),
            )
            barrier_dup.wait(timeout=5)
            try:
                telemetry_service.ingest_reading(
                    s, actor=actor_row, payload=payload, settings=test_settings
                )
                return "inserted"
            except ConflictError:
                return "conflict"
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_ingest_same_ts)
        f2 = pool.submit(_ingest_same_ts)
        outcomes = sorted([f1.result(timeout=10), f2.result(timeout=10)])

    assert outcomes == ["conflict", "inserted"]
    assert (
        db_session.scalar(
            select(func.count(TelemetryReading.id)).where(
                TelemetryReading.meter_id == dup_meter_id
            )
        )
        == 1
    )

    # 2. Concurrent deactivate_meter vs ingest_reading serializes cleanly via FOR SHARE vs FOR UPDATE
    for idx in range(4):
        _, _, race_meter = _seed_facility_zone_meter(
            db_session,
            facility_id="fac-tel-race",
            facility_code="TRC-01",
            zone_slug="chiller-plant",
            meter_code=f"MTR-DEACT-RACE-{idx}",
        )
        race_meter_id = race_meter.id
        barrier_deact = threading.Barrier(2)

        def _deactivate(m_id: uuid.UUID = race_meter_id) -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                barrier_deact.wait(timeout=5)
                meter_service.deactivate_meter(s, actor=actor_row, meter_id=m_id)
                return "deactivated"
            finally:
                s.close()

        def _ingest(m_id: uuid.UUID = race_meter_id) -> str:
            s = session_factory()
            try:
                actor_row = s.get(User, admin_id)
                assert actor_row is not None
                payload = TelemetryReadingCreate(
                    meter_id=m_id,
                    recorded_at=datetime(2026, 11, 15, 11, 15, tzinfo=UTC),
                    actual_kw=Decimal("180.00"),
                    power_factor=Decimal("0.950"),
                )
                barrier_deact.wait(timeout=5)
                try:
                    telemetry_service.ingest_reading(
                        s, actor=actor_row, payload=payload, settings=test_settings
                    )
                    return "inserted"
                except ConflictError:
                    return "conflict"
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_d = pool.submit(_deactivate)
            f_i = pool.submit(_ingest)
            deact_res = f_d.result(timeout=10)
            ingest_res = f_i.result(timeout=10)

        assert deact_res == "deactivated"
        assert ingest_res in ("inserted", "conflict")

        db_session.expire_all()
        final_meter = db_session.get(Meter, race_meter_id)
        assert final_meter is not None
        assert final_meter.is_active is False

        # Subsequent ingestion after deactivation MUST always fail with ConflictError
        with pytest.raises(ConflictError):
            telemetry_service.ingest_reading(
                db_session,
                actor=admin,
                payload=TelemetryReadingCreate(
                    meter_id=race_meter_id,
                    recorded_at=datetime(2026, 11, 15, 11, 30, tzinfo=UTC),
                    actual_kw=Decimal("180.00"),
                    power_factor=Decimal("0.950"),
                ),
                settings=test_settings,
            )
