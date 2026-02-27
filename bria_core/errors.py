"""Custom exception types for bria_core."""


class BriaError(Exception):
    """Base exception for Bria core errors."""


class BriaConfigError(BriaError):
    """Configuration resolution failed or config invalid."""


class BriaAuthError(BriaError):
    """Authentication or API key errors."""


class BriaRequestError(BriaError):
    """HTTP request or API response errors."""
