"""
optimus/llm_client.py — unified multi-provider LLM routing.

Ported from SPEDA Mark VI (packages/api/app/services/llm_client.py), adapted
to optimus: no `settings` object here, so provider credentials come straight
from environment variables, and the Anthropic path stays in optimus/api.py
(this module never talks to the Anthropic SDK).

Routing is driven by the model ref string: "provider:model"
(e.g. "openai:gpt-5.1", "gemini:gemini-2.5-flash", "ollama:llama3.1:8b").
A bare model name routes to Anthropic, so all existing refs keep working.

Internally optimus speaks Anthropic content-block format exclusively —
tool_use / tool_result blocks, stop reasons end_turn / tool_use / max_tokens.
This module translates to and from each provider's wire format at the request
boundary ONLY, and returns objects with the exact attribute surface of the
Anthropic SDK types that api.call_model() already consumes (.content blocks,
.stop_reason, .usage). Anthropic calls never enter this module — zero
degradation on the primary path.

OpenAI, Gemini, z.ai (GLM), DeepSeek and Ollama all share one adapter:
OpenAI's own API, Gemini's official OpenAI-compatibility endpoint, z.ai's
paas/v4 endpoint, DeepSeek's api.deepseek.com endpoint, and Ollama's /v1
endpoint all speak the same chat-completions dialect, so a single translation
layer covers them. GLM and DeepSeek-V4 both default to "thinking" mode on and
both disable it via the same extra_body toggle; DeepSeek additionally forces
non-thinking whenever tools are present, because V4 thinking mode is
incompatible with the tool loop (see to_openai_params).

Fallback: LLM_FALLBACK_CHAIN in the environment lists "provider:model" refs
tried in order when a provider call fails (auth, rate limit, connection, 5xx).
For streaming, fallback applies while opening the stream — once tokens are
flowing the response cannot be restarted on another provider.

Environment variables:
    OPENAI_API_KEY      — enables the "openai" provider
    GEMINI_API_KEY      — enables the "gemini" provider
    ZAI_API_KEY         — enables the "zai" provider
    DEEPSEEK_API_KEY    — enables the "deepseek" provider
    OLLAMA_BASE_URL     — Ollama /v1 endpoint (default http://localhost:11434/v1)
    LLM_FALLBACK_CHAIN  — comma-separated "provider:model" refs
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("optimus.llm_client")


def _ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"


# Provider name → AsyncOpenAI constructor kwargs. Evaluated lazily so env
# changes are picked up at first use, not import time.
_OPENAI_COMPAT = {
    "openai": lambda: {"api_key": os.environ.get("OPENAI_API_KEY", "")},
    "gemini": lambda: {
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    "zai": lambda: {
        "api_key": os.environ.get("ZAI_API_KEY", ""),
        "base_url": "https://api.z.ai/api/paas/v4/",
    },
    "deepseek": lambda: {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com",
    },
    "ollama": lambda: {"api_key": "ollama", "base_url": _ollama_base_url()},
}
_PROVIDERS = {"anthropic", *_OPENAI_COMPAT}

# OpenAI finish_reason → Anthropic stop_reason. There is no chat-completions
# analogue of pause_turn (that is Anthropic server-tools only).
_FINISH_TO_STOP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
}


def parse_model_ref(ref: str) -> tuple[str, str]:
    """Split "provider:model" → (provider, model). Bare names are Anthropic.
    Only the first segment is checked, so Ollama tags like "llama3.1:8b"
    survive inside "ollama:llama3.1:8b"."""
    provider, sep, rest = ref.partition(":")
    if sep and provider in _PROVIDERS:
        return provider, rest
    return "anthropic", ref


def fallback_chain(model_ref: str) -> list[tuple[str, str]]:
    """Primary (provider, model) followed by the LLM_FALLBACK_CHAIN entries."""
    chain = [parse_model_ref(model_ref)]
    for ref in (os.environ.get("LLM_FALLBACK_CHAIN") or "").split(","):
        ref = ref.strip()
        if ref:
            entry = parse_model_ref(ref)
            if entry not in chain:
                chain.append(entry)
    return chain


# ── Normalized response types ────────────────────────────────────────────────
# Attribute-compatible with the Anthropic SDK objects api.call_model() already
# consumes: block.type/.text/.id/.name/.input, message .id/.model/.stop_reason/
# .stop_sequence, and usage .input_tokens/.output_tokens.


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class LLMMessage:
    content: list
    stop_reason: str
    model: str = ""
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:24]}")
    stop_sequence: Optional[str] = None
    usage: Usage = field(default_factory=Usage)


# Per-provider client cache (AsyncOpenAI instances are cheap but reusable).
_compat_clients: dict[str, Any] = {}


def get_compat_client(provider: str):
    """AsyncOpenAI client for an OpenAI-compatible provider (lazy, cached)."""
    if provider not in _compat_clients:
        from openai import AsyncOpenAI  # lazy — only needed off the Anthropic path

        _compat_clients[provider] = AsyncOpenAI(**_OPENAI_COMPAT[provider]())
    return _compat_clients[provider]


async def create_via_compat(provider: str, model: str, kwargs: dict) -> LLMMessage:
    """Non-streaming chat-completions call. `kwargs` are Anthropic Messages API
    kwargs (system, messages, tools, max_tokens); returns an LLMMessage."""
    client = get_compat_client(provider)
    params = to_openai_params(provider, model, kwargs)
    resp = await client.chat.completions.create(**params)
    choice = resp.choices[0]
    blocks: list = []
    if choice.message.content:
        blocks.append(TextBlock(text=choice.message.content))
    for tc in choice.message.tool_calls or []:
        blocks.append(
            ToolUseBlock(
                id=tc.id or _gen_tool_id(),
                name=tc.function.name,
                input=_parse_tool_args(tc.function.arguments, tc.function.name),
            )
        )
    return LLMMessage(
        content=blocks,
        stop_reason=_FINISH_TO_STOP.get(choice.finish_reason, "end_turn"),
        model=f"{provider}:{model}",
        usage=_usage_from(resp.usage),
    )


# ── Model catalog ────────────────────────────────────────────────────────────
# One entry per selectable model; `id` is the routing ref passed as --model.
# Anthropic ids stay bare for backward compatibility.

_CATALOG = {
    "anthropic": [
        {
            "id": "claude-opus-4-8",
            "name": "Claude Opus 4.8",
            "description": "Most capable — complex reasoning & deep analysis",
            "tags": ["powerful"],
        },
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "description": "Smart and efficient for most tasks",
            "tags": ["fast", "default"],
        },
        {
            "id": "claude-haiku-4-5-20251001",
            "name": "Claude Haiku 4.5",
            "description": "Fastest — great for simple, quick tasks",
            "tags": ["fastest"],
        },
    ],
    "openai": [
        {
            "id": "openai:gpt-5.1",
            "name": "GPT-5.1",
            "description": "OpenAI flagship — strong reasoning",
            "tags": ["powerful"],
        },
        {
            "id": "openai:gpt-5-mini",
            "name": "GPT-5 Mini",
            "description": "Fast and inexpensive for everyday tasks",
            "tags": ["fast"],
        },
    ],
    "gemini": [
        {
            "id": "gemini:gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "description": "Google's most capable — long context",
            "tags": ["powerful"],
        },
        {
            "id": "gemini:gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "description": "Fast and inexpensive for everyday tasks",
            "tags": ["fast"],
        },
    ],
    "zai": [
        {
            "id": "zai:glm-5.2",
            "name": "GLM-5.2",
            "description": "Zhipu flagship — long-horizon agentic coding, 256K context",
            "tags": ["powerful", "default"],
        },
        {
            "id": "zai:glm-4.6",
            "name": "GLM-4.6",
            "description": "Prior flagship — strong agentic coding & tool use, 200K context",
            "tags": ["powerful"],
        },
        {
            "id": "zai:glm-4.5-air",
            "name": "GLM-4.5 Air",
            "description": "Lightweight and inexpensive for everyday tasks",
            "tags": ["fast"],
        },
    ],
    "deepseek": [
        {
            "id": "deepseek:deepseek-v4-pro",
            "name": "DeepSeek V4 Pro",
            "description": "DeepSeek flagship — 1M context, agentic tool use (non-thinking for tools)",
            "tags": ["powerful", "default"],
        },
        {
            "id": "deepseek:deepseek-v4-flash",
            "name": "DeepSeek V4 Flash",
            "description": "Fast and very inexpensive — 1M context, aggressive context caching",
            "tags": ["fast"],
        },
    ],
}


# Live models-endpoint listing is best-effort: a slow or absent endpoint must
# never hang the /model command, so every provider call is capped here.
_MODELS_TIMEOUT = 6.0


def _catalog_meta(provider: str) -> dict[str, dict]:
    """Catalog entries for a provider keyed by routing id — used to enrich
    live listings with names/descriptions/tags where we know them."""
    return {m["id"]: m for m in _CATALOG.get(provider, [])}


async def _live_anthropic_models() -> list[dict]:
    """GET /v1/models via the Anthropic SDK (paginated; 100 covers the fleet)."""
    from optimus.api import _get_client  # lazy — avoids the api↔llm_client cycle

    page = await _get_client().models.list(limit=100)
    meta = _catalog_meta("anthropic")
    out = []
    for m in page.data:
        known = meta.get(m.id, {})
        out.append({
            "id": m.id,
            "name": known.get("name") or getattr(m, "display_name", None) or m.id,
            "description": known.get("description", ""),
            "tags": known.get("tags", []),
            "provider": "anthropic",
        })
    return out


async def _live_compat_models(provider: str) -> list[dict]:
    """GET {base_url}/models via the OpenAI SDK — one shape for openai, gemini
    (official compat layer), zai and deepseek."""
    page = await get_compat_client(provider).models.list()
    meta = _catalog_meta(provider)
    out = []
    for m in page.data:
        mid = m.id
        # Gemini's compat layer returns "models/gemini-…"; the chat endpoint
        # accepts the bare name, which is also what our routing refs use.
        if provider == "gemini" and mid.startswith("models/"):
            mid = mid[len("models/"):]
        ref = f"{provider}:{mid}"
        known = meta.get(ref, {})
        out.append({
            "id": ref,
            "name": known.get("name") or mid,
            "description": known.get("description", ""),
            "tags": known.get("tags", []),
            "provider": provider,
        })
    return out


async def _live_ollama_models() -> list[dict]:
    """GET /api/tags on the local daemon. Not running is the normal case."""
    import httpx

    base = _ollama_base_url().rstrip("/").removesuffix("/v1")
    async with httpx.AsyncClient(timeout=1.5) as client:
        resp = await client.get(f"{base}/api/tags")
        resp.raise_for_status()
        return [
            {
                "id": f"ollama:{m['name']}",
                "name": m["name"],
                "description": "Local weights — operational with zero uplink",
                "tags": ["local"],
                "provider": "ollama",
            }
            for m in resp.json().get("models", [])
        ]


async def available_models(live: bool = True) -> list[dict]:
    """Selectable models across all CONFIGURED providers.

    A provider appears only when usable: Anthropic when an API key / oauth
    token is present, OpenAI/Gemini/z.ai/DeepSeek when their API key is set,
    Ollama when the local daemon answers.

    With live=True (default) each configured provider's own models endpoint is
    queried concurrently, so the list is exactly what the endpoint provides
    today; the static _CATALOG only enriches known ids with descriptions and
    serves as the per-provider fallback when an endpoint call fails."""
    # Lazy import avoids a cycle (api.py imports this module at top level).
    try:
        from optimus.api import _get_anthropic_api_key, _get_oauth_access_token

        anthropic_ok = bool(_get_oauth_access_token() or _get_anthropic_api_key())
    except Exception:
        anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))

    configured: list[str] = (["anthropic"] if anthropic_ok else [])
    configured += [
        p for p in ("openai", "gemini", "zai", "deepseek")
        if _OPENAI_COMPAT[p]()["api_key"]
    ]

    async def fetch(provider: str) -> list[dict]:
        if live:
            try:
                fetcher = (
                    _live_anthropic_models()
                    if provider == "anthropic"
                    else _live_compat_models(provider)
                )
                models = await asyncio.wait_for(fetcher, _MODELS_TIMEOUT)
                if models:
                    return models
            except Exception as exc:  # noqa: BLE001 — endpoint down ≠ provider gone
                logger.debug("live model listing failed for %s: %s", provider, exc)
        return [{**m, "provider": provider} for m in _CATALOG.get(provider, [])]

    async def fetch_ollama() -> list[dict]:
        try:
            return await asyncio.wait_for(_live_ollama_models(), _MODELS_TIMEOUT)
        except Exception:  # noqa: BLE001 — daemon not running is the normal case
            return []

    results = await asyncio.gather(
        *(fetch(p) for p in configured), fetch_ollama()
    )
    return [m for models in results for m in models]


# ── Anthropic-format → chat-completions translation ─────────────────────────


def to_openai_params(provider: str, model: str, kwargs: dict) -> dict:
    msgs: list[dict] = []

    system = kwargs.get("system")
    if isinstance(system, list):
        # System blocks. `cache_control` markers are Anthropic prompt-cache
        # hints — meaningless here, just join the text.
        system = "\n\n".join(
            b.get("text", "") for b in system if isinstance(b, dict)
        )
    if system:
        msgs.append({"role": "system", "content": system})

    for m in kwargs.get("messages", []):
        msgs.extend(_translate_message(m))

    params: dict = {"model": model, "messages": msgs}

    tools = kwargs.get("tools")
    if tools:
        params["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object"}),
                },
            }
            for t in tools
        ]

    max_tokens = kwargs.get("max_tokens")
    if max_tokens:
        # OpenAI deprecated max_tokens (reasoning models reject it); Gemini's
        # compat layer and Ollama still expect it.
        if provider == "openai":
            params["max_completion_tokens"] = max_tokens
        else:
            params["max_tokens"] = max_tokens

    # Reasoning-effort hint — lets short background tasks (e.g. WebFetch
    # summarization) work on reasoning models. Without it, a GPT-5 /
    # Gemini-2.5 model spends its whole token budget on hidden reasoning and
    # returns EMPTY visible content. Only openai and gemini document this
    # param; Ollama (local, non-reasoning) is left alone.
    reasoning_effort = kwargs.get("reasoning_effort")
    if reasoning_effort and provider in ("openai", "gemini"):
        params["reasoning_effort"] = reasoning_effort

    # z.ai GLM thinking control. GLM defaults thinking ON, so a short
    # background task burns the whole budget on hidden reasoning and returns
    # EMPTY visible content. Every GLM generation accepts the explicit
    # `thinking:{type}` toggle, so route through it rather than
    # `reasoning_effort` (GLM-4.x has no such param; GLM-5.2's rejects
    # "minimal"). extra_body is how the OpenAI SDK forwards a non-OpenAI
    # request field.
    if provider == "zai" and reasoning_effort in ("minimal", "low", "none"):
        params["extra_body"] = {"thinking": {"type": "disabled"}}

    # DeepSeek-V4 thinking control. V4 enables thinking BY DEFAULT, and
    # thinking mode is fundamentally incompatible with the agentic tool loop:
    # V4 rejects tool_choice in thinking mode and makes `reasoning_content` a
    # REQUIRED protocol field once tool_use enters the history — which the
    # multi-turn loop does not round-trip (chain-of-thought is intentionally
    # dropped). So whenever tools are in play — i.e. the entire main loop —
    # force non-thinking via the same extra_body toggle GLM uses. Also force
    # it for a low/minimal background hint. Only a genuine high/max hint on a
    # TOOL-FREE call keeps thinking on.
    if provider == "deepseek":
        if tools or reasoning_effort in ("minimal", "low", "none"):
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        elif reasoning_effort in ("high", "max"):
            params["reasoning_effort"] = reasoning_effort

    return params


def _translate_message(message: dict) -> list[dict]:
    """One Anthropic-format message → one or more chat-completions messages.
    tool_result blocks become role:"tool" messages, which must directly follow
    the assistant message carrying the matching tool_calls — Anthropic's
    history puts them in the very next user message, so emitting them first
    preserves that adjacency. thinking blocks are dropped (no analogue)."""
    role = message["role"]
    content = message.get("content")
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    tool_msgs: list[dict] = []
    user_parts: list[dict] = []
    assistant_text: list[str] = []
    tool_calls: list[dict] = []

    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            if role == "assistant":
                assistant_text.append(block.get("text", ""))
            else:
                user_parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            src = block.get("source", {})
            if src.get("type") == "base64" and src.get("data"):
                user_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{src.get('media_type', 'image/png')};"
                            f"base64,{src['data']}"
                        },
                    }
                )
        elif btype == "tool_use":
            tool_calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
        elif btype == "tool_result":
            rc = block.get("content", "")
            if isinstance(rc, list):
                rc = "\n".join(p.get("text", "") for p in rc if isinstance(p, dict))
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": rc if isinstance(rc, str) else str(rc),
                }
            )

    out: list[dict] = []
    if role == "assistant":
        text = "\n".join(assistant_text)
        if tool_calls:
            # Assistant tool-call message. `content` must be a STRING here,
            # never null: z.ai GLM rejects `content: null` with error 1214
            # ("messages parameter is illegal"), which breaks the agent loop
            # the moment any tool is used. An empty string is valid for every
            # OpenAI-compatible provider when tool_calls are present.
            out.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
        elif text:
            out.append({"role": "assistant", "content": text})
    else:
        out.extend(tool_msgs)
        if user_parts:
            if all(p["type"] == "text" for p in user_parts):
                out.append(
                    {"role": role, "content": "\n\n".join(p["text"] for p in user_parts)}
                )
            else:
                out.append({"role": role, "content": user_parts})
    return out


def _parse_tool_args(raw: Optional[str], tool_name: str) -> dict:
    # The Anthropic SDK hands tool input pre-parsed; chat-completions providers
    # send a JSON string, which open-weight models occasionally truncate.
    try:
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        logger.warning("llm_tool_args_unparseable tool=%s", tool_name)
        return {}


def _gen_tool_id() -> str:
    # Gemini's compat layer can omit tool-call ids; the internal format requires
    # one to pair tool_use with tool_result. Generated, never hardcoded.
    return f"call_{uuid.uuid4().hex[:24]}"


def _usage_from(u) -> Usage:
    if u is None:
        return Usage()
    details = getattr(u, "prompt_tokens_details", None)
    # OpenAI/Gemini report cache reads under prompt_tokens_details.cached_tokens;
    # DeepSeek (whose cache is a headline cost feature) reports them directly on
    # the usage object as prompt_cache_hit_tokens. Prefer whichever is present.
    cached = getattr(details, "cached_tokens", 0) or 0
    cached = cached or (getattr(u, "prompt_cache_hit_tokens", 0) or 0)
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read_input_tokens=cached,
    )


# ── Streaming ────────────────────────────────────────────────────────────────


class OpenAICompatStream:
    """Chat-completions stream exposing the Anthropic stream surface that
    api.call_model() consumes: .text_stream and get_final_message()."""

    def __init__(self, client, params: dict, provider: str, model: str) -> None:
        self._client = client
        self._params = params
        self._provider = provider
        self._model = model
        self._raw = None
        self._text: list[str] = []
        self._tool_calls: dict[int, dict] = {}
        self._finish: Optional[str] = None
        self._usage = Usage()
        self._consumed = False

    async def open(self) -> None:
        """Send the request. Auth/rate-limit/connection failures surface here,
        so the caller can fall back to the next provider in the chain."""
        params = dict(self._params, stream=True)
        if self._provider != "gemini":  # Gemini's compat layer rejects it
            params["stream_options"] = {"include_usage": True}
        self._raw = await self._client.chat.completions.create(**params)

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._consume()

    async def _consume(self) -> AsyncIterator[str]:
        async for chunk in self._raw:
            if getattr(chunk, "usage", None):
                self._usage = _usage_from(chunk.usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                self._finish = choice.finish_reason
            delta = choice.delta
            if delta is None:
                continue
            if delta.content:
                self._text.append(delta.content)
                yield delta.content
            for tc in delta.tool_calls or []:
                acc = self._tool_calls.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": ""}
                )
                if tc.id:
                    acc["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        acc["name"] = tc.function.name
                    if tc.function.arguments:
                        acc["arguments"] += tc.function.arguments
        self._consumed = True

    async def get_final_message(self) -> LLMMessage:
        if not self._consumed:  # drain remainder if text_stream wasn't finished
            async for _ in self._consume():
                pass
        blocks: list = []
        text = "".join(self._text)
        if text:
            blocks.append(TextBlock(text=text))
        for idx in sorted(self._tool_calls):
            acc = self._tool_calls[idx]
            blocks.append(
                ToolUseBlock(
                    id=acc["id"] or _gen_tool_id(),
                    name=acc["name"],
                    input=_parse_tool_args(acc["arguments"], acc["name"]),
                )
            )
        return LLMMessage(
            content=blocks,
            stop_reason=_FINISH_TO_STOP.get(self._finish, "end_turn"),
            model=f"{self._provider}:{self._model}",
            usage=self._usage,
        )

    async def aclose(self) -> None:
        if self._raw is not None:
            await self._raw.close()


def open_compat_stream(provider: str, model: str, kwargs: dict) -> OpenAICompatStream:
    """Build (but do not open) a streaming handle for an OpenAI-compatible
    provider. `kwargs` are Anthropic Messages API kwargs."""
    return OpenAICompatStream(
        get_compat_client(provider),
        to_openai_params(provider, model, kwargs),
        provider,
        model,
    )
