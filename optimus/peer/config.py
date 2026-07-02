"""
optimus/peer/config.py — environment-driven configuration for the SPEDA peer.

Mirrors the server precedent (optimus/server/app.py reads its config from env
at startup). Provider API keys are NOT duplicated here — optimus/api.py and
optimus/llm read those from the environment directly, so TUI / server / peer
modes stay consistent. SPEDA never transmits credentials over the socket.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


# Strictness order for permission modes: a chat/task frame may request a
# stricter mode than the configured ceiling, never a looser one.
PERMISSION_STRICTNESS = {"bypassPermissions": 0, "acceptEdits": 1, "plan": 2}


@dataclass
class PeerConfig:
    speda_ws_url: str
    speda_api_key: str
    workspace: str
    allowed_dirs: list[str] = field(default_factory=list)
    default_model: str = "claude-sonnet-4-6"
    permission_mode: str = "bypassPermissions"
    heartbeat_interval: float = 30.0

    @classmethod
    def from_env(cls) -> "PeerConfig":
        api_key = os.environ.get("SPEDA_API_KEY", "")
        if not api_key:
            raise SystemExit(
                "SPEDA_API_KEY is required — the peer authenticates the WebSocket "
                "handshake with it (same key the SPEDA backend validates on every "
                "HTTP request)."
            )
        workspace = os.environ.get("OPTIMUS_WORKSPACE") or os.getcwd()
        allowed_raw = os.environ.get("OPTIMUS_ALLOWED_DIRS", "")
        allowed = [d for d in (p.strip() for p in allowed_raw.split(os.pathsep)) if d]
        if not allowed:
            allowed = [workspace]
        mode = os.environ.get("OPTIMUS_PERMISSION_MODE", "bypassPermissions")
        if mode not in PERMISSION_STRICTNESS:
            raise SystemExit(
                f"OPTIMUS_PERMISSION_MODE={mode!r} is invalid — use one of: "
                f"{', '.join(PERMISSION_STRICTNESS)}."
            )
        return cls(
            speda_ws_url=os.environ.get(
                "SPEDA_WS_URL", "ws://127.0.0.1:8000/agents/ws/optimus"
            ),
            speda_api_key=api_key,
            workspace=workspace,
            allowed_dirs=allowed,
            default_model=os.environ.get("OPTIMUS_DEFAULT_MODEL", "claude-sonnet-4-6"),
            permission_mode=mode,
            heartbeat_interval=float(os.environ.get("OPTIMUS_HEARTBEAT_S", "30")),
        )

    def resolve_mode(self, requested: str | None) -> str:
        """Frame-requested mode may only tighten the configured ceiling."""
        if requested not in PERMISSION_STRICTNESS:
            return self.permission_mode
        if PERMISSION_STRICTNESS[requested] > PERMISSION_STRICTNESS[self.permission_mode]:
            return requested
        return self.permission_mode
