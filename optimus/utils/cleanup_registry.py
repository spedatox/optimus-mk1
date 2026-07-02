"""
utils/cleanup_registry.py — port of src/utils/cleanupRegistry.ts

A process-wide registry of cleanup callbacks run on graceful shutdown. Kept a
DAG leaf (no imports from the rest of the app) so any module can register
without risking an import cycle.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Union

CleanupHandler = Callable[[], Union[None, Awaitable[None]]]

_handlers: list[CleanupHandler] = []


def register_cleanup(handler: CleanupHandler) -> None:
    """Register a (sync or async) callback to run at shutdown."""
    _handlers.append(handler)


async def run_cleanup_handlers() -> None:
    """Run all registered handlers in reverse registration order, swallowing errors."""
    for handler in reversed(_handlers):
        try:
            result = handler()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass


def get_cleanup_handler_count() -> int:
    return len(_handlers)
