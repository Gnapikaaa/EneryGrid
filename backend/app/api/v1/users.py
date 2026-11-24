import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import UserAdminUpdateRequest, UserResponse
from app.services.auth import (
    SelfModificationForbiddenError,
    UserNotFoundError,
    get_user_by_id,
    list_users,
    update_user_by_admin,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=list[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List all registered users (admin only)",
)
def get_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    users = list_users(db)
    return [UserResponse.model_validate(user) for user in users]


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch a single user by ID (admin only)",
)
def get_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a user's role or active status (admin only)",
)
def patch_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    try:
        updated = update_user_by_admin(
            db,
            target_user_id=user_id,
            actor=current_admin,
            payload=payload,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SelfModificationForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return UserResponse.model_validate(updated)
