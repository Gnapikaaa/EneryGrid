from collections.abc import Generator
from datetime import timedelta
import json
import base64
import uuid

from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy.orm import Session

from app.cli import create_admin as create_admin_cli
from app.core.config import Settings
from app.core.constants import UserRole
from app.core.database import get_db
from app.core.security import (
    MAX_PASSWORD_LENGTH,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.main import create_app
from app.models.user import User
from app.services.auth import create_initial_admin


def _build_test_client(test_settings: Settings, db_session: Session) -> TestClient:
    app = create_app(test_settings)

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _tamper_jwt_role(token: str, new_role: str) -> str:
    header_b64, payload_b64, sig_b64 = token.split(".")
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    payload["role"] = new_role
    tampered_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    tampered_b64 = base64.urlsafe_b64encode(tampered_bytes).rstrip(b"=").decode("ascii")
    return f"{header_b64}.{tampered_b64}.{sig_b64}"


def test_argon2id_password_hashing_and_length_bounds_without_truncation() -> None:
    long_pw_100 = "A" * 99 + "1"
    long_pw_100_diff = "A" * 99 + "2"

    hashed = hash_password(long_pw_100)
    assert hashed.startswith("$argon2id$")
    assert long_pw_100 not in hashed
    assert verify_password(long_pw_100, hashed) is True
    assert verify_password(long_pw_100_diff, hashed) is False

    for invalid in ("short", "       ", "x" * (MAX_PASSWORD_LENGTH + 1)):
        with pytest.raises(ValueError):
            hash_password(invalid)


def test_empty_jwt_secret_rejected(test_settings: Settings) -> None:
    empty_secret_settings = test_settings.model_copy(update={"jwt_secret_key": "   "})
    uid = uuid.uuid4()
    token, _ = create_access_token(
        user_id=uid,
        role=UserRole.VIEWER,
        settings=test_settings,
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        create_access_token(
            user_id=uid,
            role=UserRole.VIEWER,
            settings=empty_secret_settings,
        )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        decode_access_token(token, empty_secret_settings)


def test_register_creates_viewer_omits_password_hash_and_blocks_privileged_roles(
    test_settings: Settings, db_session: Session
) -> None:
    with _build_test_client(test_settings, db_session) as client:
        # Public registration must reject privileged roles or extra fields
        for forbidden_payload in (
            {
                "email": "attacker@energygrid.example",
                "full_name": "Malicious User",
                "password": "StrongPassword#123",
                "role": "admin",
            },
            {
                "email": "attacker2@energygrid.example",
                "full_name": "Malicious Manager",
                "password": "StrongPassword#123",
                "role": "facility_manager",
            },
            {
                "email": "attacker3@energygrid.example",
                "full_name": "Malicious Engineer",
                "password": "StrongPassword#123",
                "role": "utility_engineer",
            },
            {
                "email": "attacker4@energygrid.example",
                "full_name": "Malicious Status",
                "password": "StrongPassword#123",
                "is_active": False,
            },
        ):
            bad_resp = client.post("/api/v1/auth/register", json=forbidden_payload)
            assert bad_resp.status_code == 422

        # Valid registration assigns viewer by default and normalizes email
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "  Viewer.User@EnergyGrid.EXAMPLE ",
                "full_name": "  Priya Nair  ",
                "password": "StrongPassword#123",
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "viewer.user@energygrid.example"
    assert data["full_name"] == "Priya Nair"
    assert data["role"] == "viewer"
    assert data["is_active"] is True
    assert "password_hash" not in data
    assert "password" not in data

    persisted = db_session.query(User).filter_by(email="viewer.user@energygrid.example").one()
    assert persisted.password_hash.startswith("$argon2id$")
    assert persisted.password_hash != "StrongPassword#123"
    assert persisted.role == UserRole.VIEWER.value


def test_duplicate_email_registration_rejected(
    test_settings: Settings, db_session: Session
) -> None:
    with _build_test_client(test_settings, db_session) as client:
        first = client.post(
            "/api/v1/auth/register",
            json={
                "email": "operator@energygrid.example",
                "full_name": "First Operator",
                "password": "StrongPassword#123",
            },
        )
        assert first.status_code == 201

        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "email": "Operator@EnergyGrid.example",
                "full_name": "Second Operator",
                "password": "AnotherPassword#456",
            },
        )
        assert duplicate.status_code == 409


def test_login_success_wrong_password_and_me_endpoint(
    test_settings: Settings, db_session: Session
) -> None:
    with _build_test_client(test_settings, db_session) as client:
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "analyst@energygrid.example",
                "full_name": "Rohan Kulkarni",
                "password": "GridSecret#2026",
            },
        )
        assert reg.status_code == 201

        wrong_pw = client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@energygrid.example", "password": "WrongPassword!"},
        )
        assert wrong_pw.status_code == 401

        unknown_email = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@energygrid.example", "password": "GridSecret#2026"},
        )
        assert unknown_email.status_code == 401

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ANALYST@energygrid.example", "password": "GridSecret#2026"},
        )
        assert login_resp.status_code == 200
        token_body = login_resp.json()
        assert token_body["token_type"] == "bearer"
        assert token_body["expires_in"] == test_settings.access_token_expire_minutes * 60
        assert token_body["user"]["role"] == "viewer"
        assert "password_hash" not in token_body["user"]

        payload = decode_access_token(token_body["access_token"], test_settings)
        assert str(payload.user_id) == token_body["user"]["id"]
        assert payload.role == UserRole.VIEWER

        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_body['access_token']}"},
        )
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "analyst@energygrid.example"
        assert me_data["role"] == "viewer"
        assert "password_hash" not in me_data


def test_inactive_user_rejected_on_login_and_protected_endpoints(
    test_settings: Settings, db_session: Session
) -> None:
    with _build_test_client(test_settings, db_session) as client:
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "temp@energygrid.example",
                "full_name": "Temp User",
                "password": "ValidPassword#1",
            },
        )
        assert reg.status_code == 201

        login_ok = client.post(
            "/api/v1/auth/login",
            json={"email": "temp@energygrid.example", "password": "ValidPassword#1"},
        )
        assert login_ok.status_code == 200
        token = login_ok.json()["access_token"]

        # Deactivate user in DB
        user = db_session.query(User).filter_by(email="temp@energygrid.example").one()
        user.is_active = False
        db_session.commit()

        # Login must reject inactive account
        login_blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "temp@energygrid.example", "password": "ValidPassword#1"},
        )
        assert login_blocked.status_code == 403

        # Previously issued token must also be rejected on protected endpoints
        me_blocked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_blocked.status_code == 403


def test_invalid_tampered_wrong_secret_and_expired_tokens_rejected(
    test_settings: Settings, db_session: Session
) -> None:
    with _build_test_client(test_settings, db_session) as client:
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "security@energygrid.example",
                "full_name": "Security Check",
                "password": "ValidPassword#1",
            },
        )
        assert reg.status_code == 201
        user_id = reg.json()["id"]

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "security@energygrid.example", "password": "ValidPassword#1"},
        )
        valid_token = login_resp.json()["access_token"]

        # Unauthenticated requests rejected
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/users").status_code == 401
        assert (
            client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
        )
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
            ).status_code
            == 401
        )

        # Tampered role payload rejected by signature verification
        tampered_token = _tamper_jwt_role(valid_token, "admin")
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/users", headers={"Authorization": f"Bearer {tampered_token}"}
            ).status_code
            == 401
        )

        # Wrong secret rejected
        wrong_secret_settings = test_settings.model_copy(
            update={"jwt_secret_key": "completely-different-signing-key-more-than-32-chars"}
        )
        forged_token, _ = create_access_token(
            user_id=db_session.query(User).filter_by(email="security@energygrid.example").one().id,
            role=UserRole.ADMIN,
            settings=wrong_secret_settings,
        )
        assert (
            client.get(
                "/api/v1/users", headers={"Authorization": f"Bearer {forged_token}"}
            ).status_code
            == 401
        )

        # Expired token rejected
        expired_token, _ = create_access_token(
            user_id=db_session.query(User).filter_by(email="security@energygrid.example").one().id,
            role=UserRole.VIEWER,
            settings=test_settings,
            expires_delta=timedelta(minutes=-5),
        )
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
            ).status_code
            == 401
        )

        # Non-access token type rejected
        wrong_type_token = jwt.encode(
            {
                "sub": user_id,
                "role": "admin",
                "type": "refresh",
                "iat": 1700000000,
                "exp": 2000000000,
            },
            test_settings.jwt_secret_key,
            algorithm=test_settings.jwt_algorithm,
        )
        assert (
            client.get(
                "/api/v1/users", headers={"Authorization": f"Bearer {wrong_type_token}"}
            ).status_code
            == 401
        )


def test_role_based_authorization_authoritative_db_roles_and_self_protection(
    test_settings: Settings, db_session: Session
) -> None:
    admin = create_initial_admin(
        db_session,
        email="root.admin@energygrid.example",
        full_name="Root Admin",
        password="AdminSecretPassword#1",
    )

    with _build_test_client(test_settings, db_session) as client:
        # Create a regular viewer user
        viewer_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "viewer1@energygrid.example",
                "full_name": "Viewer One",
                "password": "ViewerPassword#1",
            },
        )
        assert viewer_reg.status_code == 201
        viewer_id = viewer_reg.json()["id"]

        viewer_token = client.post(
            "/api/v1/auth/login",
            json={"email": "viewer1@energygrid.example", "password": "ViewerPassword#1"},
        ).json()["access_token"]

        admin_token = client.post(
            "/api/v1/auth/login",
            json={"email": "root.admin@energygrid.example", "password": "AdminSecretPassword#1"},
        ).json()["access_token"]

        # Viewer forbidden from admin user-management endpoints
        assert (
            client.get("/api/v1/users", headers={"Authorization": f"Bearer {viewer_token}"}).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/users/{viewer_id}",
                headers={"Authorization": f"Bearer {viewer_token}"},
                json={"role": "admin"},
            ).status_code
            == 403
        )

        # Admin can list users without exposing password_hash
        list_resp = client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert list_resp.status_code == 200
        users_payload = list_resp.json()
        assert len(users_payload) == 2
        assert all("password_hash" not in item for item in users_payload)

        # Admin promotes viewer to utility_engineer
        promote_resp = client.patch(
            f"/api/v1/users/{viewer_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "utility_engineer"},
        )
        assert promote_resp.status_code == 200
        assert promote_resp.json()["role"] == "utility_engineer"

        # Utility engineer still cannot access admin-only /users endpoints
        assert (
            client.get("/api/v1/users", headers={"Authorization": f"Bearer {viewer_token}"}).status_code
            == 403
        )

        # Admin cannot remove their own admin role or deactivate themselves
        self_demote = client.patch(
            f"/api/v1/users/{admin.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "viewer"},
        )
        assert self_demote.status_code == 400

        self_deactivate = client.patch(
            f"/api/v1/users/{admin.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"is_active": False},
        )
        assert self_deactivate.status_code == 400

        # Authoritative DB role check: if admin is demoted in DB, existing admin token is immediately denied
        admin.role = UserRole.VIEWER.value
        db_session.commit()
        assert (
            client.get("/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"}).status_code
            == 403
        )


def test_initial_admin_cli_uses_getpass_no_password_flag_and_blocks_duplicates(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # --password CLI flag must not exist
    with pytest.raises(SystemExit) as exc_info:
        create_admin_cli.main(
            [
                "--email",
                "cli@energygrid.example",
                "--full-name",
                "CLI Admin",
                "--password",
                "ShouldNotWork",
            ]
        )
    assert exc_info.value.code != 0

    # Password mismatch fails cleanly
    mismatch_answers = iter(["FirstPass#123", "DifferentPass#123"])
    monkeypatch.setattr(create_admin_cli, "getpass", lambda _prompt="": next(mismatch_answers))
    mismatch_code = create_admin_cli.run_create_admin(
        db=db_session,
        email="cli.admin@energygrid.example",
        full_name="CLI Admin",
    )
    assert mismatch_code == 1
    captured_mismatch = capsys.readouterr()
    assert "do not match" in captured_mismatch.err

    # Successful interactive creation via getpass without leaking password to stdout/stderr
    secret_pw = "BootstrapAdmin#2026"
    valid_answers = iter([secret_pw, secret_pw])
    monkeypatch.setattr(create_admin_cli, "getpass", lambda _prompt="": next(valid_answers))
    ok_code = create_admin_cli.run_create_admin(
        db=db_session,
        email="CLI.Admin@EnergyGrid.example",
        full_name="CLI Admin",
    )
    assert ok_code == 0
    captured_ok = capsys.readouterr()
    assert "cli.admin@energygrid.example" in captured_ok.out
    assert secret_pw not in captured_ok.out
    assert secret_pw not in captured_ok.err

    created_admin = db_session.query(User).filter_by(email="cli.admin@energygrid.example").one()
    assert created_admin.role == UserRole.ADMIN.value
    assert created_admin.password_hash.startswith("$argon2id$")

    # Duplicate email rejected by bootstrap CLI
    dup_answers = iter([secret_pw, secret_pw])
    monkeypatch.setattr(create_admin_cli, "getpass", lambda _prompt="": next(dup_answers))
    dup_code = create_admin_cli.run_create_admin(
        db=db_session,
        email="cli.admin@energygrid.example",
        full_name="CLI Admin Duplicate",
    )
    assert dup_code == 1
    assert "already exists" in capsys.readouterr().err
