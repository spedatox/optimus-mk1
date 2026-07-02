"""
query.py — port of src/query.ts

The agentic query loop.  Drives the full model↔tool cycle for one user turn:

  query() → query_loop() [while True]
    1. Apply tool-result budget
    2. Microcompact / autocompact (feature-gated, all False for now)
    3. Check blocking token limit
    4. Call model (streaming)
    5. Collect tool_use blocks
    6. Execute tools
    7. Attach memory / queued commands
    8. Loop with updated State, or return Terminal

Porting notes:
  - TypeScript async generators (yield / yield* / return) map 1:1 to
    Python async generators (yield / async for … yield / return).
  - All feature() gates compile to False; the branches are preserved but
    dormant — ready to activate when the corresponding modules are ported.
  - Analytics (logEvent / logAntError / logForDebugging) → no-op omitted.
  - AbortController → asyncio.Event (is_set() mirrors .signal.aborted).
  - deps injection pattern preserved; productionDeps() wires the real impls.
"""
from __future__ import annotations

import asyncio
import uuid as _uuid_mod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Optional

from optimus.Tool import (
    ToolUseContext,
    QueryChainTracking,
    find_tool_by_name,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Feature gates — all False in Mark I
# ---------------------------------------------------------------------------

def _feature(_name: str) -> bool:
    """All experimental feature gates are off in Optimus Mark I."""
    return False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_OUTPUT_TOKENS_RECOVERY_LIMIT = 3


# ---------------------------------------------------------------------------
# Message type aliases (mirrors types/message.ts)
# Proper types will be defined when message.ts is ported.
# ---------------------------------------------------------------------------

Message = dict[str, Any]
StreamEvent = dict[str, Any]
RequestStartEvent = dict[str, Any]
AssistantMessage = dict[str, Any]
UserMessage = dict[str, Any]
AttachmentMessage = dict[str, Any]
SystemMessage = dict[str, Any]
TombstoneMessage = dict[str, Any]
ToolUseSummaryMessage = dict[str, Any]
SystemPrompt = str | list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Terminal — the value returned (not yielded) by query_loop()
# ---------------------------------------------------------------------------

@dataclass
class Terminal:
    """
    Mirrors the Terminal type from src/query/transitions.ts.
    Describes why the loop stopped.
    """
    reason: str   # 'completed' | 'aborted_streaming' | 'aborted_tools' |
                  # 'blocking_limit' | 'prompt_too_long' | 'model_error' |
                  # 'max_turns' | 'stop_hook_prevented' | 'hook_stopped' |
                  # 'image_error'
    error: Optional[Exception] = None
    turn_count: Optional[int] = None


# ---------------------------------------------------------------------------
# QueryParams
# ---------------------------------------------------------------------------

@dataclass
class QueryParams:
    """
    Mirrors QueryParams in query.ts.
    Everything the caller provides to start one user turn.
    """
    messages: list[Message]
    system_prompt: SystemPrompt
    user_context: dict[str, str]
    system_context: dict[str, str]
    can_use_tool: Any                         # CanUseToolFn — checked per tool call
    tool_use_context: ToolUseContext
    fallback_model: Optional[str] = None
    query_source: str = 'repl_main_thread'
    max_output_tokens_override: Optional[int] = None
    max_turns: Optional[int] = None
    skip_cache_write: bool = False
    task_budget: Optional[dict[str, int]] = None
    deps: Optional['QueryDeps'] = None


# ---------------------------------------------------------------------------
# State — mutable across loop iterations
# ---------------------------------------------------------------------------

@dataclass
class State:
    """
    Mirrors the internal State type in query.ts.
    The mutable context carried between loop iterations.
    """
    messages: list[Message]
    tool_use_context: ToolUseContext
    auto_compact_tracking: Optional[dict[str, Any]]
    max_output_tokens_recovery_count: int
    has_attempted_reactive_compact: bool
    max_output_tokens_override: Optional[int]
    pending_tool_use_summary: Optional[asyncio.Task]  # Task[ToolUseSummaryMessage | None]
    stop_hook_active: Optional[bool]
    turn_count: int
    transition: Optional[dict[str, Any]]   # Continue reason — None on first iteration


# ---------------------------------------------------------------------------
# AutoCompactTrackingState
# ---------------------------------------------------------------------------

@dataclass
class AutoCompactTrackingState:
    """Mirrors AutoCompactTrackingState from services/compact/autoCompact.ts."""
    compacted: bool
    turn_id: str
    turn_counter: int
    consecutive_failures: int = 0


# ---------------------------------------------------------------------------
# QueryDeps — injectable dependencies (mirrors src/query/deps.ts)
# ---------------------------------------------------------------------------

@dataclass
class QueryDeps:
    """
    Injectable dependencies for query_loop().
    In production these wire the real implementations;
    in tests they can be replaced with fakes.
    """
    call_model: Callable[..., AsyncGenerator[Message | StreamEvent, None]]
    uuid: Callable[[], str] = field(default_factory=lambda: lambda: str(_uuid_mod.uuid4()))
    microcompact: Callable[..., Any] = field(default=None)  # type: ignore[assignment]
    autocompact: Callable[..., Any] = field(default=None)   # type: ignore[assignment]


def production_deps(
    call_model: Callable[..., AsyncGenerator],
) -> QueryDeps:
    """
    Build the production QueryDeps.
    Mirrors productionDeps() in src/query/deps.ts.
    `call_model` must be supplied by the caller (it wraps the Anthropic client).
    """
    async def _noop_microcompact(
        messages: list[Message],
        context: ToolUseContext,
        query_source: str,
    ) -> dict[str, Any]:
        """No-op until microcompact is ported."""
        return {'messages': messages, 'compaction_info': None}

    async def _noop_autocompact(
        messages: list[Message],
        context: ToolUseContext,
        cache_safe_params: dict[str, Any],
        query_source: str,
        tracking: Optional[AutoCompactTrackingState],
        snip_tokens_freed: int,
    ) -> dict[str, Any]:
        """No-op until autocompact is ported."""
        return {'compaction_result': None, 'consecutive_failures': None}

    return QueryDeps(
        call_model=call_model,
        uuid=lambda: str(_uuid_mod.uuid4()),
        microcompact=_noop_microcompact,
        autocompact=_noop_autocompact,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_messages_after_compact_boundary(messages: list[Message]) -> list[Message]:
    """
    Return messages after the most recent compact boundary marker.
    Stub — mirrors getMessagesAfterCompactBoundary() from utils/messages.ts.
    Returns all messages until that function is ported.
    """
    return messages


def _normalize_messages_for_api(
    messages: list[Message],
    tools: list[Any],
) -> list[Message]:
    """
    Convert internal message objects to the shape the API expects.
    Stub — mirrors normalizeMessagesForAPI() from utils/messages.ts.
    """
    return [m for m in messages if m.get('type') in ('user', 'assistant')]


def _prepend_user_context(
    messages: list[Message],
    user_context: dict[str, str],
) -> list[Message]:
    """
    Inject user context into the messages list.
    Stub — mirrors prependUserContext() from utils/api.ts.
    """
    return messages


def _append_system_context(
    system_prompt: SystemPrompt,
    system_context: dict[str, str],
) -> SystemPrompt:
    """
    Append system context to the system prompt.
    Stub — mirrors appendSystemContext() from utils/api.ts.
    """
    return system_prompt


def _create_user_message(
    content: Any,
    *,
    is_meta: bool = False,
    tool_use_result: Any = None,
    source_tool_assistant_uuid: Optional[str] = None,
) -> UserMessage:
    """
    Build a user-role message.
    Stub — mirrors createUserMessage() from utils/messages.ts.
    """
    if isinstance(content, str):
        content_val: Any = [{'type': 'text', 'text': content}]
    else:
        content_val = content
    msg: UserMessage = {
        'type': 'user',
        'message': {'role': 'user', 'content': content_val},
        'uuid': str(_uuid_mod.uuid4()),
        'isMeta': is_meta,
    }
    if tool_use_result is not None:
        msg['toolUseResult'] = tool_use_result
    if source_tool_assistant_uuid is not None:
        msg['sourceToolAssistantUUID'] = source_tool_assistant_uuid
    return msg


def _create_user_interruption_message(*, tool_use: bool) -> UserMessage:
    """Mirrors createUserInterruptionMessage() from utils/messages.ts."""
    text = '[Request interrupted by user]'
    return _create_user_message({'type': 'text', 'text': text})


def _create_assistant_api_error_message(
    *,
    content: str,
    error: Optional[str] = None,
) -> AssistantMessage:
    """Mirrors createAssistantAPIErrorMessage() from utils/messages.ts."""
    return {
        'type': 'assistant',
        'message': {
            'role': 'assistant',
            'content': [{'type': 'text', 'text': content}],
        },
        'uuid': str(_uuid_mod.uuid4()),
        'isApiErrorMessage': True,
        'apiError': error,
    }


def _create_attachment_message(attachment: dict[str, Any]) -> AttachmentMessage:
    """Mirrors createAttachmentMessage() from utils/attachments.ts."""
    return {
        'type': 'attachment',
        'attachment': attachment,
        'uuid': str(_uuid_mod.uuid4()),
    }


def _is_prompt_too_long_message(msg: Optional[Message]) -> bool:
    """Mirrors isPromptTooLongMessage() from services/api/errors.ts."""
    if msg is None:
        return False
    return msg.get('apiError') in ('prompt_too_long', 'invalid_request')


# ---------------------------------------------------------------------------
# yield_missing_tool_result_blocks
# ---------------------------------------------------------------------------

async def yield_missing_tool_result_blocks(
    assistant_messages: list[AssistantMessage],
    error_message: str,
) -> AsyncGenerator[UserMessage, None]:
    """
    For each tool_use block in the given assistant messages, emit a
    synthetic error tool_result.  Called when the loop aborts mid-tool-call.

    Mirrors yieldMissingToolResultBlocks() in query.ts.
    """
    for assistant_message in assistant_messages:
        content = assistant_message.get('message', {}).get('content', [])
        tool_use_blocks = [b for b in content if b.get('type') == 'tool_use']
        for tool_use in tool_use_blocks:
            yield _create_user_message(
                content=[{
                    'type': 'tool_result',
                    'content': error_message,
                    'is_error': True,
                    'tool_use_id': tool_use['id'],
                }],
                tool_use_result=error_message,
                source_tool_assistant_uuid=assistant_message.get('uuid'),
            )


# ---------------------------------------------------------------------------
# is_withheld_max_output_tokens
# ---------------------------------------------------------------------------

def is_withheld_max_output_tokens(
    msg: Optional[Message | StreamEvent],
) -> bool:
    """
    Return True if `msg` is an assistant message withheld due to max_output_tokens.
    Mirrors isWithheldMaxOutputTokens() in query.ts.
    """
    return (
        msg is not None
        and msg.get('type') == 'assistant'
        and msg.get('apiError') == 'max_output_tokens'
    )


# ---------------------------------------------------------------------------
# run_tools (stub until toolOrchestration.ts is ported)
# ---------------------------------------------------------------------------

async def _run_tools(
    tool_use_blocks: list[dict[str, Any]],
    assistant_messages: list[AssistantMessage],
    can_use_tool: Any,
    tool_use_context: ToolUseContext,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Execute all pending tool_use blocks and yield update objects.
    Each update has shape: {message: Message | None, new_context: ToolUseContext | None}

    Mirrors runTools() from services/tools/toolOrchestration.ts. Per tool:
      1. validate_input  → on fail, yield an error tool_result.
      2. check_permissions → 'allow' | 'deny' | 'ask'.
         - 'deny'  → yield a denied tool_result.
         - 'ask'   → gate via can_use_tool; for tools that require user
                     interaction (AskUserQuestion), collect answers via the
                     context's ask_user_questions callback and merge into input.
      3. call(updated_input, ...) with the (possibly answer-injected) input.
    """
    import inspect as _inspect

    for block in tool_use_blocks:
        tool_name = block.get('name', '')
        tool_input = block.get('input', {})
        tool_use_id = block.get('id', '')

        tool = find_tool_by_name(tool_use_context.options.tools, tool_name)

        if tool is None:
            error_text = f"Tool {tool_name!r} not found"
            result_msg = _create_user_message(
                content=[{
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': error_text,
                    'is_error': True,
                }],
                tool_use_result=error_text,
            )
            yield {'message': result_msg, 'new_context': None}
            continue

        # --- 1. validate_input ---
        try:
            validation = await tool.validate_input(tool_input, tool_use_context)
        except Exception as exc:
            validation = None
            error_text = f"Tool {tool_name!r} validate_input raised {type(exc).__name__}: {exc}"
            result_msg = _create_user_message(
                content=[{
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': error_text,
                    'is_error': True,
                }],
                tool_use_result=error_text,
            )
            yield {'message': result_msg, 'new_context': None}
            continue

        if validation is not None and not validation.result:
            error_text = validation.message or f"Tool {tool_name!r} input validation failed"
            result_msg = _create_user_message(
                content=[{
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': error_text,
                    'is_error': True,
                }],
                tool_use_result=error_text,
            )
            yield {'message': result_msg, 'new_context': None}
            continue

        # --- 2. check_permissions ---
        effective_input = tool_input
        try:
            permission = await tool.check_permissions(tool_input, tool_use_context)
        except Exception:
            # No permission info → fall through to can_use_tool gate below.
            permission = None

        if permission is not None:
            behavior = permission.behavior
            effective_input = permission.updated_input or tool_input

            if behavior == 'deny':
                deny_text = permission.message or f"Tool {tool_name!r} was denied"
                result_msg = _create_user_message(
                    content=[{
                        'type': 'tool_result',
                        'tool_use_id': tool_use_id,
                        'content': deny_text,
                        'is_error': True,
                    }],
                    tool_use_result=deny_text,
                )
                yield {'message': result_msg, 'new_context': None}
                continue

            if behavior == 'ask':
                # Tools that require user interaction (AskUserQuestion) collect
                # structured answers via the context callback; the answers are
                # merged into the input before call(), mirroring the TS flow
                # where the AskUserQuestionFrame writes answers into updatedInput.
                requires_interaction = getattr(tool, 'requires_user_interaction', None)
                is_interactive = bool(requires_interaction and requires_interaction())
                if is_interactive and tool_use_context.ask_user_questions is not None:
                    try:
                        answers = tool_use_context.ask_user_questions(
                            effective_input.get('questions', [])
                        )
                        if _inspect.isawaitable(answers):
                            answers = await answers
                    except Exception as exc:
                        deny_text = f"User interaction failed: {exc}"
                        result_msg = _create_user_message(
                            content=[{
                                'type': 'tool_result',
                                'tool_use_id': tool_use_id,
                                'content': deny_text,
                                'is_error': True,
                            }],
                            tool_use_result=deny_text,
                        )
                        yield {'message': result_msg, 'new_context': None}
                        continue
                    if not answers:
                        # User declined to answer.
                        deny_text = "User declined to answer questions"
                        result_msg = _create_user_message(
                            content=[{
                                'type': 'tool_result',
                                'tool_use_id': tool_use_id,
                                'content': deny_text,
                                'is_error': True,
                            }],
                            tool_use_result=deny_text,
                        )
                        yield {'message': result_msg, 'new_context': None}
                        continue
                    effective_input = {**effective_input, 'answers': answers}
                else:
                    # General 'ask' gate: defer to can_use_tool (bool).
                    allowed = True
                    if can_use_tool is not None:
                        decision = can_use_tool(tool.name, effective_input)
                        if _inspect.isawaitable(decision):
                            decision = await decision
                        allowed = bool(decision)
                    if not allowed:
                        deny_text = f"Tool {tool_name!r} was denied by the user"
                        result_msg = _create_user_message(
                            content=[{
                                'type': 'tool_result',
                                'tool_use_id': tool_use_id,
                                'content': deny_text,
                                'is_error': True,
                            }],
                            tool_use_result=deny_text,
                        )
                        yield {'message': result_msg, 'new_context': None}
                        continue
            # behavior == 'allow' → proceed with effective_input.

        # --- 3. call ---
        try:
            tool_result = await tool.call(
                effective_input,
                tool_use_context,
                can_use_tool,
                assistant_messages[-1] if assistant_messages else {},
            )
            output = tool_result.data

            # Map result to API block params
            result_block_param = tool.map_tool_result_to_tool_result_block_param(
                output, tool_use_id
            )
            result_msg = _create_user_message(
                content=[result_block_param],
                tool_use_result=output,
            )

            # Apply context modifier if the tool returned one
            new_context = tool_use_context
            if tool_result.context_modifier:
                new_context = tool_result.context_modifier(tool_use_context)

            yield {'message': result_msg, 'new_context': new_context}

        except Exception as exc:
            error_text = f"Tool {tool_name!r} raised {type(exc).__name__}: {exc}"
            result_msg = _create_user_message(
                content=[{
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': error_text,
                    'is_error': True,
                }],
                tool_use_result=error_text,
            )
            yield {'message': result_msg, 'new_context': None}


# ---------------------------------------------------------------------------
# query() — public entry point
# ---------------------------------------------------------------------------

async def query(
    params: QueryParams,
) -> AsyncGenerator[StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage, Terminal]:
    """
    Public entry point for one user turn.
    Yields stream events / messages as they arrive, then returns a Terminal.

    Mirrors query() in query.ts.
    """
    consumed_command_uuids: list[str] = []
    # TypeScript: yield* queryLoop(params, consumedCommandUuids)
    # Python async generators can't return values, so Terminal is yielded as
    # the last event in the stream. Callers check isinstance(event, Terminal).
    async for event in query_loop(params, consumed_command_uuids):
        yield event
    # RE-ENTRY: post-yield* command lifecycle notification from commands.ts


# ---------------------------------------------------------------------------
# query_loop() — the core state machine
# ---------------------------------------------------------------------------

async def query_loop(
    params: QueryParams,
    consumed_command_uuids: list[str],
) -> AsyncGenerator[StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage, Terminal]:
    """
    The main agentic loop.  Runs until the model produces a final response
    with no tool calls, or until an abort / error / limit condition fires.

    Mirrors queryLoop() in query.ts.
    """
    # --- Immutable params ---
    system_prompt = params.system_prompt
    user_context = params.user_context
    system_context = params.system_context
    can_use_tool = params.can_use_tool
    fallback_model = params.fallback_model
    query_source = params.query_source
    max_turns = params.max_turns
    skip_cache_write = params.skip_cache_write

    deps = params.deps if params.deps is not None else _require_deps()

    # --- Mutable cross-iteration state ---
    state = State(
        messages=params.messages,
        tool_use_context=params.tool_use_context,
        max_output_tokens_override=params.max_output_tokens_override,
        auto_compact_tracking=None,
        stop_hook_active=None,
        max_output_tokens_recovery_count=0,
        has_attempted_reactive_compact=False,
        turn_count=1,
        pending_tool_use_summary=None,
        transition=None,
    )

    # task_budget.remaining — undefined until first compact fires.
    task_budget_remaining: Optional[int] = None

    # Feature: TOKEN_BUDGET → False
    # budget_tracker = None

    while True:
        # Destructure state at top of each iteration.
        tool_use_context = state.tool_use_context
        messages = state.messages
        auto_compact_tracking = state.auto_compact_tracking
        max_output_tokens_recovery_count = state.max_output_tokens_recovery_count
        has_attempted_reactive_compact = state.has_attempted_reactive_compact
        max_output_tokens_override = state.max_output_tokens_override
        pending_tool_use_summary = state.pending_tool_use_summary
        stop_hook_active = state.stop_hook_active
        turn_count = state.turn_count

        # Feature: EXPERIMENTAL_SKILL_SEARCH → False
        # pending_skill_prefetch = None

        yield {'type': 'stream_request_start'}

        # --- Initialize / increment query chain tracking ---
        query_tracking = (
            QueryChainTracking(
                chain_id=tool_use_context.query_tracking.chain_id,
                depth=tool_use_context.query_tracking.depth + 1,
            )
            if tool_use_context.query_tracking
            else QueryChainTracking(
                chain_id=deps.uuid(),
                depth=0,
            )
        )

        tool_use_context = _update_context(tool_use_context, query_tracking=query_tracking)

        messages_for_query = list(_get_messages_after_compact_boundary(messages))

        tracking = auto_compact_tracking

        # --- Tool result budget ---
        # mirrors applyToolResultBudget() — stub until toolResultStorage.ts ported
        # messages_for_query = messages_for_query  (no-op)

        # Feature: HISTORY_SNIP → False
        snip_tokens_freed = 0

        # --- Microcompact ---
        microcompact_result = await deps.microcompact(
            messages_for_query,
            tool_use_context,
            query_source,
        )
        messages_for_query = microcompact_result['messages']
        # Feature: CACHED_MICROCOMPACT → False (pending_cache_edits = None)

        # Feature: CONTEXT_COLLAPSE → False

        full_system_prompt = _append_system_context(system_prompt, system_context)

        # --- Autocompact ---
        compact_response = await deps.autocompact(
            messages_for_query,
            tool_use_context,
            {
                'system_prompt': system_prompt,
                'user_context': user_context,
                'system_context': system_context,
                'tool_use_context': tool_use_context,
                'fork_context_messages': messages_for_query,
            },
            query_source,
            tracking,
            snip_tokens_freed,
        )
        compaction_result = compact_response['compaction_result']
        consecutive_failures = compact_response['consecutive_failures']

        if compaction_result:
            from optimus.services.compact.compact import build_post_compact_messages  # type: ignore[import]
            post_compact_messages = build_post_compact_messages(compaction_result)
            for message in post_compact_messages:
                yield message
            messages_for_query = post_compact_messages
            tracking = AutoCompactTrackingState(
                compacted=True,
                turn_id=deps.uuid(),
                turn_counter=0,
                consecutive_failures=0,
            )
        elif consecutive_failures is not None:
            if tracking:
                tracking.consecutive_failures = consecutive_failures
            else:
                tracking = AutoCompactTrackingState(
                    compacted=False,
                    turn_id='',
                    turn_counter=0,
                    consecutive_failures=consecutive_failures,
                )

        tool_use_context = _update_context(tool_use_context, messages=messages_for_query)

        # Per-iteration collections
        assistant_messages: list[AssistantMessage] = []
        tool_results: list[UserMessage | AttachmentMessage] = []
        tool_use_blocks: list[dict[str, Any]] = []
        needs_follow_up = False

        # Feature: STREAMING_TOOL_EXECUTION → False
        # streaming_tool_executor = None

        # Determine model for this turn
        app_state = tool_use_context.get_app_state() if tool_use_context.get_app_state else None
        current_model = tool_use_context.options.main_loop_model

        attempt_with_fallback = True
        try:
            while attempt_with_fallback:
                attempt_with_fallback = False
                try:
                    # --- Stream model response ---
                    async for message in deps.call_model(
                        messages=_prepend_user_context(messages_for_query, user_context),
                        system_prompt=full_system_prompt,
                        thinking_config=tool_use_context.options.thinking_config,
                        tools=tool_use_context.options.tools,
                        abort_event=tool_use_context.abort_controller,
                        options={
                            'model': current_model,
                            'is_non_interactive_session': tool_use_context.options.is_non_interactive_session,
                            'fallback_model': fallback_model,
                            'query_source': query_source,
                            'max_output_tokens_override': max_output_tokens_override,
                            'skip_cache_write': skip_cache_write,
                        },
                    ):
                        # Backfill observable inputs (mutations on a clone for SDK stream)
                        yield_message = message
                        if message.get('type') == 'assistant':
                            content = message.get('message', {}).get('content', [])
                            cloned_content = None
                            for i, block in enumerate(content):
                                if block.get('type') == 'tool_use' and isinstance(block.get('input'), dict):
                                    tool = find_tool_by_name(
                                        tool_use_context.options.tools,
                                        block['name'],
                                    )
                                    if tool and hasattr(tool, 'backfill_observable_input') and tool.backfill_observable_input:
                                        input_copy = dict(block['input'])
                                        original_keys = set(block['input'].keys())
                                        tool.backfill_observable_input(input_copy)
                                        added_fields = any(k not in original_keys for k in input_copy)
                                        if added_fields:
                                            if cloned_content is None:
                                                cloned_content = list(content)
                                            cloned_content[i] = {**block, 'input': input_copy}
                            if cloned_content is not None:
                                import copy
                                yield_message = copy.deepcopy(message)
                                yield_message['message']['content'] = cloned_content

                        # Withheld recoverable errors — same logic as TS
                        withheld = is_withheld_max_output_tokens(message)
                        if not withheld:
                            yield yield_message

                        if message.get('type') == 'assistant':
                            assistant_messages.append(message)
                            msg_tool_use_blocks = [
                                b for b in message.get('message', {}).get('content', [])
                                if b.get('type') == 'tool_use'
                            ]
                            if msg_tool_use_blocks:
                                tool_use_blocks.extend(msg_tool_use_blocks)
                                needs_follow_up = True

                except Exception as inner_error:
                    # Model fallback (mirrors FallbackTriggeredError branch)
                    if (
                        getattr(inner_error, 'is_fallback_triggered', False)
                        and fallback_model
                    ):
                        current_model = fallback_model
                        attempt_with_fallback = True

                        async for msg in yield_missing_tool_result_blocks(
                            assistant_messages, 'Model fallback triggered'
                        ):
                            yield msg
                        assistant_messages.clear()
                        tool_results.clear()
                        tool_use_blocks.clear()
                        needs_follow_up = False

                        tool_use_context.options.main_loop_model = fallback_model
                        continue

                    raise inner_error

        except Exception as error:
            error_message_str = str(error)

            async for msg in yield_missing_tool_result_blocks(assistant_messages, error_message_str):
                yield msg

            yield _create_assistant_api_error_message(content=error_message_str)
            yield Terminal(reason='model_error', error=error); return

        # --- Post-sampling hooks (fire and forget) ---
        # mirrors executePostSamplingHooks — no-op until hooks.ts is ported

        # --- Abort during streaming ---
        if tool_use_context.abort_controller.is_set():
            async for msg in yield_missing_tool_result_blocks(
                assistant_messages, 'Interrupted by user'
            ):
                yield msg

            if tool_use_context.abort_controller.is_set():
                yield _create_user_interruption_message(tool_use=False)

            yield Terminal(reason='aborted_streaming'); return

        # --- Yield pending tool use summary from previous turn ---
        if pending_tool_use_summary is not None:
            try:
                summary = await pending_tool_use_summary
                if summary:
                    yield summary
            except Exception:
                pass  # Summary generation is best-effort

        # --- No tool calls → check for recoverable errors or return ---
        if not needs_follow_up:
            last_message = assistant_messages[-1] if assistant_messages else None

            is_withheld_413 = (
                last_message is not None
                and last_message.get('isApiErrorMessage')
                and _is_prompt_too_long_message(last_message)
            )

            # Feature: CONTEXT_COLLAPSE → False (no collapse drain)
            # Feature: REACTIVE_COMPACT → False (no reactive compact)

            # max_output_tokens recovery
            if is_withheld_max_output_tokens(last_message):
                if max_output_tokens_recovery_count < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT:
                    recovery_message = _create_user_message(
                        content=(
                            'Output token limit hit. Resume directly — no apology, '
                            'no recap of what you were doing. Pick up mid-thought if '
                            'that is where the cut happened. Break remaining work into smaller pieces.'
                        ),
                        is_meta=True,
                    )
                    state = State(
                        messages=[*messages_for_query, *assistant_messages, recovery_message],
                        tool_use_context=tool_use_context,
                        auto_compact_tracking=tracking,
                        max_output_tokens_recovery_count=max_output_tokens_recovery_count + 1,
                        has_attempted_reactive_compact=has_attempted_reactive_compact,
                        max_output_tokens_override=None,
                        pending_tool_use_summary=None,
                        stop_hook_active=None,
                        turn_count=turn_count,
                        transition={'reason': 'max_output_tokens_recovery',
                                    'attempt': max_output_tokens_recovery_count + 1},
                    )
                    continue

                # Recovery exhausted — surface the withheld error
                if last_message:
                    yield last_message

            # API error messages (rate limit, auth failure, etc.) — skip stop hooks
            if last_message and last_message.get('isApiErrorMessage'):
                yield Terminal(reason='completed'); return

            # --- Stop hooks ---
            # Stub until hooks.ts is ported — no stop hook blocking for now.
            # stop_hook_result = await handle_stop_hooks(...)

            # Feature: TOKEN_BUDGET → False

            yield Terminal(reason='completed'); return

        # --- Tool execution ---
        should_prevent_continuation = False
        updated_tool_use_context = tool_use_context

        async for update in _run_tools(
            tool_use_blocks,
            assistant_messages,
            can_use_tool,
            tool_use_context,
        ):
            if update.get('message'):
                msg = update['message']
                yield msg

                if (
                    msg.get('type') == 'attachment'
                    and msg.get('attachment', {}).get('type') == 'hook_stopped_continuation'
                ):
                    should_prevent_continuation = True

                # Normalise to API format and collect tool results
                tool_results.extend(
                    m for m in _normalize_messages_for_api(
                        [msg], tool_use_context.options.tools
                    )
                    if m.get('type') == 'user'
                )

            if update.get('new_context'):
                # TS: updatedToolUseContext = { ...update.newContext, queryTracking }
                # The spread keeps a ToolUseContext (not a plain dict) — mirror
                # with dataclasses.replace so .options/.abort_controller survive.
                updated_tool_use_context = _update_context(
                    update['new_context'], query_tracking=query_tracking
                )

        # --- Abort during tool calls ---
        if tool_use_context.abort_controller.is_set():
            yield _create_user_interruption_message(tool_use=True)
            next_turn_count = turn_count + 1
            if max_turns and next_turn_count > max_turns:
                yield _create_attachment_message({
                    'type': 'max_turns_reached',
                    'maxTurns': max_turns,
                    'turnCount': next_turn_count,
                })
            yield Terminal(reason='aborted_tools'); return

        if should_prevent_continuation:
            yield Terminal(reason='hook_stopped'); return

        if tracking and getattr(tracking, 'compacted', False):
            tracking.turn_counter += 1

        # --- Attachment messages (memory, queued commands) ---
        # Stub until attachments.ts and messageQueueManager.ts are ported.
        # async for attachment in get_attachment_messages(...):
        #     yield attachment
        #     tool_results.append(attachment)

        # --- Refresh tools between turns (MCP reconnect) ---
        if updated_tool_use_context.options.refresh_tools:
            refreshed = updated_tool_use_context.options.refresh_tools()
            if refreshed is not updated_tool_use_context.options.tools:
                updated_tool_use_context = _update_context(
                    updated_tool_use_context,
                    tools=refreshed,
                )

        tool_use_context_with_tracking = _update_context(
            updated_tool_use_context,
            query_tracking=query_tracking,
        )

        next_turn_count = turn_count + 1

        # --- Max turns check ---
        if max_turns and next_turn_count > max_turns:
            yield _create_attachment_message({
                'type': 'max_turns_reached',
                'maxTurns': max_turns,
                'turnCount': next_turn_count,
            })
            yield Terminal(reason='max_turns', turn_count=next_turn_count); return

        # --- Continue to next iteration ---
        state = State(
            messages=[*messages_for_query, *assistant_messages, *tool_results],
            tool_use_context=tool_use_context_with_tracking,
            auto_compact_tracking=tracking,
            turn_count=next_turn_count,
            max_output_tokens_recovery_count=0,
            has_attempted_reactive_compact=False,
            pending_tool_use_summary=None,
            max_output_tokens_override=None,
            stop_hook_active=stop_hook_active,
            transition={'reason': 'next_turn'},
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _update_context(ctx: ToolUseContext, **kwargs: Any) -> ToolUseContext:
    """
    Return a shallow copy of ToolUseContext with the given fields updated.
    Mirrors the `{ ...toolUseContext, field: value }` spread pattern in TS.
    """
    import dataclasses
    return dataclasses.replace(ctx, **kwargs)


def _require_deps() -> QueryDeps:
    """Raise a clear error if deps were not provided and no default is wired."""
    raise RuntimeError(
        "QueryDeps not provided. Pass `deps=production_deps(call_model=...)` "
        "to query() or wire it via the Agent."
    )
