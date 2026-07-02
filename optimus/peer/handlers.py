"""
optimus/peer/handlers.py — work handlers for frames dispatched by SPEDA.

run_query_events() is the translation core factored from the proven
server/app.py:_run_agent path: it drives one optimus.query pass and yields
(kind, data) tuples in the SSE vocabulary SPEDA's ExternalAgentProxy re-wraps
1:1 — ("chunk", str), ("tool", {...}), ("tool_result", {...}), ("error", str),
("done", final_text).

Permission policy (v1 — no interactive round-trip): the query loop's
can_use_tool is not enforced as an outer gate by _run_tools yet, so policy is
enforced where it cannot be bypassed — the tools themselves are wrapped in a
_PolicyGuard whose denial raises PermissionError; _run_tools converts that
into an is_error tool_result the model can react to. Policy: Write/Edit only
inside the configured allowed directories; "plan" mode additionally denies
Write/Edit/PowerShell.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncGenerator

from optimus import query as Q
from optimus.api import call_model
from optimus.Tool import ToolUseContext, ToolUseContextOptions
from optimus.peer.config import PeerConfig
from optimus.tools import get_project_tools

logger = logging.getLogger("optimus.peer")

TASK_RESULT_MAX_CHARS = 12_000   # matches SPEDA's dispatch MAX_RESULT_CHARS
TOOL_RESULT_PREVIEW_CHARS = 4_000

# Global-cwd guard: bootstrap.state.cwd is process-wide, so a task that needs a
# different working directory must not race concurrent chats. Serialized here;
# documented v1 limitation (the system prompt carries the cwd either way, and
# tools are instructed to use absolute paths).
_CWD_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# History conversion — SPEDA sends Anthropic {"role","content"}, the query
# loop wants {'type','message','uuid'} envelopes.
# ---------------------------------------------------------------------------


def to_envelopes(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    for m in history:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if isinstance(content, str):
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            # Defensive: drop any display-only meta blocks that slipped through.
            blocks = [
                b for b in content
                if isinstance(b, dict) and not str(b.get("type", "")).startswith("_")
            ]
        else:
            continue
        if not blocks:
            continue
        envelopes.append({
            "type": role,
            "message": {"role": role, "content": blocks},
            "uuid": str(uuid.uuid4()),
        })
    return envelopes


# ---------------------------------------------------------------------------
# Permission policy
# ---------------------------------------------------------------------------


def _path_allowed(path: str, allowed_dirs: list[str]) -> bool:
    try:
        target = os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return False
    for root in allowed_dirs:
        root_n = os.path.normcase(os.path.abspath(root))
        if target == root_n or target.startswith(root_n.rstrip("\\/") + os.sep):
            return True
    return False


class _PolicyGuard:
    """Wraps one tool; denial raises PermissionError, which _run_tools turns
    into an is_error tool_result — the loop keeps running."""

    def __init__(self, tool: Any, cfg: PeerConfig, mode: str) -> None:
        self._tool = tool
        self._cfg = cfg
        self._mode = mode

    def __getattr__(self, item: str) -> Any:
        return getattr(self._tool, item)

    def _deny_reason(self, input: dict[str, Any]) -> str | None:
        name = self._tool.name
        if self._mode == "plan" and name in ("Write", "Edit", "PowerShell"):
            return (
                f"Permission denied: {name} is disabled in plan mode. Present a "
                "plan instead of making changes."
            )
        if name in ("Write", "Edit"):
            path = str(input.get("file_path", ""))
            if not _path_allowed(path, self._cfg.allowed_dirs):
                dirs = os.pathsep.join(self._cfg.allowed_dirs)
                return (
                    f"Permission denied: {path!r} is outside the allowed "
                    f"directories ({dirs}). Work within them, or ask the owner to "
                    "widen OPTIMUS_ALLOWED_DIRS on the Optimus host."
                )
        return None

    async def call(self, input: dict[str, Any], context: Any,
                   can_use_tool: Any = None, parent_message: Any = None,
                   on_progress: Any = None) -> Any:
        reason = self._deny_reason(input)
        if reason:
            raise PermissionError(reason)
        return await self._tool.call(input, context, can_use_tool, parent_message)


def guard_tools(cfg: PeerConfig, mode: str) -> list[Any]:
    """The project toolset with the v1 policy applied to mutating tools."""
    guarded = []
    for tool in get_project_tools():
        if tool.name in ("Write", "Edit", "PowerShell"):
            guarded.append(_PolicyGuard(tool, cfg, mode))
        else:
            guarded.append(tool)
    return guarded


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def build_system_prompt(cfg: PeerConfig, cwd: str | None) -> str:
    workdir = cwd or cfg.workspace
    return (
        "You are Optimus, the systems, code & infrastructure agent of the SPEDA "
        "network — an autonomous coding agent (a Python port of Claude Code) "
        "running on the owner's machine. You have real tools: Read, Write, Edit, "
        "Glob, Grep, PowerShell, TodoWrite, WebFetch, WebSearch. Use them to "
        f"inspect and modify the project at the working directory ({workdir}). "
        "Always use absolute paths. Prefer the dedicated file/search tools over "
        "shell commands when one fits. Read a file before editing it. Be concise "
        "and act decisively — when you have enough information, make the change."
    )


# ---------------------------------------------------------------------------
# Translation core (factored from server/app.py:_run_agent)
# ---------------------------------------------------------------------------


async def run_query_events(
    envelopes: list[dict[str, Any]],
    *,
    model: str,
    system_prompt: str,
    tools: list[Any],
    abort_event: asyncio.Event,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Drive one query pass; yield (kind, data) events in the SSE vocabulary.
    Terminates with exactly one ("done", final_text) or ("error", message)."""
    ctx = ToolUseContext(
        options=ToolUseContextOptions(
            tools=tools,
            main_loop_model=model,
            is_non_interactive_session=True,
        ),
        abort_controller=abort_event,
        read_file_state={},
    )
    params = Q.QueryParams(
        messages=envelopes,
        system_prompt=system_prompt,
        user_context={},
        system_context={},
        can_use_tool=lambda *a, **k: {"behavior": "allow"},
        tool_use_context=ctx,
        deps=Q.production_deps(call_model=call_model),
    )

    assistant_text_parts: list[str] = []
    streamed_any_delta = False

    try:
        async for ev in Q.query(params):
            if isinstance(ev, Q.Terminal):
                if ev.reason == "model_error":
                    yield ("error", str(ev.error) if ev.error else "Model error")
                    return
                break
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")

            if etype == "stream_delta":
                text = ev.get("text", "")
                if text:
                    streamed_any_delta = True
                    yield ("chunk", text)

            elif etype == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        yield ("tool", {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })
                    elif block.get("type") == "text":
                        assistant_text_parts.append(block.get("text", ""))

            elif etype == "user":
                # Tool result envelope — surface result text per tool_use_id.
                for block in ev.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(
                                b.get("text", "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        yield ("tool_result", {
                            "id": block.get("tool_use_id", ""),
                            "result": str(content)[:TOOL_RESULT_PREVIEW_CHARS],
                        })

    except Exception as exc:  # noqa: BLE001 — one turn must never kill the peer
        logger.exception("query pass failed")
        yield ("error", f"{type(exc).__name__}: {exc}")
        return

    final_text = "".join(assistant_text_parts).strip()
    if final_text and not streamed_any_delta:
        # The model produced text without streaming deltas (some providers /
        # paths) — surface it so the proxied UI and persistence still see it.
        yield ("chunk", final_text)
    yield ("done", final_text)


# ---------------------------------------------------------------------------
# Frame handlers
# ---------------------------------------------------------------------------


async def handle_chat_request(client: Any, frame: dict[str, Any]) -> None:
    """Run one proxied interactive chat turn; stream chat_event frames back."""
    cfg: PeerConfig = client.cfg
    chat_id = str(frame.get("chat_id", ""))
    abort_event = client.track_chat(chat_id)
    model = frame.get("model") or cfg.default_model
    cwd = frame.get("cwd")
    mode = cfg.resolve_mode(frame.get("permission_mode"))
    system_prompt = frame.get("system_prompt") or build_system_prompt(cfg, cwd)
    envelopes = to_envelopes(frame.get("history") or [])

    async def send_event(kind: str, data: Any) -> None:
        await client.send({
            "type": "chat_event",
            "chat_id": chat_id,
            "event": {"type": kind, "data": data},
        })

    terminal_sent = False
    try:
        if not envelopes:
            await send_event("error", "chat_request carried an empty history.")
            terminal_sent = True
            return
        async for kind, data in run_query_events(
            envelopes,
            model=model,
            system_prompt=system_prompt,
            tools=guard_tools(cfg, mode),
            abort_event=abort_event,
        ):
            if kind == "done":
                await send_event("done", {})
            else:
                await send_event(kind, data)
            if kind in ("done", "error"):
                terminal_sent = True
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat handler failed", extra={"chat_id": chat_id})
        if not terminal_sent:
            try:
                await send_event("error", f"{type(exc).__name__}: {exc}")
                terminal_sent = True
            except Exception:  # noqa: BLE001 — socket may be gone
                pass
    finally:
        client.untrack_chat(chat_id)
        if not terminal_sent:
            # Aborted (chat_cancel / disconnect) — best-effort terminal frame so
            # SPEDA's proxy never waits out its idle timeout.
            try:
                await send_event("done", {})
            except Exception:  # noqa: BLE001
                pass


async def handle_task_dispatch(client: Any, frame: dict[str, Any]) -> None:
    """Run one delegated task headless; always answer with task_result."""
    cfg: PeerConfig = client.cfg
    task_id = str(frame.get("task_id", ""))
    from_agent = str(frame.get("from", "speda"))
    task = str(frame.get("task", ""))
    cwd = frame.get("cwd")
    mode = cfg.resolve_mode(frame.get("permission_mode"))
    abort_event = asyncio.Event()

    prompt = (
        f"Inter-agent dispatch from {from_agent.upper()}. Complete the task below "
        "and reply with the result — your answer goes back to "
        f"{from_agent.upper()}, not to the owner, so lead with the substance. "
        "Be complete but compact.\n\n"
    )
    if cwd:
        prompt += f"Working directory for this task: {cwd}. Use absolute paths.\n\n"
    prompt += f"TASK: {task}"

    result_text = ""
    status = "error"
    try:
        chunks: list[str] = []
        final = ""

        async def _run() -> None:
            nonlocal final
            async for kind, data in run_query_events(
                [Q._create_user_message(prompt)],
                model=cfg.default_model,
                system_prompt=build_system_prompt(cfg, cwd),
                tools=guard_tools(cfg, mode),
                abort_event=abort_event,
            ):
                if kind == "chunk":
                    chunks.append(str(data))
                elif kind == "error":
                    raise RuntimeError(str(data))
                elif kind == "done":
                    final = str(data)

        needs_cwd_switch = bool(cwd) and os.path.normcase(
            os.path.abspath(cwd)
        ) != os.path.normcase(os.path.abspath(cfg.workspace))

        if needs_cwd_switch:
            # PowerShell inherits the process cwd, which is global state —
            # serialize and restore. v1 limitation: concurrent different-cwd
            # tasks queue here rather than race.
            from optimus.bootstrap.state import set_cwd_state

            async with _CWD_LOCK:
                set_cwd_state(cwd)
                try:
                    await _run()
                finally:
                    set_cwd_state(cfg.workspace)
        else:
            await _run()

        result_text = (final or "".join(chunks)).strip()
        status = "ok" if result_text else "error"
        if not result_text:
            result_text = "Optimus returned an empty response."
    except Exception as exc:  # noqa: BLE001
        logger.exception("task handler failed", extra={"task_id": task_id})
        result_text = f"Optimus task failed: {exc}"
        status = "error"
    finally:
        try:
            await client.send({
                "type": "task_result",
                "agent_id": "optimus",
                "task_id": task_id,
                "result": result_text[:TASK_RESULT_MAX_CHARS],
                "status": status,
            })
        except Exception:  # noqa: BLE001 — socket gone; dispatcher will time out
            logger.warning("could not deliver task_result %s", task_id)
