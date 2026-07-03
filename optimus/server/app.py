"""
optimus/server/app.py — FastAPI backend for the Optimus Mark I desktop UI.

Bridges the Heartbreaker/Optimus React client to the agent query loop. Implements
the contract the UI's lib/api.ts expects:

  POST /auth/login            owner login → JWT
  GET  /auth/me               token / X-API-Key validation
  GET  /models                available models
  GET  /sessions              session list
  GET  /sessions/{id}/messages
  DELETE/PATCH /sessions/{id}
  POST /chat                  SSE stream of {type,data,session_id,request_id}
  (peripheral endpoints stubbed so the UI's optional panels don't error)

The /chat stream drives optimus.query.query() with the project toolset and maps
its events to the UI's SSE event types:
  start | chunk | tool | tool_result | done | error

Run:  python -m optimus.server      (or: uvicorn optimus.server.app:app)
Env:  OPTIMUS_OWNER_PASSWORD (default 'optimus'), OPTIMUS_SERVICE_KEY ('dev-key'),
      OPTIMUS_JWT_SECRET, OPTIMUS_WORKSPACE (agent cwd), ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
import uuid
from typing import Any, AsyncGenerator, Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from optimus import query as Q
from optimus.api import call_model
from optimus.tool import ToolUseContext, ToolUseContextOptions
from optimus.tools import get_project_tools

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OWNER_PASSWORD = os.environ.get("OPTIMUS_OWNER_PASSWORD", "optimus")
SERVICE_KEY = os.environ.get("OPTIMUS_SERVICE_KEY", "dev-key")
JWT_SECRET = os.environ.get("OPTIMUS_JWT_SECRET", "optimus-dev-secret-change-me")
JWT_ALGO = "HS256"
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
WORKSPACE = os.environ.get("OPTIMUS_WORKSPACE") or os.getcwd()
DEFAULT_MODEL = "claude-sonnet-4-6"

MODELS = [
    {"id": "claude-opus-4-8", "name": "Opus 4.8", "description": "Most capable — deep reasoning & hard tasks", "provider": "anthropic", "tags": ["smartest"]},
    {"id": "claude-sonnet-4-6", "name": "Sonnet 4.6", "description": "Balanced default — fast and strong", "provider": "anthropic", "tags": ["default"]},
    {"id": "claude-haiku-4-5", "name": "Haiku 4.5", "description": "Fastest — quick edits and lookups", "provider": "anthropic", "tags": ["fast"]},
]

OPTIMUS_SYSTEM_PROMPT = (
    "You are Optimus Mark I, an autonomous coding agent (a Python port of Claude "
    "Code) running on the user's machine. You have real tools: Read, Write, Edit, "
    "Glob, Grep, and PowerShell. Use them to inspect and modify the project at the "
    f"working directory ({WORKSPACE}). Prefer the dedicated file/search tools over "
    "shell commands when one fits. Read a file before editing it. Be concise and act "
    "decisively — when you have enough information, make the change."
)


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------


class _Session:
    _ids = itertools.count(1)

    def __init__(self) -> None:
        self.id: int = next(_Session._ids)
        self.title: Optional[str] = None
        self.started_at: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.messages: list[dict[str, Any]] = []  # UI ChatMessage shape
        # Internal agent message envelopes (for multi-turn context).
        self.agent_messages: list[dict[str, Any]] = []


_SESSIONS: dict[int, _Session] = {}


def _get_or_create_session(session_id: Optional[int]) -> _Session:
    if session_id is not None and session_id in _SESSIONS:
        return _SESSIONS[session_id]
    s = _Session()
    _SESSIONS[s.id] = s
    return s


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _issue_token() -> dict[str, Any]:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    token = jwt.encode({"sub": "owner", "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)
    return {"token": token, "expires_at": exp}


def _valid_token(token: str) -> bool:
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return True
    except jwt.PyJWTError:
        return False


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> None:
    """Accept a valid Bearer JWT or the service X-API-Key (matches the UI's authHeaders)."""
    if authorization and authorization.startswith("Bearer "):
        if _valid_token(authorization[7:]):
            return
    if x_api_key and x_api_key == SERVICE_KEY:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Optimus Mark I backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    # Anchor the agent's cwd to the workspace so the tools operate there.
    from optimus.bootstrap.state import set_cwd_state, set_original_cwd

    set_original_cwd(WORKSPACE)
    set_cwd_state(WORKSPACE)


@app.post("/auth/login")
async def auth_login(body: dict[str, Any]) -> JSONResponse:
    password = body.get("password", "")
    if password != OWNER_PASSWORD:
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    return JSONResponse(_issue_token())


@app.get("/auth/me")
async def auth_me(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"ok": True, "user": "owner"}


@app.get("/models")
async def models(_: None = Depends(require_auth)) -> list[dict[str, Any]]:
    return MODELS


@app.get("/sessions")
async def sessions(limit: int = 500, _: None = Depends(require_auth)) -> list[dict[str, Any]]:
    items = sorted(_SESSIONS.values(), key=lambda s: s.id, reverse=True)[:limit]
    return [{"id": s.id, "title": s.title, "started_at": s.started_at} for s in items]


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: int, _: None = Depends(require_auth)) -> list[dict[str, Any]]:
    s = _SESSIONS.get(session_id)
    return s.messages if s else []


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int, _: None = Depends(require_auth)) -> dict[str, Any]:
    _SESSIONS.pop(session_id, None)
    return {"ok": True}


@app.patch("/sessions/{session_id}")
async def rename_session(session_id: int, body: dict[str, Any], _: None = Depends(require_auth)) -> dict[str, Any]:
    s = _SESSIONS.get(session_id)
    if s and "title" in body:
        s.title = body["title"]
    return {"ok": True}


# --- Peripheral endpoints the UI probes; stubbed so optional panels don't error.

@app.get("/connections")
async def connections(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"servers": [], "active_tool_tokens": 0, "itpm_limit": 30000}


@app.get("/automations")
async def automations(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"automations": []}


@app.get("/automations/status")
async def automations_status(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"n8n_configured": False, "n8n_online": False, "n8n_url": "", "telegram_configured": False, "telegram_connected": False}


@app.get("/memory/files")
async def memory_files(_: None = Depends(require_auth)) -> list[dict[str, Any]]:
    return []


@app.get("/budget-mode")
async def get_budget_mode(_: None = Depends(require_auth)) -> dict[str, Any]:
    return {"budget_mode": False}


@app.post("/budget-mode")
async def set_budget_mode(body: dict[str, Any], _: None = Depends(require_auth)) -> dict[str, Any]:
    return {"budget_mode": bool(body.get("enabled"))}


# ---------------------------------------------------------------------------
# /chat — the SSE bridge to the query loop
# ---------------------------------------------------------------------------


def _sse(type_: str, data: Any, session_id: int, request_id: str) -> dict[str, str]:
    """Format one SSE event the way lib/api.ts parses it."""
    return {"data": json.dumps({"type": type_, "data": data, "session_id": session_id, "request_id": request_id})}


def _build_user_content(message: str, attachments: Optional[list[dict[str, Any]]]) -> Any:
    if not attachments:
        return message
    blocks: list[dict[str, Any]] = [{"type": "text", "text": message}]
    for img in attachments:
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img.get("data", "")},
            }
        )
    return blocks


async def _run_agent(
    session: _Session,
    message: str,
    model: str,
    system_prompt: str,
    attachments: Optional[list[dict[str, Any]]],
    request_id: str,
) -> AsyncGenerator[dict[str, str], None]:
    """Drive the query loop for one user turn, yielding SSE events."""
    yield _sse("start", {}, session.id, request_id)

    tools = get_project_tools()
    user_content = _build_user_content(message, attachments)
    user_msg = Q._create_user_message(user_content)
    session.agent_messages.append(user_msg)

    ctx = ToolUseContext(
        options=ToolUseContextOptions(
            tools=tools,
            main_loop_model=model,
            is_non_interactive_session=True,
        ),
        abort_controller=asyncio.Event(),
        read_file_state={},
    )
    params = Q.QueryParams(
        messages=list(session.agent_messages),
        system_prompt=system_prompt,
        user_context={},
        system_context={},
        can_use_tool=lambda *a, **k: {"behavior": "allow"},
        tool_use_context=ctx,
        deps=Q.production_deps(call_model=call_model),
    )

    assistant_text_parts: list[str] = []
    tool_names: dict[str, str] = {}
    new_envelopes: list[dict[str, Any]] = []

    try:
        async for ev in Q.query(params):
            if isinstance(ev, Q.Terminal):
                if ev.reason == "model_error":
                    yield _sse("error", str(ev.error) if ev.error else "Model error", session.id, request_id)
                break
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")

            if etype == "stream_delta":
                text = ev.get("text", "")
                if text:
                    yield _sse("chunk", text, session.id, request_id)

            elif etype == "assistant":
                new_envelopes.append(ev)
                for block in ev.get("message", {}).get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and not assistant_text_parts:
                        # If the model streamed no deltas, surface the final text.
                        pass
                    if block.get("type") == "tool_use":
                        tid = block.get("id", "")
                        tool_names[tid] = block.get("name", "")
                        yield _sse("tool", {"id": tid, "name": block.get("name", ""), "input": block.get("input", {})}, session.id, request_id)
                # Track full assistant text for persistence.
                for block in ev.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_text_parts.append(block.get("text", ""))

            elif etype == "user":
                # Tool result envelope — surface result text per tool_use_id.
                new_envelopes.append(ev)
                for block in ev.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        content = block.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(
                                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                            )
                        result = str(content)
                        yield _sse("tool_result", {"id": tid, "result": result[:4000]}, session.id, request_id)

    except Exception as exc:  # noqa: BLE001
        yield _sse("error", f"{type(exc).__name__}: {exc}", session.id, request_id)
        return

    # Persist this turn into the session (UI ChatMessage shape + agent envelopes).
    session.agent_messages.extend(new_envelopes)
    final_text = "".join(assistant_text_parts).strip()
    session.messages.append(
        {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": message,
            "tools": [],
            "isStreaming": False,
            "isError": False,
        }
    )
    session.messages.append(
        {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": final_text,
            "tools": [{"id": tid, "name": name} for tid, name in tool_names.items()],
            "isStreaming": False,
            "isError": False,
        }
    )
    if session.title is None:
        session.title = (message[:48] + "…") if len(message) > 48 else message

    yield _sse("done", {}, session.id, request_id)


@app.post("/chat")
async def chat(request: Request, body: dict[str, Any], _: None = Depends(require_auth)) -> EventSourceResponse:
    message = body.get("message", "")
    session = _get_or_create_session(body.get("session_id"))
    model = body.get("model") or DEFAULT_MODEL
    system_prompt = body.get("system_prompt") or OPTIMUS_SYSTEM_PROMPT
    attachments = body.get("attachments")
    request_id = str(uuid.uuid4())

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        async for evt in _run_agent(session, message, model, system_prompt, attachments, request_id):
            if await request.is_disconnected():
                break
            yield evt

    return EventSourceResponse(event_stream())


def main() -> None:
    import uvicorn

    port = int(os.environ.get("OPTIMUS_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
