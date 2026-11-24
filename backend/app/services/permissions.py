from app.core.constants import UserRole
from app.models.user import User
from app.services.exceptions import PermissionDeniedError

ALL_AUTHENTICATED_ROLES: frozenset[UserRole] = frozenset(
    {
        UserRole.ADMIN,
        UserRole.FACILITY_MANAGER,
        UserRole.UTILITY_ENGINEER,
        UserRole.VIEWER,
    }
)
ADMIN_ONLY_ROLES: frozenset[UserRole] = frozenset({UserRole.ADMIN})
METER_UPDATE_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.ADMIN, UserRole.UTILITY_ENGINEER}
)
ANALYTICS_OPERATIONS_ROLES: frozenset[UserRole] = METER_UPDATE_ROLES


def assert_actor_authorized(
    actor: User | None,
    allowed_roles: frozenset[UserRole],
) -> User:
    """Enforce active-user status and authoritative role permissions in the service layer."""
    if actor is None or not actor.is_active:
        raise PermissionDeniedError("Inactive or unauthenticated user account.")

    try:
        role = UserRole(actor.role)
    except ValueError as exc:
        raise PermissionDeniedError("Insufficient permissions.") from exc

    if role not in allowed_roles:
        raise PermissionDeniedError("Insufficient permissions.")

    return actor
