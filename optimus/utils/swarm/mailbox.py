"""
utils/swarm/mailbox.py — async message passing between swarm agents.

Restored from the pre-restructure port (commit f696afe). In-process queues
keyed by agent id; SendMessage writes, teammates poll with a timeout.
"""
from __future__ import annotations

import asyncio
from typing import Any

_mailboxes: dict[str, asyncio.Queue] = {}


def _get_mailbox(agent_id: str) -> asyncio.Queue:
    if agent_id not in _mailboxes:
        _mailboxes[agent_id] = asyncio.Queue()
    return _mailboxes[agent_id]


async def write_to_mailbox(agent_id: str, message: dict[str, Any]) -> None:
    await _get_mailbox(agent_id).put(message)


async def read_from_mailbox(agent_id: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        return await asyncio.wait_for(_get_mailbox(agent_id).get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


def pending_message_count(agent_id: str) -> int:
    box = _mailboxes.get(agent_id)
    return box.qsize() if box else 0
