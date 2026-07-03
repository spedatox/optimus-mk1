"""
utils/tasks.py — port of src/utils/tasks.ts (task-list core).

Verified against the real source (2026-07-03). Tasks are stored one JSON file
per task under `<claude-config-home>/tasks/<taskListId>/<id>.json`, with
sequential string IDs ("1", "2", ...) allocated under an exclusive lock and a
high-water-mark file preventing ID reuse after a reset.

Porting notes:
  - proper-lockfile → `_task_lock()`: O_EXCL lock file with bounded retry
    (same strategy as utils/config.py).
  - notifyTasksUpdated() (ink re-render signal) → no-op; the TUI polls state.
  - getTeammateContext() → None until utils/teammate.ts is ported, so
    get_task_list_id falls back to the session id / 'default'.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

from optimus.env_utils import get_claude_config_home_dir, is_env_truthy

TASK_STATUSES = ("pending", "in_progress", "completed")

HIGH_WATER_MARK_FILE = ".high-water-mark"

Task = dict[str, Any]  # id, subject, description, activeForm?, status, owner?,
#                        blocks, blockedBy, metadata?


def is_todo_v2_enabled() -> bool:
    """Port of isTodoV2Enabled(): env force-enable, else interactive sessions."""
    if is_env_truthy(os.environ.get("CLAUDE_CODE_ENABLE_TASKS")):
        return True
    try:
        from optimus.bootstrap.state import get_is_non_interactive_session

        return not get_is_non_interactive_session()
    except Exception:
        return True


def is_agent_swarms_enabled() -> bool:
    """Port of isAgentSwarmsEnabled(): USER_TYPE=ant always; else env opt-in."""
    if os.environ.get("USER_TYPE") == "ant":
        return True
    return is_env_truthy(os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"))


def _sanitize_path_component(component: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", component) or "_"


def get_task_list_id() -> str:
    """Port of getTaskListId(): env override → teammate team → session id."""
    env_id = os.environ.get("CLAUDE_CODE_TASK_LIST_ID")
    if env_id:
        return env_id
    # RE-ENTRY: getTeammateContext().teamName once utils/teammate.ts is ported.
    try:
        from optimus.bootstrap.state import get_session_id

        return get_session_id() or "default"
    except Exception:
        return "default"


def get_tasks_dir(task_list_id: str) -> str:
    return os.path.join(
        get_claude_config_home_dir(), "tasks", _sanitize_path_component(task_list_id)
    )


def get_task_path(task_list_id: str, task_id: str) -> str:
    return os.path.join(get_tasks_dir(task_list_id), f"{_sanitize_path_component(task_id)}.json")


# ---------------------------------------------------------------------------
# Locking (mirrors proper-lockfile usage: exclusive per-task-list lock)
# ---------------------------------------------------------------------------


class _TaskLock:
    def __init__(self, lock_path: str, fd: int) -> None:
        self._lock_path = lock_path
        self._fd = fd

    def release(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass
        try:
            os.unlink(self._lock_path)
        except OSError:
            pass


def _task_lock(task_list_id: str) -> _TaskLock:
    lock_dir = get_tasks_dir(task_list_id)
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, ".lock")
    deadline = time.monotonic() + 10
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            return _TaskLock(lock_path, fd)
        except FileExistsError:
            try:
                if time.time() - os.stat(lock_path).st_mtime > 60:
                    os.unlink(lock_path)  # stale
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                continue
            time.sleep(0.02)


# ---------------------------------------------------------------------------
# High-water mark (prevents ID reuse after reset)
# ---------------------------------------------------------------------------


def _high_water_mark_path(task_list_id: str) -> str:
    return os.path.join(get_tasks_dir(task_list_id), HIGH_WATER_MARK_FILE)


def _read_high_water_mark(task_list_id: str) -> int:
    try:
        with open(_high_water_mark_path(task_list_id), encoding="utf-8") as f:
            value = int(f.read().strip())
        return value
    except (OSError, ValueError):
        return 0


def _find_highest_task_id(task_list_id: str) -> int:
    highest = _read_high_water_mark(task_list_id)
    tasks_dir = get_tasks_dir(task_list_id)
    try:
        names = os.listdir(tasks_dir)
    except OSError:
        return highest
    for name in names:
        if name.endswith(".json"):
            try:
                highest = max(highest, int(name[:-5]))
            except ValueError:
                pass
    return highest


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _read_task_file(path: str) -> Optional[Task]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_task_file(path: str, task: Task) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, indent=2)


async def create_task(task_list_id: str, task_data: dict[str, Any]) -> str:
    """Port of createTask(): allocate the next sequential ID under lock."""
    lock = _task_lock(task_list_id)
    try:
        task_id = str(_find_highest_task_id(task_list_id) + 1)
        task: Task = {"id": task_id, **task_data}
        _write_task_file(get_task_path(task_list_id, task_id), task)
        return task_id
    finally:
        lock.release()


async def get_task(task_list_id: str, task_id: str) -> Optional[Task]:
    return _read_task_file(get_task_path(task_list_id, task_id))


async def update_task(task_list_id: str, task_id: str, updates: dict[str, Any]) -> Optional[Task]:
    lock = _task_lock(task_list_id)
    try:
        path = get_task_path(task_list_id, task_id)
        task = _read_task_file(path)
        if task is None:
            return None
        task.update(updates)
        _write_task_file(path, task)
        return task
    finally:
        lock.release()


async def delete_task(task_list_id: str, task_id: str) -> bool:
    try:
        os.unlink(get_task_path(task_list_id, task_id))
        return True
    except OSError:
        return False


async def block_task(task_list_id: str, blocker_id: str, blocked_id: str) -> None:
    """Port of blockTask(): record that `blocker_id` blocks `blocked_id`."""
    lock = _task_lock(task_list_id)
    try:
        blocker_path = get_task_path(task_list_id, blocker_id)
        blocked_path = get_task_path(task_list_id, blocked_id)
        blocker = _read_task_file(blocker_path)
        blocked = _read_task_file(blocked_path)
        if blocker is None or blocked is None:
            return
        if blocked_id not in blocker.setdefault("blocks", []):
            blocker["blocks"].append(blocked_id)
            _write_task_file(blocker_path, blocker)
        if blocker_id not in blocked.setdefault("blockedBy", []):
            blocked["blockedBy"].append(blocker_id)
            _write_task_file(blocked_path, blocked)
    finally:
        lock.release()


async def list_tasks(task_list_id: str) -> list[Task]:
    tasks_dir = get_tasks_dir(task_list_id)
    try:
        names = os.listdir(tasks_dir)
    except OSError:
        return []
    tasks: list[Task] = []
    for name in sorted(names):
        if not name.endswith(".json"):
            continue
        task = _read_task_file(os.path.join(tasks_dir, name))
        if task is not None:
            tasks.append(task)
    # Numeric ID order (directory listing is lexicographic: "10" < "2").
    tasks.sort(key=lambda t: int(t["id"]) if str(t.get("id", "")).isdigit() else 0)
    return tasks


async def reset_task_list(task_list_id: str) -> None:
    """Port of resetTaskList(): clear tasks, persist high-water mark."""
    lock = _task_lock(task_list_id)
    try:
        highest = _find_highest_task_id(task_list_id)
        with open(_high_water_mark_path(task_list_id), "w", encoding="utf-8") as f:
            f.write(str(highest))
        tasks_dir = get_tasks_dir(task_list_id)
        for name in os.listdir(tasks_dir):
            if name.endswith(".json"):
                try:
                    os.unlink(os.path.join(tasks_dir, name))
                except OSError:
                    pass
    finally:
        lock.release()
