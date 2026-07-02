"""
optimus/context.py — port of src/context.ts

Builds the system-prompt context blocks injected into every conversation:
  - getGitStatus()     → git snapshot (branch, status, recent commits)
  - getSystemContext() → {gitStatus} dict, memoized per session
  - getUserContext()   → {claudeMd, currentDate} dict, memoized per session

Dependencies not yet ported → minimal stubs with RE-ENTRY comments.
Analytics (logForDiagnosticsNoPII) → dropped.
feature('BREAK_CACHE_COMMAND') → False.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from optimus.constants import get_local_iso_date
from optimus.env_utils import is_bare_mode, is_env_truthy


# ---------------------------------------------------------------------------
# Stubs — RE-ENTRY comments mark where real modules plug in
# ---------------------------------------------------------------------------

# RE-ENTRY: from optimus.utils.claudemd import get_claude_mds, get_memory_files, filter_injected_memory_files
async def get_memory_files() -> list:
    return []

def filter_injected_memory_files(files: list) -> list:
    return files

def get_claude_mds(files: list) -> Optional[str]:
    return None

# RE-ENTRY: from optimus.bootstrap.state import get_additional_directories_for_claude_md, set_cached_claude_md_content
def get_additional_directories_for_claude_md() -> list:
    return []

def set_cached_claude_md_content(content: Optional[str]) -> None:
    pass

# RE-ENTRY: from optimus.utils.git_settings import should_include_git_instructions
def should_include_git_instructions() -> bool:
    env_val = os.environ.get("CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS")
    if is_env_truthy(env_val):
        return False
    if env_val is not None and not is_env_truthy(env_val):
        return True
    return True  # default: include git instructions


# ---------------------------------------------------------------------------
# exec_file_no_throw — async subprocess helper (port of execFileNoThrow)
# ---------------------------------------------------------------------------

async def _exec_git(*args: str, cwd: Optional[str] = None) -> tuple[str, str, int]:
    """Run a git command, return (stdout, stderr, returncode). Never raises."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _git_exe(), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or os.getcwd(),
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout_b.decode(errors="replace").strip(), stderr_b.decode(errors="replace").strip(), proc.returncode or 0
    except Exception:
        return "", "", 1


# ---------------------------------------------------------------------------
# Minimal git helpers (subset of git.ts used by context.ts)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _git_exe() -> str:
    """Port of gitExe() — find git on PATH, memoized."""
    found = shutil.which("git")
    return found or "git"


def _find_git_root(start_path: str) -> Optional[str]:
    """
    Port of findGitRoot() — walk up the directory tree looking for a .git
    directory or file (worktrees/submodules use a file).
    """
    current = Path(start_path).resolve()
    while True:
        git_path = current / ".git"
        if git_path.exists():
            return str(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


@lru_cache(maxsize=1)
def _get_is_git_sync() -> bool:
    return _find_git_root(os.getcwd()) is not None


async def get_is_git() -> bool:
    """Port of getIsGit() — True if cwd is inside a git repository."""
    return _get_is_git_sync()


async def get_branch() -> str:
    """Port of getBranch() — returns current branch name or 'HEAD'."""
    stdout, _, code = await _exec_git("rev-parse", "--abbrev-ref", "HEAD")
    return stdout if code == 0 and stdout else "HEAD"


async def get_default_branch() -> str:
    """
    Port of getCachedDefaultBranch() — tries to detect the default branch.
    Order: origin/HEAD symbolic ref → check for 'main' → check for 'master' → 'main'.
    """
    # Try symbolic ref for origin/HEAD
    stdout, _, code = await _exec_git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and stdout:
        # e.g. "origin/main" → "main"
        return stdout.split("/", 1)[-1]

    # Check if 'main' branch exists
    _, _, main_code = await _exec_git("show-ref", "--verify", "--quiet", "refs/heads/main")
    if main_code == 0:
        return "main"

    # Check if 'master' branch exists
    _, _, master_code = await _exec_git("show-ref", "--verify", "--quiet", "refs/heads/master")
    if master_code == 0:
        return "master"

    return "main"


# ---------------------------------------------------------------------------
# System prompt injection (ant-only debug feature — always None here)
# ---------------------------------------------------------------------------

_system_prompt_injection: Optional[str] = None


def get_system_prompt_injection() -> Optional[str]:
    return _system_prompt_injection


def set_system_prompt_injection(value: Optional[str]) -> None:
    global _system_prompt_injection
    _system_prompt_injection = value
    # Clear caches so the new injection takes effect immediately
    get_git_status.cache_clear()  # type: ignore[attr-defined]
    _get_system_context_cache.clear()
    _get_user_context_cache.clear()


# ---------------------------------------------------------------------------
# getGitStatus — memoized async (port of getGitStatus in context.ts)
# ---------------------------------------------------------------------------

MAX_STATUS_CHARS = 2000

_git_status_cache: dict[str, Optional[str]] = {}


class _Sentinel:
    pass

_GIT_STATUS_SENTINEL = _Sentinel()


async def get_git_status() -> Optional[str]:
    """
    Port of getGitStatus() — collects branch, status, and recent commits.
    Returns a formatted string for the system prompt, or None if not a git repo.
    Memoized: runs once per session.
    """
    if "result" in _git_status_cache:
        return _git_status_cache["result"]

    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("NODE_ENV") == "test":
        _git_status_cache["result"] = None
        return None

    is_git = await get_is_git()
    if not is_git:
        _git_status_cache["result"] = None
        return None

    try:
        cwd = os.getcwd()
        branch_task = asyncio.ensure_future(get_branch())
        default_branch_task = asyncio.ensure_future(get_default_branch())
        status_task = asyncio.ensure_future(_exec_git("--no-optional-locks", "status", "--short", cwd=cwd))
        log_task = asyncio.ensure_future(_exec_git("--no-optional-locks", "log", "--oneline", "-n", "5", cwd=cwd))
        user_name_task = asyncio.ensure_future(_exec_git("config", "user.name", cwd=cwd))

        branch, default_branch, status_res, log_res, user_res = await asyncio.gather(
            branch_task, default_branch_task, status_task, log_task, user_name_task
        )

        status = status_res[0]
        log = log_res[0]
        user_name = user_res[0] if user_res[2] == 0 else ""

        if len(status) > MAX_STATUS_CHARS:
            status = (
                status[:MAX_STATUS_CHARS]
                + '\n... (truncated because it exceeds 2k characters. If you need more information, run "git status" using BashTool)'
            )

        lines = [
            "This is the git status at the start of the conversation. Note that this status is a snapshot in time, and will not update during the conversation.",
            f"Current branch: {branch}",
            f"Main branch (you will usually use this for PRs): {default_branch}",
            *([ f"Git user: {user_name}" ] if user_name else []),
            f"Status:\n{status or '(clean)'}",
            f"Recent commits:\n{log}",
        ]
        result = "\n\n".join(lines)
        _git_status_cache["result"] = result
        return result

    except Exception:
        _git_status_cache["result"] = None
        return None


def get_git_status_cache_clear() -> None:
    """Allow external callers to invalidate the git status cache."""
    _git_status_cache.clear()

# Attach cache_clear for compatibility with set_system_prompt_injection
get_git_status.cache_clear = get_git_status_cache_clear  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# getSystemContext — memoized async (port of getSystemContext in context.ts)
# ---------------------------------------------------------------------------

_get_system_context_cache: dict[str, dict[str, str]] = {}


async def get_system_context() -> dict[str, str]:
    """
    Port of getSystemContext() — returns {gitStatus?} dict.
    Memoized for prompt-cache stability. feature('BREAK_CACHE_COMMAND') → False.
    """
    if "result" in _get_system_context_cache:
        return _get_system_context_cache["result"]

    skip_git = (
        is_env_truthy(os.environ.get("CLAUDE_CODE_REMOTE"))
        or not should_include_git_instructions()
    )
    git_status = None if skip_git else await get_git_status()

    result: dict[str, str] = {}
    if git_status:
        result["gitStatus"] = git_status
    # feature('BREAK_CACHE_COMMAND') → False: cacheBreaker block omitted

    _get_system_context_cache["result"] = result
    return result


# ---------------------------------------------------------------------------
# getUserContext — memoized async (port of getUserContext in context.ts)
# ---------------------------------------------------------------------------

_get_user_context_cache: dict[str, dict[str, str]] = {}


async def get_user_context() -> dict[str, str]:
    """
    Port of getUserContext() — returns {claudeMd?, currentDate} dict.
    Memoized for prompt-cache stability.
    claudemd.ts not yet ported → stub returns None (RE-ENTRY below).
    """
    if "result" in _get_user_context_cache:
        return _get_user_context_cache["result"]

    # CLAUDE_CODE_DISABLE_CLAUDE_MDS: always skip.
    # --bare with no explicit --add-dir: also skip.
    should_disable = (
        is_env_truthy(os.environ.get("CLAUDE_CODE_DISABLE_CLAUDE_MDS"))
        or (is_bare_mode() and len(get_additional_directories_for_claude_md()) == 0)
    )

    # RE-ENTRY: replace stub below when claudemd.ts is ported
    claude_md: Optional[str]
    if should_disable:
        claude_md = None
    else:
        memory_files = await get_memory_files()
        claude_md = get_claude_mds(filter_injected_memory_files(memory_files))

    set_cached_claude_md_content(claude_md or None)

    result: dict[str, str] = {
        "currentDate": f"Today's date is {get_local_iso_date()}.",
    }
    if claude_md:
        result["claudeMd"] = claude_md

    _get_user_context_cache["result"] = result
    return result
