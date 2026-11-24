import uuid

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import UserRole
from app.core.security import hash_password, verify_dummy_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest, UserAdminUpdateRequest

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class DuplicateEmailError(Exception):
    """Raised when attempting to register or bootstrap an already-existing email."""


class InvalidCredentialsError(Exception):
    """Raised when email or password authentication fails."""


class InactiveUserError(Exception):
    """Raised when an inactive user attempts to authenticate."""


class UserNotFoundError(Exception):
    """Raised when a target user does not exist."""


class SelfModificationForbiddenError(Exception):
    """Raised when an administrator attempts to demote or deactivate themselves."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized = normalize_email(email)
    return db.scalar(select(User).where(func.lower(User.email) == normalized))


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def register_viewer_user(db: Session, payload: RegisterRequest) -> User:
    normalized_email = normalize_email(str(payload.email))
    if get_user_by_email(db, normalized_email) is not None:
        raise DuplicateEmailError("An account with this email address already exists.")

    user = User(
        email=normalized_email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateEmailError("An account with this email address already exists.") from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if user is None:
        verify_dummy_password(password)
        raise InvalidCredentialsError("Invalid email or password.")

    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid email or password.")

    if not user.is_active:
        raise InactiveUserError("This account is inactive.")

    return user


def create_initial_admin(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
) -> User:
    validated_email = normalize_email(str(_EMAIL_ADAPTER.validate_python(email)))
    cleaned_name = full_name.strip()
    if not cleaned_name or len(cleaned_name) > 120:
        raise ValueError("Full name must be between 1 and 120 non-whitespace characters.")

    if get_user_by_email(db, validated_email) is not None:
        raise DuplicateEmailError(f"A user with email '{validated_email}' already exists.")

    admin = User(
        email=validated_email,
        full_name=cleaned_name,
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateEmailError(f"A user with email '{validated_email}' already exists.") from exc
    db.refresh(admin)
    return admin


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.asc(), User.email.asc())).all())


def update_user_by_admin(
    db: Session,
    *,
    target_user_id: uuid.UUID,
    actor: User,
    payload: UserAdminUpdateRequest,
) -> User:
    target = get_user_by_id(db, target_user_id)
    if target is None:
        raise UserNotFoundError("User not found.")

    if target.id == actor.id:
        if payload.role is not None and payload.role != UserRole.ADMIN:
            raise SelfModificationForbiddenError(
                "Administrators cannot remove their own admin role."
            )
        if payload.is_active is not None and payload.is_active is False:
            raise SelfModificationForbiddenError(
                "Administrators cannot deactivate their own account."
            )

    if payload.role is not None:
        target.role = payload.role.value
    if payload.is_active is not None:
        target.is_active = payload.is_active

    db.commit()
    db.refresh(target)
    return target
