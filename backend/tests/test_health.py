from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.main import create_app


def test_health_endpoint_reports_connected_database(
    test_settings: Settings, db_session: Session
) -> None:
    app = create_app(test_settings)

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["service"] == "EnergyGrid API"
    assert payload["service"] == test_settings.app_name
    assert payload["environment"] == "test"
    assert "timestamp" in payload


def test_health_endpoint_returns_503_when_database_unavailable(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)

    class _BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def _override_broken_db() -> Generator[object, None, None]:
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _override_broken_db  # type: ignore[assignment]
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "unavailable"
    assert "password" not in response.text.lower()
    assert "postgresql" not in response.text.lower()
