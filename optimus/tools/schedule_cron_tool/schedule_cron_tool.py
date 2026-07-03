"""tools/schedule_cron_tool/schedule_cron_tool.py — port of the ScheduleCron
tool family (CronCreate / CronDelete / CronList), restored from commit f696afe
and upgraded to the current Tool protocol.

Jobs live in a session-scoped in-memory registry; `durable` jobs are also
persisted to ~/.optimus/cron_jobs.json so a scheduler can pick them up across
restarts (RE-ENTRY: the firing loop itself lives in the REPL/main loop, which
enqueues job prompts at match time — not yet wired).
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any, Optional

from optimus.tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.tools.schedule_cron_tool.prompt import (
    CRON_CREATE_DESCRIPTION,
    CRON_CREATE_PROMPT,
    CRON_CREATE_TOOL_NAME,
    CRON_DELETE_DESCRIPTION,
    CRON_DELETE_PROMPT,
    CRON_DELETE_TOOL_NAME,
    CRON_LIST_DESCRIPTION,
    CRON_LIST_PROMPT,
    CRON_LIST_TOOL_NAME,
    MAX_CRON_JOBS,
)

_cron_jobs: dict[str, dict[str, Any]] = {}
_DURABLE_FILE = Path.home() / ".optimus" / "cron_jobs.json"

_CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")


def get_cron_jobs() -> dict[str, dict[str, Any]]:
    """Registry accessor for the scheduler loop."""
    return _cron_jobs


def _validate_cron(expr: str) -> Optional[str]:
    parts = expr.split()
    if len(parts) != 5:
        return "Cron expression must have exactly 5 fields (minute hour day month weekday)."
    for part in parts:
        if not _CRON_FIELD_RE.match(part):
            return f"Invalid cron field: '{part}'"
    return None


def _cron_to_human(expr: str) -> str:
    """Best-effort human description of a cron expression."""
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, _dom, _month, _dow = parts
    if expr == "* * * * *":
        return "every minute"
    if minute.startswith("*/") and hour == "*":
        return f"every {minute[2:]} minutes"
    if hour == "*":
        return f"at minute {minute} of every hour"
    if minute.isdigit() and hour.isdigit():
        return f"at {hour}:{minute.zfill(2)}"
    return expr


def _persist_durable() -> None:
    durable = {jid: j for jid, j in _cron_jobs.items() if j.get("durable")}
    try:
        _DURABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DURABLE_FILE.write_text(json.dumps(durable, indent=2), encoding="utf-8")
    except OSError:
        pass  # persistence is best-effort; the in-memory job still runs


@build_tool
class CronCreateTool:
    name = CRON_CREATE_TOOL_NAME
    search_hint = "schedule a recurring prompt"
    max_result_size_chars = 20_000
    strict = True
    should_defer = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "cron": {"type": "string", "description": 'Standard 5-field cron expression (e.g. "*/5 * * * *")'},
            "prompt": {"type": "string", "description": "The prompt to enqueue at each fire time"},
            "recurring": {"type": "boolean", "description": "true (default) = fire every match; false = fire once then auto-delete"},
            "durable": {"type": "boolean", "description": "true = persist to disk; false (default) = in-memory only"},
        },
        "required": ["cron", "prompt"],
        "additionalProperties": False,
    }

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_CREATE_DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_CREATE_PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True  # session state (disk only for durable, still config-ish)

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("cron", "")

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        err = _validate_cron(input.get("cron", ""))
        if err:
            return ValidationResult.fail(err, error_code=1)
        if not input.get("prompt", "").strip():
            return ValidationResult.fail("prompt must not be empty", error_code=2)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(self, input: dict[str, Any], context: ToolUseContext,
                   can_use_tool: Any = None, parent_message: Any = None,
                   on_progress: Any = None) -> ToolResult:
        if len(_cron_jobs) >= MAX_CRON_JOBS:
            return ToolResult(data={"error": f"Maximum of {MAX_CRON_JOBS} cron jobs reached."})

        job_id = secrets.token_hex(8)
        job = {
            "id": job_id,
            "cron": input["cron"],
            "prompt": input["prompt"],
            "recurring": bool(input.get("recurring", True)),
            "durable": bool(input.get("durable", False)),
            "humanSchedule": _cron_to_human(input["cron"]),
        }
        _cron_jobs[job_id] = job
        if job["durable"]:
            _persist_durable()
        return ToolResult(data={"job": job})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        job = data["job"]
        content = (
            f"Cron job {job['id']} created: {job['humanSchedule']}"
            f" ({'recurring' if job['recurring'] else 'one-shot'}"
            f"{', durable' if job['durable'] else ''})"
        )
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}


@build_tool
class CronDeleteTool:
    name = CRON_DELETE_TOOL_NAME
    search_hint = "cancel a scheduled cron job"
    max_result_size_chars = 10_000
    strict = True
    should_defer = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Job ID returned by CronCreate"},
        },
        "required": ["id"],
        "additionalProperties": False,
    }

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_DELETE_DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_DELETE_PROMPT

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(self, input: dict[str, Any], context: ToolUseContext,
                   can_use_tool: Any = None, parent_message: Any = None,
                   on_progress: Any = None) -> ToolResult:
        job_id = input["id"]
        job = _cron_jobs.pop(job_id, None)
        if job is None:
            return ToolResult(data={"error": f"Job '{job_id}' not found."})
        if job.get("durable"):
            _persist_durable()
        return ToolResult(data={"id": job_id})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        if data.get("error"):
            return {"type": "tool_result", "content": data["error"],
                    "tool_use_id": tool_use_id, "is_error": True}
        return {"type": "tool_result", "content": f"Cron job {data['id']} deleted.",
                "tool_use_id": tool_use_id}


@build_tool
class CronListTool:
    name = CRON_LIST_TOOL_NAME
    search_hint = "list scheduled cron jobs"
    max_result_size_chars = 50_000
    strict = True
    should_defer = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_LIST_DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return CRON_LIST_PROMPT

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(self, input: dict[str, Any], context: ToolUseContext,
                   can_use_tool: Any = None, parent_message: Any = None,
                   on_progress: Any = None) -> ToolResult:
        return ToolResult(data={"jobs": list(_cron_jobs.values())})

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        jobs = data.get("jobs", [])
        if not jobs:
            content = "No scheduled cron jobs."
        else:
            content = "\n".join(
                f"{j['id']}: {j['cron']} ({j['humanSchedule']}) — {j['prompt'][:80]}"
                for j in jobs
            )
        return {"type": "tool_result", "content": content, "tool_use_id": tool_use_id}
