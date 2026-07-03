"""
optimus/peer/client.py — the SPEDA peering WebSocket client.

Speaks the agents protocol of SPEDA Mark VI (packages/api/app/routers/agents.py
+ websocket/protocol.py):

  connect  →  send agent_register handshake
  then     →  heartbeat every cfg.heartbeat_interval (backend answers
              acknowledge), and receive frames:

    task_dispatch  {task_id, from, task[, cwd, permission_mode]}
                   → handlers.handle_task_dispatch → one task_result frame
    chat_request   {chat_id, history, ...}   (SPEDA ExternalAgentProxy)
                   → handlers.handle_chat_request → chat_event stream
    chat_cancel    {chat_id}                 → abort the tracked chat
    acknowledge    heartbeat reply — ignored
    shutdown       backend asks us to go away — close, no reconnect

Auth: the X-API-Key header carries SPEDA_API_KEY on the handshake (the same
key the backend validates on HTTP requests; the WS route tolerates extras).

Resilience: the connection loop reconnects with capped exponential backoff.
Work handlers run as independent tasks, so a slow task never blocks the
receive loop; send() is serialized so concurrent handlers cannot interleave
frames on the socket.
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Any, Optional

from optimus.peer.config import PeerConfig
from optimus.peer.handlers import handle_chat_request, handle_task_dispatch

logger = logging.getLogger("optimus.peer")

AGENT_ID = "optimus"
AGENT_NAME = "Optimus Mark I"
AGENT_DOMAIN = "systems, code & infrastructure"
CAPABILITIES = [
    "Read", "Write", "Edit", "Glob", "Grep", "PowerShell",
    "TodoWrite", "WebFetch", "WebSearch",
]

_BACKOFF_START_S = 1.0
_BACKOFF_MAX_S = 60.0


class PeerClient:
    """One persistent connection to the SPEDA agents WebSocket."""

    def __init__(self, cfg: PeerConfig) -> None:
        self.cfg = cfg
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._chats: dict[str, asyncio.Event] = {}   # chat_id → abort event
        self._work: set[asyncio.Task] = set()        # in-flight handler tasks
        self._shutdown = False                       # backend-initiated: no reconnect
        self._stop = asyncio.Event()                 # owner-initiated (Ctrl-C)

    # ── Surface consumed by handlers.py ─────────────────────────────────────

    async def send(self, frame: dict[str, Any]) -> None:
        """Serialize one frame onto the socket. Raises if disconnected —
        handlers treat that as delivery failure and log it."""
        ws = self._ws
        if ws is None:
            raise ConnectionError("peer socket is not connected")
        async with self._send_lock:
            await ws.send(json.dumps(frame))

    def track_chat(self, chat_id: str) -> asyncio.Event:
        """Register a chat's abort event; chat_cancel / disconnect sets it."""
        event = asyncio.Event()
        self._chats[chat_id] = event
        return event

    def untrack_chat(self, chat_id: str) -> None:
        self._chats.pop(chat_id, None)

    # ── Connection lifecycle ─────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Connect-serve-reconnect until the backend says shutdown or the
        owner stops the process."""
        backoff = _BACKOFF_START_S
        while not self._shutdown and not self._stop.is_set():
            try:
                await self._serve_one_connection()
                backoff = _BACKOFF_START_S  # a served connection resets backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — connect/serve failed
                logger.warning("connection lost (%s: %s)", type(exc).__name__, exc)
            if self._shutdown or self._stop.is_set():
                break
            logger.info("reconnecting in %.0fs", backoff)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                break  # owner stop during the wait
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, _BACKOFF_MAX_S)
        await self._abort_all("peer shutting down")

    def request_stop(self) -> None:
        """Owner-initiated stop (signal handler) — idempotent."""
        self._stop.set()

    async def _serve_one_connection(self) -> None:
        import websockets

        headers = {"X-API-Key": self.cfg.speda_api_key}
        try:  # websockets ≥13 renamed extra_headers → additional_headers
            connect_cm = websockets.connect(
                self.cfg.speda_ws_url, additional_headers=headers
            )
        except TypeError:
            connect_cm = websockets.connect(
                self.cfg.speda_ws_url, extra_headers=headers
            )

        async with connect_cm as ws:
            self._ws = ws
            try:
                await self._register()
                logger.info("registered with SPEDA at %s", self.cfg.speda_ws_url)
                heartbeat = asyncio.create_task(self._heartbeat_loop())
                stopper = asyncio.create_task(self._stop.wait())
                try:
                    receiver = asyncio.create_task(self._receive_loop())
                    done, _ = await asyncio.wait(
                        {receiver, stopper}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if receiver in done:
                        receiver.result()  # surface receive-loop errors
                    else:
                        receiver.cancel()
                finally:
                    heartbeat.cancel()
                    stopper.cancel()
            finally:
                self._ws = None
                # A dropped socket must not leave chats streaming into the void.
                await self._abort_all("socket disconnected")

    async def _register(self) -> None:
        await self.send({
            "type": "agent_register",
            "agent_id": AGENT_ID,
            "agent_name": AGENT_NAME,
            "domain": AGENT_DOMAIN,
            "capabilities": CAPABILITIES,
            "status": "online",
            "model_preference": self.cfg.default_model,
        })

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.heartbeat_interval)
            try:
                await self.send({
                    "type": "heartbeat", "agent_id": AGENT_ID, "payload": {},
                })
            except Exception:  # noqa: BLE001 — receive loop handles the drop
                return

    # ── Frame dispatch ───────────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            try:
                frame = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("undecodable frame: %.200r", raw)
                continue
            if not isinstance(frame, dict):
                continue
            self._dispatch(frame)
            if self._shutdown:
                return

    def _dispatch(self, frame: dict[str, Any]) -> None:
        ftype = frame.get("type")

        if ftype == "task_dispatch":
            self._spawn(handle_task_dispatch(self, frame), f"task:{frame.get('task_id')}")

        elif ftype == "chat_request":
            self._spawn(handle_chat_request(self, frame), f"chat:{frame.get('chat_id')}")

        elif ftype == "chat_cancel":
            event = self._chats.get(str(frame.get("chat_id", "")))
            if event is not None:
                event.set()

        elif ftype == "acknowledge":
            pass  # heartbeat reply

        elif ftype == "shutdown":
            logger.info("backend requested shutdown")
            self._shutdown = True

        else:
            logger.debug("ignoring unknown frame type %r", ftype)

    def _spawn(self, coro: Any, label: str) -> None:
        """Run a handler as an independent task so the receive loop never
        blocks on model calls."""
        task = asyncio.create_task(coro, name=f"peer-{label}")
        self._work.add(task)
        task.add_done_callback(self._work.discard)

    async def _abort_all(self, reason: str) -> None:
        """Signal every tracked chat to abort and let in-flight work drain
        briefly. task_result frames for a dead socket fail inside the handler
        (logged there); SPEDA's dispatcher timeout covers the rest."""
        for event in self._chats.values():
            event.set()
        if self._work:
            logger.info("%s — waiting for %d handler(s)", reason, len(self._work))
            done, pending = await asyncio.wait(set(self._work), timeout=5.0)
            for task in pending:
                task.cancel()


def main() -> int:
    """Entry point for `python -m optimus.peer`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = PeerConfig.from_env()  # SystemExit with guidance when misconfigured
    client = PeerClient(cfg)

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, client.request_stop)
            except (NotImplementedError, OSError):
                signal.signal(sig, lambda *_: client.request_stop())
        await client.run_forever()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    logger.info("peer stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
