"""
optimus/__main__.py — port of src/entrypoints/cli.tsx + src/entrypoints/init.ts

cli.tsx  (302 TS lines) → main() + feature-gated fast-path stubs
init.ts  (340 TS lines) → init() + telemetry no-ops
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from functools import lru_cache
from typing import Optional

# ---------------------------------------------------------------------------
# Version — injected at build time by cli.tsx MACRO.VERSION
# ---------------------------------------------------------------------------
VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Feature flags — all False in the open-source build (matches feature() → False)
# ---------------------------------------------------------------------------
FEATURE_DUMP_SYSTEM_PROMPT = False
FEATURE_ABLATION_BASELINE = False
FEATURE_DAEMON = False
FEATURE_BRIDGE_MODE = False
FEATURE_BG_SESSIONS = False
FEATURE_TEMPLATES = False
FEATURE_BYOC_ENVIRONMENT_RUNNER = False
FEATURE_SELF_HOSTED_RUNNER = False
FEATURE_CHICAGO_MCP = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown registry
# ---------------------------------------------------------------------------
_cleanup_handlers: list = []
_shutdown_event: asyncio.Event | None = None


def register_cleanup(fn) -> None:
    """Register a coroutine function (or sync callable) to run on exit."""
    _cleanup_handlers.append(fn)


async def _run_cleanup_handlers() -> None:
    for fn in reversed(_cleanup_handlers):
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            log.debug("[cleanup] handler raised: %s", exc)


def setup_graceful_shutdown() -> None:
    """Wire SIGINT / SIGTERM to set the shutdown event (mirrors setupGracefulShutdown)."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    loop = asyncio.get_event_loop()

    def _handle_signal(sig) -> None:
        log.debug("[shutdown] received signal %s", sig)
        if _shutdown_event is not None:
            _shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))
        except (NotImplementedError, OSError):
            # Windows: add_signal_handler not supported for all signals
            signal.signal(sig, lambda signum, frame: _handle_signal(signum))


def graceful_shutdown_sync(exit_code: int = 0) -> None:
    """Synchronous shutdown path (used from ConfigParseError handler)."""
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Stub imports for not-yet-ported modules
# Use try/except so __main__.py can be imported even before all modules exist.
# Each RE-ENTRY comment marks where the real import plugs in once ported.
# ---------------------------------------------------------------------------

# RE-ENTRY: from optimus.utils.config import enable_configs, record_first_start_time
try:
    from optimus.utils.config import enable_configs, record_first_start_time  # type: ignore[import]
except ImportError:
    def enable_configs() -> None: ...          # type: ignore[misc]
    def record_first_start_time() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.managed_env import apply_safe_config_environment_variables, apply_config_environment_variables
try:
    from optimus.utils.managed_env import (    # type: ignore[import]
        apply_safe_config_environment_variables,
        apply_config_environment_variables,
    )
except ImportError:
    def apply_safe_config_environment_variables() -> None: ... # type: ignore[misc]
    def apply_config_environment_variables() -> None: ...     # type: ignore[misc]

# RE-ENTRY: from optimus.utils.ca_certs_config import apply_extra_ca_certs_from_config
try:
    from optimus.utils.ca_certs_config import apply_extra_ca_certs_from_config  # type: ignore[import]
except ImportError:
    def apply_extra_ca_certs_from_config() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.services.oauth.client import populate_oauth_account_info_if_needed
try:
    from optimus.services.oauth.client import populate_oauth_account_info_if_needed  # type: ignore[import]
except ImportError:
    async def populate_oauth_account_info_if_needed() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.env_dynamic import init_jet_brains_detection
try:
    from optimus.utils.env_dynamic import init_jet_brains_detection  # type: ignore[import]
except ImportError:
    async def init_jet_brains_detection() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.detect_repository import detect_current_repository
try:
    from optimus.utils.detect_repository import detect_current_repository  # type: ignore[import]
except ImportError:
    async def detect_current_repository() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.mtls import configure_global_mtls
try:
    from optimus.utils.mtls import configure_global_mtls  # type: ignore[import]
except ImportError:
    def configure_global_mtls() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.proxy import configure_global_agents
try:
    from optimus.utils.proxy import configure_global_agents  # type: ignore[import]
except ImportError:
    def configure_global_agents() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.api_preconnect import preconnect_anthropic_api
try:
    from optimus.utils.api_preconnect import preconnect_anthropic_api  # type: ignore[import]
except ImportError:
    def preconnect_anthropic_api() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.windows_paths import set_shell_if_windows
try:
    from optimus.utils.windows_paths import set_shell_if_windows  # type: ignore[import]
except ImportError:
    def set_shell_if_windows() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.services.lsp.manager import shutdown_lsp_server_manager
try:
    from optimus.services.lsp.manager import shutdown_lsp_server_manager  # type: ignore[import]
except ImportError:
    async def shutdown_lsp_server_manager() -> None: ... # type: ignore[misc]

# RE-ENTRY: from optimus.utils.permissions.filesystem import is_scratchpad_enabled, ensure_scratchpad_dir
try:
    from optimus.utils.permissions.filesystem import (  # type: ignore[import]
        is_scratchpad_enabled,
        ensure_scratchpad_dir,
    )
except ImportError:
    def is_scratchpad_enabled() -> bool: return False  # type: ignore[misc]
    async def ensure_scratchpad_dir() -> None: ...     # type: ignore[misc]

# RE-ENTRY: from optimus.utils.env_utils import is_env_truthy
try:
    from optimus.utils.env_utils import is_env_truthy  # type: ignore[import]
except ImportError:
    def is_env_truthy(value: Optional[str]) -> bool:  # type: ignore[misc]
        return value is not None and value.strip().lower() in ("1", "true", "yes")

# RE-ENTRY: from optimus.utils.errors import ConfigParseError
try:
    from optimus.utils.errors import ConfigParseError  # type: ignore[import]
except ImportError:
    class ConfigParseError(Exception):  # type: ignore[no-redef]
        file_path: str = ""

# RE-ENTRY: from optimus.bootstrap.state import get_is_non_interactive_session
try:
    from optimus.bootstrap.state import get_is_non_interactive_session  # type: ignore[import]
except ImportError:
    def get_is_non_interactive_session() -> bool: return False  # type: ignore[misc]

# ---------------------------------------------------------------------------
# Telemetry — all no-ops (init.ts: initializeTelemetryAfterTrust, doInitializeTelemetry, setMeterState)
# Signatures are preserved so callers can be ported without changes.
# ---------------------------------------------------------------------------
_telemetry_initialized = False


def initialize_telemetry_after_trust() -> None:
    """
    Port of initializeTelemetryAfterTrust() — no-op.
    In the TS source this initializes customer OTLP telemetry (metrics, logs, traces)
    after the user has accepted the trust dialog. Dropped in Python: no OTLP pipeline.
    RE-ENTRY: wire optimus.utils.telemetry.instrumentation when ported.
    """
    asyncio.ensure_future(_do_initialize_telemetry())


async def _do_initialize_telemetry() -> None:
    """
    Port of doInitializeTelemetry() — guards against double init then calls setMeterState.
    No-op here because setMeterState is a no-op.
    """
    global _telemetry_initialized
    if _telemetry_initialized:
        return
    _telemetry_initialized = True
    try:
        await _set_meter_state()
    except Exception:
        _telemetry_initialized = False
        raise


async def _set_meter_state() -> None:
    """
    Port of setMeterState() — lazy-loads OpenTelemetry instrumentation.
    No-op: Python build does not ship the OTLP pipeline.
    RE-ENTRY: import optimus.utils.telemetry.instrumentation and call initialize_telemetry().
    """


# ---------------------------------------------------------------------------
# init() — port of src/entrypoints/init.ts  export const init = memoize(...)
# ---------------------------------------------------------------------------
_init_called = False


async def init() -> None:
    """
    Memoized initialization function (mirrors `export const init = memoize(async () => {...})`).

    Steps (in order, matching init.ts):
      1. enable_configs()                       — validate + enable config system
      2. apply_safe_config_environment_variables() — safe subset before trust dialog
      3. apply_extra_ca_certs_from_config()     — inject CA certs before TLS
      4. setup_graceful_shutdown()              — SIGINT/SIGTERM handlers
      5. populate_oauth_account_info_if_needed()— fire-and-forget
      6. init_jet_brains_detection()            — fire-and-forget
      7. detect_current_repository()            — fire-and-forget
      8. record_first_start_time()
      9. configure_global_mtls()
     10. configure_global_agents()              — proxy + mTLS HTTP agents
     11. preconnect_anthropic_api()             — overlap TCP/TLS with init work
     12. upstream proxy init (CLAUDE_CODE_REMOTE only)
     13. set_shell_if_windows()
     14. register_cleanup(shutdown_lsp_server_manager)
     15. register_cleanup(cleanup_session_teams)
     16. ensure_scratchpad_dir() if enabled
    """
    global _init_called
    if _init_called:
        return
    _init_called = True

    import time
    init_start = time.monotonic()
    log.debug("[init] init_started")

    try:
        # 1. Enable configs
        enable_configs()
        log.debug("[init] init_configs_enabled")

        # 2. Apply safe environment variables (subset allowed before trust dialog)
        apply_safe_config_environment_variables()

        # 3. Apply extra CA certs from config — must happen before first TLS handshake
        apply_extra_ca_certs_from_config()
        log.debug("[init] init_safe_env_vars_applied")

        # 4. Graceful shutdown handlers
        setup_graceful_shutdown()
        log.debug("[init] init_after_graceful_shutdown")

        # 5. OAuth account info — fire-and-forget (mirrors void populateOAuthAccountInfoIfNeeded())
        asyncio.ensure_future(populate_oauth_account_info_if_needed())
        log.debug("[init] init_after_oauth_populate")

        # 6. JetBrains detection — fire-and-forget
        asyncio.ensure_future(init_jet_brains_detection())
        log.debug("[init] init_after_jetbrains_detection")

        # 7. Git repository detection — fire-and-forget
        asyncio.ensure_future(detect_current_repository())

        # 8. Record first start time
        record_first_start_time()

        # 9. mTLS configuration
        log.debug("[init] configureGlobalMTLS starting")
        configure_global_mtls()
        log.debug("[init] configureGlobalMTLS complete")

        # 10. HTTP agents (proxy + mTLS)
        log.debug("[init] configureGlobalAgents starting")
        configure_global_agents()
        log.debug("[init] configureGlobalAgents complete")
        log.debug("[init] init_network_configured")

        # 11. Preconnect to Anthropic API — fire-and-forget TCP/TLS warmup
        preconnect_anthropic_api()

        # 12. Upstream proxy for CCR environments (CLAUDE_CODE_REMOTE=true)
        if is_env_truthy(os.environ.get("CLAUDE_CODE_REMOTE")):
            try:
                # RE-ENTRY: from optimus.upstreamproxy.upstreamproxy import init_upstream_proxy, get_upstream_proxy_env
                # RE-ENTRY: from optimus.utils.subprocess_env import register_upstream_proxy_env_fn
                # register_upstream_proxy_env_fn(get_upstream_proxy_env)
                # await init_upstream_proxy()
                pass
            except Exception as exc:
                log.warning("[init] upstreamproxy init failed: %s; continuing without proxy", exc)

        # 13. Windows shell
        set_shell_if_windows()

        # 14. Register LSP manager cleanup
        register_cleanup(shutdown_lsp_server_manager)

        # 15. Register session team cleanup (swarm / agent teams)
        async def _cleanup_session_teams() -> None:
            # RE-ENTRY: from optimus.utils.swarm.team_helpers import cleanup_session_teams
            # await cleanup_session_teams()
            pass

        register_cleanup(_cleanup_session_teams)

        # 16. Scratchpad directory
        if is_scratchpad_enabled():
            await ensure_scratchpad_dir()
            log.debug("[init] init_scratchpad_created")

        elapsed = time.monotonic() - init_start
        log.debug("[init] init_completed in %.1fms", elapsed * 1000)

    except Exception as error:
        if isinstance(error, ConfigParseError):
            if get_is_non_interactive_session():
                sys.stderr.write(
                    f"Configuration error in {error.file_path}: {error}\n"
                )
                graceful_shutdown_sync(1)
                return
            # Interactive path: show the invalid-config dialog
            # RE-ENTRY: from optimus.components.invalid_config_dialog import show_invalid_config_dialog
            # await show_invalid_config_dialog(error=error)
            sys.stderr.write(f"Configuration error in {error.file_path}: {error}\n")
            graceful_shutdown_sync(1)
        else:
            raise


# ---------------------------------------------------------------------------
# main() — port of src/entrypoints/cli.tsx  async function main()
# ---------------------------------------------------------------------------
def main() -> None:
    """
    Bootstrap entry point — port of cli.tsx main().

    Checks argv for special fast-path flags before loading the full CLI.
    All feature-gated paths are False in the open-source build (see constants above).
    Falls through to the full REPL via optimus.main.main() (synchronous Click entry).
    """
    args = sys.argv[1:]

    # ── Fast-path: --version / -v / -V ──────────────────────────────────────
    if len(args) == 1 and args[0] in ("--version", "-v", "-V"):
        print(f"{VERSION} (Optimus Mark I)")
        return

    # ── Feature-gated fast paths — all False in external build ──────────────
    # RE-ENTRY DUMP_SYSTEM_PROMPT: if args and args[0] == "--dump-system-prompt": ...
    # RE-ENTRY CHICAGO_MCP claude-in-chrome: if args and args[0] == "--claude-in-chrome-mcp": ...
    # RE-ENTRY chrome-native-host: if args and args[0] == "--chrome-native-host": ...
    # RE-ENTRY CHICAGO_MCP computer-use: if args and args[0] == "--computer-use-mcp": ...
    # RE-ENTRY DAEMON worker: if args and args[0] == "--daemon-worker": ...
    # RE-ENTRY BRIDGE_MODE remote-control/rc/remote/sync/bridge: ...
    # RE-ENTRY DAEMON daemon subcommand: ...
    # RE-ENTRY BG_SESSIONS ps/logs/attach/kill/--bg/--background: ...
    # RE-ENTRY TEMPLATES new/list/reply: ...
    # RE-ENTRY BYOC_ENVIRONMENT_RUNNER environment-runner: ...
    # RE-ENTRY SELF_HOSTED_RUNNER self-hosted-runner: ...
    # RE-ENTRY --tmux --worktree exec-into-tmux fast path: ...

    # ── Redirect --update / --upgrade → update subcommand ───────────────────
    if len(args) == 1 and args[0] in ("--update", "--upgrade"):
        sys.argv = [sys.argv[0], "update"] + sys.argv[3:]

    # ── --bare: set CLAUDE_CODE_SIMPLE early (before module-level gates fire) ─
    if "--bare" in args:
        os.environ["CLAUDE_CODE_SIMPLE"] = "1"

    # ── Full CLI — load optimus.main and run the REPL ────────────────────────
    # optimus.main.main() is synchronous (Click owns the event loop internally).
    # RE-ENTRY: from optimus.main import main as cli_main; cli_main()
    try:
        from optimus.main import main as cli_main  # type: ignore[import]
        cli_main()
    except ImportError:
        # optimus.main not yet ported — show minimal startup message
        import platform
        print(f"Optimus Mark I {VERSION}")
        print(f"Python {platform.python_version()} on {sys.platform}")
        print("(optimus.main not yet ported — run after all modules are complete)")


# ---------------------------------------------------------------------------
# Entry point — mirrors `void main()` at end of cli.tsx
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # CLAUDE_CODE_REMOTE: no heap-size flag needed in Python (unlike Node)
    # ABLATION_BASELINE: feature-gated, FEATURE_ABLATION_BASELINE = False
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("OPTIMUS_DEBUG") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # main() is now synchronous — Click in main.py owns the asyncio event loop
    main()
