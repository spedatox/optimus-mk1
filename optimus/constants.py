"""
optimus/constants.py — port of src/constants/*.ts

Batches the following source files (no external deps, safe to import anywhere):
  common.ts · tools.ts · apiLimits.ts · toolLimits.ts · figures.ts
  errorIds.ts · betas.ts · system.ts · xml.ts · product.ts

Analytics / GrowthBook feature flags → all disabled (False / empty string).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Optional


# ===========================================================================
# common.ts — date helpers
# ===========================================================================

def get_local_iso_date() -> str:
    """Return today's local date as YYYY-MM-DD, honouring override env var."""
    override = os.environ.get("CLAUDE_CODE_OVERRIDE_DATE")
    if override:
        return override
    import datetime
    d = datetime.date.today()
    return d.strftime("%Y-%m-%d")


@lru_cache(maxsize=1)
def _cached_session_start_date() -> str:
    return get_local_iso_date()


def get_session_start_date() -> str:
    """Memoized — captures the date once at session start for prompt-cache stability."""
    return _cached_session_start_date()


def get_local_month_year() -> str:
    """Return 'Month YYYY' in the local timezone, e.g. 'February 2026'."""
    import datetime
    override = os.environ.get("CLAUDE_CODE_OVERRIDE_DATE")
    if override:
        import datetime as dt
        d = dt.date.fromisoformat(override)
    else:
        d = datetime.date.today()
    return d.strftime("%B %Y")


# ===========================================================================
# apiLimits.ts — Anthropic API size/count limits
# ===========================================================================

API_IMAGE_MAX_BASE64_SIZE = 5 * 1024 * 1024          # 5 MB (base64 length)
IMAGE_TARGET_RAW_SIZE = (API_IMAGE_MAX_BASE64_SIZE * 3) // 4  # 3.75 MB
IMAGE_MAX_WIDTH = 2000
IMAGE_MAX_HEIGHT = 2000

PDF_TARGET_RAW_SIZE = 20 * 1024 * 1024               # 20 MB
API_PDF_MAX_PAGES = 100
PDF_EXTRACT_SIZE_THRESHOLD = 3 * 1024 * 1024         # 3 MB
PDF_MAX_EXTRACT_SIZE = 100 * 1024 * 1024             # 100 MB
PDF_MAX_PAGES_PER_READ = 20
PDF_AT_MENTION_INLINE_THRESHOLD = 10

API_MAX_MEDIA_PER_REQUEST = 100


# ===========================================================================
# toolLimits.ts — tool result size limits
# ===========================================================================

DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000
MAX_TOOL_RESULT_TOKENS = 100_000
BYTES_PER_TOKEN = 4
MAX_TOOL_RESULT_BYTES = MAX_TOOL_RESULT_TOKENS * BYTES_PER_TOKEN
MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000
TOOL_SUMMARY_MAX_LENGTH = 50


# ===========================================================================
# figures.ts — Unicode / symbol constants (platform-aware)
# ===========================================================================

BLACK_CIRCLE = "⏺" if sys.platform == "darwin" else "●"
BULLET_OPERATOR = "∙"
TEARDROP_ASTERISK = "✻"
UP_ARROW = "\u2191"          # ↑
DOWN_ARROW = "\u2193"        # ↓
LIGHTNING_BOLT = "↯"         # \u21af
EFFORT_LOW = "○"             # \u25cb
EFFORT_MEDIUM = "◐"          # \u25d0
EFFORT_HIGH = "●"            # \u25cf
EFFORT_MAX = "◉"             # \u25c9

PLAY_ICON = "\u25b6"         # ▶
PAUSE_ICON = "\u23f8"        # ⏸

REFRESH_ARROW = "\u21bb"     # ↻
CHANNEL_ARROW = "\u2190"     # ←
INJECTED_ARROW = "\u2192"    # →
FORK_GLYPH = "\u2442"        # ⑂

DIAMOND_OPEN = "\u25c7"      # ◇
DIAMOND_FILLED = "\u25c6"    # ◆
REFERENCE_MARK = "\u203b"    # ※

FLAG_ICON = "\u2691"         # ⚑
BLOCKQUOTE_BAR = "\u258e"    # ▎
HEAVY_HORIZONTAL = "\u2501"  # ━

BRIDGE_SPINNER_FRAMES = ["\u00b7|\u00b7", "\u00b7/\u00b7", "\u00b7\u2014\u00b7", "\u00b7\\\u00b7"]
BRIDGE_READY_INDICATOR = "\u00b7\u2714\ufe0e\u00b7"
BRIDGE_FAILED_INDICATOR = "\u00d7"


# ===========================================================================
# errorIds.ts — numeric error ID constants
# ===========================================================================

E_TOOL_USE_SUMMARY_GENERATION_FAILED = 344


# ===========================================================================
# betas.ts — Anthropic API beta header strings
# Feature-gated headers (CONNECTOR_TEXT, TRANSCRIPT_CLASSIFIER) → empty string.
# ANT-internal header → empty string (USER_TYPE != 'ant' in open-source build).
# ===========================================================================

CLAUDE_CODE_20250219_BETA_HEADER = "claude-code-20250219"
INTERLEAVED_THINKING_BETA_HEADER = "interleaved-thinking-2025-05-14"
CONTEXT_1M_BETA_HEADER = "context-1m-2025-08-07"
CONTEXT_MANAGEMENT_BETA_HEADER = "context-management-2025-06-27"
STRUCTURED_OUTPUTS_BETA_HEADER = "structured-outputs-2025-12-15"
WEB_SEARCH_BETA_HEADER = "web-search-2025-03-05"
TOOL_SEARCH_BETA_HEADER_1P = "advanced-tool-use-2025-11-20"
TOOL_SEARCH_BETA_HEADER_3P = "tool-search-tool-2025-10-19"
EFFORT_BETA_HEADER = "effort-2025-11-24"
TASK_BUDGETS_BETA_HEADER = "task-budgets-2026-03-13"
PROMPT_CACHING_SCOPE_BETA_HEADER = "prompt-caching-scope-2026-01-05"
FAST_MODE_BETA_HEADER = "fast-mode-2026-02-01"
REDACT_THINKING_BETA_HEADER = "redact-thinking-2026-02-12"
TOKEN_EFFICIENT_TOOLS_BETA_HEADER = "token-efficient-tools-2026-03-28"
SUMMARIZE_CONNECTOR_TEXT_BETA_HEADER = ""   # feature('CONNECTOR_TEXT') → False
AFK_MODE_BETA_HEADER = ""                   # feature('TRANSCRIPT_CLASSIFIER') → False
CLI_INTERNAL_BETA_HEADER = ""               # USER_TYPE != 'ant' in open-source build
ADVISOR_BETA_HEADER = "advisor-tool-2026-03-01"

BEDROCK_EXTRA_PARAMS_HEADERS: frozenset[str] = frozenset({
    INTERLEAVED_THINKING_BETA_HEADER,
    CONTEXT_1M_BETA_HEADER,
    TOOL_SEARCH_BETA_HEADER_3P,
})

VERTEX_COUNT_TOKENS_ALLOWED_BETAS: frozenset[str] = frozenset({
    CLAUDE_CODE_20250219_BETA_HEADER,
    INTERLEAVED_THINKING_BETA_HEADER,
    CONTEXT_MANAGEMENT_BETA_HEADER,
})


# ===========================================================================
# system.ts — CLI sysprompt prefix constants and helpers
# getAttributionHeader → no-op (GrowthBook / Bun attestation dropped).
# ===========================================================================

_DEFAULT_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."
_AGENT_SDK_CC_PRESET_PREFIX = (
    "You are Claude Code, Anthropic's official CLI for Claude, "
    "running within the Claude Agent SDK."
)
_AGENT_SDK_PREFIX = "You are a Claude agent, built on Anthropic's Claude Agent SDK."

CLI_SYSPROMPT_PREFIXES: frozenset[str] = frozenset({
    _DEFAULT_PREFIX,
    _AGENT_SDK_CC_PRESET_PREFIX,
    _AGENT_SDK_PREFIX,
})


def get_cli_sysprompt_prefix(
    *,
    is_non_interactive: bool = False,
    has_append_system_prompt: bool = False,
    api_provider: str = "anthropic",
) -> str:
    """
    Port of getCLISyspromptPrefix() from system.ts.
    Selects the right identity blurb for the system prompt.
    """
    if api_provider == "vertex":
        return _DEFAULT_PREFIX
    if is_non_interactive:
        if has_append_system_prompt:
            return _AGENT_SDK_CC_PRESET_PREFIX
        return _AGENT_SDK_PREFIX
    return _DEFAULT_PREFIX


def get_attribution_header(fingerprint: str) -> str:
    """
    Port of getAttributionHeader() from system.ts.
    Returns empty string — Bun attestation and GrowthBook are not available.
    RE-ENTRY: wire real attribution if native attestation is ported.
    """
    return ""


# ===========================================================================
# xml.ts — XML tag name constants
# ===========================================================================

COMMAND_NAME_TAG = "command-name"
COMMAND_MESSAGE_TAG = "command-message"
COMMAND_ARGS_TAG = "command-args"

BASH_INPUT_TAG = "bash-input"
BASH_STDOUT_TAG = "bash-stdout"
BASH_STDERR_TAG = "bash-stderr"
LOCAL_COMMAND_STDOUT_TAG = "local-command-stdout"
LOCAL_COMMAND_STDERR_TAG = "local-command-stderr"
LOCAL_COMMAND_CAVEAT_TAG = "local-command-caveat"

TERMINAL_OUTPUT_TAGS: tuple[str, ...] = (
    BASH_INPUT_TAG,
    BASH_STDOUT_TAG,
    BASH_STDERR_TAG,
    LOCAL_COMMAND_STDOUT_TAG,
    LOCAL_COMMAND_STDERR_TAG,
    LOCAL_COMMAND_CAVEAT_TAG,
)

TICK_TAG = "tick"

TASK_NOTIFICATION_TAG = "task-notification"
TASK_ID_TAG = "task-id"
TOOL_USE_ID_TAG = "tool-use-id"
TASK_TYPE_TAG = "task-type"
OUTPUT_FILE_TAG = "output-file"
STATUS_TAG = "status"
SUMMARY_TAG = "summary"
REASON_TAG = "reason"
WORKTREE_TAG = "worktree"
WORKTREE_PATH_TAG = "worktreePath"
WORKTREE_BRANCH_TAG = "worktreeBranch"

ULTRAPLAN_TAG = "ultraplan"
REMOTE_REVIEW_TAG = "remote-review"
REMOTE_REVIEW_PROGRESS_TAG = "remote-review-progress"
TEAMMATE_MESSAGE_TAG = "teammate-message"
CHANNEL_MESSAGE_TAG = "channel-message"
CHANNEL_TAG = "channel"
CROSS_SESSION_MESSAGE_TAG = "cross-session-message"
FORK_BOILERPLATE_TAG = "fork-boilerplate"
FORK_DIRECTIVE_PREFIX = "Your directive: "

COMMON_HELP_ARGS: tuple[str, ...] = ("help", "-h", "--help")
COMMON_INFO_ARGS: tuple[str, ...] = (
    "list", "show", "display", "current", "view", "get",
    "check", "describe", "print", "version", "about", "status", "?",
)


# ===========================================================================
# product.ts — URLs and remote session helpers
# ===========================================================================

PRODUCT_URL = "https://claude.com/claude-code"
CLAUDE_AI_BASE_URL = "https://claude.ai"
CLAUDE_AI_STAGING_BASE_URL = "https://claude-ai.staging.ant.dev"
CLAUDE_AI_LOCAL_BASE_URL = "http://localhost:4000"


def is_remote_session_staging(
    session_id: Optional[str] = None,
    ingress_url: Optional[str] = None,
) -> bool:
    return bool(
        (session_id and "_staging_" in session_id)
        or (ingress_url and "staging" in ingress_url)
    )


def is_remote_session_local(
    session_id: Optional[str] = None,
    ingress_url: Optional[str] = None,
) -> bool:
    return bool(
        (session_id and "_local_" in session_id)
        or (ingress_url and "localhost" in ingress_url)
    )


def get_claude_ai_base_url(
    session_id: Optional[str] = None,
    ingress_url: Optional[str] = None,
) -> str:
    if is_remote_session_local(session_id, ingress_url):
        return CLAUDE_AI_LOCAL_BASE_URL
    if is_remote_session_staging(session_id, ingress_url):
        return CLAUDE_AI_STAGING_BASE_URL
    return CLAUDE_AI_BASE_URL


def get_remote_session_url(session_id: str, ingress_url: Optional[str] = None) -> str:
    base = get_claude_ai_base_url(session_id, ingress_url)
    return f"{base}/code/{session_id}"


# ===========================================================================
# tools.ts — tool name strings and permission sets
# Feature-gated additions (WORKFLOW_SCRIPTS, AGENT_TRIGGERS) → omitted.
# USER_TYPE == 'ant' branch (nested agents) → omitted.
# ===========================================================================

# Individual tool name constants (mirrors each tool's own constants.ts)
AGENT_TOOL_NAME = "Agent"
LEGACY_AGENT_TOOL_NAME = "Task"
ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"
TASK_OUTPUT_TOOL_NAME = "TaskOutput"
TASK_STOP_TOOL_NAME = "TaskStop"
TASK_CREATE_TOOL_NAME = "TaskCreate"
TASK_GET_TOOL_NAME = "TaskGet"
TASK_LIST_TOOL_NAME = "TaskList"
TASK_UPDATE_TOOL_NAME = "TaskUpdate"
SEND_MESSAGE_TOOL_NAME = "SendMessage"
EXIT_PLAN_MODE_TOOL_NAME = "ExitPlanMode"
EXIT_PLAN_MODE_V2_TOOL_NAME = "ExitPlanMode"
ENTER_PLAN_MODE_TOOL_NAME = "EnterPlanMode"
ENTER_WORKTREE_TOOL_NAME = "EnterWorktree"
EXIT_WORKTREE_TOOL_NAME = "ExitWorktree"
FILE_READ_TOOL_NAME = "Read"
FILE_EDIT_TOOL_NAME = "Edit"
FILE_WRITE_TOOL_NAME = "Write"
GLOB_TOOL_NAME = "Glob"
GREP_TOOL_NAME = "Grep"
WEB_FETCH_TOOL_NAME = "WebFetch"
WEB_SEARCH_TOOL_NAME = "WebSearch"
TODO_WRITE_TOOL_NAME = "TodoWrite"
NOTEBOOK_EDIT_TOOL_NAME = "NotebookEdit"
SKILL_TOOL_NAME = "Skill"
TOOL_SEARCH_TOOL_NAME = "ToolSearch"
SYNTHETIC_OUTPUT_TOOL_NAME = "StructuredOutput"
BRIEF_TOOL_NAME = "SendUserMessage"
LEGACY_BRIEF_TOOL_NAME = "Brief"
BASH_TOOL_NAME = "Bash"
POWERSHELL_TOOL_NAME = "PowerShell"
REPL_TOOL_NAME = "REPL"
LSP_TOOL_NAME = "LSP"
LIST_MCP_RESOURCES_TOOL_NAME = "ListMcpResourcesTool"
REMOTE_TRIGGER_TOOL_NAME = "RemoteTrigger"
CRON_CREATE_TOOL_NAME = "CronCreate"
CRON_DELETE_TOOL_NAME = "CronDelete"
CRON_LIST_TOOL_NAME = "CronList"
SLEEP_TOOL_NAME = "Sleep"
CONFIG_TOOL_NAME = "Config"

SHELL_TOOL_NAMES: list[str] = [BASH_TOOL_NAME, POWERSHELL_TOOL_NAME]

ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    TASK_OUTPUT_TOOL_NAME,
    EXIT_PLAN_MODE_V2_TOOL_NAME,
    ENTER_PLAN_MODE_TOOL_NAME,
    AGENT_TOOL_NAME,          # nested agents disallowed (USER_TYPE != 'ant')
    ASK_USER_QUESTION_TOOL_NAME,
    TASK_STOP_TOOL_NAME,
    # WORKFLOW_TOOL_NAME omitted — feature('WORKFLOW_SCRIPTS') → False
})

CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = ALL_AGENT_DISALLOWED_TOOLS

ASYNC_AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    FILE_READ_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
    TODO_WRITE_TOOL_NAME,
    GREP_TOOL_NAME,
    WEB_FETCH_TOOL_NAME,
    GLOB_TOOL_NAME,
    *SHELL_TOOL_NAMES,
    FILE_EDIT_TOOL_NAME,
    FILE_WRITE_TOOL_NAME,
    NOTEBOOK_EDIT_TOOL_NAME,
    SKILL_TOOL_NAME,
    SYNTHETIC_OUTPUT_TOOL_NAME,
    TOOL_SEARCH_TOOL_NAME,
    ENTER_WORKTREE_TOOL_NAME,
    EXIT_WORKTREE_TOOL_NAME,
})

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    TASK_CREATE_TOOL_NAME,
    TASK_GET_TOOL_NAME,
    TASK_LIST_TOOL_NAME,
    TASK_UPDATE_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    # CRON_*_TOOL_NAME omitted — feature('AGENT_TRIGGERS') → False
})

COORDINATOR_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    AGENT_TOOL_NAME,
    TASK_STOP_TOOL_NAME,
    SEND_MESSAGE_TOOL_NAME,
    SYNTHETIC_OUTPUT_TOOL_NAME,
})
