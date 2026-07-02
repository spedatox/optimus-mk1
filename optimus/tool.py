"""
Tool.py — port of src/Tool.ts

The Tool protocol is the foundation of the entire tool system.
Every tool in Optimus conforms to this interface.

Porting notes:
- TypeScript generics (Input, Output, P) → Python generics via TypeVar
- z.ZodType / z.infer<Input> → dict[str, Any] (JSON schema + raw input dicts)
- React.ReactNode render methods → return str | None (no UI layer yet)
- AbortController → asyncio.Event (cancellation signal)
- DeepImmutable<T> → plain dataclass (Python has no deep-freeze primitive)
- analytics/telemetry fields → kept but no-op
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    Protocol,
    TypeVar,
    runtime_checkable,
)

# ---------------------------------------------------------------------------
# Forward-declared types (will be filled in by other modules)
# ---------------------------------------------------------------------------

# Placeholder until message.py is ported
Message = dict[str, Any]
UserMessage = dict[str, Any]
AssistantMessage = dict[str, Any]
AttachmentMessage = dict[str, Any]
SystemMessage = dict[str, Any]

# Placeholder until tools.py progress types are ported
ToolProgressData = dict[str, Any]
HookProgress = dict[str, Any]

# ---------------------------------------------------------------------------
# ToolInputJSONSchema
# ---------------------------------------------------------------------------

# JSON Schema object describing a tool's inputs.
# Must have type="object" and optional properties dict.
ToolInputJSONSchema = dict[str, Any]


# ---------------------------------------------------------------------------
# Permission types (mirrors types/permissions.ts)
# ---------------------------------------------------------------------------

PermissionMode = str  # 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan'

# Rules keyed by source (e.g. 'cli', 'settings', 'api')
ToolPermissionRulesBySource = dict[str, list[str]]


@dataclass
class AdditionalWorkingDirectory:
    path: str
    source: str  # 'cli' | 'api' | 'settings'


@dataclass
class ToolPermissionContext:
    """
    Immutable-by-convention permission context passed to every tool call.
    Mirrors ToolPermissionContext in Tool.ts.
    """
    mode: PermissionMode = 'default'
    additional_working_directories: dict[str, AdditionalWorkingDirectory] = field(default_factory=dict)
    always_allow_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_deny_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_ask_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    is_bypass_permissions_mode_available: bool = False
    is_auto_mode_available: bool = False
    stripped_dangerous_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    should_avoid_permission_prompts: bool = False
    await_automated_checks_before_dialog: bool = False
    pre_plan_mode: Optional[PermissionMode] = None


def get_empty_tool_permission_context() -> ToolPermissionContext:
    """Return a default (allow-all) ToolPermissionContext. Mirrors getEmptyToolPermissionContext."""
    return ToolPermissionContext()


# ---------------------------------------------------------------------------
# PermissionResult (mirrors types/permissions.ts)
# ---------------------------------------------------------------------------

@dataclass
class PermissionResult:
    """
    Result of checkPermissions(). behavior drives the agent:
      'allow'  — proceed immediately
      'deny'   — reject with message
      'ask'    — show permission UI
    """
    behavior: str  # 'allow' | 'deny' | 'ask'
    updated_input: dict[str, Any] = field(default_factory=dict)
    message: str = ''
    error_code: int = 0


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of validateInput(). Mirrors ValidationResult in Tool.ts."""
    result: bool
    message: str = ''
    error_code: int = 0

    @classmethod
    def ok(cls) -> 'ValidationResult':
        return cls(result=True)

    @classmethod
    def fail(cls, message: str, error_code: int = 1) -> 'ValidationResult':
        return cls(result=False, message=message, error_code=error_code)


# ---------------------------------------------------------------------------
# Progress types
# ---------------------------------------------------------------------------

@dataclass
class ToolProgress:
    """Mirrors ToolProgress<P> in Tool.ts."""
    tool_use_id: str
    data: ToolProgressData


Progress = ToolProgressData | HookProgress

ToolCallProgress = Callable[[ToolProgress], None]


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """
    Mirrors ToolResult<T> in Tool.ts.
    What a tool's call() method returns.
    """
    data: Any
    new_messages: list[UserMessage | AssistantMessage | AttachmentMessage | SystemMessage] = field(default_factory=list)
    context_modifier: Optional[Callable[['ToolUseContext'], 'ToolUseContext']] = None
    mcp_meta: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# QueryChainTracking
# ---------------------------------------------------------------------------

@dataclass
class QueryChainTracking:
    """Mirrors QueryChainTracking in Tool.ts."""
    chain_id: str
    depth: int


# ---------------------------------------------------------------------------
# CompactProgressEvent
# ---------------------------------------------------------------------------

@dataclass
class CompactProgressEvent:
    """Mirrors CompactProgressEvent in Tool.ts."""
    type: str  # 'hooks_start' | 'compact_start' | 'compact_end'
    hook_type: Optional[str] = None  # 'pre_compact' | 'post_compact' | 'session_start'


# ---------------------------------------------------------------------------
# ToolUseContext
# ---------------------------------------------------------------------------

@dataclass
class ToolUseContextOptions:
    """The options sub-object of ToolUseContext."""
    commands: list[Any] = field(default_factory=list)
    debug: bool = False
    main_loop_model: str = ''
    tools: list[Any] = field(default_factory=list)  # 'Tools' — forward ref
    verbose: bool = False
    thinking_config: dict[str, Any] = field(default_factory=dict)
    mcp_clients: list[Any] = field(default_factory=list)
    mcp_resources: dict[str, list[Any]] = field(default_factory=dict)
    is_non_interactive_session: bool = False
    agent_definitions: Any = None
    max_budget_usd: Optional[float] = None
    custom_system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    query_source: Optional[str] = None
    refresh_tools: Optional[Callable[[], list[Any]]] = None


@dataclass
class ToolUseContext:
    """
    Context passed to every tool call.
    Mirrors ToolUseContext in Tool.ts.

    Most UI-specific callbacks (set_tool_jsx, send_os_notification, etc.) are
    optional and default to None — they are only wired in interactive sessions.
    """
    options: ToolUseContextOptions = field(default_factory=ToolUseContextOptions)

    # Cancellation signal (mirrors AbortController)
    abort_controller: asyncio.Event = field(default_factory=asyncio.Event)

    # App state (mirrors getAppState / setAppState)
    get_app_state: Optional[Callable[[], Any]] = None
    set_app_state: Optional[Callable[[Callable[[Any], Any]], None]] = None
    set_app_state_for_tasks: Optional[Callable[[Callable[[Any], Any]], None]] = None

    # MCP elicitation handler (only in SDK/print mode)
    handle_elicitation: Optional[Callable[..., Any]] = None

    # AskUserQuestion answer collector. Given the questions list, returns a dict
    # {question_text: answer_string} (multi-select answers comma-separated).
    # Wired by the REPL (modal) and headless (stdin). When None, AskUserQuestion
    # falls back to the can_use_tool gate with empty answers.
    ask_user_questions: Optional[Callable[[list], Any]] = None

    # UI callbacks (REPL only)
    set_tool_jsx: Optional[Callable[..., None]] = None
    add_notification: Optional[Callable[..., None]] = None
    append_system_message: Optional[Callable[..., None]] = None
    send_os_notification: Optional[Callable[..., None]] = None

    # Nested memory / skill tracking
    nested_memory_attachment_triggers: set[str] = field(default_factory=set)
    loaded_nested_memory_paths: set[str] = field(default_factory=set)
    dynamic_skill_dir_triggers: set[str] = field(default_factory=set)
    discovered_skill_names: set[str] = field(default_factory=set)

    user_modified: bool = False

    set_in_progress_tool_use_ids: Optional[Callable[[Callable[[set[str]], set[str]]], None]] = None
    set_has_interruptible_tool_in_progress: Optional[Callable[[bool], None]] = None
    set_response_length: Optional[Callable[[Callable[[int], int]], None]] = None
    push_api_metrics_entry: Optional[Callable[[float], None]] = None
    set_stream_mode: Optional[Callable[[str], None]] = None
    on_compact_progress: Optional[Callable[[CompactProgressEvent], None]] = None
    set_sdk_status: Optional[Callable[[Any], None]] = None
    open_message_selector: Optional[Callable[[], None]] = None

    update_file_history_state: Optional[Callable[[Callable[[Any], Any]], None]] = None
    update_attribution_state: Optional[Callable[[Callable[[Any], Any]], None]] = None
    set_conversation_id: Optional[Callable[[str], None]] = None

    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    require_can_use_tool: bool = False

    messages: list[Message] = field(default_factory=list)

    file_reading_limits: Optional[dict[str, Any]] = None
    glob_limits: Optional[dict[str, Any]] = None
    tool_decisions: Optional[dict[str, Any]] = None
    query_tracking: Optional[QueryChainTracking] = None
    request_prompt: Optional[Callable[..., Any]] = None
    tool_use_id: Optional[str] = None
    critical_system_reminder_experimental: Optional[str] = None
    preserve_tool_use_results: bool = False
    local_denial_tracking: Optional[Any] = None
    content_replacement_state: Optional[Any] = None
    rendered_system_prompt: Optional[Any] = None
    read_file_state: Optional[Any] = None

    # Permission context — set once per session, read by tools
    tool_permission_context: ToolPermissionContext = field(default_factory=get_empty_tool_permission_context)


# ---------------------------------------------------------------------------
# Tool protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Tool(Protocol):
    """
    The Tool protocol. Every tool in Optimus implements this interface.
    Mirrors the Tool<Input, Output, P> type in Tool.ts.

    Required attributes / methods:
      name, inputSchema, maxResultSizeChars,
      call, description, checkPermissions, prompt,
      userFacingName, mapToolResultToToolResultBlockParam,
      renderToolUseMessage, isConcurrencySafe, isReadOnly, isEnabled,
      toAutoClassifierInput

    Optional methods default via buildTool().
    """

    # --- Identity ---
    name: str
    aliases: list[str]
    search_hint: Optional[str]

    # --- Schema ---
    input_schema: Any          # Pydantic model class or JSON schema dict
    input_json_schema: Optional[ToolInputJSONSchema]
    output_schema: Optional[Any]
    max_result_size_chars: int
    strict: bool

    # --- Core behaviour ---
    async def call(
        self,
        args: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any,
        parent_message: AssistantMessage,
        on_progress: Optional[ToolCallProgress] = None,
    ) -> ToolResult: ...

    async def description(
        self,
        input: dict[str, Any],
        options: dict[str, Any],
    ) -> str: ...

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool: ...
    def is_enabled(self) -> bool: ...
    def is_read_only(self, input: dict[str, Any]) -> bool: ...
    def is_destructive(self, input: dict[str, Any]) -> bool: ...

    async def check_permissions(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
    ) -> PermissionResult: ...

    async def validate_input(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
    ) -> ValidationResult: ...

    async def prompt(self, options: dict[str, Any]) -> str: ...

    def user_facing_name(self, input: Optional[dict[str, Any]]) -> str: ...

    def to_auto_classifier_input(self, input: dict[str, Any]) -> Any: ...

    def map_tool_result_to_tool_result_block_param(
        self,
        content: Any,
        tool_use_id: str,
    ) -> dict[str, Any]: ...

    def render_tool_use_message(
        self,
        input: dict[str, Any],
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def inputs_equivalent(
        self,
        a: dict[str, Any],
        b: dict[str, Any],
    ) -> bool: ...

    def interrupt_behavior(self) -> str: ...  # 'cancel' | 'block'

    def is_search_or_read_command(
        self,
        input: dict[str, Any],
    ) -> dict[str, bool]: ...

    def is_open_world(self, input: dict[str, Any]) -> bool: ...
    def requires_user_interaction(self) -> bool: ...

    # Optional flags
    is_mcp: bool
    is_lsp: bool
    should_defer: bool
    always_load: bool
    mcp_info: Optional[dict[str, str]]

    def get_path(self, input: dict[str, Any]) -> Optional[str]: ...

    async def prepare_permission_matcher(
        self,
        input: dict[str, Any],
    ) -> Callable[[str], bool]: ...

    def backfill_observable_input(self, input: dict[str, Any]) -> None: ...

    def get_tool_use_summary(
        self,
        input: Optional[dict[str, Any]],
    ) -> Optional[str]: ...

    def get_activity_description(
        self,
        input: Optional[dict[str, Any]],
    ) -> Optional[str]: ...

    def is_result_truncated(self, output: Any) -> bool: ...
    def extract_search_text(self, output: Any) -> str: ...

    def render_tool_result_message(
        self,
        content: Any,
        progress_messages: list[Any],
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def render_tool_use_progress_message(
        self,
        progress_messages: list[Any],
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def render_tool_use_queued_message(self) -> Optional[str]: ...

    def render_tool_use_rejected_message(
        self,
        input: dict[str, Any],
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def render_tool_use_error_message(
        self,
        result: Any,
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def render_grouped_tool_use(
        self,
        tool_uses: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> Optional[str]: ...

    def render_tool_use_tag(
        self,
        input: Optional[dict[str, Any]],
    ) -> Optional[str]: ...

    def user_facing_name_background_color(
        self,
        input: Optional[dict[str, Any]],
    ) -> Optional[str]: ...

    def is_transparent_wrapper(self) -> bool: ...


# Alias — use this type for a list of tools throughout the codebase.
Tools = list[Tool]


# ---------------------------------------------------------------------------
# toolMatchesName / findToolByName
# ---------------------------------------------------------------------------

def tool_matches_name(tool: Any, name: str) -> bool:
    """
    Check if a tool matches the given name (primary name or alias).
    Mirrors toolMatchesName() in Tool.ts.
    """
    if tool.name == name:
        return True
    aliases = getattr(tool, 'aliases', None)
    if aliases and name in aliases:
        return True
    return False


def find_tool_by_name(tools: Tools, name: str) -> Optional[Tool]:
    """
    Find a tool by name or alias. Returns None if not found.
    Mirrors findToolByName() in Tool.ts.
    """
    for t in tools:
        if tool_matches_name(t, name):
            return t
    return None


# ---------------------------------------------------------------------------
# filterToolProgressMessages
# ---------------------------------------------------------------------------

def filter_tool_progress_messages(
    progress_messages_for_message: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep only ToolProgressData progress messages (drop HookProgress).
    Mirrors filterToolProgressMessages() in Tool.ts.
    """
    return [
        msg for msg in progress_messages_for_message
        if (msg.get('data') or {}).get('type') != 'hook_progress'
    ]


# ---------------------------------------------------------------------------
# TOOL_DEFAULTS + buildTool
# ---------------------------------------------------------------------------

async def _default_check_permissions(
    input: dict[str, Any],
    context: ToolUseContext,
) -> PermissionResult:
    """Default: allow everything, pass input through unchanged."""
    return PermissionResult(behavior='allow', updated_input=input)


async def _default_validate_input(
    input: dict[str, Any],
    context: ToolUseContext,
) -> ValidationResult:
    """Default: always valid."""
    return ValidationResult.ok()


TOOL_DEFAULTS: dict[str, Any] = {
    'aliases': [],
    'search_hint': None,
    'input_json_schema': None,
    'output_schema': None,
    'strict': False,
    'is_mcp': False,
    'is_lsp': False,
    'should_defer': False,
    'always_load': False,
    'mcp_info': None,
    'is_enabled': lambda self: True,
    'is_concurrency_safe': lambda self, input: False,
    'is_read_only': lambda self, input: False,
    'is_destructive': lambda self, input: False,
    'check_permissions': _default_check_permissions,
    'validate_input': _default_validate_input,
    'to_auto_classifier_input': lambda self, input: '',
    'user_facing_name': lambda self, input=None: getattr(self, 'name', ''),
    'inputs_equivalent': lambda self, a, b: a == b,
    'interrupt_behavior': lambda self: 'block',
    'is_search_or_read_command': lambda self, input: {'isSearch': False, 'isRead': False, 'isList': False},
    'is_open_world': lambda self, input: False,
    'requires_user_interaction': lambda self: False,
    'get_path': lambda self, input: None,
    'backfill_observable_input': lambda self, input: None,
    'get_tool_use_summary': lambda self, input=None: None,
    'get_activity_description': lambda self, input=None: None,
    'is_result_truncated': lambda self, output: False,
    'extract_search_text': lambda self, output: '',
    'render_tool_result_message': lambda self, content, progress, options: None,
    'render_tool_use_progress_message': lambda self, progress, options: None,
    'render_tool_use_queued_message': lambda self: None,
    'render_tool_use_rejected_message': lambda self, input, options: None,
    'render_tool_use_error_message': lambda self, result, options: None,
    'render_grouped_tool_use': lambda self, tool_uses, options: None,
    'render_tool_use_tag': lambda self, input=None: None,
    'user_facing_name_background_color': lambda self, input=None: None,
    'is_transparent_wrapper': lambda self: False,
    'prepare_permission_matcher': None,  # filled per-tool if needed
}


def build_tool(cls: type) -> type:
    """
    Class decorator (mirrors buildTool() in Tool.ts).

    Fills in safe defaults for every method that the ToolDef omits.
    Apply it to any Tool implementation class:

        @build_tool
        class MyTool:
            name = 'MyTool'
            ...

    Defaults (fail-closed where it matters):
      - is_enabled          → True
      - is_concurrency_safe → False  (assume not safe)
      - is_read_only        → False  (assume writes)
      - is_destructive      → False
      - check_permissions   → allow (defer to general permission system)
      - validate_input      → always valid
      - to_auto_classifier_input → '' (skip classifier)
      - user_facing_name    → self.name
    """
    for attr, default in TOOL_DEFAULTS.items():
        if not hasattr(cls, attr) or getattr(cls, attr) is None:
            if callable(default):
                # Bind as a method
                import types
                setattr(cls, attr, default)
            else:
                setattr(cls, attr, default)
    return cls
