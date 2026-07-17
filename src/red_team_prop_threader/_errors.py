"""user-safe error hierarchy for the prop-threader application."""

from __future__ import annotations


__all__ = ("ConfigurationError", "ConflictError", "ExternalServiceError", "ImportValidationError", "NotFoundError", "PropThreaderError", "ValidationError")


class PropThreaderError(Exception):
    """Base error for all prop-threader application errors."""


class ConfigurationError(PropThreaderError):
    """Raised when application configuration is missing or invalid."""


class ValidationError(PropThreaderError):
    """Raised when user-supplied input fails validation."""


class ImportValidationError(ValidationError):
    """Raised when an import batch contains one or more invalid records."""


class ExternalServiceError(PropThreaderError):
    """Raised when a call to an external service (Slack, ShotGrid) fails."""


class ConflictError(PropThreaderError):
    """Raised when an operation conflicts with existing data."""


class NotFoundError(PropThreaderError):
    """Raised when a requested resource does not exist."""
