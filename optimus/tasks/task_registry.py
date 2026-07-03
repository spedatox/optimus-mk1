"""
tasks/task_registry.py — in-memory registry for background task handles.

Restored from the pre-restructure port (commit f696afe). Backs the TaskOutput
and TaskStop tools: anything that launches background work (background shell
commands, background sub-agents) registers a handle here under its task_id.

A handle must expose:
    task_type: str          — e.g. "shell", "agent"
    status: str             — "running" | "completed" | "failed" | "stopped"
    description: str
    async stop()            — terminate the underlying work
    async wait()            — resolve when the work finishes
    async get_output() -> str
    get_partial_output() -> str
"""
from __future__ import annotations

from typing import Any, Protocol


class TaskHandle(Protocol):
    task_type: str
    status: str
    description: str

    async def stop(self) -> None: ...
    async def wait(self) -> None: ...
    async def get_output(self) -> str: ...
    def get_partial_output(self) -> str: ...


_registry: dict[str, Any] = {}


def get_task_registry() -> dict[str, Any]:
    return _registry


def register_task(task_id: str, handle: Any) -> None:
    _registry[task_id] = handle


def unregister_task(task_id: str) -> None:
    _registry.pop(task_id, None)
