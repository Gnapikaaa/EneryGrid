from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.constants import UserRole
from app.core.database import get_db
from app.core.security import TokenValidationError, decode_access_token
from app.models.user import User
from app.services.auth import get_user_by_id

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Could not validate credentials.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise _unauthorized("Authentication credentials were not provided.")

    try:
        token_payload = decode_access_token(credentials.credentials, settings)
    except (TokenValidationError, ValueError) as exc:
        raise _unauthorized("Invalid or expired authentication token.") from exc

    # Authoritative user lookup in PostgreSQL for current role and active status
    user = get_user_by_id(db, token_payload.user_id)
    if user is None:
        raise _unauthorized("Invalid authentication credentials.")

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    return user


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Dependency factory enforcing authoritative database role membership."""
    if not allowed_roles:
        raise ValueError("require_roles requires at least one allowed role.")
    allowed_set = frozenset(allowed_roles)

    def _role_guard(current_user: User = Depends(get_current_user)) -> User:
        try:
            current_role = UserRole(current_user.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            ) from exc

        if current_role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return current_user

    return _role_guard


require_admin = require_roles(UserRole.ADMIN)
require_meter_updater = require_roles(
    UserRole.ADMIN,
    UserRole.UTILITY_ENGINEER,
)
require_analytics_operator = require_meter_updater
require_facility_manager_or_admin = require_roles(
    UserRole.ADMIN,
    UserRole.FACILITY_MANAGER,
)
require_engineer_or_above = require_roles(
    UserRole.ADMIN,
    UserRole.FACILITY_MANAGER,
    UserRole.UTILITY_ENGINEER,
)

