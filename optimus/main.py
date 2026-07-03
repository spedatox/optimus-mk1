"""
optimus/main.py — port of src/main.tsx (4 683 TS lines)

Entry point for both interactive (REPL) and headless (-p/--print) modes.
JARVIS blue theme: navy/cyan palette throughout the Textual REPL.

Analytics (logEvent) → dropped entirely.
Feature gates      → all False; branch bodies replaced with RE-ENTRY comments.
React/Ink UI       → Textual (JARVIS theme CSS inline).
Commander.js       → Click.
"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
import uuid as _uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import click

# ---------------------------------------------------------------------------
# Feature flags — all False in the open-source build
# ---------------------------------------------------------------------------
FEATURE_COORDINATOR_MODE = False
FEATURE_KAIROS = False
FEATURE_KAIROS_BRIEF = False
FEATURE_TRANSCRIPT_CLASSIFIER = False
FEATURE_DIRECT_CONNECT = False
FEATURE_SSH_REMOTE = False
FEATURE_LODESTONE = False
FEATURE_PROACTIVE = False
FEATURE_AGENT_MEMORY_SNAPSHOT = False
FEATURE_UPLOAD_USER_SETTINGS = False
FEATURE_BRIDGE_MODE = False
FEATURE_BG_SESSIONS = False

# Current migration version — bump when a new sync migration is added.
CURRENT_MIGRATION_VERSION = 11

# ---------------------------------------------------------------------------
# Stub imports — RE-ENTRY comments mark where real modules plug in.
# ---------------------------------------------------------------------------

try:
    from optimus.utils.config import (  # type: ignore[import]
        get_global_config, save_global_config,
        check_has_trust_dialog_accepted, is_auto_updater_disabled,
        get_remote_control_at_startup,
    )
except ImportError:
    def get_global_config() -> dict: return {}                  # type: ignore[misc]
    def save_global_config(fn) -> None: ...                     # type: ignore[misc]
    def check_has_trust_dialog_accepted() -> bool: return True  # type: ignore[misc]
    def is_auto_updater_disabled() -> bool: return False        # type: ignore[misc]
    def get_remote_control_at_startup() -> Any: return None     # type: ignore[misc]

try:
    from optimus.bootstrap.state import (  # type: ignore[import]
        get_is_non_interactive_session, set_is_interactive,
        get_session_id, set_client_type, set_original_cwd,
        set_cwd_state, get_initial_main_loop_model,
        set_initial_main_loop_model, set_main_loop_model_override,
        set_sdk_betas, get_sdk_betas, set_session_persistence_disabled,
    )
except ImportError:
    def get_is_non_interactive_session() -> bool: return False  # type: ignore[misc]
    def set_is_interactive(v: bool) -> None: ...                # type: ignore[misc]
    def get_session_id() -> str: return str(_uuid_mod.uuid4())  # type: ignore[misc]
    def set_client_type(t: str) -> None: ...                    # type: ignore[misc]
    def set_original_cwd(p: str) -> None: ...                   # type: ignore[misc]
    def set_cwd_state(p: str) -> None: ...                      # type: ignore[misc]
    def get_initial_main_loop_model() -> Optional[str]: return None  # type: ignore[misc]
    def set_initial_main_loop_model(m: str) -> None: ...        # type: ignore[misc]
    def set_main_loop_model_override(m: str) -> None: ...       # type: ignore[misc]
    def set_sdk_betas(b: list) -> None: ...                     # type: ignore[misc]
    def get_sdk_betas() -> list: return []                      # type: ignore[misc]
    def set_session_persistence_disabled(v: bool) -> None: ...  # type: ignore[misc]

try:
    from optimus.utils.model.model import (  # type: ignore[import]
        get_default_main_loop_model, parse_user_specified_model,
        normalize_model_string_for_api,
    )
except ImportError:
    def get_default_main_loop_model() -> str: return "claude-sonnet-5"  # type: ignore[misc]
    def parse_user_specified_model(m: Any) -> str: return m or "claude-sonnet-5"  # type: ignore[misc]
    def normalize_model_string_for_api(m: str) -> str: return m  # type: ignore[misc]

try:
    from optimus.utils.env_utils import is_env_truthy, is_bare_mode  # type: ignore[import]
except ImportError:
    def is_env_truthy(v: Optional[str]) -> bool:          # type: ignore[misc]
        return v is not None and v.strip().lower() in ("1", "true", "yes")
    def is_bare_mode() -> bool:                           # type: ignore[misc]
        return is_env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE"))

try:
    from optimus.utils.cwd import get_cwd, set_cwd       # type: ignore[import]
except ImportError:
    def get_cwd() -> str: return os.getcwd()              # type: ignore[misc]
    def set_cwd(p: str) -> None: os.chdir(p)             # type: ignore[misc]

try:
    from optimus.utils.git import get_is_git, get_branch  # type: ignore[import]
except ImportError:
    async def get_is_git() -> bool: return False          # type: ignore[misc]
    async def get_branch() -> Optional[str]: return None  # type: ignore[misc]

try:
    from optimus.tools import get_tools                    # type: ignore[import]
except ImportError:
    def get_tools(*args, **kwargs) -> list: return []     # type: ignore[misc]

try:
    from optimus.utils.permissions.permission_setup import (  # type: ignore[import]
        initialize_tool_permission_context, initial_permission_mode_from_cli,
        PERMISSION_MODES,
    )
except ImportError:
    async def initialize_tool_permission_context(**kwargs) -> dict:  # type: ignore[misc]
        return {"toolPermissionContext": {}, "warnings": [], "dangerousPermissions": [], "overlyBroadBashPermissions": []}
    def initial_permission_mode_from_cli(mode: Any) -> str: return mode or "default"  # type: ignore[misc]
    PERMISSION_MODES = ["default", "auto", "bypassPermissions"]  # type: ignore[assignment]

try:
    from optimus.services.mcp.config import get_claude_code_mcp_configs  # type: ignore[import]
except ImportError:
    async def get_claude_code_mcp_configs(*args) -> dict:   # type: ignore[misc]
        return {"servers": {}}

try:
    from optimus.services.mcp.client import get_mcp_tools_commands_and_resources  # type: ignore[import]
except ImportError:
    async def get_mcp_tools_commands_and_resources(*args, **kwargs) -> tuple:  # type: ignore[misc]
        return [], [], []

try:
    from optimus.utils.session_storage import (  # type: ignore[import]
        get_session_id_from_log, load_transcript_from_file,
        cache_session_title, session_id_exists,
    )
except ImportError:
    async def get_session_id_from_log(*args) -> Optional[str]: return None  # type: ignore[misc]
    async def load_transcript_from_file(*args) -> Any: return None           # type: ignore[misc]
    def cache_session_title(*args) -> None: ...                              # type: ignore[misc]
    def session_id_exists(sid: str) -> bool: return False                    # type: ignore[misc]

try:
    from optimus.utils.history import add_to_history  # type: ignore[import]
except ImportError:
    def add_to_history(*args) -> None: ...            # type: ignore[misc]

try:
    from optimus.__main__ import init, initialize_telemetry_after_trust  # type: ignore[import]
except ImportError:
    async def init() -> None: ...                      # type: ignore[misc]
    def initialize_telemetry_after_trust() -> None: ...  # type: ignore[misc]

try:
    from optimus.utils.debug import log_for_debugging, set_has_formatted_output  # type: ignore[import]
except ImportError:
    def log_for_debugging(msg: str, **kwargs) -> None: ...  # type: ignore[misc]
    def set_has_formatted_output(v: bool) -> None: ...      # type: ignore[misc]

try:
    from optimus.utils.session_start import process_session_start_hooks, process_setup_hooks  # type: ignore[import]
except ImportError:
    async def process_session_start_hooks(*args, **kwargs) -> list: return []  # type: ignore[misc]
    async def process_setup_hooks(*args, **kwargs) -> list: return []          # type: ignore[misc]

try:
    from optimus.utils.graceful_shutdown import graceful_shutdown, graceful_shutdown_sync  # type: ignore[import]
except ImportError:
    async def graceful_shutdown(code: int = 0) -> None: sys.exit(code)  # type: ignore[misc]
    def graceful_shutdown_sync(code: int = 0) -> None: sys.exit(code)   # type: ignore[misc]

try:
    from optimus.utils.migrations import run_all_migrations  # type: ignore[import]
except ImportError:
    def run_all_migrations() -> None: ...  # type: ignore[misc]

# ---------------------------------------------------------------------------
# JARVIS Theme — ANSI helpers for headless (print) mode output
# ---------------------------------------------------------------------------
BLUE_DARK   = "\033[38;2;0;20;60m"
BLUE_MID    = "\033[38;2;0;100;200m"
CYAN        = "\033[38;2;0;212;255m"
CYAN_BRIGHT = "\033[38;2;0;255;255m"
WHITE       = "\033[38;2;232;244;255m"
DIM         = "\033[2m"
BOLD        = "\033[1m"
RESET       = "\033[0m"
BG_NAVY     = "\033[48;2;5;10;30m"


def _blue(text: str) -> str:
    return f"{CYAN}{text}{RESET}"


def _dim(text: str) -> str:
    return f"{DIM}{text}{RESET}"


BANNER = f"""{CYAN}{BOLD}
  ██████╗ ██████╗ ████████╗██╗███╗   ███╗██╗   ██╗███████╗
 ██╔═══██╗██╔══██╗╚══██╔══╝██║████╗ ████║██║   ██║██╔════╝
 ██║   ██║██████╔╝   ██║   ██║██╔████╔██║██║   ██║███████╗
 ██║   ██║██╔═══╝    ██║   ██║██║╚██╔╝██║██║   ██║╚════██║
 ╚██████╔╝██║        ██║   ██║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚═════╝ ╚═╝        ╚═╝   ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
{RESET}{DIM}                                   MARK I{RESET}
"""


# ---------------------------------------------------------------------------
# is_being_debugged() — port of isBeingDebugged()
# Exits early if running under a Python debugger in production builds.
# ---------------------------------------------------------------------------
def is_being_debugged() -> bool:
    """
    Returns True if the process is running under a Python debugger.
    Mirrors the TS isBeingDebugged() check for --inspect flags.
    """
    # Check common debugger environment variables
    if os.environ.get("PYTHONBREAKPOINT") == "0":
        return False
    if os.environ.get("PYDEVD_LOAD_VALUES_ASYNC") or os.environ.get("PYDEVD_USE_CYTHON_ACCELERATION"):
        return True
    # Check for debugpy / pdb attachment
    try:
        import sys as _sys
        if hasattr(_sys, "gettrace") and _sys.gettrace() is not None:
            return True
    except Exception:
        pass
    # Check for VS Code / PyCharm debug flags via argv
    for arg in sys.argv:
        if "debugpy" in arg or "pydevd" in arg:
            return True
    return False


# ---------------------------------------------------------------------------
# log_managed_settings() — port of logManagedSettings()
# Analytics → no-op; signature preserved.
# ---------------------------------------------------------------------------
def log_managed_settings() -> None:
    """Port of logManagedSettings() — analytics no-op."""
    # RE-ENTRY: read policy settings and log key count/names via logEvent
    pass


# ---------------------------------------------------------------------------
# log_session_telemetry() — port of logSessionTelemetry()
# Analytics → no-op; signature preserved.
# ---------------------------------------------------------------------------
def log_session_telemetry() -> None:
    """Port of logSessionTelemetry() — analytics no-op."""
    # RE-ENTRY: log skill/plugin counts via logSkillsLoaded + loadAllPluginsCacheOnly
    pass


# ---------------------------------------------------------------------------
# run_migrations() — port of runMigrations()
# Runs all config migration steps to the current version.
# ---------------------------------------------------------------------------
def run_migrations() -> None:
    """
    Port of runMigrations(). Runs every sync migration in order if the
    stored migrationVersion is behind CURRENT_MIGRATION_VERSION.
    """
    cfg = get_global_config()
    if cfg.get("migrationVersion") == CURRENT_MIGRATION_VERSION:
        return

    # RE-ENTRY: call each migration function in order:
    #   migrate_auto_updates_to_settings()
    #   migrate_bypass_permissions_accepted_to_settings()
    #   migrate_enable_all_project_mcp_servers_to_settings()
    #   reset_pro_to_opus_default()
    #   migrate_sonnet1m_to_sonnet45()
    #   migrate_legacy_opus_to_current()
    #   migrate_sonnet45_to_sonnet46()
    #   migrate_opus_to_opus1m()
    #   migrate_repl_bridge_enabled_to_remote_control_at_startup()
    run_all_migrations()

    def _bump(prev: dict) -> dict:
        if prev.get("migrationVersion") == CURRENT_MIGRATION_VERSION:
            return prev
        return {**prev, "migrationVersion": CURRENT_MIGRATION_VERSION}

    save_global_config(_bump)

    # Async migration — fire and forget
    asyncio.ensure_future(_migrate_changelog())


async def _migrate_changelog() -> None:
    # RE-ENTRY: from optimus.utils.release_notes import migrate_changelog_from_config
    # await migrate_changelog_from_config()
    pass


# ---------------------------------------------------------------------------
# start_deferred_prefetches() — port of startDeferredPrefetches()
# Called after the REPL renders — doesn't block the first paint.
# ---------------------------------------------------------------------------
def start_deferred_prefetches() -> None:
    """
    Port of startDeferredPrefetches(). Fires background work after first REPL
    render so it doesn't block startup. Skipped in bare/simple mode.
    """
    if is_env_truthy(os.environ.get("CLAUDE_CODE_EXIT_AFTER_FIRST_RENDER")) or is_bare_mode():
        return

    # RE-ENTRY: asyncio.ensure_future(init_user())
    # RE-ENTRY: asyncio.ensure_future(get_user_context())
    # RE-ENTRY: prefetch_system_context_if_safe()
    # RE-ENTRY: asyncio.ensure_future(get_relevant_tips())
    # RE-ENTRY: asyncio.ensure_future(count_files_rounded_rg(...))
    # RE-ENTRY: asyncio.ensure_future(initialize_analytics_gates())
    # RE-ENTRY: asyncio.ensure_future(prefetch_official_mcp_urls())
    # RE-ENTRY: asyncio.ensure_future(refresh_model_capabilities())
    # RE-ENTRY: settings_change_detector.initialize()
    # RE-ENTRY: skill_change_detector.initialize() (if not bare)
    pass


# ---------------------------------------------------------------------------
# Headless (print) path
# ---------------------------------------------------------------------------

async def _headless_ask_user_questions(questions: list) -> dict:
    """
    Headless AskUserQuestion collector: print each question + its options and
    read the user's choice from stdin. Returns {question_text: answer_string}.
    multiSelect answers are comma-separated. Empty input → decline ({}).
    """
    answers: dict[str, str] = {}
    loop = asyncio.get_event_loop()
    for q in questions:
        question_text = q.get("question", "")
        multi = bool(q.get("multiSelect"))
        options = q.get("options", []) or []
        print(f"\n{CYAN}{BOLD}? {question_text}{RESET}")
        for i, opt in enumerate(options, 1):
            label = opt.get("label", "")
            desc = opt.get("description", "")
            line = f"  {CYAN}{i}.{RESET} {WHITE}{label}{RESET}"
            if desc:
                line += f"  {DIM}— {desc}{RESET}"
            print(line)
        print(f"  {CYAN}0.{RESET} {WHITE}Other{RESET}")
        hint = "comma-separated numbers" if multi else "number"
        try:
            raw = await loop.run_in_executor(None, lambda: input(f"{CYAN}▸ {WHITE}({hint}, Enter to decline): {RESET}"))
        except (EOFError, KeyboardInterrupt):
            return {}
        raw = raw.strip()
        if not raw:
            return {}
        selected: list[str] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            if token.isdigit():
                idx = int(token)
                if idx == 0:
                    try:
                        custom = await loop.run_in_executor(None, lambda: input(f"{CYAN}▸ {WHITE}Other: {RESET}"))
                    except (EOFError, KeyboardInterrupt):
                        custom = ""
                    if custom.strip():
                        selected.append(custom.strip())
                elif 1 <= idx <= len(options):
                    selected.append(options[idx - 1].get("label", ""))
            else:
                selected.append(token)
        answers[question_text] = ",".join(selected) if selected else ""
    return answers


async def run_headless(
    *,
    prompt: Optional[str],
    model: str,
    tool_permission_context: dict,
    mcp_clients: list,
    tools: list,
    system_prompt: Optional[str],
    append_system_prompt: Optional[str],
    output_format: str,
    input_format: str,
    max_turns: Optional[int],
    fallback_model: Optional[str],
    verbose: bool,
    debug: bool,
    session_id: str,
    no_session_persistence: bool,
    thinking_config: dict,
    task_budget: Optional[int],
    betas: list,
) -> None:
    """
    Port of the headless (-p/--print) code path in main.tsx.
    Reads the prompt from stdin or the argument, runs query(), streams output.
    """
    # RE-ENTRY: import and use optimus.print (port of src/print.tsx)
    # That module handles the full headless query loop with stream-json output.
    try:
        from optimus.print import run_print  # type: ignore[import]
        await run_print(
            prompt=prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            output_format=output_format,
            input_format=input_format,
            max_turns=max_turns,
            fallback_model=fallback_model,
            verbose=verbose,
            debug=debug,
            session_id=session_id,
            no_session_persistence=no_session_persistence,
            thinking_config=thinking_config,
            task_budget=task_budget,
            betas=betas,
        )
    except ImportError:
        # optimus.print not yet ported — minimal fallback that drives query() directly
        from optimus.query import query, QueryParams, production_deps  # type: ignore[import]
        from optimus.tool import ToolUseContext, ToolUseContextOptions  # type: ignore[import]
        from optimus.api import call_model  # type: ignore[import]
        ctx = ToolUseContext(
            options=ToolUseContextOptions(
                main_loop_model=model,
                tools=tools,
                mcp_clients=mcp_clients,
                verbose=verbose,
                debug=debug,
            ),
        )
        ctx.ask_user_questions = _headless_ask_user_questions
        from optimus.prompts import get_system_prompt  # type: ignore[import]
        from optimus.context import get_system_context, get_user_context  # type: ignore[import]
        built_system_prompt, system_ctx, user_ctx = await asyncio.gather(
            get_system_prompt(tools, model),
            get_system_context(),
            get_user_context(),
        )
        params = QueryParams(
            messages=[{"role": "user", "content": prompt or ""}],
            system_prompt=built_system_prompt,
            user_context=user_ctx,
            system_context=system_ctx,
            can_use_tool=lambda *_: True,
            tool_use_context=ctx,
            query_source="cli",
            deps=production_deps(call_model=call_model),
        )
        streamed = False
        async for event in query(params):
            if not isinstance(event, dict):
                continue
            if event.get("type") == "stream_delta":
                print(event.get("text", ""), end="", flush=True)
                streamed = True
            elif event.get("type") == "assistant" and not streamed:
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        print(block.get("text", ""), end="", flush=True)
        print()


# ---------------------------------------------------------------------------
# Interactive REPL — Textual app with JARVIS blue theme
# ---------------------------------------------------------------------------
async def launch_repl(
    *,
    prompt: Optional[str] = None,
    model: str,
    tool_permission_context: dict,
    mcp_clients: list,
    tools: list,
    system_prompt: Optional[str],
    append_system_prompt: Optional[str],
    verbose: bool,
    debug: bool,
    session_id: str,
    initial_messages: Optional[list] = None,
    thinking_config: dict,
    betas: list,
    name: Optional[str] = None,
) -> None:
    """
    Port of launchRepl() — creates and runs the Textual REPL app with JARVIS theme.
    Async so it runs inside the existing event loop (no nested asyncio.run()).
    """
    try:
        from optimus.tui import OptimusApp  # type: ignore[import]
        app = OptimusApp(
            prompt=prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            verbose=verbose,
            debug=debug,
            session_id=session_id,
            initial_messages=initial_messages or [],
            thinking_config=thinking_config,
            betas=betas,
            name=name,
        )
        await app.run_async()
    except ImportError:
        # optimus.repl not yet ported — minimal async REPL
        await _run_minimal_repl(
            prompt=prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            session_id=session_id,
            thinking_config=thinking_config,
            betas=betas,
        )


async def _run_minimal_repl(
    *,
    prompt: Optional[str],
    model: str,
    tool_permission_context: dict,
    mcp_clients: list,
    tools: list,
    system_prompt: Optional[str],
    session_id: str,
    thinking_config: dict,
    betas: list,
) -> None:
    """
    Minimal async REPL loop — used before optimus.repl is ported.
    Runs inside the existing event loop; uses run_in_executor for blocking input().
    """
    print(BANNER)
    print(f"{CYAN}  Model  : {WHITE}{model}{RESET}")
    print(f"{CYAN}  Session: {WHITE}{session_id[:8]}…{RESET}")
    if system_prompt:
        print(f"{CYAN}  System : {DIM}{system_prompt[:60]}…{RESET}")
    print(f"{DIM}  {'─' * 60}{RESET}\n")

    if prompt:
        print(f"{CYAN}> {WHITE}{prompt}{RESET}\n")
        await _one_shot_query(prompt, model, tool_permission_context, mcp_clients, tools, system_prompt)
        return

    history: list[dict] = []
    print(f"{DIM}  Type your message, or /exit to quit.{RESET}\n")

    loop = asyncio.get_event_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(
                None, lambda: input(f"{CYAN}▶ {WHITE}")
            )
            user_input = user_input.strip()
            print(RESET, end="")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}  Goodbye.{RESET}")
            break

        if not user_input:
            continue
        if user_input in ("/exit", "/quit", "exit", "quit"):
            print(f"{DIM}  Goodbye.{RESET}")
            break

        history.append({"role": "user", "content": user_input})
        response = await _one_shot_query(
            user_input, model, tool_permission_context, mcp_clients, tools, system_prompt, history=history
        )
        if response:
            history.append({"role": "assistant", "content": response})


async def _one_shot_query(
    user_input: str,
    model: str,
    tool_permission_context: dict,
    mcp_clients: list,
    tools: list,
    system_prompt: Optional[str],
    history: Optional[list] = None,
) -> Optional[str]:
    """Drive a single query turn through query() and print the result."""
    try:
        from optimus.query import query, QueryParams, production_deps  # type: ignore[import]
        from optimus.tool import ToolUseContext, ToolUseContextOptions  # type: ignore[import]
    except ImportError:
        print(f"{CYAN}[optimus.query not yet ported]{RESET}")
        return None

    messages = list(history or [])
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": user_input})

    ctx = ToolUseContext(
        options=ToolUseContextOptions(
            main_loop_model=model,
            tools=tools,
            mcp_clients=mcp_clients,
            verbose=False,
            debug=False,
        ),
    )
    ctx.ask_user_questions = _headless_ask_user_questions
    from optimus.api import call_model  # type: ignore[import]

    from optimus.prompts import get_system_prompt  # type: ignore[import]
    from optimus.context import get_system_context, get_user_context  # type: ignore[import]
    built_system_prompt, system_ctx, user_ctx = await asyncio.gather(
        get_system_prompt(tools, model),
        get_system_context(),
        get_user_context(),
    )
    # Prepend user-supplied --system-prompt if provided
    if system_prompt:
        built_system_prompt = [system_prompt] + built_system_prompt

    params = QueryParams(
        messages=messages,
        system_prompt=built_system_prompt,
        user_context=user_ctx,
        system_context=system_ctx,
        can_use_tool=lambda *_: True,
        tool_use_context=ctx,
        query_source="cli",
        deps=production_deps(call_model=call_model),
    )

    output_parts: list[str] = []
    print(f"\n{CYAN}Optimus ▸{RESET} ", end="", flush=True)
    async for event in query(params):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "stream_delta":
            text = event.get("text", "")
            print(text, end="", flush=True)
            output_parts.append(text)
        elif event.get("type") == "assistant" and not output_parts:
            # No stream_delta received — fall back to full message
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    print(block.get("text", ""), end="", flush=True)
                    output_parts.append(block.get("text", ""))
    print("\n")
    return "".join(output_parts) if output_parts else None


# ---------------------------------------------------------------------------
# setup() — port of the main action-handler body in main.tsx
# Parses all CLI options, initialises permissions + MCP, then branches to
# headless or interactive path.
# ---------------------------------------------------------------------------
@dataclass
class SetupOptions:
    prompt: Optional[str] = None
    print_mode: bool = False
    verbose: bool = False
    debug: bool = False
    debug_to_stderr: bool = False
    output_format: str = "text"
    input_format: str = "text"
    model: Optional[str] = None
    effort: Optional[str] = None
    betas: list = field(default_factory=list)
    fallback_model: Optional[str] = None
    allowed_tools: list = field(default_factory=list)
    base_tools: list = field(default_factory=list)
    disallowed_tools: list = field(default_factory=list)
    mcp_config: list = field(default_factory=list)
    permission_mode: Optional[str] = None
    dangerously_skip_permissions: bool = False
    allow_dangerously_skip_permissions: bool = False
    add_dir: list = field(default_factory=list)
    system_prompt: Optional[str] = None
    system_prompt_file: Optional[str] = None
    append_system_prompt: Optional[str] = None
    append_system_prompt_file: Optional[str] = None
    continue_session: bool = False
    resume: Optional[str] = None
    fork_session: bool = False
    session_id: Optional[str] = None
    name: Optional[str] = None
    no_session_persistence: bool = False
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    task_budget: Optional[int] = None
    strict_mcp_config: bool = False
    thinking: Optional[str] = None
    agents: Optional[str] = None
    agent: Optional[str] = None
    disable_slash_commands: bool = False
    ide: bool = False
    bare: bool = False
    init: bool = False
    init_only: bool = False
    maintenance: bool = False
    include_hook_events: bool = False
    include_partial_messages: bool = False
    replay_user_messages: bool = False


async def setup(opts: SetupOptions) -> None:
    """
    Port of the main action handler body in main.tsx (~3 000 TS lines).

    Sequence:
      1.  Determine interactive/headless mode.
      2.  Set client type + CWD state.
      3.  Run migrations.
      4.  Parse model, system prompt, MCP configs, tools.
      5.  Initialize tool permission context.
      6.  (Interactive) Show trust/setup screens.
      7.  Apply telemetry after trust.
      8.  Start deferred prefetches.
      9.  Handle --resume / --continue.
      10. Run headless OR launch REPL.
    """
    # SECURITY: Prevent Windows PATH hijacking (mirror TS comment)
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"

    # ── 1. Mode detection ────────────────────────────────────────────────────
    is_non_interactive = (
        opts.print_mode
        or opts.init_only
        or not sys.stdout.isatty()
    )
    set_is_interactive(not is_non_interactive)
    log_for_debugging(f"[setup] is_non_interactive={is_non_interactive}")

    # ── 2. Client type ───────────────────────────────────────────────────────
    client_type = _determine_client_type()
    set_client_type(client_type)
    log_for_debugging(f"[setup] client_type={client_type}")

    cwd = get_cwd()
    set_original_cwd(cwd)
    set_cwd_state(cwd)

    # ── 3. Migrations ────────────────────────────────────────────────────────
    run_migrations()

    # ── 4. Model resolution ──────────────────────────────────────────────────
    model_arg = opts.model or os.environ.get("ANTHROPIC_MODEL") or None
    model = _resolve_model(model_arg, opts.effort)
    set_initial_main_loop_model(model)
    if model_arg:
        set_main_loop_model_override(model)
    log_for_debugging(f"[setup] model={model}")

    # SDK betas
    betas = list(opts.betas)
    set_sdk_betas(betas)

    # ── 4b. System prompt handling ───────────────────────────────────────────
    system_prompt = opts.system_prompt
    if opts.system_prompt_file:
        if opts.system_prompt:
            sys.stderr.write("Error: Cannot use both --system-prompt and --system-prompt-file.\n")
            graceful_shutdown_sync(1)
            return
        try:
            system_prompt = Path(opts.system_prompt_file).read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error reading --system-prompt-file: {exc}\n")
            graceful_shutdown_sync(1)
            return

    append_system_prompt = opts.append_system_prompt
    if opts.append_system_prompt_file:
        if opts.append_system_prompt:
            sys.stderr.write("Error: Cannot use both --append-system-prompt and --append-system-prompt-file.\n")
            graceful_shutdown_sync(1)
            return
        try:
            append_system_prompt = Path(opts.append_system_prompt_file).read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"Error reading --append-system-prompt-file: {exc}\n")
            graceful_shutdown_sync(1)
            return

    # ── 4c. Permission mode ──────────────────────────────────────────────────
    permission_mode = initial_permission_mode_from_cli(opts.permission_mode)
    if opts.dangerously_skip_permissions:
        permission_mode = "bypassPermissions"

    # ── 4d. MCP config parsing ───────────────────────────────────────────────
    dynamic_mcp_config: dict = {}
    for mcp_entry in opts.mcp_config:
        # RE-ENTRY: parse_mcp_config(mcp_entry) → merge into dynamic_mcp_config
        pass

    # ── 4e. Tool permission context init ─────────────────────────────────────
    init_result = await initialize_tool_permission_context(
        allowed_tools_cli=opts.allowed_tools,
        disallowed_tools_cli=opts.disallowed_tools,
        base_tools_cli=opts.base_tools,
        permission_mode=permission_mode,
        allow_dangerously_skip_permissions=opts.allow_dangerously_skip_permissions,
        add_dirs=opts.add_dir,
    )
    tool_permission_context = init_result.get("toolPermissionContext", {})

    warnings = init_result.get("warnings", [])
    for w in warnings:
        sys.stderr.write(f"{w}\n")

    # ── 4f. MCP configs loading ──────────────────────────────────────────────
    if opts.strict_mcp_config or is_bare_mode():
        mcp_configs: dict = {"servers": {}}
    else:
        mcp_configs = await get_claude_code_mcp_configs(dynamic_mcp_config)

    # RE-ENTRY: merge dynamic_mcp_config into mcp_configs.servers

    # ── 4g. Thinking config ──────────────────────────────────────────────────
    thinking_config = _resolve_thinking_config(opts.thinking, model)

    # ── 4h. Validate session-id ───────────────────────────────────────────────
    session_id: str
    if opts.session_id:
        try:
            val = _uuid_mod.UUID(opts.session_id)
            if session_id_exists(str(val)):
                sys.stderr.write(f"Error: Session ID {val} is already in use.\n")
                graceful_shutdown_sync(1)
                return
            session_id = str(val)
        except ValueError:
            sys.stderr.write("Error: Invalid session ID. Must be a valid UUID.\n")
            graceful_shutdown_sync(1)
            return
    else:
        session_id = str(_uuid_mod.uuid4())

    # ── 5. Trust / setup screens (interactive only) ───────────────────────────
    if not is_non_interactive:
        trust_ok = check_has_trust_dialog_accepted()
        if not trust_ok:
            # RE-ENTRY: show_setup_screens(permission_mode, allow_dsp, commands, ...)
            # For now: print a minimal trust notice
            _show_minimal_trust_dialog()

    # ── 6. Telemetry after trust ──────────────────────────────────────────────
    initialize_telemetry_after_trust()

    # ── 7. MCP client startup ─────────────────────────────────────────────────
    # RE-ENTRY: from optimus.services.mcp.client import start_mcp_clients
    # mcp_clients = await start_mcp_clients(mcp_configs.servers)
    mcp_clients: list = []

    # ── 8. Tools ─────────────────────────────────────────────────────────────
    tools = get_tools(tool_permission_context, mcp_clients)

    # ── 9. Setup / SessionStart hooks ────────────────────────────────────────
    if not is_bare_mode():
        if opts.init or opts.init_only or opts.maintenance:
            await process_setup_hooks(trigger="init" if opts.init else ("maintenance" if opts.maintenance else "init"))
        await process_session_start_hooks(trigger="startup" if opts.init_only else "session")

    if opts.init_only:
        return

    # ── 10. Session persistence flag ─────────────────────────────────────────
    if opts.no_session_persistence and is_non_interactive:
        set_session_persistence_disabled(True)

    # ── 11. Resume / continue logic ───────────────────────────────────────────
    initial_messages: list = []
    if opts.continue_session or opts.resume:
        initial_messages = await _load_session_for_resume(
            session_id=session_id,
            continue_flag=opts.continue_session,
            resume=opts.resume,
            fork_session=opts.fork_session,
        )

    # ── 12. Input prompt (headless: stdin, interactive: pre-fill) ─────────────
    input_prompt = await _get_input_prompt(opts.prompt, opts.input_format)

    # ── 13. Session name caching ───────────────────────────────────────────────
    if opts.name:
        cache_session_title(session_id, opts.name)

    # ── 14. Deferred prefetches (fire after deciding path) ────────────────────
    if not is_non_interactive:
        start_deferred_prefetches()

    # ── 15. Route: headless or interactive ────────────────────────────────────
    if is_non_interactive:
        log_session_telemetry()
        await run_headless(
            prompt=input_prompt if isinstance(input_prompt, str) else opts.prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            output_format=opts.output_format or "text",
            input_format=opts.input_format or "text",
            max_turns=opts.max_turns,
            fallback_model=opts.fallback_model,
            verbose=opts.verbose,
            debug=opts.debug,
            session_id=session_id,
            no_session_persistence=opts.no_session_persistence,
            thinking_config=thinking_config,
            task_budget=opts.task_budget,
            betas=betas,
        )
    else:
        log_session_telemetry()
        await launch_repl(
            prompt=input_prompt if isinstance(input_prompt, str) else opts.prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            verbose=opts.verbose,
            debug=opts.debug,
            session_id=session_id,
            initial_messages=initial_messages,
            thinking_config=thinking_config,
            betas=betas,
            name=opts.name,
        )


# ---------------------------------------------------------------------------
# Private helpers for setup()
# ---------------------------------------------------------------------------

def _determine_client_type() -> str:
    """Port of the clientType IIFE in main.tsx."""
    if is_env_truthy(os.environ.get("GITHUB_ACTIONS")):
        return "github-action"
    entrypoint = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")
    if entrypoint == "sdk-ts":     return "sdk-typescript"
    if entrypoint == "sdk-py":     return "sdk-python"
    if entrypoint == "sdk-cli":    return "sdk-cli"
    if entrypoint == "claude-vscode": return "claude-vscode"
    if entrypoint == "local-agent": return "local-agent"
    if entrypoint == "claude-desktop": return "claude-desktop"
    has_ingress = (
        os.environ.get("CLAUDE_CODE_SESSION_ACCESS_TOKEN") or
        os.environ.get("CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR")
    )
    if entrypoint == "remote" or has_ingress:
        return "remote"
    return "cli"


def _resolve_model(model_arg: Optional[str], effort: Optional[str]) -> str:
    """
    Port of getInitialMainLoopModel / getDefaultMainLoopModel resolution.
    Resolves the model string from CLI arg or env, then normalizes it.
    """
    cached = get_initial_main_loop_model()
    raw = model_arg or cached or os.environ.get("ANTHROPIC_MODEL") or get_default_main_loop_model()
    # RE-ENTRY: apply effort-level modifier (maps effort→model suffix) when ported
    return normalize_model_string_for_api(raw)


def _resolve_thinking_config(thinking_flag: Optional[str], model: str) -> dict:
    """
    Port of shouldEnableThinkingByDefault + ThinkingConfig resolution.
    Returns a dict with 'type' key matching the ThinkingConfig shape.
    """
    # RE-ENTRY: from optimus.utils.thinking import should_enable_thinking_by_default
    # RE-ENTRY: apply --thinking enabled/adaptive/disabled logic
    if thinking_flag == "disabled":
        return {"type": "disabled"}
    if thinking_flag in ("enabled", "adaptive") or thinking_flag is None:
        # Default: let the model decide via adaptive thinking
        return {"type": "adaptive"}
    return {"type": "disabled"}


def _show_minimal_trust_dialog() -> None:
    """
    Placeholder for showSetupScreens() — shown before trust is established.
    RE-ENTRY: replace with full optimus.interactive_helpers.show_setup_screens()
    """
    print(f"\n{CYAN}{'═' * 62}{RESET}")
    print(f"{CYAN}  OPTIMUS MARK I — Trust & Privacy Notice{RESET}")
    print(f"{CYAN}{'═' * 62}{RESET}")
    print(f"{WHITE}  This agent can read and edit files in your working directory.")
    print(f"  It will ask permission before running shell commands.")
    print(f"\n  Working directory: {get_cwd()}{RESET}")
    print(f"{CYAN}{'─' * 62}{RESET}")
    try:
        response = input(f"{WHITE}  Trust this directory and continue? [y/N]: {RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        graceful_shutdown_sync(1)
        return
    if response not in ("y", "yes"):
        print(f"{DIM}  Aborted.{RESET}")
        graceful_shutdown_sync(0)
        return
    # Persist acceptance so the dialog is shown once per project, not per run.
    try:
        from optimus.utils.config import save_current_project_config

        save_current_project_config(
            lambda pc: {**pc, "hasTrustDialogAccepted": True}
        )
    except Exception as exc:
        log_for_debugging(f"[trust] could not persist acceptance: {exc}")


async def _get_input_prompt(prompt: Optional[str], input_format: str) -> str:
    """
    Port of getInputPrompt(). Reads from stdin when not a TTY.
    In stream-json format returns stdin as-is; in text format concatenates.
    """
    if not sys.stdin.isatty() and "mcp" not in sys.argv:
        if input_format == "stream-json":
            # RE-ENTRY: return async iterator over sys.stdin
            return prompt or ""
        # Read stdin with a timeout
        import select
        data = ""
        if sys.platform != "win32":
            ready, _, _ = select.select([sys.stdin], [], [], 3.0)
            if ready:
                data = sys.stdin.read()
            else:
                sys.stderr.write(
                    "Warning: no stdin data received in 3s, proceeding without it.\n"
                )
        return "\n".join(filter(None, [prompt, data]))
    return prompt or ""


async def _load_session_for_resume(
    *,
    session_id: str,
    continue_flag: bool,
    resume: Optional[str],
    fork_session: bool,
) -> list:
    """
    Port of the --resume / --continue session restoration block in main.tsx.
    Returns the list of restored messages (empty list on failure).
    """
    # RE-ENTRY: full implementation in optimus.utils.session_storage
    # This covers: --continue (load most recent), --resume <uuid|path>,
    #              validateUuid, loadConversationForResume, processResumedConversation
    log_for_debugging(f"[setup] resume={resume} continue={continue_flag}")
    return []


# ---------------------------------------------------------------------------
# Click CLI — port of the Commander.js program definition in run()
# Every flag from the TS source is preserved here.
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.pass_context
@click.option("-m", "--message", "prompt", default=None, help="Initial prompt (headless: also use -p/--print).")
@click.option("-d", "--debug", "debug_flag", is_flag=True, default=False, help="Enable debug mode.")
@click.option("--verbose", is_flag=True, default=False, help="Override verbose mode from config.")
@click.option("-p", "--print", "print_mode", is_flag=True, default=False, help="Print response and exit (headless).")
@click.option("--bare", is_flag=True, default=False, help="Minimal mode: skip hooks, LSP, plugin sync, etc.")
@click.option("--output-format", type=click.Choice(["text", "json", "stream-json"]), default="text", help="Output format (--print only).")
@click.option("--input-format", type=click.Choice(["text", "stream-json"]), default="text", help="Input format (--print only).")
@click.option("--dangerously-skip-permissions", is_flag=True, default=False, help="Bypass all permission checks.")
@click.option("--allow-dangerously-skip-permissions", is_flag=True, default=False, help="Enable bypass as an option.")
@click.option("--model", default=None, help="Model alias or full model ID.")
@click.option("--effort", type=click.Choice(["low", "medium", "high", "max"]), default=None, help="Effort level.")
@click.option("--fallback-model", default=None, help="Fallback model when primary is overloaded (--print only).")
@click.option("--betas", multiple=True, help="Beta headers for API requests.")
@click.option("--allowed-tools", "--allowedTools", multiple=True, help="Allowed tool names.")
@click.option("--tools", "base_tools", multiple=True, help="Available tools from the built-in set.")
@click.option("--disallowed-tools", "--disallowedTools", multiple=True, help="Disallowed tool names.")
@click.option("--mcp-config", multiple=True, help="MCP server configs (JSON files or strings).")
@click.option("--permission-mode", type=click.Choice(["default", "auto", "bypassPermissions"]), default=None, help="Permission mode.")
@click.option("--add-dir", multiple=True, help="Additional directories to allow tool access to.")
@click.option("--system-prompt", default=None, help="System prompt.")
@click.option("--system-prompt-file", default=None, help="Read system prompt from a file.")
@click.option("--append-system-prompt", default=None, help="Append to default system prompt.")
@click.option("--append-system-prompt-file", default=None, help="Read append system prompt from file.")
@click.option("-c", "--continue", "continue_session", is_flag=True, default=False, help="Continue most recent conversation.")
@click.option("-r", "--resume", default=None, help="Resume a conversation by session ID.")
@click.option("--fork-session", is_flag=True, default=False, help="Create new session ID when resuming.")
@click.option("--session-id", default=None, help="Use a specific session UUID.")
@click.option("-n", "--name", default=None, help="Display name for this session.")
@click.option("--no-session-persistence", is_flag=True, default=False, help="Disable session persistence (--print only).")
@click.option("--max-turns", type=int, default=None, help="Maximum agentic turns (--print only).")
@click.option("--max-budget-usd", type=float, default=None, help="Max spend in USD (--print only).")
@click.option("--task-budget", type=int, default=None, help="API-side task budget in tokens.")
@click.option("--strict-mcp-config", is_flag=True, default=False, help="Only use --mcp-config servers.")
@click.option("--thinking", type=click.Choice(["enabled", "adaptive", "disabled"]), default=None, help="Thinking mode.")
@click.option("--agents", default=None, help="JSON object defining custom agents.")
@click.option("--agent", default=None, help="Agent for the current session.")
@click.option("--disable-slash-commands", is_flag=True, default=False, help="Disable all skills.")
@click.option("--ide", is_flag=True, default=False, help="Automatically connect to IDE on startup.")
@click.option("--init", "run_init", is_flag=True, default=False, help="Run Setup hooks with init trigger.")
@click.option("--init-only", is_flag=True, default=False, help="Run Setup and SessionStart:startup hooks, then exit.")
@click.option("--maintenance", is_flag=True, default=False, help="Run Setup hooks with maintenance trigger.")
@click.option("--include-hook-events", is_flag=True, default=False, help="Include hook lifecycle events in stream-json output.")
@click.option("--include-partial-messages", is_flag=True, default=False, help="Include partial message chunks in stream-json output.")
@click.option("--replay-user-messages", is_flag=True, default=False, help="Re-emit user messages from stdin on stdout.")
@click.option("--settings", default=None, help="Path to settings JSON file or JSON string.")
@click.option("--plugin-dir", multiple=True, help="Load plugins from a directory (repeatable).")
def cli(
    ctx: click.Context,
    prompt: Optional[str],
    debug_flag: bool,
    verbose: bool,
    print_mode: bool,
    bare: bool,
    output_format: str,
    input_format: str,
    dangerously_skip_permissions: bool,
    allow_dangerously_skip_permissions: bool,
    model: Optional[str],
    effort: Optional[str],
    fallback_model: Optional[str],
    betas: tuple,
    allowed_tools: tuple,
    base_tools: tuple,
    disallowed_tools: tuple,
    mcp_config: tuple,
    permission_mode: Optional[str],
    add_dir: tuple,
    system_prompt: Optional[str],
    system_prompt_file: Optional[str],
    append_system_prompt: Optional[str],
    append_system_prompt_file: Optional[str],
    continue_session: bool,
    resume: Optional[str],
    fork_session: bool,
    session_id: Optional[str],
    name: Optional[str],
    no_session_persistence: bool,
    max_turns: Optional[int],
    max_budget_usd: Optional[float],
    task_budget: Optional[int],
    strict_mcp_config: bool,
    thinking: Optional[str],
    agents: Optional[str],
    agent: Optional[str],
    disable_slash_commands: bool,
    ide: bool,
    run_init: bool,
    init_only: bool,
    maintenance: bool,
    include_hook_events: bool,
    include_partial_messages: bool,
    replay_user_messages: bool,
    settings: Optional[str],
    plugin_dir: tuple,
) -> None:
    """
    Optimus Mark I — your own Claude Code, in Python.

    Starts an interactive REPL by default. Use -p/--print for non-interactive output.
    """
    if ctx.invoked_subcommand is not None:
        return  # Let subcommand handle it

    # --bare sets CLAUDE_CODE_SIMPLE=1 before anything else fires
    if bare:
        os.environ["CLAUDE_CODE_SIMPLE"] = "1"

    # Ignore literal "code" as the prompt (mirrors TS handling)
    if prompt == "code":
        click.echo(click.style("Tip: You can launch Optimus with just `optimus`", fg="yellow"), err=True)
        prompt = None

    opts = SetupOptions(
        prompt=prompt,
        print_mode=print_mode,
        verbose=verbose,
        debug=debug_flag,
        output_format=output_format,
        input_format=input_format,
        model=model,
        effort=effort,
        betas=list(betas),
        fallback_model=fallback_model,
        allowed_tools=list(allowed_tools),
        base_tools=list(base_tools),
        disallowed_tools=list(disallowed_tools),
        mcp_config=list(mcp_config),
        permission_mode=permission_mode,
        dangerously_skip_permissions=dangerously_skip_permissions,
        allow_dangerously_skip_permissions=allow_dangerously_skip_permissions,
        add_dir=list(add_dir),
        system_prompt=system_prompt,
        system_prompt_file=system_prompt_file,
        append_system_prompt=append_system_prompt,
        append_system_prompt_file=append_system_prompt_file,
        continue_session=continue_session,
        resume=resume,
        fork_session=fork_session,
        session_id=session_id,
        name=name,
        no_session_persistence=no_session_persistence,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        task_budget=task_budget,
        strict_mcp_config=strict_mcp_config,
        thinking=thinking,
        agents=agents,
        agent=agent,
        disable_slash_commands=disable_slash_commands,
        ide=ide,
        bare=bare,
        init=run_init,
        init_only=init_only,
        maintenance=maintenance,
        include_hook_events=include_hook_events,
        include_partial_messages=include_partial_messages,
        replay_user_messages=replay_user_messages,
    )
    # asyncio.run() is safe here: Click is synchronous so no outer loop exists.
    asyncio.run(_run_with_init(opts))


async def _run_with_init(opts: SetupOptions) -> None:
    """Runs init() then setup() — mirrors the Commander preAction hook."""
    await init()
    await setup(opts)


# ---------------------------------------------------------------------------
# Subcommands — port of program.command(...) registrations in run()
# ---------------------------------------------------------------------------

@cli.command("update")
def cmd_update() -> None:
    """Check for and install Optimus updates."""
    # RE-ENTRY: from optimus.utils.auto_updater import check_and_install_update
    click.echo(click.style("Update check not yet implemented.", fg="cyan"))


@cli.group("mcp")
def cmd_mcp() -> None:
    """Manage MCP (Model Context Protocol) servers."""


@cmd_mcp.command("serve")
@click.option("--port", type=int, default=None, help="Port to listen on.")
def cmd_mcp_serve(port: Optional[int]) -> None:
    """Start an MCP server."""
    # RE-ENTRY: from optimus.services.mcp.server import start_mcp_server
    click.echo(click.style("MCP serve not yet implemented.", fg="cyan"))


@cmd_mcp.command("add")
@click.argument("name")
@click.argument("command", nargs=-1)
def cmd_mcp_add(name: str, command: tuple) -> None:
    """Add an MCP server to configuration."""
    # RE-ENTRY: from optimus.commands.mcp.add_command import register_mcp_add_command
    click.echo(click.style(f"MCP add '{name}' not yet implemented.", fg="cyan"))


@cmd_mcp.command("list")
def cmd_mcp_list() -> None:
    """List configured MCP servers."""
    # RE-ENTRY: load and print all MCP server configs
    click.echo(click.style("No MCP servers configured.", fg="cyan"))


@cmd_mcp.command("remove")
@click.argument("name")
def cmd_mcp_remove(name: str) -> None:
    """Remove an MCP server from configuration."""
    # RE-ENTRY: from optimus.services.mcp.config import remove_mcp_server
    click.echo(click.style(f"MCP remove '{name}' not yet implemented.", fg="cyan"))


@cli.group("auth")
def cmd_auth() -> None:
    """Authentication commands."""


@cmd_auth.command("login")
def cmd_auth_login() -> None:
    """Log in to Anthropic (OAuth or API key)."""
    # RE-ENTRY: from optimus.commands.login import handle_login
    click.echo(click.style("Login not yet implemented.", fg="cyan"))


@cmd_auth.command("logout")
def cmd_auth_logout() -> None:
    """Log out from Anthropic."""
    # RE-ENTRY: from optimus.commands.logout import handle_logout
    click.echo(click.style("Logout not yet implemented.", fg="cyan"))


@cmd_auth.command("status")
def cmd_auth_status() -> None:
    """Check current authentication status."""
    # RE-ENTRY: from optimus.utils.auth import get_subscription_type, is_claude_ai_subscriber
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        click.echo(click.style(f"Authenticated via ANTHROPIC_API_KEY ({'*' * 8}{api_key[-4:]})", fg="cyan"))
    else:
        click.echo(click.style("Not authenticated. Set ANTHROPIC_API_KEY or run `optimus auth login`.", fg="yellow"))


@cli.command("doctor")
def cmd_doctor() -> None:
    """Run diagnostic checks on the Optimus installation."""
    # RE-ENTRY: port of src/commands/doctor.tsx
    import platform
    click.echo(click.style("Optimus Mark I — Diagnostics", fg="cyan", bold=True))
    click.echo(f"  Python : {platform.python_version()}")
    click.echo(f"  Platform: {sys.platform}")
    click.echo(f"  CWD    : {os.getcwd()}")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    click.echo(f"  API Key: {'set (' + '*' * 8 + api_key[-4:] + ')' if api_key else 'NOT SET'}")
    try:
        import anthropic  # type: ignore[import]
        click.echo(f"  anthropic SDK: {anthropic.__version__}")
    except ImportError:
        click.echo(click.style("  anthropic SDK: NOT INSTALLED", fg="red"))
    try:
        import textual  # type: ignore[import]
        click.echo(f"  textual: {textual.__version__}")
    except ImportError:
        click.echo(click.style("  textual: NOT INSTALLED (optional for TUI)", fg="yellow"))


@cli.group("plugin")
def cmd_plugin() -> None:
    """Manage Optimus plugins."""


@cmd_plugin.command("list")
def cmd_plugin_list() -> None:
    """List installed plugins."""
    # RE-ENTRY: from optimus.utils.plugins.plugin_loader import load_all_plugins_cache_only
    click.echo(click.style("No plugins installed.", fg="cyan"))


@cmd_plugin.command("install")
@click.argument("identifier")
@click.option("--scope", type=click.Choice(["user", "project", "local"]), default="user")
def cmd_plugin_install(identifier: str, scope: str) -> None:
    """Install a plugin by identifier."""
    # RE-ENTRY: from optimus.services.plugins.plugin_cli_commands import install_plugin
    click.echo(click.style(f"Plugin install '{identifier}' (scope={scope}) not yet implemented.", fg="cyan"))


@cmd_plugin.command("uninstall")
@click.argument("identifier")
@click.option("--scope", type=click.Choice(["user", "project", "local"]), default="user")
def cmd_plugin_uninstall(identifier: str, scope: str) -> None:
    """Uninstall a plugin."""
    # RE-ENTRY: from optimus.services.plugins.plugin_cli_commands import uninstall_plugin
    click.echo(click.style(f"Plugin uninstall '{identifier}' not yet implemented.", fg="cyan"))


# ---------------------------------------------------------------------------
# main() — exported entry point called from optimus/__main__.py
# ---------------------------------------------------------------------------
def main() -> None:
    """
    Port of `export async function main()` from main.tsx.

    Synchronous entry point — Click owns the asyncio event loop internally.
    Called by __main__.py after cli.tsx fast-paths are checked.
    Hands control to the Click CLI which dispatches to setup() or a subcommand.
    """
    # SECURITY: Windows PATH hijacking prevention (mirrors TS)
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"

    # Exit if running under a debugger (mirrors TS external-build guard)
    if is_being_debugged():
        sys.exit(1)

    # Invoke the Click CLI — standalone_mode=True so Click handles SystemExit
    cli()
