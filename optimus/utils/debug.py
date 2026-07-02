"""
utils/debug.py — partial port of src/utils/debug.ts

log_for_debugging mirrors logForDebugging: gated debug logging, active only
when CLAUDE_CODE_DEBUG / OPTIMUS_DEBUG (or ANTHROPIC_LOG=debug) is set.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

_log = logging.getLogger("optimus.debug")


def _debug_enabled() -> bool:
    from optimus.env_utils import is_env_truthy

    return (
        is_env_truthy(os.environ.get("CLAUDE_CODE_DEBUG"))
        or is_env_truthy(os.environ.get("OPTIMUS_DEBUG"))
        or os.environ.get("ANTHROPIC_LOG") == "debug"
    )


def log_for_debugging(message: Any, options: Optional[dict[str, Any]] = None) -> None:
    """Mirrors logForDebugging(message, { level }). No-op unless debug is enabled."""
    if not _debug_enabled():
        return
    level = (options or {}).get("level", "info")
    if level == "error":
        _log.error("%s", message)
    elif level in ("warn", "warning"):
        _log.warning("%s", message)
    else:
        _log.info("%s", message)
