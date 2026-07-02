"""
optimus/env_utils.py — port of src/utils/envUtils.ts

Environment variable helpers, config-dir resolution, and cloud/platform flags.
Analytics-only helpers (isInProtectedNamespace, isRunningOnHomespace) → always False.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_claude_config_home_dir_impl(cache_key: Optional[str]) -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return str(Path(base))


def get_claude_config_home_dir() -> str:
    """
    Port of getClaudeConfigHomeDir() — memoized, keyed on CLAUDE_CONFIG_DIR so
    tests that change the env var get a fresh value.
    """
    return _get_claude_config_home_dir_impl(os.environ.get("CLAUDE_CONFIG_DIR"))


def get_teams_dir() -> str:
    return str(Path(get_claude_config_home_dir()) / "teams")


# ---------------------------------------------------------------------------
# Boolean env-var helpers
# ---------------------------------------------------------------------------

def is_env_truthy(env_var: object) -> bool:
    """Port of isEnvTruthy() — treats '1','true','yes','on' as True."""
    if not env_var:
        return False
    if isinstance(env_var, bool):
        return env_var
    return str(env_var).lower().strip() in ("1", "true", "yes", "on")


def is_env_defined_falsy(env_var: object) -> bool:
    """Port of isEnvDefinedFalsy() — treats '0','false','no','off' as False-when-defined."""
    if env_var is None:
        return False
    if isinstance(env_var, bool):
        return not env_var
    if not env_var:
        return False
    return str(env_var).lower().strip() in ("0", "false", "no", "off")


def is_bare_mode() -> bool:
    """
    Port of isBareMode() — checks CLAUDE_CODE_SIMPLE env var or --bare argv flag.
    Bare mode skips hooks, LSP, plugins, and credential reads.
    """
    return is_env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE")) or "--bare" in sys.argv


def has_node_option(flag: str) -> bool:
    """Port of hasNodeOption() — checks NODE_OPTIONS for an exact flag match."""
    node_options = os.environ.get("NODE_OPTIONS", "")
    if not node_options:
        return False
    return flag in node_options.split()


# ---------------------------------------------------------------------------
# Cloud / platform helpers
# ---------------------------------------------------------------------------

def get_aws_region() -> str:
    """Port of getAWSRegion() — AWS region with Bedrock SDK fallback."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def get_default_vertex_region() -> str:
    """Port of getDefaultVertexRegion()."""
    return os.environ.get("CLOUD_ML_REGION") or "us-east5"


def should_maintain_project_working_dir() -> bool:
    """Port of shouldMaintainProjectWorkingDir()."""
    return is_env_truthy(os.environ.get("CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"))


def is_running_on_homespace() -> bool:
    """Port of isRunningOnHomespace() — always False in open-source build."""
    return False


def is_in_protected_namespace() -> bool:
    """Port of isInProtectedNamespace() — always False (USER_TYPE != 'ant')."""
    return False


# ---------------------------------------------------------------------------
# Vertex region per model
# ---------------------------------------------------------------------------

_VERTEX_REGION_OVERRIDES: list[tuple[str, str]] = [
    ("claude-haiku-4-5", "VERTEX_REGION_CLAUDE_HAIKU_4_5"),
    ("claude-3-5-haiku", "VERTEX_REGION_CLAUDE_3_5_HAIKU"),
    ("claude-3-5-sonnet", "VERTEX_REGION_CLAUDE_3_5_SONNET"),
    ("claude-3-7-sonnet", "VERTEX_REGION_CLAUDE_3_7_SONNET"),
    ("claude-opus-4-1", "VERTEX_REGION_CLAUDE_4_1_OPUS"),
    ("claude-opus-4", "VERTEX_REGION_CLAUDE_4_0_OPUS"),
    ("claude-sonnet-4-6", "VERTEX_REGION_CLAUDE_4_6_SONNET"),
    ("claude-sonnet-4-5", "VERTEX_REGION_CLAUDE_4_5_SONNET"),
    ("claude-sonnet-4", "VERTEX_REGION_CLAUDE_4_0_SONNET"),
]


def get_vertex_region_for_model(model: Optional[str]) -> str:
    """Port of getVertexRegionForModel() — returns region env var or default."""
    if model:
        for prefix, env_var in _VERTEX_REGION_OVERRIDES:
            if model.startswith(prefix):
                return os.environ.get(env_var) or get_default_vertex_region()
    return get_default_vertex_region()


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def parse_env_vars(raw_env_args: Optional[list[str]]) -> dict[str, str]:
    """Port of parseEnvVars() — parses KEY=VALUE strings into a dict."""
    result: dict[str, str] = {}
    if not raw_env_args:
        return result
    for entry in raw_env_args:
        parts = entry.split("=", 1)
        if len(parts) != 2 or not parts[0]:
            raise ValueError(
                f"Invalid environment variable format: {entry}, "
                "environment variables should be added as: -e KEY1=value1 -e KEY2=value2"
            )
        result[parts[0]] = parts[1]
    return result
