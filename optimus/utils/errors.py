"""
utils/errors.py — partial port of src/utils/errors.ts

Error classes and errno helpers used across the config + tool layers. Only the
exports needed so far are ported; the rest of errors.ts plugs in here later.
"""
from __future__ import annotations

from typing import Any, Optional


class ClaudeError(Exception):
    """Mirrors ClaudeError — base class for known/expected Claude Code errors."""


class MalformedCommandError(Exception):
    """Mirrors MalformedCommandError."""


class AbortError(Exception):
    """Mirrors AbortError — raised when an operation is aborted by the user."""


def is_abort_error(e: Any) -> bool:
    """Mirrors isAbortError() — True for AbortError or DOMException 'AbortError'."""
    if isinstance(e, AbortError):
        return True
    # asyncio.CancelledError is the Python analogue of an aborted async op.
    import asyncio

    if isinstance(e, asyncio.CancelledError):
        return True
    return getattr(e, "name", None) == "AbortError"


class ConfigParseError(Exception):
    """
    Mirrors ConfigParseError. Carries the offending file path and the default
    config to fall back to, so callers can surface a clear message.
    """

    def __init__(self, message: str, file_path: str, default_config: Any) -> None:
        super().__init__(message)
        self.name = "ConfigParseError"
        self.message = message
        self.file_path = file_path
        self.default_config = default_config


def get_errno_code(e: Any) -> Optional[str]:
    """
    Mirrors getErrnoCode(). Returns the OS errno *name* (e.g. 'ENOENT') for an
    exception, or None. Python's OSError exposes .errno (int) and on some paths
    a string code; normalize to the POSIX name via the errno module.
    """
    code = getattr(e, "code", None)
    if isinstance(code, str):
        return code
    errno_int = getattr(e, "errno", None)
    if isinstance(errno_int, int):
        import errno as _errno

        return _errno.errorcode.get(errno_int)
    return None


def is_enoent_error(e: Any) -> bool:
    """Mirrors isENOENTError() — True if the error is a missing file/dir."""
    return get_errno_code(e) == "ENOENT"


def has_exact_error_message(error: Any, message: str) -> bool:
    """Mirrors hasExactErrorMessage()."""
    return isinstance(error, Exception) and str(error) == message


def to_error(e: Any) -> Exception:
    """Mirrors toError() — coerce any thrown value into an Exception."""
    if isinstance(e, Exception):
        return e
    return Exception(str(e))
