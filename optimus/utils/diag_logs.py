"""
utils/diag_logs.py — partial port of src/utils/diagLogs.ts

log_for_diagnostics_no_pii mirrors logForDiagnosticsNoPII: structured, PII-free
diagnostic breadcrumbs. Routed to the debug logger here; the diagnostic sink
plugs in when diagnostics infrastructure is ported.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger("optimus.diag")


def log_for_diagnostics_no_pii(
    level: str, event: str, data: Optional[dict[str, Any]] = None
) -> None:
    """Mirrors logForDiagnosticsNoPII(level, event, data?). No PII by contract."""
    payload = f"{event} {data}" if data else event
    if level == "error":
        _log.error("%s", payload)
    elif level in ("warn", "warning"):
        _log.warning("%s", payload)
    else:
        _log.debug("%s", payload)
