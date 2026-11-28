class PermissionDeniedError(Exception):
    """Raised when an authenticated or inactive actor lacks permission for an operation."""


class ResourceNotFoundError(Exception):
    """Raised when a target facility, zone, or meter does not exist."""


class ConflictError(Exception):
    """Raised when an operation conflicts with uniqueness, state, or historical records."""


class InvalidRelationError(Exception):
    """Raised when a referenced parent/child relationship is structurally invalid."""


class ValidationFailureError(Exception):
    """Raised when domain or CSV payload validation fails against meter/physical rules."""


class PayloadTooLargeError(Exception):
    """Raised when a bulk or CSV upload exceeds configured byte or row caps."""
