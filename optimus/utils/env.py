"""
utils/env.py — partial port of src/utils/env.ts

Config/data path resolution. get_global_claude_file mirrors getGlobalClaudeFile:
the path to the user's global config (`~/.claude.json`, with oauth-env suffix),
honoring the legacy `.config.json` and the CLAUDE_CONFIG_DIR override.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from optimus.env_utils import get_claude_config_home_dir, is_env_truthy


def _get_oauth_config_type() -> str:
    """Mirrors getOauthConfigType() from constants/oauth.ts."""
    if os.environ.get("USER_TYPE") == "ant":
        if is_env_truthy(os.environ.get("USE_LOCAL_OAUTH")):
            return "local"
        if is_env_truthy(os.environ.get("USE_STAGING_OAUTH")):
            return "staging"
    return "prod"


def file_suffix_for_oauth_config() -> str:
    """Mirrors fileSuffixForOauthConfig() — suffix injected into the config filename."""
    if os.environ.get("CLAUDE_CODE_CUSTOM_OAUTH_URL"):
        return "-custom-oauth"
    t = _get_oauth_config_type()
    if t == "local":
        return "-local-oauth"
    if t == "staging":
        return "-staging-oauth"
    return ""  # prod — no suffix


@lru_cache(maxsize=1)
def get_global_claude_file() -> str:
    """Mirrors getGlobalClaudeFile() (memoized)."""
    # Legacy fallback for backwards compatibility.
    legacy = os.path.join(get_claude_config_home_dir(), ".config.json")
    if os.path.exists(legacy):
        return legacy

    filename = f".claude{file_suffix_for_oauth_config()}.json"
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home())
    return os.path.join(base, filename)
