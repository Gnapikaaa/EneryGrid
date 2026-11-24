from typing import Generic, TypeVar

from pydantic import BaseModel, Field

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response envelope with stable bounds and totals."""

    items: list[T]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=MAX_PAGE_SIZE)
    pages: int = Field(..., ge=0)
