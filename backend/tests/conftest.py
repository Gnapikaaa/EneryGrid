import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import Environment
from app.core.database import build_engine, build_session_factory

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _resolve_test_database_url() -> str:
    env_url = os.getenv("TEST_DATABASE_URL")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # avoid ALLOWED_ORIGINS parse error when .env uses CSV format
    resolved_url = env_url or settings.test_database_url
    if not resolved_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must be configured (via env or .env) to run PostgreSQL backend tests."
        )

    dev_parsed = make_url(settings.database_url)
    test_parsed = make_url(resolved_url)
    if (test_parsed.host, test_parsed.port, test_parsed.database) == (
        dev_parsed.host,
        dev_parsed.port,
        dev_parsed.database,
    ):
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a separate test database, not the development DATABASE_URL."
        )
    return resolved_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return _resolve_test_database_url()


@pytest.fixture(scope="session")
def test_settings(test_database_url: str) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=test_database_url,
        test_database_url=test_database_url,
        jwt_secret_key="test-only-signing-key-with-more-than-32-characters",
        allow_dev_auth_bypass=False,
        allowed_origins=["http://localhost:3000"],
        cors_allow_credentials=True,
    )


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Generator[Engine, None, None]:
    alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(alembic_cfg, "head")

    engine = build_engine(test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    session_factory = build_session_factory(db_engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(
            text(
                """
                TRUNCATE TABLE
                    meter_calibration_audits,
                    insight_workflow_logs,
                    energy_insights,
                    anomaly_workflow_logs,
                    anomalies,
                    telemetry_readings,
                    meters,
                    zones,
                    facilities,
                    users
                RESTART IDENTITY CASCADE
                """
            )
        )
        session.commit()
        session.close()
