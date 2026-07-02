"""
bootstrap/state.py — port of src/bootstrap/state.ts

The global session-state singleton. Holds the one mutable STATE record that
the rest of the program reads/writes through ~110 accessor functions:
cwd / project root, cost & duration counters, per-turn timing, model
selection, session id + lineage, telemetry counters, beta-header latches,
plan/auto-mode transition flags, invoked skills, scroll-drain gating, etc.

Porting notes:
  - The TS module holds a single `STATE` object created once by
    getInitialState(); Python mirrors this with a `State` dataclass and a
    module-level `_STATE` singleton.
  - randomUUID (src/utils/crypto.ts) → uuid.uuid4().
  - createSignal (src/utils/signal.ts) → ported faithfully inline (8-line leaf).
  - resetSettingsCache (src/utils/settings/settingsCache.ts) → dependency stub
    until settings/ is ported (see _reset_settings_cache).
  - sumBy (lodash-es) → _sum_by() helper.
  - Date.now() → _now_ms() (epoch milliseconds, matching JS semantics).
  - OpenTelemetry types (Meter, AttributedCounter, LoggerProvider, …) → Any.
    The telemetry *pipeline* is dropped per project rules, but the state
    fields + accessors are preserved because non-telemetry code reads them.
  - process.env.USER_TYPE === 'ant' branches → os.environ checks (always the
    external build in practice, but preserved for fidelity).
  - .normalize('NFC') → unicodedata.normalize('NFC', …).
  - setTimeout(...).unref() for scroll-drain debounce → threading.Timer
    (daemon) so it never blocks interpreter exit.
"""
from __future__ import annotations

import os
import threading
import time
import unicodedata
import uuid as _uuid_mod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Leaf helpers (faithful ports / dependency stubs)
# ---------------------------------------------------------------------------


def _random_uuid() -> str:
    """Mirrors randomUUID() from src/utils/crypto.ts (re-export of node:crypto)."""
    return str(_uuid_mod.uuid4())


def _now_ms() -> int:
    """Mirror JS Date.now() — epoch milliseconds as an int."""
    return int(time.time() * 1000)


def _sum_by(values: list[dict[str, Any]], key: str) -> float:
    """Mirror lodash-es sumBy(collection, key) over numeric fields (missing → 0)."""
    total = 0.0
    for v in values:
        n = v.get(key) if isinstance(v, dict) else getattr(v, key, None)
        if isinstance(n, (int, float)):
            total += n
    return total


def _reset_settings_cache() -> None:
    """
    Dependency stub — mirrors resetSettingsCache() from
    src/utils/settings/settingsCache.ts. Invalidates the settings read cache.
    Replace when settings/ is ported.
    """
    # RE-ENTRY: from optimus.utils.settings.settings_cache import reset_settings_cache


class Signal:
    """
    Faithful port of createSignal() from src/utils/signal.ts.

    Tiny listener-set primitive for pure event signals (no stored state).
    subscribe() returns an unsubscribe callable; emit() fans out to all
    listeners; clear() drops them all.
    """

    def __init__(self) -> None:
        self._listeners: set[Callable[..., None]] = set()

    def subscribe(self, listener: Callable[..., None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def _unsubscribe() -> None:
            self._listeners.discard(listener)

        return _unsubscribe

    def emit(self, *args: Any) -> None:
        # Iterate over a copy so listeners may unsubscribe during emit.
        for listener in list(self._listeners):
            listener(*args)

    def clear(self) -> None:
        self._listeners.clear()


def create_signal() -> Signal:
    """Mirror createSignal<Args>() — returns a fresh Signal."""
    return Signal()


# ---------------------------------------------------------------------------
# ChannelEntry / SessionCronTask / InvokedSkillInfo type mirrors
# ---------------------------------------------------------------------------

# ChannelEntry — discriminated union in TS:
#   { kind: 'plugin', name, marketplace, dev? } | { kind: 'server', name, dev? }
# In Python it's a plain dict with those keys.
ChannelEntry = dict[str, Any]


@dataclass
class SessionCronTask:
    """Mirror SessionCronTask from state.ts (session-only cron, never persisted)."""
    id: str
    cron: str
    prompt: str
    created_at: int
    recurring: Optional[bool] = None
    agent_id: Optional[str] = None


@dataclass
class InvokedSkillInfo:
    """Mirror InvokedSkillInfo — tracks invoked skills across compaction."""
    skill_name: str
    skill_path: str
    content: str
    invoked_at: int
    agent_id: Optional[str]


# ---------------------------------------------------------------------------
# State — the single mutable record (mirrors the `State` type in state.ts)
# ---------------------------------------------------------------------------


@dataclass
class State:
    original_cwd: str
    project_root: str
    total_cost_usd: float
    total_api_duration: float
    total_api_duration_without_retries: float
    total_tool_duration: float
    turn_hook_duration_ms: float
    turn_tool_duration_ms: float
    turn_classifier_duration_ms: float
    turn_tool_count: int
    turn_hook_count: int
    turn_classifier_count: int
    start_time: int
    last_interaction_time: int
    total_lines_added: int
    total_lines_removed: int
    has_unknown_model_cost: bool
    cwd: str
    model_usage: dict[str, Any]
    main_loop_model_override: Optional[Any]
    initial_main_loop_model: Any
    model_strings: Optional[Any]
    is_interactive: bool
    kairos_active: bool
    strict_tool_result_pairing: bool
    sdk_agent_progress_summaries_enabled: bool
    user_msg_opt_in: bool
    client_type: str
    session_source: Optional[str]
    question_preview_format: Optional[str]  # 'markdown' | 'html' | None
    flag_settings_path: Optional[str]
    flag_settings_inline: Optional[dict[str, Any]]
    allowed_setting_sources: list[str]
    session_ingress_token: Optional[str]
    oauth_token_from_fd: Optional[str]
    api_key_from_fd: Optional[str]
    # Telemetry state (pipeline dropped; fields kept for non-telemetry readers)
    meter: Optional[Any]
    session_counter: Optional[Any]
    loc_counter: Optional[Any]
    pr_counter: Optional[Any]
    commit_counter: Optional[Any]
    cost_counter: Optional[Any]
    token_counter: Optional[Any]
    code_edit_tool_decision_counter: Optional[Any]
    active_time_counter: Optional[Any]
    stats_store: Optional[Any]
    session_id: str
    parent_session_id: Optional[str]
    logger_provider: Optional[Any]
    event_logger: Optional[Any]
    meter_provider: Optional[Any]
    tracer_provider: Optional[Any]
    agent_color_map: dict[str, str]
    agent_color_index: int
    last_api_request: Optional[Any]
    last_api_request_messages: Optional[Any]
    last_classifier_requests: Optional[list[Any]]
    cached_claude_md_content: Optional[str]
    in_memory_error_log: list[dict[str, str]]
    inline_plugins: list[str]
    chrome_flag_override: Optional[bool]
    use_cowork_plugins: bool
    session_bypass_permissions_mode: bool
    scheduled_tasks_enabled: bool
    session_cron_tasks: list[SessionCronTask]
    session_created_teams: set[str]
    session_trust_accepted: bool
    session_persistence_disabled: bool
    has_exited_plan_mode: bool
    needs_plan_mode_exit_attachment: bool
    needs_auto_mode_exit_attachment: bool
    lsp_recommendation_shown_this_session: bool
    init_json_schema: Optional[dict[str, Any]]
    registered_hooks: Optional[dict[str, list[Any]]]
    plan_slug_cache: dict[str, str]
    teleported_session_info: Optional[dict[str, Any]]
    invoked_skills: dict[str, InvokedSkillInfo]
    slow_operations: list[dict[str, Any]]
    sdk_betas: Optional[list[str]]
    main_thread_agent_type: Optional[str]
    is_remote_mode: bool
    direct_connect_server_url: Optional[str]
    system_prompt_section_cache: dict[str, Optional[str]]
    last_emitted_date: Optional[str]
    additional_directories_for_claude_md: list[str]
    allowed_channels: list[ChannelEntry]
    has_dev_channels: bool
    session_project_dir: Optional[str]
    prompt_cache_1h_allowlist: Optional[list[str]]
    prompt_cache_1h_eligible: Optional[bool]
    afk_mode_header_latched: Optional[bool]
    fast_mode_header_latched: Optional[bool]
    cache_editing_header_latched: Optional[bool]
    thinking_clear_latched: Optional[bool]
    prompt_id: Optional[str]
    last_main_request_id: Optional[str]
    last_api_completion_timestamp: Optional[int]
    pending_post_compaction: bool


# ALSO HERE - THINK THRICE BEFORE MODIFYING
def get_initial_state() -> State:
    # Resolve symlinks in cwd to match shell.ts setCwd, so paths are sanitized
    # consistently for session storage.
    resolved_cwd = ""
    try:
        raw_cwd = os.getcwd()
        try:
            resolved_cwd = unicodedata.normalize("NFC", os.path.realpath(raw_cwd))
        except OSError:
            # File Provider EPERM on CloudStorage mounts (lstat per component).
            resolved_cwd = unicodedata.normalize("NFC", raw_cwd)
    except OSError:
        resolved_cwd = ""

    now = _now_ms()
    return State(
        original_cwd=resolved_cwd,
        project_root=resolved_cwd,
        total_cost_usd=0,
        total_api_duration=0,
        total_api_duration_without_retries=0,
        total_tool_duration=0,
        turn_hook_duration_ms=0,
        turn_tool_duration_ms=0,
        turn_classifier_duration_ms=0,
        turn_tool_count=0,
        turn_hook_count=0,
        turn_classifier_count=0,
        start_time=now,
        last_interaction_time=now,
        total_lines_added=0,
        total_lines_removed=0,
        has_unknown_model_cost=False,
        cwd=resolved_cwd,
        model_usage={},
        main_loop_model_override=None,
        initial_main_loop_model=None,
        model_strings=None,
        is_interactive=False,
        kairos_active=False,
        strict_tool_result_pairing=False,
        sdk_agent_progress_summaries_enabled=False,
        user_msg_opt_in=False,
        client_type="cli",
        session_source=None,
        question_preview_format=None,
        session_ingress_token=None,
        oauth_token_from_fd=None,
        api_key_from_fd=None,
        flag_settings_path=None,
        flag_settings_inline=None,
        allowed_setting_sources=[
            "userSettings",
            "projectSettings",
            "localSettings",
            "flagSettings",
            "policySettings",
        ],
        # Telemetry state
        meter=None,
        session_counter=None,
        loc_counter=None,
        pr_counter=None,
        commit_counter=None,
        cost_counter=None,
        token_counter=None,
        code_edit_tool_decision_counter=None,
        active_time_counter=None,
        stats_store=None,
        session_id=_random_uuid(),
        parent_session_id=None,
        # Logger state
        logger_provider=None,
        event_logger=None,
        # Meter / tracer providers
        meter_provider=None,
        tracer_provider=None,
        # Agent color state
        agent_color_map={},
        agent_color_index=0,
        # Last API request for bug reports
        last_api_request=None,
        last_api_request_messages=None,
        last_classifier_requests=None,
        cached_claude_md_content=None,
        in_memory_error_log=[],
        inline_plugins=[],
        chrome_flag_override=None,
        use_cowork_plugins=False,
        session_bypass_permissions_mode=False,
        scheduled_tasks_enabled=False,
        session_cron_tasks=[],
        session_created_teams=set(),
        session_trust_accepted=False,
        session_persistence_disabled=False,
        has_exited_plan_mode=False,
        needs_plan_mode_exit_attachment=False,
        needs_auto_mode_exit_attachment=False,
        lsp_recommendation_shown_this_session=False,
        init_json_schema=None,
        registered_hooks=None,
        plan_slug_cache={},
        teleported_session_info=None,
        invoked_skills={},
        slow_operations=[],
        sdk_betas=None,
        main_thread_agent_type=None,
        is_remote_mode=False,
        # (USER_TYPE === 'ant' replBridgeActive spread omitted — not in State type)
        direct_connect_server_url=None,
        system_prompt_section_cache={},
        last_emitted_date=None,
        additional_directories_for_claude_md=[],
        allowed_channels=[],
        has_dev_channels=False,
        session_project_dir=None,
        prompt_cache_1h_allowlist=None,
        prompt_cache_1h_eligible=None,
        afk_mode_header_latched=None,
        fast_mode_header_latched=None,
        cache_editing_header_latched=None,
        thinking_clear_latched=None,
        prompt_id=None,
        last_main_request_id=None,
        last_api_completion_timestamp=None,
        pending_post_compaction=False,
    )


# AND ESPECIALLY HERE
_STATE: State = get_initial_state()

# Signal fired when switch_session changes the active session id.
_session_switched = create_signal()


# ---------------------------------------------------------------------------
# Session id / lineage
# ---------------------------------------------------------------------------


def get_session_id() -> str:
    return _STATE.session_id


def regenerate_session_id(set_current_as_parent: bool = False) -> str:
    if set_current_as_parent:
        _STATE.parent_session_id = _STATE.session_id
    # Drop the outgoing session's plan-slug entry so the map doesn't accumulate.
    _STATE.plan_slug_cache.pop(_STATE.session_id, None)
    # Regenerated sessions live in the current project: reset projectDir to None.
    _STATE.session_id = _random_uuid()
    _STATE.session_project_dir = None
    return _STATE.session_id


def get_parent_session_id() -> Optional[str]:
    return _STATE.parent_session_id


def switch_session(session_id: str, project_dir: Optional[str] = None) -> None:
    """
    Atomically switch the active session. sessionId and sessionProjectDir always
    change together so they cannot drift out of sync.
    """
    _STATE.plan_slug_cache.pop(_STATE.session_id, None)
    _STATE.session_id = session_id
    _STATE.session_project_dir = project_dir
    _session_switched.emit(session_id)


# Register a callback fired when switch_session changes the active sessionId.
on_session_switch = _session_switched.subscribe


def get_session_project_dir() -> Optional[str]:
    return _STATE.session_project_dir


# ---------------------------------------------------------------------------
# Cwd / project root
# ---------------------------------------------------------------------------


def get_original_cwd() -> str:
    return _STATE.original_cwd


def get_project_root() -> str:
    return _STATE.project_root


def set_original_cwd(cwd: str) -> None:
    _STATE.original_cwd = unicodedata.normalize("NFC", cwd)


def set_project_root(cwd: str) -> None:
    _STATE.project_root = unicodedata.normalize("NFC", cwd)


def get_cwd_state() -> str:
    return _STATE.cwd


def set_cwd_state(cwd: str) -> None:
    _STATE.cwd = unicodedata.normalize("NFC", cwd)


def get_direct_connect_server_url() -> Optional[str]:
    return _STATE.direct_connect_server_url


def set_direct_connect_server_url(url: str) -> None:
    _STATE.direct_connect_server_url = url


# ---------------------------------------------------------------------------
# Cost / duration accounting
# ---------------------------------------------------------------------------


def add_to_total_duration_state(duration: float, duration_without_retries: float) -> None:
    _STATE.total_api_duration += duration
    _STATE.total_api_duration_without_retries += duration_without_retries


def reset_total_duration_state_and_cost_for_tests_only() -> None:
    _STATE.total_api_duration = 0
    _STATE.total_api_duration_without_retries = 0
    _STATE.total_cost_usd = 0


def add_to_total_cost_state(cost: float, model_usage: Any, model: str) -> None:
    _STATE.model_usage[model] = model_usage
    _STATE.total_cost_usd += cost


def get_total_cost_usd() -> float:
    return _STATE.total_cost_usd


def get_total_api_duration() -> float:
    return _STATE.total_api_duration


def get_total_duration() -> int:
    return _now_ms() - _STATE.start_time


def get_total_api_duration_without_retries() -> float:
    return _STATE.total_api_duration_without_retries


def get_total_tool_duration() -> float:
    return _STATE.total_tool_duration


def add_to_tool_duration(duration: float) -> None:
    _STATE.total_tool_duration += duration
    _STATE.turn_tool_duration_ms += duration
    _STATE.turn_tool_count += 1


def get_turn_hook_duration_ms() -> float:
    return _STATE.turn_hook_duration_ms


def add_to_turn_hook_duration(duration: float) -> None:
    _STATE.turn_hook_duration_ms += duration
    _STATE.turn_hook_count += 1


def reset_turn_hook_duration() -> None:
    _STATE.turn_hook_duration_ms = 0
    _STATE.turn_hook_count = 0


def get_turn_hook_count() -> int:
    return _STATE.turn_hook_count


def get_turn_tool_duration_ms() -> float:
    return _STATE.turn_tool_duration_ms


def reset_turn_tool_duration() -> None:
    _STATE.turn_tool_duration_ms = 0
    _STATE.turn_tool_count = 0


def get_turn_tool_count() -> int:
    return _STATE.turn_tool_count


def get_turn_classifier_duration_ms() -> float:
    return _STATE.turn_classifier_duration_ms


def add_to_turn_classifier_duration(duration: float) -> None:
    _STATE.turn_classifier_duration_ms += duration
    _STATE.turn_classifier_count += 1


def reset_turn_classifier_duration() -> None:
    _STATE.turn_classifier_duration_ms = 0
    _STATE.turn_classifier_count = 0


def get_turn_classifier_count() -> int:
    return _STATE.turn_classifier_count


def get_stats_store() -> Optional[Any]:
    return _STATE.stats_store


def set_stats_store(store: Optional[Any]) -> None:
    _STATE.stats_store = store


# ---------------------------------------------------------------------------
# Interaction time (deferred-flush batching)
# ---------------------------------------------------------------------------

_interaction_time_dirty = False


def update_last_interaction_time(immediate: bool = False) -> None:
    global _interaction_time_dirty
    if immediate:
        _flush_interaction_time_inner()
    else:
        _interaction_time_dirty = True


def flush_interaction_time() -> None:
    if _interaction_time_dirty:
        _flush_interaction_time_inner()


def _flush_interaction_time_inner() -> None:
    global _interaction_time_dirty
    _STATE.last_interaction_time = _now_ms()
    _interaction_time_dirty = False


# ---------------------------------------------------------------------------
# Lines changed / token aggregation
# ---------------------------------------------------------------------------


def add_to_total_lines_changed(added: int, removed: int) -> None:
    _STATE.total_lines_added += added
    _STATE.total_lines_removed += removed


def get_total_lines_added() -> int:
    return _STATE.total_lines_added


def get_total_lines_removed() -> int:
    return _STATE.total_lines_removed


def get_total_input_tokens() -> float:
    return _sum_by(list(_STATE.model_usage.values()), "inputTokens")


def get_total_output_tokens() -> float:
    return _sum_by(list(_STATE.model_usage.values()), "outputTokens")


def get_total_cache_read_input_tokens() -> float:
    return _sum_by(list(_STATE.model_usage.values()), "cacheReadInputTokens")


def get_total_cache_creation_input_tokens() -> float:
    return _sum_by(list(_STATE.model_usage.values()), "cacheCreationInputTokens")


def get_total_web_search_requests() -> float:
    return _sum_by(list(_STATE.model_usage.values()), "webSearchRequests")


# ---------------------------------------------------------------------------
# Per-turn token budget
# ---------------------------------------------------------------------------

_output_tokens_at_turn_start = 0.0
_current_turn_token_budget: Optional[int] = None
_budget_continuation_count = 0


def get_turn_output_tokens() -> float:
    return get_total_output_tokens() - _output_tokens_at_turn_start


def get_current_turn_token_budget() -> Optional[int]:
    return _current_turn_token_budget


def snapshot_output_tokens_for_turn(budget: Optional[int]) -> None:
    global _output_tokens_at_turn_start, _current_turn_token_budget, _budget_continuation_count
    _output_tokens_at_turn_start = get_total_output_tokens()
    _current_turn_token_budget = budget
    _budget_continuation_count = 0


def get_budget_continuation_count() -> int:
    return _budget_continuation_count


def increment_budget_continuation_count() -> None:
    global _budget_continuation_count
    _budget_continuation_count += 1


# ---------------------------------------------------------------------------
# Model cost / request tracking
# ---------------------------------------------------------------------------


def set_has_unknown_model_cost() -> None:
    _STATE.has_unknown_model_cost = True


def has_unknown_model_cost() -> bool:
    return _STATE.has_unknown_model_cost


def get_last_main_request_id() -> Optional[str]:
    return _STATE.last_main_request_id


def set_last_main_request_id(request_id: str) -> None:
    _STATE.last_main_request_id = request_id


def get_last_api_completion_timestamp() -> Optional[int]:
    return _STATE.last_api_completion_timestamp


def set_last_api_completion_timestamp(timestamp: int) -> None:
    _STATE.last_api_completion_timestamp = timestamp


def mark_post_compaction() -> None:
    _STATE.pending_post_compaction = True


def consume_post_compaction() -> bool:
    was = _STATE.pending_post_compaction
    _STATE.pending_post_compaction = False
    return was


def get_last_interaction_time() -> int:
    return _STATE.last_interaction_time


# ---------------------------------------------------------------------------
# Scroll-drain suspension (module-scope, ephemeral hot-path flag)
# ---------------------------------------------------------------------------

_scroll_draining = False
_scroll_drain_timer: Optional[threading.Timer] = None
_SCROLL_DRAIN_IDLE_MS = 150


def mark_scroll_activity() -> None:
    global _scroll_draining, _scroll_drain_timer
    _scroll_draining = True
    if _scroll_drain_timer is not None:
        _scroll_drain_timer.cancel()

    def _clear() -> None:
        global _scroll_draining, _scroll_drain_timer
        _scroll_draining = False
        _scroll_drain_timer = None

    _scroll_drain_timer = threading.Timer(_SCROLL_DRAIN_IDLE_MS / 1000, _clear)
    _scroll_drain_timer.daemon = True  # mirror .unref() — never block process exit
    _scroll_drain_timer.start()


def get_is_scroll_draining() -> bool:
    return _scroll_draining


async def wait_for_scroll_idle() -> None:
    import asyncio

    while _scroll_draining:
        await asyncio.sleep(_SCROLL_DRAIN_IDLE_MS / 1000)


# ---------------------------------------------------------------------------
# Model usage / model selection
# ---------------------------------------------------------------------------


def get_model_usage() -> dict[str, Any]:
    return _STATE.model_usage


def get_usage_for_model(model: str) -> Optional[Any]:
    return _STATE.model_usage.get(model)


def get_main_loop_model_override() -> Optional[Any]:
    return _STATE.main_loop_model_override


def get_initial_main_loop_model() -> Any:
    return _STATE.initial_main_loop_model


def set_main_loop_model_override(model: Optional[Any]) -> None:
    _STATE.main_loop_model_override = model


def set_initial_main_loop_model(model: Any) -> None:
    _STATE.initial_main_loop_model = model


def get_sdk_betas() -> Optional[list[str]]:
    return _STATE.sdk_betas


def set_sdk_betas(betas: Optional[list[str]]) -> None:
    _STATE.sdk_betas = betas


def reset_cost_state() -> None:
    _STATE.total_cost_usd = 0
    _STATE.total_api_duration = 0
    _STATE.total_api_duration_without_retries = 0
    _STATE.total_tool_duration = 0
    _STATE.start_time = _now_ms()
    _STATE.total_lines_added = 0
    _STATE.total_lines_removed = 0
    _STATE.has_unknown_model_cost = False
    _STATE.model_usage = {}
    _STATE.prompt_id = None


def set_cost_state_for_restore(
    *,
    total_cost_usd: float,
    total_api_duration: float,
    total_api_duration_without_retries: float,
    total_tool_duration: float,
    total_lines_added: int,
    total_lines_removed: int,
    last_duration: Optional[float],
    model_usage: Optional[dict[str, Any]],
) -> None:
    """Set cost state for session restore (mirrors restoreCostStateForSession)."""
    _STATE.total_cost_usd = total_cost_usd
    _STATE.total_api_duration = total_api_duration
    _STATE.total_api_duration_without_retries = total_api_duration_without_retries
    _STATE.total_tool_duration = total_tool_duration
    _STATE.total_lines_added = total_lines_added
    _STATE.total_lines_removed = total_lines_removed

    if model_usage:
        _STATE.model_usage = model_usage

    if last_duration:
        _STATE.start_time = _now_ms() - int(last_duration)


def reset_state_for_tests() -> None:
    global _output_tokens_at_turn_start, _current_turn_token_budget, _budget_continuation_count
    if os.environ.get("NODE_ENV") != "test" and os.environ.get("OPTIMUS_ENV") != "test":
        raise RuntimeError("reset_state_for_tests can only be called in tests")
    fresh = get_initial_state()
    for f in fresh.__dataclass_fields__:  # type: ignore[attr-defined]
        setattr(_STATE, f, getattr(fresh, f))
    _output_tokens_at_turn_start = 0
    _current_turn_token_budget = None
    _budget_continuation_count = 0
    _session_switched.clear()


# ---------------------------------------------------------------------------
# Model strings
# ---------------------------------------------------------------------------


def get_model_strings() -> Optional[Any]:
    return _STATE.model_strings


def set_model_strings(model_strings: Any) -> None:
    _STATE.model_strings = model_strings


def reset_model_strings_for_testing_only() -> None:
    _STATE.model_strings = None


# ---------------------------------------------------------------------------
# Telemetry counters — pipeline dropped, state + factory wiring preserved
# ---------------------------------------------------------------------------


def set_meter(
    meter: Any,
    create_counter: Callable[[str, dict[str, Any]], Any],
) -> None:
    _STATE.meter = meter
    _STATE.session_counter = create_counter(
        "claude_code.session.count",
        {"description": "Count of CLI sessions started"},
    )
    _STATE.loc_counter = create_counter(
        "claude_code.lines_of_code.count",
        {
            "description": "Count of lines of code modified, with the 'type' "
            "attribute indicating whether lines were added or removed"
        },
    )
    _STATE.pr_counter = create_counter(
        "claude_code.pull_request.count",
        {"description": "Number of pull requests created"},
    )
    _STATE.commit_counter = create_counter(
        "claude_code.commit.count",
        {"description": "Number of git commits created"},
    )
    _STATE.cost_counter = create_counter(
        "claude_code.cost.usage",
        {"description": "Cost of the Claude Code session", "unit": "USD"},
    )
    _STATE.token_counter = create_counter(
        "claude_code.token.usage",
        {"description": "Number of tokens used", "unit": "tokens"},
    )
    _STATE.code_edit_tool_decision_counter = create_counter(
        "claude_code.code_edit_tool.decision",
        {
            "description": "Count of code editing tool permission decisions "
            "(accept/reject) for Edit, Write, and NotebookEdit tools"
        },
    )
    _STATE.active_time_counter = create_counter(
        "claude_code.active_time.total",
        {"description": "Total active time in seconds", "unit": "s"},
    )


def get_meter() -> Optional[Any]:
    return _STATE.meter


def get_session_counter() -> Optional[Any]:
    return _STATE.session_counter


def get_loc_counter() -> Optional[Any]:
    return _STATE.loc_counter


def get_pr_counter() -> Optional[Any]:
    return _STATE.pr_counter


def get_commit_counter() -> Optional[Any]:
    return _STATE.commit_counter


def get_cost_counter() -> Optional[Any]:
    return _STATE.cost_counter


def get_token_counter() -> Optional[Any]:
    return _STATE.token_counter


def get_code_edit_tool_decision_counter() -> Optional[Any]:
    return _STATE.code_edit_tool_decision_counter


def get_active_time_counter() -> Optional[Any]:
    return _STATE.active_time_counter


def get_logger_provider() -> Optional[Any]:
    return _STATE.logger_provider


def set_logger_provider(provider: Optional[Any]) -> None:
    _STATE.logger_provider = provider


def get_event_logger() -> Optional[Any]:
    return _STATE.event_logger


def set_event_logger(logger: Optional[Any]) -> None:
    _STATE.event_logger = logger


def get_meter_provider() -> Optional[Any]:
    return _STATE.meter_provider


def set_meter_provider(provider: Optional[Any]) -> None:
    _STATE.meter_provider = provider


def get_tracer_provider() -> Optional[Any]:
    return _STATE.tracer_provider


def set_tracer_provider(provider: Optional[Any]) -> None:
    _STATE.tracer_provider = provider


# ---------------------------------------------------------------------------
# Interactivity / client type
# ---------------------------------------------------------------------------


def get_is_non_interactive_session() -> bool:
    return not _STATE.is_interactive


def get_is_interactive() -> bool:
    return _STATE.is_interactive


def set_is_interactive(value: bool) -> None:
    _STATE.is_interactive = value


def get_client_type() -> str:
    return _STATE.client_type


def set_client_type(client_type: str) -> None:
    _STATE.client_type = client_type


def get_sdk_agent_progress_summaries_enabled() -> bool:
    return _STATE.sdk_agent_progress_summaries_enabled


def set_sdk_agent_progress_summaries_enabled(value: bool) -> None:
    _STATE.sdk_agent_progress_summaries_enabled = value


def get_kairos_active() -> bool:
    return _STATE.kairos_active


def set_kairos_active(value: bool) -> None:
    _STATE.kairos_active = value


def get_strict_tool_result_pairing() -> bool:
    return _STATE.strict_tool_result_pairing


def set_strict_tool_result_pairing(value: bool) -> None:
    _STATE.strict_tool_result_pairing = value


def get_user_msg_opt_in() -> bool:
    return _STATE.user_msg_opt_in


def set_user_msg_opt_in(value: bool) -> None:
    _STATE.user_msg_opt_in = value


def get_session_source() -> Optional[str]:
    return _STATE.session_source


def set_session_source(source: str) -> None:
    _STATE.session_source = source


def get_question_preview_format() -> Optional[str]:
    return _STATE.question_preview_format


def set_question_preview_format(fmt: str) -> None:
    _STATE.question_preview_format = fmt


def get_agent_color_map() -> dict[str, str]:
    return _STATE.agent_color_map


# ---------------------------------------------------------------------------
# Flag settings / FD-sourced credentials
# ---------------------------------------------------------------------------


def get_flag_settings_path() -> Optional[str]:
    return _STATE.flag_settings_path


def set_flag_settings_path(path: Optional[str]) -> None:
    _STATE.flag_settings_path = path


def get_flag_settings_inline() -> Optional[dict[str, Any]]:
    return _STATE.flag_settings_inline


def set_flag_settings_inline(settings: Optional[dict[str, Any]]) -> None:
    _STATE.flag_settings_inline = settings


def get_session_ingress_token() -> Optional[str]:
    return _STATE.session_ingress_token


def set_session_ingress_token(token: Optional[str]) -> None:
    _STATE.session_ingress_token = token


def get_oauth_token_from_fd() -> Optional[str]:
    return _STATE.oauth_token_from_fd


def set_oauth_token_from_fd(token: Optional[str]) -> None:
    _STATE.oauth_token_from_fd = token


def get_api_key_from_fd() -> Optional[str]:
    return _STATE.api_key_from_fd


def set_api_key_from_fd(key: Optional[str]) -> None:
    _STATE.api_key_from_fd = key


# ---------------------------------------------------------------------------
# Last API request (for /share + bug reports)
# ---------------------------------------------------------------------------


def set_last_api_request(params: Optional[Any]) -> None:
    _STATE.last_api_request = params


def get_last_api_request() -> Optional[Any]:
    return _STATE.last_api_request


def set_last_api_request_messages(messages: Optional[Any]) -> None:
    _STATE.last_api_request_messages = messages


def get_last_api_request_messages() -> Optional[Any]:
    return _STATE.last_api_request_messages


def set_last_classifier_requests(requests: Optional[list[Any]]) -> None:
    _STATE.last_classifier_requests = requests


def get_last_classifier_requests() -> Optional[list[Any]]:
    return _STATE.last_classifier_requests


def set_cached_claude_md_content(content: Optional[str]) -> None:
    _STATE.cached_claude_md_content = content


def get_cached_claude_md_content() -> Optional[str]:
    return _STATE.cached_claude_md_content


def add_to_in_memory_error_log(error_info: dict[str, str]) -> None:
    MAX_IN_MEMORY_ERRORS = 100
    if len(_STATE.in_memory_error_log) >= MAX_IN_MEMORY_ERRORS:
        _STATE.in_memory_error_log.pop(0)  # Remove oldest error
    _STATE.in_memory_error_log.append(error_info)


# ---------------------------------------------------------------------------
# Setting sources / auth preference
# ---------------------------------------------------------------------------


def get_allowed_setting_sources() -> list[str]:
    return _STATE.allowed_setting_sources


def set_allowed_setting_sources(sources: list[str]) -> None:
    _STATE.allowed_setting_sources = sources


def prefer_third_party_authentication() -> bool:
    # IDE extension should behave as 1P for authentication reasons.
    return get_is_non_interactive_session() and _STATE.client_type != "claude-vscode"


# ---------------------------------------------------------------------------
# Inline plugins / chrome / cowork
# ---------------------------------------------------------------------------


def set_inline_plugins(plugins: list[str]) -> None:
    _STATE.inline_plugins = plugins


def get_inline_plugins() -> list[str]:
    return _STATE.inline_plugins


def set_chrome_flag_override(value: Optional[bool]) -> None:
    _STATE.chrome_flag_override = value


def get_chrome_flag_override() -> Optional[bool]:
    return _STATE.chrome_flag_override


def set_use_cowork_plugins(value: bool) -> None:
    _STATE.use_cowork_plugins = value
    _reset_settings_cache()


def get_use_cowork_plugins() -> bool:
    return _STATE.use_cowork_plugins


# ---------------------------------------------------------------------------
# Permissions / scheduled tasks
# ---------------------------------------------------------------------------


def set_session_bypass_permissions_mode(enabled: bool) -> None:
    _STATE.session_bypass_permissions_mode = enabled


def get_session_bypass_permissions_mode() -> bool:
    return _STATE.session_bypass_permissions_mode


def set_scheduled_tasks_enabled(enabled: bool) -> None:
    _STATE.scheduled_tasks_enabled = enabled


def get_scheduled_tasks_enabled() -> bool:
    return _STATE.scheduled_tasks_enabled


def get_session_cron_tasks() -> list[SessionCronTask]:
    return _STATE.session_cron_tasks


def add_session_cron_task(task: SessionCronTask) -> None:
    _STATE.session_cron_tasks.append(task)


def remove_session_cron_tasks(ids: list[str]) -> int:
    """Return the number of tasks actually removed."""
    if len(ids) == 0:
        return 0
    id_set = set(ids)
    remaining = [t for t in _STATE.session_cron_tasks if t.id not in id_set]
    removed = len(_STATE.session_cron_tasks) - len(remaining)
    if removed == 0:
        return 0
    _STATE.session_cron_tasks = remaining
    return removed


# ---------------------------------------------------------------------------
# Trust / persistence
# ---------------------------------------------------------------------------


def set_session_trust_accepted(accepted: bool) -> None:
    _STATE.session_trust_accepted = accepted


def get_session_trust_accepted() -> bool:
    return _STATE.session_trust_accepted


def set_session_persistence_disabled(disabled: bool) -> None:
    _STATE.session_persistence_disabled = disabled


def is_session_persistence_disabled() -> bool:
    return _STATE.session_persistence_disabled


# ---------------------------------------------------------------------------
# Plan-mode / auto-mode transition tracking
# ---------------------------------------------------------------------------


def has_exited_plan_mode_in_session() -> bool:
    return _STATE.has_exited_plan_mode


def set_has_exited_plan_mode(value: bool) -> None:
    _STATE.has_exited_plan_mode = value


def needs_plan_mode_exit_attachment() -> bool:
    return _STATE.needs_plan_mode_exit_attachment


def set_needs_plan_mode_exit_attachment(value: bool) -> None:
    _STATE.needs_plan_mode_exit_attachment = value


def handle_plan_mode_transition(from_mode: str, to_mode: str) -> None:
    # Switching TO plan mode clears any pending exit attachment (avoids sending
    # both plan_mode and plan_mode_exit on a quick toggle).
    if to_mode == "plan" and from_mode != "plan":
        _STATE.needs_plan_mode_exit_attachment = False
    # Switching out of plan mode triggers the plan_mode_exit attachment.
    if from_mode == "plan" and to_mode != "plan":
        _STATE.needs_plan_mode_exit_attachment = True


def needs_auto_mode_exit_attachment() -> bool:
    return _STATE.needs_auto_mode_exit_attachment


def set_needs_auto_mode_exit_attachment(value: bool) -> None:
    _STATE.needs_auto_mode_exit_attachment = value


def handle_auto_mode_transition(from_mode: str, to_mode: str) -> None:
    # Auto↔plan transitions are handled elsewhere; skip both directions so this
    # only handles direct auto transitions.
    if (from_mode == "auto" and to_mode == "plan") or (
        from_mode == "plan" and to_mode == "auto"
    ):
        return
    from_is_auto = from_mode == "auto"
    to_is_auto = to_mode == "auto"
    if to_is_auto and not from_is_auto:
        _STATE.needs_auto_mode_exit_attachment = False
    if from_is_auto and not to_is_auto:
        _STATE.needs_auto_mode_exit_attachment = True


# ---------------------------------------------------------------------------
# LSP recommendation
# ---------------------------------------------------------------------------


def has_shown_lsp_recommendation_this_session() -> bool:
    return _STATE.lsp_recommendation_shown_this_session


def set_lsp_recommendation_shown_this_session(value: bool) -> None:
    _STATE.lsp_recommendation_shown_this_session = value


# ---------------------------------------------------------------------------
# SDK init event state / registered hooks
# ---------------------------------------------------------------------------


def set_init_json_schema(schema: dict[str, Any]) -> None:
    _STATE.init_json_schema = schema


def get_init_json_schema() -> Optional[dict[str, Any]]:
    return _STATE.init_json_schema


def register_hook_callbacks(hooks: dict[str, list[Any]]) -> None:
    if _STATE.registered_hooks is None:
        _STATE.registered_hooks = {}
    # May be called multiple times — merge (don't overwrite).
    for event, matchers in hooks.items():
        if not _STATE.registered_hooks.get(event):
            _STATE.registered_hooks[event] = []
        _STATE.registered_hooks[event].extend(matchers)


def get_registered_hooks() -> Optional[dict[str, list[Any]]]:
    return _STATE.registered_hooks


def clear_registered_hooks() -> None:
    _STATE.registered_hooks = None


def clear_registered_plugin_hooks() -> None:
    if _STATE.registered_hooks is None:
        return
    filtered: dict[str, list[Any]] = {}
    for event, matchers in _STATE.registered_hooks.items():
        # Keep only callback hooks (those without pluginRoot).
        callback_hooks = [
            m
            for m in matchers
            if not (isinstance(m, dict) and "pluginRoot" in m)
            and not hasattr(m, "pluginRoot")
        ]
        if len(callback_hooks) > 0:
            filtered[event] = callback_hooks
    _STATE.registered_hooks = filtered if len(filtered) > 0 else None


def reset_sdk_init_state() -> None:
    _STATE.init_json_schema = None
    _STATE.registered_hooks = None


def get_plan_slug_cache() -> dict[str, str]:
    return _STATE.plan_slug_cache


def get_session_created_teams() -> set[str]:
    return _STATE.session_created_teams


# ---------------------------------------------------------------------------
# Teleported session tracking
# ---------------------------------------------------------------------------


def set_teleported_session_info(session_id: Optional[str]) -> None:
    _STATE.teleported_session_info = {
        "isTeleported": True,
        "hasLoggedFirstMessage": False,
        "sessionId": session_id,
    }


def get_teleported_session_info() -> Optional[dict[str, Any]]:
    return _STATE.teleported_session_info


def mark_first_teleport_message_logged() -> None:
    if _STATE.teleported_session_info:
        _STATE.teleported_session_info["hasLoggedFirstMessage"] = True


# ---------------------------------------------------------------------------
# Invoked skills (preserved across compaction)
# ---------------------------------------------------------------------------


def add_invoked_skill(
    skill_name: str,
    skill_path: str,
    content: str,
    agent_id: Optional[str] = None,
) -> None:
    key = f"{agent_id or ''}:{skill_name}"
    _STATE.invoked_skills[key] = InvokedSkillInfo(
        skill_name=skill_name,
        skill_path=skill_path,
        content=content,
        invoked_at=_now_ms(),
        agent_id=agent_id,
    )


def get_invoked_skills() -> dict[str, InvokedSkillInfo]:
    return _STATE.invoked_skills


def get_invoked_skills_for_agent(agent_id: Optional[str]) -> dict[str, InvokedSkillInfo]:
    normalized_id = agent_id if agent_id is not None else None
    filtered: dict[str, InvokedSkillInfo] = {}
    for key, skill in _STATE.invoked_skills.items():
        if skill.agent_id == normalized_id:
            filtered[key] = skill
    return filtered


def clear_invoked_skills(preserved_agent_ids: Optional[set[str]] = None) -> None:
    if not preserved_agent_ids or len(preserved_agent_ids) == 0:
        _STATE.invoked_skills.clear()
        return
    for key in list(_STATE.invoked_skills.keys()):
        skill = _STATE.invoked_skills[key]
        if skill.agent_id is None or skill.agent_id not in preserved_agent_ids:
            del _STATE.invoked_skills[key]


def clear_invoked_skills_for_agent(agent_id: str) -> None:
    for key in list(_STATE.invoked_skills.keys()):
        if _STATE.invoked_skills[key].agent_id == agent_id:
            del _STATE.invoked_skills[key]


# ---------------------------------------------------------------------------
# Slow operations (dev bar; ant-only)
# ---------------------------------------------------------------------------

_MAX_SLOW_OPERATIONS = 10
_SLOW_OPERATION_TTL_MS = 10000


def add_slow_operation(operation: str, duration_ms: float) -> None:
    if os.environ.get("USER_TYPE") != "ant":
        return
    # Skip editor sessions (user editing a prompt file in $EDITOR) — intentionally slow.
    if "exec" in operation and "claude-prompt-" in operation:
        return
    now = _now_ms()
    _STATE.slow_operations = [
        op for op in _STATE.slow_operations if now - op["timestamp"] < _SLOW_OPERATION_TTL_MS
    ]
    _STATE.slow_operations.append(
        {"operation": operation, "durationMs": duration_ms, "timestamp": now}
    )
    if len(_STATE.slow_operations) > _MAX_SLOW_OPERATIONS:
        _STATE.slow_operations = _STATE.slow_operations[-_MAX_SLOW_OPERATIONS:]


_EMPTY_SLOW_OPERATIONS: list[dict[str, Any]] = []


def get_slow_operations() -> list[dict[str, Any]]:
    # Most common case: nothing tracked. Return a stable reference.
    if len(_STATE.slow_operations) == 0:
        return _EMPTY_SLOW_OPERATIONS
    now = _now_ms()
    if any(now - op["timestamp"] >= _SLOW_OPERATION_TTL_MS for op in _STATE.slow_operations):
        _STATE.slow_operations = [
            op for op in _STATE.slow_operations if now - op["timestamp"] < _SLOW_OPERATION_TTL_MS
        ]
        if len(_STATE.slow_operations) == 0:
            return _EMPTY_SLOW_OPERATIONS
    return _STATE.slow_operations


# ---------------------------------------------------------------------------
# Main-thread agent type / remote mode
# ---------------------------------------------------------------------------


def get_main_thread_agent_type() -> Optional[str]:
    return _STATE.main_thread_agent_type


def set_main_thread_agent_type(agent_type: Optional[str]) -> None:
    _STATE.main_thread_agent_type = agent_type


def get_is_remote_mode() -> bool:
    return _STATE.is_remote_mode


def set_is_remote_mode(value: bool) -> None:
    _STATE.is_remote_mode = value


# ---------------------------------------------------------------------------
# System prompt section cache
# ---------------------------------------------------------------------------


def get_system_prompt_section_cache() -> dict[str, Optional[str]]:
    return _STATE.system_prompt_section_cache


def set_system_prompt_section_cache_entry(name: str, value: Optional[str]) -> None:
    _STATE.system_prompt_section_cache[name] = value


def clear_system_prompt_section_state() -> None:
    _STATE.system_prompt_section_cache.clear()


# ---------------------------------------------------------------------------
# Last emitted date / additional dirs / channels
# ---------------------------------------------------------------------------


def get_last_emitted_date() -> Optional[str]:
    return _STATE.last_emitted_date


def set_last_emitted_date(date: Optional[str]) -> None:
    _STATE.last_emitted_date = date


def get_additional_directories_for_claude_md() -> list[str]:
    return _STATE.additional_directories_for_claude_md


def set_additional_directories_for_claude_md(directories: list[str]) -> None:
    _STATE.additional_directories_for_claude_md = directories


def get_allowed_channels() -> list[ChannelEntry]:
    return _STATE.allowed_channels


def set_allowed_channels(entries: list[ChannelEntry]) -> None:
    _STATE.allowed_channels = entries


def get_has_dev_channels() -> bool:
    return _STATE.has_dev_channels


def set_has_dev_channels(value: bool) -> None:
    _STATE.has_dev_channels = value


# ---------------------------------------------------------------------------
# Prompt-cache 1h allowlist / eligibility + beta-header latches
# ---------------------------------------------------------------------------


def get_prompt_cache_1h_allowlist() -> Optional[list[str]]:
    return _STATE.prompt_cache_1h_allowlist


def set_prompt_cache_1h_allowlist(allowlist: Optional[list[str]]) -> None:
    _STATE.prompt_cache_1h_allowlist = allowlist


def get_prompt_cache_1h_eligible() -> Optional[bool]:
    return _STATE.prompt_cache_1h_eligible


def set_prompt_cache_1h_eligible(eligible: Optional[bool]) -> None:
    _STATE.prompt_cache_1h_eligible = eligible


def get_afk_mode_header_latched() -> Optional[bool]:
    return _STATE.afk_mode_header_latched


def set_afk_mode_header_latched(v: bool) -> None:
    _STATE.afk_mode_header_latched = v


def get_fast_mode_header_latched() -> Optional[bool]:
    return _STATE.fast_mode_header_latched


def set_fast_mode_header_latched(v: bool) -> None:
    _STATE.fast_mode_header_latched = v


def get_cache_editing_header_latched() -> Optional[bool]:
    return _STATE.cache_editing_header_latched


def set_cache_editing_header_latched(v: bool) -> None:
    _STATE.cache_editing_header_latched = v


def get_thinking_clear_latched() -> Optional[bool]:
    return _STATE.thinking_clear_latched


def set_thinking_clear_latched(v: bool) -> None:
    _STATE.thinking_clear_latched = v


def clear_beta_header_latches() -> None:
    """Reset beta header latches to None (called on /clear and /compact)."""
    _STATE.afk_mode_header_latched = None
    _STATE.fast_mode_header_latched = None
    _STATE.cache_editing_header_latched = None
    _STATE.thinking_clear_latched = None


# ---------------------------------------------------------------------------
# Prompt id
# ---------------------------------------------------------------------------


def get_prompt_id() -> Optional[str]:
    return _STATE.prompt_id


def set_prompt_id(prompt_id: Optional[str]) -> None:
    _STATE.prompt_id = prompt_id


# ---------------------------------------------------------------------------
# Todo store — session/agent-keyed task lists (backs TodoWriteTool)
# ---------------------------------------------------------------------------
# In TS this lives in AppState (context.getAppState().todos). We don't have a
# full AppState store yet, so the session-scoped todo lists live here.

_todos: dict[str, list[dict[str, Any]]] = {}


def get_todos(key: str) -> list[dict[str, Any]]:
    return _todos.get(key, [])


def set_todos(key: str, todos: list[dict[str, Any]]) -> None:
    _todos[key] = todos


def clear_all_todos() -> None:
    _todos.clear()
