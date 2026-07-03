"""
utils/swarm/team_helpers.py — team file helpers for swarm coordination.

Restored from the pre-restructure port (commit f696afe). Team metadata is
persisted as JSON under ~/.optimus/teams/<name>.json; the "current" team is
session-scoped module state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_current_team: str | None = None
_TEAMS_DIR = Path.home() / ".optimus" / "teams"


def sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]


def get_team_file_path(team_name: str) -> str:
    return str(_TEAMS_DIR / f"{team_name}.json")


async def write_team_file(team_name: str, data: dict[str, Any]) -> None:
    global _current_team
    _TEAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(get_team_file_path(team_name))
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _current_team = team_name


async def read_team_file(team_name: str) -> dict[str, Any] | None:
    path = Path(get_team_file_path(team_name))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def cleanup_team_directories(team_name: str) -> None:
    global _current_team
    path = Path(get_team_file_path(team_name))
    if path.exists():
        path.unlink()
    if _current_team == team_name:
        _current_team = None


def get_current_team_name() -> str | None:
    return _current_team
