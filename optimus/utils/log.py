"""
utils/log.py — partial port of src/utils/log.ts

log_error mirrors logError: record an error for diagnostics + the in-memory
error log. Telemetry/sink delivery is dropped per project rules; the in-memory
error log (read by bug-report flows) is preserved.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("optimus")


def log_error(error: Any) -> None:
    """Mirrors logError() — push to the in-memory error log and the logger."""
    message = str(error)
    try:
        from optimus.bootstrap.state import add_to_in_memory_error_log

        add_to_in_memory_error_log(
            {"error": message, "timestamp": datetime.now(timezone.utc).isoformat()}
        )
    except Exception:
        pass
    _log.debug("logError: %s", message)
