"""
utils/config.py — port of src/utils/config.ts

The global + per-project configuration system: read/write of ~/.claude.json
with an in-memory cache, a background freshness watcher, atomic locked writes,
timestamped backups, corruption recovery, trust-dialog checks, and the
auto-updater / userID / memory-path accessors layered on top.

Porting notes:
  - GlobalConfig / ProjectConfig are TS object types; here they are plain dicts
    with factory-built defaults (createDefaultGlobalConfig / DEFAULT_PROJECT_CONFIG).
  - getFsImplementation() abstraction → Python's os / open directly (the FS
    indirection exists in TS for the browser-sdk build; not needed here).
  - lodash memoize → functools.lru_cache; lodash pickBy → dict comprehension.
  - fs.watchFile poll watcher → a daemon thread polling st_mtime every 1s.
  - lockfile.lockSync → _config_lock(): atomic O_EXCL creation of `${file}.lock`
    with brief retry, always released in a finally.
  - randomBytes(32).hex → secrets.token_hex(32).
  - logEvent / analytics → dropped (telemetry no-op) per project rules.
  - getEssentialTrafficOnlyReason / getManagedFilePath / getAutoMemEntrypoint →
    inline RE-ENTRY stubs until privacyLevel / settings / memdir are ported.
  - NODE_ENV==='test' branches → _is_test_env() (NODE_ENV or OPTIMUS_ENV == test).
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Optional

from optimus.bootstrap.state import get_original_cwd, get_session_trust_accepted
from optimus.env_utils import get_claude_config_home_dir, is_env_truthy
from optimus.utils.cleanup_registry import register_cleanup
from optimus.utils.cwd import get_cwd
from optimus.utils.debug import log_for_debugging
from optimus.utils.diag_logs import log_for_diagnostics_no_pii
from optimus.utils.env import get_global_claude_file
from optimus.utils.errors import ConfigParseError, get_errno_code
from optimus.utils.git import find_canonical_git_root
from optimus.utils.json import json_parse, json_stringify, safe_parse_json, strip_bom
from optimus.utils.log import log_error
from optimus.utils.path import normalize_path_for_config_key

# Config types live as dicts; these aliases document intent.
GlobalConfig = dict[str, Any]
ProjectConfig = dict[str, Any]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_test_env() -> bool:
    return os.environ.get("NODE_ENV") == "test" or os.environ.get("OPTIMUS_ENV") == "test"


# Re-entrancy guard: prevents getConfig → logEvent → getGlobalConfig → getConfig
# recursion on a corrupted file. logEvent is a no-op here, but the guard is kept.
_inside_get_config = False


# ---------------------------------------------------------------------------
# RE-ENTRY dependency stubs (small peripheral leaves, ported later)
# ---------------------------------------------------------------------------


def _get_essential_traffic_only_reason() -> Optional[str]:
    """Stub — mirrors getEssentialTrafficOnlyReason() from utils/privacyLevel.ts."""
    # RE-ENTRY: from optimus.utils.privacy_level import get_essential_traffic_only_reason
    return None


def _get_managed_file_path() -> str:
    """Stub — mirrors getManagedFilePath() from utils/settings/managedPath.ts."""
    # RE-ENTRY: from optimus.utils.settings.managed_path import get_managed_file_path
    return get_claude_config_home_dir()


def _get_auto_mem_entrypoint() -> str:
    """Stub — mirrors getAutoMemEntrypoint() from memdir/paths.ts."""
    # RE-ENTRY: from optimus.memdir.paths import get_auto_mem_entrypoint
    return os.path.join(get_claude_config_home_dir(), "memdir", "CLAUDE.md")


# ---------------------------------------------------------------------------
# Default configs
# ---------------------------------------------------------------------------

DEFAULT_PROJECT_CONFIG: ProjectConfig = {
    "allowedTools": [],
    "mcpContextUris": [],
    "mcpServers": {},
    "enabledMcpjsonServers": [],
    "disabledMcpjsonServers": [],
    "hasTrustDialogAccepted": False,
    "projectOnboardingSeenCount": 0,
    "hasClaudeMdExternalIncludesApproved": False,
    "hasClaudeMdExternalIncludesWarningShown": False,
}


def create_default_global_config() -> GlobalConfig:
    """Factory for a fresh default GlobalConfig (fresh nested container refs)."""
    return {
        "numStartups": 0,
        "installMethod": None,
        "autoUpdates": None,
        "theme": "dark",
        "preferredNotifChannel": "auto",
        "verbose": False,
        "editorMode": "normal",
        "autoCompactEnabled": True,
        "showTurnDuration": True,
        "hasSeenTasksHint": False,
        "hasUsedStash": False,
        "hasUsedBackgroundTask": False,
        "queuedCommandUpHintCount": 0,
        "diffTool": "auto",
        "customApiKeyResponses": {"approved": [], "rejected": []},
        "env": {},
        "tipsHistory": {},
        "memoryUsageCount": 0,
        "promptQueueUseCount": 0,
        "btwUseCount": 0,
        "todoFeatureEnabled": True,
        "showExpandedTodos": False,
        "messageIdleNotifThresholdMs": 60000,
        "autoConnectIde": False,
        "autoInstallIdeExtension": True,
        "fileCheckpointingEnabled": True,
        "terminalProgressBarEnabled": True,
        "cachedStatsigGates": {},
        "cachedDynamicConfigs": {},
        "cachedGrowthBookFeatures": {},
        "respectGitignore": True,
        "copyFullResponse": False,
    }


DEFAULT_GLOBAL_CONFIG: GlobalConfig = create_default_global_config()

GLOBAL_CONFIG_KEYS: tuple[str, ...] = (
    "apiKeyHelper",
    "installMethod",
    "autoUpdates",
    "autoUpdatesProtectedForNative",
    "theme",
    "verbose",
    "preferredNotifChannel",
    "shiftEnterKeyBindingInstalled",
    "editorMode",
    "hasUsedBackslashReturn",
    "autoCompactEnabled",
    "showTurnDuration",
    "diffTool",
    "env",
    "tipsHistory",
    "todoFeatureEnabled",
    "showExpandedTodos",
    "messageIdleNotifThresholdMs",
    "autoConnectIde",
    "autoInstallIdeExtension",
    "fileCheckpointingEnabled",
    "terminalProgressBarEnabled",
    "showStatusInTerminalTab",
    "taskCompleteNotifEnabled",
    "inputNeededNotifEnabled",
    "agentPushNotifEnabled",
    "respectGitignore",
    "claudeInChromeDefaultEnabled",
    "hasCompletedClaudeInChromeOnboarding",
    "lspRecommendationDisabled",
    "lspRecommendationNeverPlugins",
    "lspRecommendationIgnoredCount",
    "copyFullResponse",
    "copyOnSelect",
    "permissionExplainerEnabled",
    "prStatusFooterEnabled",
    "remoteControlAtStartup",
    "remoteDialogSeen",
)


def is_global_config_key(key: str) -> bool:
    return key in GLOBAL_CONFIG_KEYS


PROJECT_CONFIG_KEYS: tuple[str, ...] = (
    "allowedTools",
    "hasTrustDialogAccepted",
    "hasCompletedProjectOnboarding",
)


def is_project_config_key(key: str) -> bool:
    return key in PROJECT_CONFIG_KEYS


# Jest can't mock ES modules, so the TS keeps test fixtures inline. Mirrored.
_TEST_GLOBAL_CONFIG_FOR_TESTING: GlobalConfig = {
    **DEFAULT_GLOBAL_CONFIG,
    "autoUpdates": False,
}
_TEST_PROJECT_CONFIG_FOR_TESTING: ProjectConfig = {**DEFAULT_PROJECT_CONFIG}


# ---------------------------------------------------------------------------
# Trust dialog
# ---------------------------------------------------------------------------

_trust_accepted = False


def reset_trust_dialog_accepted_cache_for_testing() -> None:
    global _trust_accepted
    _trust_accepted = False


def check_has_trust_dialog_accepted() -> bool:
    # Trust only transitions false→true within a session, so latch on true.
    # false is never cached — re-checked each call to pick up mid-session accept.
    global _trust_accepted
    if not _trust_accepted:
        _trust_accepted = _compute_trust_dialog_accepted()
    return _trust_accepted


def _compute_trust_dialog_accepted() -> bool:
    # Session-level trust (home-directory case, not persisted to disk).
    if get_session_trust_accepted():
        return True

    config = get_global_config()

    # Primary persisted location: git root or original cwd.
    project_path = get_project_path_for_config()
    project_config = (config.get("projects") or {}).get(project_path)
    if project_config and project_config.get("hasTrustDialogAccepted"):
        return True

    # Walk from cwd up through parents (trust is inherited by children).
    current_path = normalize_path_for_config_key(get_cwd())
    while True:
        path_config = (config.get("projects") or {}).get(current_path)
        if path_config and path_config.get("hasTrustDialogAccepted"):
            return True
        parent_path = normalize_path_for_config_key(
            os.path.abspath(os.path.join(current_path, ".."))
        )
        if parent_path == current_path:
            break
        current_path = parent_path

    return False


def is_path_trusted(directory: str) -> bool:
    """Check trust for an arbitrary directory (walks ancestors; no session trust)."""
    config = get_global_config()
    current_path = normalize_path_for_config_key(os.path.abspath(directory))
    while True:
        pc = (config.get("projects") or {}).get(current_path)
        if pc and pc.get("hasTrustDialogAccepted"):
            return True
        parent_path = normalize_path_for_config_key(
            os.path.abspath(os.path.join(current_path, ".."))
        )
        if parent_path == current_path:
            return False
        current_path = parent_path


# ---------------------------------------------------------------------------
# Auth-loss guard
# ---------------------------------------------------------------------------


def _would_lose_auth_state(fresh: dict[str, Any]) -> bool:
    """
    True if writing `fresh` would drop auth/onboarding state the cache still has
    (a corrupted/truncated mid-write read returned defaults). See GH #3117.
    """
    cached = _global_config_cache["config"]
    if not cached:
        return False
    lost_oauth = cached.get("oauthAccount") is not None and fresh.get("oauthAccount") is None
    lost_onboarding = (
        cached.get("hasCompletedOnboarding") is True
        and fresh.get("hasCompletedOnboarding") is not True
    )
    return lost_oauth or lost_onboarding


# ---------------------------------------------------------------------------
# Global config cache + write counters
# ---------------------------------------------------------------------------

_global_config_cache: dict[str, Any] = {"config": None, "mtime": 0}
_last_read_file_stats: Optional[dict[str, float]] = None
_config_cache_hits = 0
_config_cache_misses = 0
_global_config_write_count = 0

CONFIG_WRITE_DISPLAY_THRESHOLD = 20


def get_global_config_write_count() -> int:
    return _global_config_write_count


def _report_config_cache_stats() -> None:
    global _config_cache_hits, _config_cache_misses
    # logEvent dropped — counters still reset to mirror behavior.
    _config_cache_hits = 0
    _config_cache_misses = 0


register_cleanup(_report_config_cache_stats)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def _migrate_config_fields(config: GlobalConfig) -> GlobalConfig:
    """Migrate legacy autoUpdaterStatus → installMethod + autoUpdates."""
    if config.get("installMethod") is not None:
        return config

    legacy_status = config.get("autoUpdaterStatus")
    install_method = "unknown"
    auto_updates = config.get("autoUpdates")
    if auto_updates is None:
        auto_updates = True  # default enabled unless explicitly disabled

    if legacy_status == "migrated":
        install_method = "local"
    elif legacy_status == "installed":
        install_method = "native"
    elif legacy_status == "disabled":
        auto_updates = False
    elif legacy_status in ("enabled", "no_permissions", "not_configured"):
        install_method = "global"

    return {**config, "installMethod": install_method, "autoUpdates": auto_updates}


def _remove_project_history(
    projects: Optional[dict[str, ProjectConfig]],
) -> Optional[dict[str, ProjectConfig]]:
    """Strip the legacy `history` field from projects (migrated to history.jsonl)."""
    if not projects:
        return projects
    cleaned: dict[str, ProjectConfig] = {}
    needs_cleaning = False
    for path, project_config in projects.items():
        if "history" in project_config:
            needs_cleaning = True
            cleaned[path] = {k: v for k, v in project_config.items() if k != "history"}
        else:
            cleaned[path] = project_config
    return cleaned if needs_cleaning else projects


# ---------------------------------------------------------------------------
# Freshness watcher (fs.watchFile poll → daemon thread)
# ---------------------------------------------------------------------------

CONFIG_FRESHNESS_POLL_MS = 1000
_freshness_watcher_started = False
_freshness_stop = threading.Event()


def _start_global_config_freshness_watcher() -> None:
    global _freshness_watcher_started
    if _freshness_watcher_started or _is_test_env():
        return
    _freshness_watcher_started = True
    file = get_global_claude_file()

    def _poll() -> None:
        while not _freshness_stop.wait(CONFIG_FRESHNESS_POLL_MS / 1000):
            try:
                st = os.stat(file)
            except OSError:
                continue
            mtime_ms = st.st_mtime * 1000
            # Our own write-through overshoots cache mtime, so we skip re-reading it.
            if mtime_ms <= _global_config_cache["mtime"]:
                continue
            try:
                with open(file, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue
            if mtime_ms <= _global_config_cache["mtime"]:
                continue
            parsed = safe_parse_json(strip_bom(content))
            if parsed is None or not isinstance(parsed, dict):
                continue
            _global_config_cache["config"] = _migrate_config_fields(
                {**create_default_global_config(), **parsed}
            )
            _global_config_cache["mtime"] = mtime_ms
            global _last_read_file_stats
            _last_read_file_stats = {"mtime": mtime_ms, "size": st.st_size}

    t = threading.Thread(target=_poll, name="optimus-config-watcher", daemon=True)
    t.start()

    def _stop() -> None:
        global _freshness_watcher_started
        _freshness_stop.set()
        _freshness_watcher_started = False

    register_cleanup(_stop)


def _write_through_global_config_cache(config: GlobalConfig) -> None:
    global _last_read_file_stats
    _global_config_cache["config"] = config
    _global_config_cache["mtime"] = _now_ms()
    _last_read_file_stats = None


# ---------------------------------------------------------------------------
# getGlobalConfig
# ---------------------------------------------------------------------------


def get_global_config() -> GlobalConfig:
    global _config_cache_hits, _config_cache_misses, _last_read_file_stats
    if _is_test_env():
        return _TEST_GLOBAL_CONFIG_FOR_TESTING

    # Fast path: pure memory read.
    if _global_config_cache["config"]:
        _config_cache_hits += 1
        return _global_config_cache["config"]

    # Slow path: startup load (sync I/O acceptable — runs once before UI).
    _config_cache_misses += 1
    try:
        stats = None
        try:
            stats = os.stat(get_global_claude_file())
        except OSError:
            pass
        config = _migrate_config_fields(
            _get_config(get_global_claude_file(), create_default_global_config)
        )
        _global_config_cache["config"] = config
        _global_config_cache["mtime"] = (stats.st_mtime * 1000) if stats else _now_ms()
        _last_read_file_stats = (
            {"mtime": stats.st_mtime * 1000, "size": stats.st_size} if stats else None
        )
        _start_global_config_freshness_watcher()
        return config
    except Exception:
        return _migrate_config_fields(
            _get_config(get_global_claude_file(), create_default_global_config)
        )


def get_remote_control_at_startup() -> bool:
    explicit = get_global_config().get("remoteControlAtStartup")
    if explicit is not None:
        return explicit
    # feature('CCR_AUTO_CONNECT') → False
    return False


def get_custom_api_key_status(truncated_api_key: str) -> str:
    config = get_global_config()
    responses = config.get("customApiKeyResponses") or {}
    if truncated_api_key in (responses.get("approved") or []):
        return "approved"
    if truncated_api_key in (responses.get("rejected") or []):
        return "rejected"
    return "new"


# ---------------------------------------------------------------------------
# Low-level fs helpers
# ---------------------------------------------------------------------------


def _write_file_and_flush(file: str, content: str, mode: int = 0o600) -> None:
    """Mirrors writeFileSyncAndFlush_DEPRECATED — write + fsync, 0o600 on create."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(file, flags, mode)
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _pick_by_non_default(config: dict[str, Any], default_config: dict[str, Any]) -> dict[str, Any]:
    """Mirrors pickBy() — drop keys whose JSON matches the default's JSON."""
    return {
        k: v
        for k, v in config.items()
        if json_stringify(v) != json_stringify(default_config.get(k))
    }


def _save_config(file: str, config: dict[str, Any], default_config: dict[str, Any]) -> None:
    global _global_config_write_count
    os.makedirs(os.path.dirname(file), exist_ok=True)
    filtered = _pick_by_non_default(config, default_config)
    _write_file_and_flush(file, json_stringify(filtered, None, 2))
    if file == get_global_claude_file():
        _global_config_write_count += 1


class _LockHandle:
    def __init__(self, lock_path: str, fd: int) -> None:
        self.lock_path = lock_path
        self.fd = fd

    def release(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.unlink(self.lock_path)
        except OSError:
            pass


def _config_lock(file: str) -> _LockHandle:
    """
    Acquire an exclusive lock via atomic O_EXCL creation of `${file}.lock`.
    Mirrors lockfile.lockSync's intent (cross-process mutual exclusion) with a
    short bounded retry; stale locks older than 60s are reclaimed.
    """
    lock_path = f"{file}.lock"
    deadline = time.monotonic() + 10  # bounded wait
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            return _LockHandle(lock_path, fd)
        except FileExistsError:
            # Reclaim a stale lock (compromised holder / crash).
            try:
                age = time.time() - os.stat(lock_path).st_mtime
                if age > 60:
                    os.unlink(lock_path)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                log_for_debugging(
                    "Lock acquisition took longer than expected - another instance may be running"
                )
                # Steal the lock rather than hang forever.
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                continue
            time.sleep(0.02)


def _save_config_with_lock(
    file: str,
    create_default: Callable[[], dict[str, Any]],
    merge_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> bool:
    """
    Returns True if a write was performed; False if skipped (no change / auth
    guard). Callers gate cache invalidation on this.
    """
    global _global_config_write_count
    default_config = create_default()
    os.makedirs(os.path.dirname(file), exist_ok=True)

    release: Optional[_LockHandle] = None
    try:
        start_time = _now_ms()
        release = _config_lock(file)
        lock_time = _now_ms() - start_time
        if lock_time > 100:
            log_for_debugging(
                "Lock acquisition took longer than expected - another Claude instance may be running"
            )

        # Stale-write detection (global file only).
        if _last_read_file_stats and file == get_global_claude_file():
            try:
                cs = os.stat(file)
                # logEvent dropped; the stat read still self-documents the race.
                _ = (cs.st_mtime * 1000, cs.st_size)
            except OSError as e:
                if get_errno_code(e) != "ENOENT":
                    raise

        current_config = _get_config(file, create_default)
        if file == get_global_claude_file() and _would_lose_auth_state(current_config):
            log_for_debugging(
                "saveConfigWithLock: re-read config is missing auth that cache has; "
                "refusing to write to avoid wiping ~/.claude.json. See GH #3117.",
                {"level": "error"},
            )
            return False

        merged_config = merge_fn(current_config)
        if merged_config is current_config:
            return False

        filtered = _pick_by_non_default(merged_config, default_config)

        # Timestamped backup of existing config before writing.
        try:
            file_base = os.path.basename(file)
            backup_dir = _get_config_backup_dir()
            os.makedirs(backup_dir, exist_ok=True)

            MIN_BACKUP_INTERVAL_MS = 60_000
            try:
                existing_backups = sorted(
                    [
                        f
                        for f in os.listdir(backup_dir)
                        if f.startswith(f"{file_base}.backup.")
                    ],
                    reverse=True,
                )
            except OSError:
                existing_backups = []
            most_recent = existing_backups[0] if existing_backups else None
            try:
                most_recent_ts = int(most_recent.split(".backup.")[-1]) if most_recent else 0
            except ValueError:
                most_recent_ts = -1  # NaN-equivalent → force a backup
            should_create_backup = (
                most_recent_ts < 0 or _now_ms() - most_recent_ts >= MIN_BACKUP_INTERVAL_MS
            )

            if should_create_backup and os.path.exists(file):
                backup_path = os.path.join(backup_dir, f"{file_base}.backup.{_now_ms()}")
                _copy_file(file, backup_path)

            MAX_BACKUPS = 5
            if should_create_backup:
                backups_for_cleanup = sorted(
                    [f for f in os.listdir(backup_dir) if f.startswith(f"{file_base}.backup.")],
                    reverse=True,
                )
            else:
                backups_for_cleanup = existing_backups
            for old_backup in backups_for_cleanup[MAX_BACKUPS:]:
                try:
                    os.unlink(os.path.join(backup_dir, old_backup))
                except OSError:
                    pass
        except OSError as e:
            if get_errno_code(e) != "ENOENT":
                log_for_debugging(f"Failed to backup config: {e}", {"level": "error"})

        _write_file_and_flush(file, json_stringify(filtered, None, 2))
        if file == get_global_claude_file():
            _global_config_write_count += 1
        return True
    finally:
        if release:
            release.release()


def _copy_file(src: str, dst: str) -> None:
    with open(src, "rb") as fsrc:
        data = fsrc.read()
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# enableConfigs / config read
# ---------------------------------------------------------------------------

_config_reading_allowed = False


def enable_configs() -> None:
    global _config_reading_allowed
    if _config_reading_allowed:
        return  # idempotent

    start_time = _now_ms()
    log_for_diagnostics_no_pii("info", "enable_configs_started")

    _config_reading_allowed = True
    # All configs share one file — checking the global config validates it.
    _get_config(get_global_claude_file(), create_default_global_config, throw_on_invalid=True)

    log_for_diagnostics_no_pii(
        "info", "enable_configs_completed", {"duration_ms": _now_ms() - start_time}
    )


def _get_config_backup_dir() -> str:
    return os.path.join(get_claude_config_home_dir(), "backups")


def _find_most_recent_backup(file: str) -> Optional[str]:
    file_base = os.path.basename(file)
    backup_dir = _get_config_backup_dir()
    try:
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith(f"{file_base}.backup.")]
        )
        if backups:
            return os.path.join(backup_dir, backups[-1])
    except OSError:
        pass

    file_dir = os.path.dirname(file)
    try:
        backups = sorted(
            [f for f in os.listdir(file_dir) if f.startswith(f"{file_base}.backup.")]
        )
        if backups:
            return os.path.join(file_dir, backups[-1])
        legacy_backup = f"{file}.backup"
        if os.path.exists(legacy_backup):
            return legacy_backup
    except OSError:
        pass
    return None


def _get_config(
    file: str,
    create_default: Callable[[], Any],
    throw_on_invalid: bool = False,
) -> Any:
    global _inside_get_config
    if not _config_reading_allowed and not _is_test_env():
        raise RuntimeError("Config accessed before allowed.")

    try:
        try:
            with open(file, encoding="utf-8") as f:
                file_content = f.read()
        except OSError as read_err:
            raise read_err
        try:
            parsed_config = json_parse(strip_bom(file_content))
            return {**create_default(), **parsed_config}
        except Exception as error:
            raise ConfigParseError(str(error), file, create_default())
    except OSError as error:
        if get_errno_code(error) == "ENOENT":
            backup_path = _find_most_recent_backup(file)
            if backup_path:
                import sys

                sys.stderr.write(
                    f"\nClaude configuration file not found at: {file}\n"
                    f"A backup file exists at: {backup_path}\n"
                    f'You can manually restore it by running: cp "{backup_path}" "{file}"\n\n'
                )
            return create_default()
        raise
    except ConfigParseError as error:
        if throw_on_invalid:
            raise

        log_for_debugging(
            f"Config file corrupted, resetting to defaults: {error.message}",
            {"level": "error"},
        )
        if not _inside_get_config:
            _inside_get_config = True
            try:
                log_error(error)
            finally:
                _inside_get_config = False

        import sys

        sys.stderr.write(f"\nClaude configuration file at {file} is corrupted: {error.message}\n")

        # Back up the corrupted file (dedup against existing corrupted backups).
        try:
            file_base = os.path.basename(file)
            corrupted_backup_dir = _get_config_backup_dir()
            os.makedirs(corrupted_backup_dir, exist_ok=True)

            existing_corrupted = [
                f
                for f in os.listdir(corrupted_backup_dir)
                if f.startswith(f"{file_base}.corrupted.")
            ]
            corrupted_backup_path: Optional[str] = None
            already_backed_up = False
            try:
                with open(file, encoding="utf-8") as cf:
                    current_content = cf.read()
            except OSError:
                current_content = ""
            for backup in existing_corrupted:
                try:
                    with open(os.path.join(corrupted_backup_dir, backup), encoding="utf-8") as bf:
                        backup_content = bf.read()
                    if current_content == backup_content:
                        already_backed_up = True
                        break
                except OSError:
                    pass
            if not already_backed_up:
                corrupted_backup_path = os.path.join(
                    corrupted_backup_dir, f"{file_base}.corrupted.{_now_ms()}"
                )
                try:
                    _copy_file(file, corrupted_backup_path)
                    log_for_debugging(
                        f"Corrupted config backed up to: {corrupted_backup_path}",
                        {"level": "error"},
                    )
                except OSError:
                    corrupted_backup_path = None

            backup_path = _find_most_recent_backup(file)
            if corrupted_backup_path:
                sys.stderr.write(
                    f"The corrupted file has been backed up to: {corrupted_backup_path}\n"
                )
            elif already_backed_up:
                sys.stderr.write("The corrupted file has already been backed up.\n")
            if backup_path:
                sys.stderr.write(
                    f"A backup file exists at: {backup_path}\n"
                    f'You can manually restore it by running: cp "{backup_path}" "{file}"\n\n'
                )
            else:
                sys.stderr.write("\n")
        except OSError:
            pass

        return create_default()


# ---------------------------------------------------------------------------
# saveGlobalConfig
# ---------------------------------------------------------------------------


def save_global_config(updater: Callable[[GlobalConfig], GlobalConfig]) -> None:
    if _is_test_env():
        config = updater(_TEST_GLOBAL_CONFIG_FOR_TESTING)
        if config is _TEST_GLOBAL_CONFIG_FOR_TESTING:
            return
        _TEST_GLOBAL_CONFIG_FOR_TESTING.update(config)
        return

    written: dict[str, Any] = {"value": None}
    try:
        def _merge(current: GlobalConfig) -> GlobalConfig:
            config = updater(current)
            if config is current:
                return current
            written["value"] = {
                **config,
                "projects": _remove_project_history(current.get("projects")),
            }
            return written["value"]

        did_write = _save_config_with_lock(
            get_global_claude_file(), create_default_global_config, _merge
        )
        if did_write and written["value"]:
            _write_through_global_config_cache(written["value"])
    except Exception as error:
        log_for_debugging(f"Failed to save config with lock: {error}", {"level": "error"})
        current_config = _get_config(get_global_claude_file(), create_default_global_config)
        if _would_lose_auth_state(current_config):
            log_for_debugging(
                "saveGlobalConfig fallback: re-read config is missing auth that cache has; "
                "refusing to write. See GH #3117.",
                {"level": "error"},
            )
            return
        config = updater(current_config)
        if config is current_config:
            return
        written_value = {
            **config,
            "projects": _remove_project_history(current_config.get("projects")),
        }
        _save_config(get_global_claude_file(), written_value, DEFAULT_GLOBAL_CONFIG)
        _write_through_global_config_cache(written_value)


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def get_project_path_for_config() -> str:
    """Memoized project identity path: canonical git root, else resolved cwd."""
    original_cwd = get_original_cwd()
    git_root = find_canonical_git_root(original_cwd)
    if git_root:
        return normalize_path_for_config_key(git_root)
    return normalize_path_for_config_key(os.path.abspath(original_cwd))


def get_current_project_config() -> ProjectConfig:
    if _is_test_env():
        return _TEST_PROJECT_CONFIG_FOR_TESTING

    absolute_path = get_project_path_for_config()
    config = get_global_config()
    if not config.get("projects"):
        return DEFAULT_PROJECT_CONFIG

    project_config = config["projects"].get(absolute_path, DEFAULT_PROJECT_CONFIG)
    # Defensive: allowedTools occasionally persisted as a JSON string upstream.
    if isinstance(project_config.get("allowedTools"), str):
        project_config["allowedTools"] = safe_parse_json(project_config["allowedTools"]) or []
    return project_config


def save_current_project_config(updater: Callable[[ProjectConfig], ProjectConfig]) -> None:
    if _is_test_env():
        config = updater(_TEST_PROJECT_CONFIG_FOR_TESTING)
        if config is _TEST_PROJECT_CONFIG_FOR_TESTING:
            return
        _TEST_PROJECT_CONFIG_FOR_TESTING.update(config)
        return

    absolute_path = get_project_path_for_config()
    written: dict[str, Any] = {"value": None}
    try:
        def _merge(current: GlobalConfig) -> GlobalConfig:
            current_project_config = (current.get("projects") or {}).get(
                absolute_path, DEFAULT_PROJECT_CONFIG
            )
            new_project_config = updater(current_project_config)
            if new_project_config is current_project_config:
                return current
            written["value"] = {
                **current,
                "projects": {**(current.get("projects") or {}), absolute_path: new_project_config},
            }
            return written["value"]

        did_write = _save_config_with_lock(
            get_global_claude_file(), create_default_global_config, _merge
        )
        if did_write and written["value"]:
            _write_through_global_config_cache(written["value"])
    except Exception as error:
        log_for_debugging(f"Failed to save config with lock: {error}", {"level": "error"})
        config = _get_config(get_global_claude_file(), create_default_global_config)
        if _would_lose_auth_state(config):
            log_for_debugging(
                "saveCurrentProjectConfig fallback: re-read config is missing auth that cache "
                "has; refusing to write. See GH #3117.",
                {"level": "error"},
            )
            return
        current_project_config = (config.get("projects") or {}).get(
            absolute_path, DEFAULT_PROJECT_CONFIG
        )
        new_project_config = updater(current_project_config)
        if new_project_config is current_project_config:
            return
        written_value = {
            **config,
            "projects": {**(config.get("projects") or {}), absolute_path: new_project_config},
        }
        _save_config(get_global_claude_file(), written_value, DEFAULT_GLOBAL_CONFIG)
        _write_through_global_config_cache(written_value)


# ---------------------------------------------------------------------------
# Auto-updater
# ---------------------------------------------------------------------------


def is_auto_updater_disabled() -> bool:
    return get_auto_updater_disabled_reason() is not None


def should_skip_plugin_autoupdate() -> bool:
    return is_auto_updater_disabled() and not is_env_truthy(
        os.environ.get("FORCE_AUTOUPDATE_PLUGINS")
    )


def format_auto_updater_disabled_reason(reason: dict[str, Any]) -> str:
    t = reason.get("type")
    if t == "development":
        return "development build"
    if t == "env":
        return f"{reason.get('envVar')} set"
    return "config"  # 'config'


def get_auto_updater_disabled_reason() -> Optional[dict[str, Any]]:
    if os.environ.get("NODE_ENV") == "development":
        return {"type": "development"}
    if is_env_truthy(os.environ.get("DISABLE_AUTOUPDATER")):
        return {"type": "env", "envVar": "DISABLE_AUTOUPDATER"}
    essential_traffic_env_var = _get_essential_traffic_only_reason()
    if essential_traffic_env_var:
        return {"type": "env", "envVar": essential_traffic_env_var}
    config = get_global_config()
    if config.get("autoUpdates") is False and (
        config.get("installMethod") != "native"
        or config.get("autoUpdatesProtectedForNative") is not True
    ):
        return {"type": "config"}
    return None


# ---------------------------------------------------------------------------
# User ID / first start / memory paths
# ---------------------------------------------------------------------------


def get_or_create_user_id() -> str:
    config = get_global_config()
    if config.get("userID"):
        return config["userID"]
    user_id = secrets.token_hex(32)
    save_global_config(lambda current: {**current, "userID": user_id})
    return user_id


def record_first_start_time() -> None:
    config = get_global_config()
    if not config.get("firstStartTime"):
        first_start_time = datetime.now(timezone.utc).isoformat()
        save_global_config(
            lambda current: {
                **current,
                "firstStartTime": current.get("firstStartTime") or first_start_time,
            }
        )


def get_memory_path(memory_type: str) -> str:
    cwd = get_original_cwd()
    if memory_type == "User":
        return os.path.join(get_claude_config_home_dir(), "CLAUDE.md")
    if memory_type == "Local":
        return os.path.join(cwd, "CLAUDE.local.md")
    if memory_type == "Project":
        return os.path.join(cwd, "CLAUDE.md")
    if memory_type == "Managed":
        return os.path.join(_get_managed_file_path(), "CLAUDE.md")
    if memory_type == "AutoMem":
        return _get_auto_mem_entrypoint()
    # feature('TEAMMEM') → False; TeamMem isn't a valid MemoryType externally.
    return ""


def get_managed_claude_rules_dir() -> str:
    return os.path.join(_get_managed_file_path(), ".claude", "rules")


def get_user_claude_rules_dir() -> str:
    return os.path.join(get_claude_config_home_dir(), "rules")


# Exported for testing only
_get_config_for_testing = _get_config
_would_lose_auth_state_for_testing = _would_lose_auth_state


def _set_global_config_cache_for_testing(config: Optional[GlobalConfig]) -> None:
    _global_config_cache["config"] = config
    _global_config_cache["mtime"] = _now_ms() if config else 0
