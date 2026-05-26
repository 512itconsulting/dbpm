class DbpmError(Exception):
    """Base exception for user-facing dbpm errors."""


class ManifestError(DbpmError):
    """Raised when a package manifest is missing or invalid."""


class SourceError(DbpmError):
    """Raised when a package source cannot be read."""


class PolicyError(DbpmError):
    """Raised when environment policy blocks a requested action."""


class DependencyError(DbpmError):
    """Raised when package dependencies cannot be resolved."""


class ExecutionError(DbpmError):
    """Raised when a deployment command fails."""
