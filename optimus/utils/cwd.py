"""
utils/cwd.py — port of src/utils/cwd.ts

Current-working-directory resolution with per-async-context override.

Porting notes:
  - AsyncLocalStorage<string> → contextvars.ContextVar[Optional[str]].
    Both propagate a value to async descendants while isolating concurrent
    contexts: asyncio.create_task() copies the current context at creation,
    so a task spawned inside run_with_cwd_override() keeps the override even
    after the outer call returns and resets it — matching AsyncLocalStorage.run.
  - getCwdState / getOriginalCwd come from bootstrap/state.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Callable, Optional, TypeVar

from optimus.bootstrap.state import get_cwd_state, get_original_cwd

T = TypeVar("T")

_cwd_override_storage: ContextVar[Optional[str]] = ContextVar(
    "cwd_override", default=None
)


def run_with_cwd_override(cwd: str, fn: Callable[[], T]) -> T:
    """
    Run `fn` with an overridden working directory for the current async context.
    All pwd()/get_cwd() calls within fn (and its async descendants) return the
    override instead of the global cwd. Enables concurrent agents to each see
    their own working directory without affecting each other.
    """
    token = _cwd_override_storage.set(cwd)
    try:
        return fn()
    finally:
        _cwd_override_storage.reset(token)


def pwd() -> str:
    """Get the current working directory (override if set, else global state)."""
    store = _cwd_override_storage.get()
    return store if store is not None else get_cwd_state()


def get_cwd() -> str:
    """
    Get the current working directory, falling back to the original working
    directory if the current one is not available.
    """
    try:
        return pwd()
    except Exception:
        return get_original_cwd()
