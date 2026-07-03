"""
optimus/api.py — port of src/utils/api.ts

The real call_model() function that wraps the Anthropic SDK.
query_loop() calls this via QueryDeps.call_model.

Multi-provider support (ported from SPEDA Mark VI): the model option is a
"provider:model" ref — "openai:gpt-5.1", "gemini:gemini-2.5-flash",
"zai:glm-5.2", "deepseek:deepseek-v4-pro", "ollama:llama3.1:8b". A bare model
name routes to Anthropic exactly as before. Non-Anthropic refs are served by
optimus.llm_client through each provider's OpenAI-compatible endpoint and
translated back into the same yield format, so query_loop() never notices.
LLM_FALLBACK_CHAIN (comma-separated refs) is tried in order when a provider
fails while opening the stream.

Expected yield format (one message per API call, matching the TS callModel shape):
    {
        'type': 'assistant',
        'message': {
            'id': str,
            'role': 'assistant',
            'content': [{'type': 'text', 'text': str} | {'type': 'tool_use', ...}],
            'model': str,
            'stop_reason': str,
            'usage': {'input_tokens': int, 'output_tokens': int},
        }
    }
"""

from __future__ import annotations

import os
from typing import Any, AsyncGenerator, Optional

import anthropic

from optimus import llm_client


# ---------------------------------------------------------------------------
# Auth — partial port of getAnthropicApiKey / isClaudeAISubscriber (auth.ts)
# ---------------------------------------------------------------------------
# RE-ENTRY: full auth.ts (keychain, apiKeyHelper, oauth scopes, approval lists).
# This covers the realistic external-build paths: ANTHROPIC_API_KEY env,
# config.primaryApiKey (/login managed key), oauth bearer (ANTHROPIC_AUTH_TOKEN
# or the FD-sourced token in bootstrap state).


def _get_oauth_access_token() -> Optional[str]:
    """OAuth bearer token, if present (env or FD-sourced session token)."""
    env_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if env_token:
        return env_token
    try:
        from optimus.bootstrap.state import get_oauth_token_from_fd

        return get_oauth_token_from_fd() or None
    except Exception:
        return None


def _get_anthropic_api_key() -> Optional[str]:
    """Mirror getAnthropicApiKey(): env key, else config primaryApiKey, else None."""
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    try:
        from optimus.utils.config import get_global_config

        primary = get_global_config().get("primaryApiKey")
        if primary:
            return primary
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# query_fast_model — one-shot non-streaming call (WebFetch summarization, etc.)
# Mirrors queryHaiku() from services/api/claude.ts.
# ---------------------------------------------------------------------------


async def query_fast_model(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: str = "claude-haiku-4-5",
    max_tokens: int = 2048,
) -> str:
    """Run a single non-streaming completion and return the text."""
    kwargs: dict[str, Any] = {
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    last_exc: Optional[Exception] = None
    for provider, provider_model in llm_client.fallback_chain(model):
        try:
            if provider == "anthropic":
                client = _get_client()
                msg = await client.messages.create(**kwargs, model=provider_model)
            else:
                # Short one-shot task: cap hidden reasoning so the visible
                # output isn't starved (see llm_client.to_openai_params).
                msg = await llm_client.create_via_compat(
                    provider, provider_model, {**kwargs, "reasoning_effort": "low"}
                )
            return "".join(
                b.text for b in msg.content if getattr(b, "type", None) == "text"
            )
        except Exception as exc:
            last_exc = exc
    raise last_exc  # chain exhausted


async def run_web_search(
    query: str,
    *,
    allowed_domains: Optional[list] = None,
    blocked_domains: Optional[list] = None,
    model: str = "claude-haiku-4-5",
    max_uses: int = 8,
) -> list[Any]:
    """
    Run the Anthropic server-side web_search tool and return the response content
    blocks (server_tool_use / web_search_tool_result / text). Mirrors WebSearchTool.
    """
    client = _get_client()
    tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    if blocked_domains:
        tool["blocked_domains"] = blocked_domains
    msg = await client.messages.create(
        model=model,
        max_tokens=4096,
        system="You are an assistant for performing a web search tool use",
        messages=[{"role": "user", "content": f"Perform a web search for the query: {query}"}],
        tools=[tool],
    )
    return list(msg.content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CredentialsError(Exception):
    """No usable Anthropic credentials — carries actionable guidance."""


_NO_CREDENTIALS_MESSAGE = """\
No Anthropic credentials found. Fix one of:
  1. Set ANTHROPIC_API_KEY in your environment (or in a .env next to the optimus package)
  2. Set ANTHROPIC_AUTH_TOKEN (OAuth bearer token)
  3. Add "primaryApiKey" to ~/.claude.json
  4. Use another provider via --model provider:model —
     openai:gpt-5-mini (OPENAI_API_KEY), gemini:gemini-2.5-flash (GEMINI_API_KEY),
     zai:glm-4.5-air (ZAI_API_KEY), deepseek:deepseek-v4-flash (DEEPSEEK_API_KEY),
     or ollama:<model> (local, free — no key needed)"""


def _get_client() -> anthropic.AsyncAnthropic:
    """Return a configured AsyncAnthropic client (oauth bearer or API key)."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url

    # OAuth subscriber path takes precedence (apiKey must be None when set).
    oauth_token = _get_oauth_access_token()
    if oauth_token:
        kwargs["auth_token"] = oauth_token
    else:
        api_key = _get_anthropic_api_key()
        if api_key:
            kwargs["api_key"] = api_key
        else:
            # Fail here with guidance instead of letting the SDK raise its
            # cryptic "Could not resolve authentication method" later.
            raise CredentialsError(_NO_CREDENTIALS_MESSAGE)
    return anthropic.AsyncAnthropic(**kwargs)


async def _convert_tools(tools: list) -> list[dict]:
    """
    Convert optimus Tool objects to the Anthropic API tools format.
    Each tool must have .name, .description() (async), and .input_schema.
    """
    result = []
    for tool in tools:
        try:
            description = tool.description
            if callable(description):
                # description is an async method — must be awaited to get the str.
                description = await description()
            result.append({
                "name": tool.name,
                "description": description,
                "input_schema": tool.input_schema if hasattr(tool, "input_schema") else {"type": "object", "properties": {}},
            })
        except Exception:
            pass
    return result


def _convert_messages(messages: list) -> list[dict]:
    """
    Normalise the messages list to the plain {role, content} format the Anthropic
    API expects.

    The query loop carries internal message *envelopes*:
        {'type': 'user'|'assistant', 'message': {'role', 'content'}, 'uuid', ...}
    where role/content live under 'message'. It may also carry already-flat
    {'role', 'content'} dicts. Both forms are handled here; non-user/assistant
    envelopes (attachments, tombstones, system) are dropped — system text is
    passed separately, and tool_result/tool_use blocks ride inside content.
    """
    result = []
    for msg in messages:
        role: Any = None
        content: Any = None
        if isinstance(msg, dict):
            if isinstance(msg.get("message"), dict):
                # Internal envelope — unwrap the nested message.
                inner = msg["message"]
                role = inner.get("role")
                content = inner.get("content")
            else:
                # Already-flat {role, content}.
                role = msg.get("role")
                content = msg.get("content")
        elif hasattr(msg, "role") and hasattr(msg, "content"):
            role = msg.role
            content = msg.content

        if role not in ("user", "assistant"):
            continue
        if content is None:
            content = ""
        # Pass strings and block-lists through unchanged; the API accepts both.
        result.append({"role": role, "content": content})
    return result


# ---------------------------------------------------------------------------
# call_model() — the production implementation of QueryDeps.call_model
# ---------------------------------------------------------------------------

async def call_model(
    *,
    messages: list,
    system_prompt: list,
    thinking_config: dict,
    tools: list,
    abort_event: Any,
    options: dict,
) -> AsyncGenerator[dict, None]:
    """
    Port of callModel() from src/utils/api.ts.

    Calls the Anthropic messages API and yields one assistant message dict
    in the format query_loop() expects.

    Parameters match how query_loop() invokes deps.call_model():
        messages        — normalised conversation history
        system_prompt   — list of system prompt strings
        thinking_config — {'type': 'adaptive'|'enabled'|'disabled'}
        tools           — list of Tool objects
        abort_event     — asyncio.Event (set → cancel)
        options         — dict with 'model', 'max_output_tokens_override', etc.
    """
    model: str = options.get("model", "claude-sonnet-5")
    max_tokens: int = options.get("max_output_tokens_override") or 8096

    # Build system string
    system_str = "\n\n".join(s for s in system_prompt if isinstance(s, str) and s.strip())

    # Normalise messages
    api_messages = _convert_messages(messages)
    if not api_messages:
        # Fallback: wrap the last item as a user message
        api_messages = [{"role": "user", "content": "Hello"}]

    # Convert tools
    api_tools = await _convert_tools(tools)

    # Build kwargs in Anthropic Messages format — the internal lingua franca.
    # llm_client translates these at the wire boundary for other providers.
    kwargs: dict[str, Any] = {
        "max_tokens": max_tokens,
        "messages": api_messages,
    }
    if system_str:
        kwargs["system"] = system_str
    if api_tools:
        kwargs["tools"] = api_tools

    thinking_type = thinking_config.get("type", "disabled") if thinking_config else "disabled"

    # Open a stream, trying each (provider, model) in the fallback chain.
    # Fallback applies only while opening — once tokens are flowing the
    # response cannot be restarted on another provider.
    anthropic_cm: Any = None
    compat_stream: Any = None
    stream: Any = None
    last_exc: Optional[Exception] = None
    for provider, provider_model in llm_client.fallback_chain(model):
        try:
            if provider == "anthropic":
                anthro = dict(kwargs, model=provider_model)
                # Extended thinking is Anthropic-only; other providers manage
                # reasoning via their own toggles (see llm_client).
                if thinking_type in ("enabled", "adaptive"):
                    anthro["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": min(max_tokens // 2, 10000),
                    }
                anthropic_cm = _get_client().messages.stream(**anthro)
                stream = await anthropic_cm.__aenter__()
            else:
                compat_stream = llm_client.open_compat_stream(provider, provider_model, kwargs)
                await compat_stream.open()
                stream = compat_stream
            break
        except Exception as exc:
            anthropic_cm = compat_stream = None
            last_exc = exc
    if stream is None:
        raise last_exc  # chain exhausted

    try:
        # Yield partial text events as stream events so the REPL can
        # display text as it arrives (mirrors TS callModel streaming)
        async for text in stream.text_stream:
            if abort_event is not None and hasattr(abort_event, "is_set") and abort_event.is_set():
                break
            # Yield a stream-delta event for live display
            yield {
                "type": "stream_delta",
                "text": text,
            }

        # Yield the final complete assistant message
        final = await stream.get_final_message()
    finally:
        if anthropic_cm is not None:
            await anthropic_cm.__aexit__(None, None, None)
        elif compat_stream is not None:
            await compat_stream.aclose()

    # Convert SDK ContentBlock objects to plain dicts
    content_blocks = []
    for block in final.content:
        if block.type == "text":
            content_blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content_blocks.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        elif block.type == "thinking":
            content_blocks.append({"type": "thinking", "thinking": getattr(block, "thinking", "")})

    yield {
        "type": "assistant",
        "message": {
            "id": final.id,
            "role": "assistant",
            "content": content_blocks,
            "model": final.model,
            "stop_reason": final.stop_reason,
            "stop_sequence": final.stop_sequence,
            "usage": {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            },
        },
    }
