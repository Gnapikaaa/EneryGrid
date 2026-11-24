from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import jwt
from jwt import InvalidTokenError as PyJWTError

from app.core.config import Settings
from app.core.constants import UserRole

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Used to equalize timing when authenticating unknown email addresses
_DUMMY_PASSWORD_HASH: str | None = None


class TokenValidationError(Exception):
    """Raised when a JWT access token is missing, malformed, expired, or invalid."""


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    role: UserRole
    issued_at: datetime
    expires_at: datetime
    token_id: str


def validate_password_policy(plain_password: str) -> str:
    """Validate password bounds without silently truncating or altering characters."""
    if not isinstance(plain_password, str) or not plain_password.strip():
        raise ValueError("Password cannot be blank.")
    if len(plain_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(plain_password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_LENGTH} characters.")
    return plain_password


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    validated = validate_password_policy(plain_password)
    return _password_hasher.hash(validated)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored Argon2id hash without truncation."""
    if (
        not isinstance(plain_password, str)
        or not plain_password
        or len(plain_password) > MAX_PASSWORD_LENGTH
        or not password_hash
    ):
        return False
    try:
        return bool(_password_hasher.verify(password_hash, plain_password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy_password(plain_password: str) -> None:
    """Execute a constant-cost Argon2id verification to mitigate user-enumeration timing."""
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = _password_hasher.hash("energygrid-timing-normalization-dummy")
    verify_password(plain_password, _DUMMY_PASSWORD_HASH)


def _require_signing_secret(settings: Settings) -> str:
    secret = settings.jwt_secret_key.strip()
    if not secret:
        raise ValueError("JWT_SECRET_KEY must be configured before signing or verifying tokens.")
    return secret


def create_access_token(
    *,
    user_id: uuid.UUID,
    role: UserRole | str,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Create a signed JWT access token embedding user ID, role, and explicit expiration."""
    secret = _require_signing_secret(settings)
    normalized_role = UserRole(role)
    now = datetime.now(UTC)
    delta = expires_delta if expires_delta is not None else timedelta(
        minutes=settings.access_token_expire_minutes
    )
    expires_at = now + delta

    claims = {
        "sub": str(user_id),
        "role": normalized_role.value,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, secret, algorithm=settings.jwt_algorithm)
    expires_in_seconds = max(0, int(delta.total_seconds()))
    return token, expires_in_seconds


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    """Verify JWT signature and expiration, returning validated claims."""
    if not token or not token.strip():
        raise TokenValidationError("Authentication token is required.")

    secret = _require_signing_secret(settings)
    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "role", "exp", "iat", "type"]},
        )
    except PyJWTError as exc:
        raise TokenValidationError("Invalid or expired authentication token.") from exc

    if decoded.get("type") != "access":
        raise TokenValidationError("Invalid token type.")

    try:
        user_id = uuid.UUID(str(decoded["sub"]))
        role = UserRole(str(decoded["role"]))
        issued_at = datetime.fromtimestamp(int(decoded["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(int(decoded["exp"]), tz=UTC)
        token_id = str(decoded.get("jti", ""))
    except (ValueError, TypeError, KeyError) as exc:
        raise TokenValidationError("Malformed authentication token claims.") from exc

    return TokenPayload(
        user_id=user_id,
        role=role,
        issued_at=issued_at,
        expires_at=expires_at,
        token_id=token_id,
    )
