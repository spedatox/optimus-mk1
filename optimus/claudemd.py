"""
claudemd.py — port of src/utils/claudeMd.ts

Discovers and assembles CLAUDE.md "memory" files into the system-prompt
instruction block. Load order (reverse priority — later = higher priority):

  1. Managed memory   (/etc/claude-code/CLAUDE.md + managed .claude/rules/*.md)
  2. User memory       (~/.claude/CLAUDE.md + ~/.claude/rules/*.md)
  3. Project memory    (CLAUDE.md, .claude/CLAUDE.md, .claude/rules/*.md, root→cwd)
  4. Local memory      (CLAUDE.local.md, root→cwd)

Plus the @include directive (`@path`, `@./rel`, `@~/home`, `@/abs`) which pulls
referenced text files in as separate entries before the including file.

Porting notes:
  - marked Lexer → a focused markdown scanner (_strip_html_comments,
    _extract_include_paths) that tracks fenced code blocks + inline code spans
    so comments/@paths inside code are preserved, matching the marked gfm:false
    behavior the source relies on. Documented in PORTING_NOTES.
  - `ignore` / `picomatch` glob matching → `pathspec` (gitwildmatch).
  - lodash memoize → _AsyncMemo (single-arg cache with .clear()).
  - RE-ENTRY stubs (ported later): settings (claudeMdExcludes / getInitialSettings),
    hooks (InstructionsLoaded), memdir (truncateEntrypointContent / auto-memory),
    growthbook feature values, team memory. is_setting_source_enabled is wired to
    bootstrap state's allowed_setting_sources.
  - logEvent / analytics → dropped.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Any, Awaitable, Callable, Optional

import pathspec

from optimus.bootstrap.state import (
    get_additional_directories_for_claude_md,
    get_original_cwd,
)
from optimus.utils.config import (
    get_current_project_config,
    get_managed_claude_rules_dir,
    get_memory_path,
    get_user_claude_rules_dir,
)
from optimus.utils.debug import log_for_debugging
from optimus.utils.diag_logs import log_for_diagnostics_no_pii
from optimus.env_utils import get_claude_config_home_dir, is_env_truthy
from optimus.utils.errors import get_errno_code
from optimus.utils.file import normalize_path_for_comparison
from optimus.utils.frontmatter_parser import parse_frontmatter, split_path_in_frontmatter
from optimus.utils.git import find_canonical_git_root, find_git_root
from optimus.utils.path import expand_path
from optimus.utils.permissions.filesystem import path_in_working_path

# ---------------------------------------------------------------------------
# RE-ENTRY dependency stubs
# ---------------------------------------------------------------------------


def _is_setting_source_enabled(source: str) -> bool:
    """Wired to bootstrap state's allowed setting sources (settings/constants.ts)."""
    from optimus.bootstrap.state import get_allowed_setting_sources

    return source in get_allowed_setting_sources()


def _get_initial_settings() -> dict[str, Any]:
    """Stub — mirrors getInitialSettings() from settings/settings.ts."""
    # RE-ENTRY: from optimus.utils.settings.settings import get_initial_settings
    return {}


def _truncate_entrypoint_content(content: str) -> dict[str, Any]:
    """Stub — mirrors truncateEntrypointContent() from memdir/memdir.ts."""
    # RE-ENTRY: from optimus.memdir.memdir import truncate_entrypoint_content
    return {"content": content}


def _is_auto_memory_enabled() -> bool:
    """Stub — mirrors isAutoMemoryEnabled() from memdir/paths.ts."""
    # RE-ENTRY: from optimus.memdir.paths import is_auto_memory_enabled
    return False


def _get_auto_mem_entrypoint() -> str:
    """Stub — mirrors getAutoMemEntrypoint() from memdir/paths.ts."""
    # RE-ENTRY: from optimus.memdir.paths import get_auto_mem_entrypoint
    return os.path.join(get_claude_config_home_dir(), "memdir", "MEMORY.md")


def _get_feature_value_cached(_name: str, default: Any) -> Any:
    """Stub — mirrors getFeatureValue_CACHED_MAY_BE_STALE() (growthbook). All off."""
    return default


def _has_instructions_loaded_hook() -> bool:
    """Stub — mirrors hasInstructionsLoadedHook() from hooks.ts."""
    return False


async def _execute_instructions_loaded_hooks(*args: Any, **kwargs: Any) -> None:
    """Stub — mirrors executeInstructionsLoadedHooks() from hooks.ts."""
    return None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_has_logged_initial_load = False

MEMORY_INSTRUCTION_PROMPT = (
    "Codebase and user instructions are shown below. Be sure to adhere to these "
    "instructions. IMPORTANT: These instructions OVERRIDE any default behavior "
    "and you MUST follow them exactly as written."
)
MAX_MEMORY_CHARACTER_COUNT = 40000

TEXT_FILE_EXTENSIONS = {
    ".md", ".txt", ".text",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".csv",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
    ".py", ".pyi", ".pyw",
    ".rb", ".erb", ".rake",
    ".go", ".rs",
    ".java", ".kt", ".kts", ".scala",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".cs", ".swift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".env", ".ini", ".cfg", ".conf", ".config", ".properties",
    ".sql", ".graphql", ".gql", ".proto",
    ".vue", ".svelte", ".astro",
    ".ejs", ".hbs", ".pug", ".jade",
    ".php", ".pl", ".pm", ".lua", ".r", ".R", ".dart",
    ".ex", ".exs", ".erl", ".hrl",
    ".clj", ".cljs", ".cljc", ".edn",
    ".hs", ".lhs", ".elm", ".ml", ".mli",
    ".f", ".f90", ".f95", ".for",
    ".cmake", ".make", ".makefile", ".gradle", ".sbt",
    ".rst", ".adoc", ".asciidoc", ".org", ".tex", ".latex",
    ".lock", ".log", ".diff", ".patch",
}

MAX_INCLUDE_DEPTH = 5

# MemoryFileInfo is a plain dict: {path, type, content, parent?, globs?,
# contentDiffersFromDisk?, rawContent?}
MemoryFileInfo = dict[str, Any]


def _path_in_original_cwd(path: str) -> bool:
    return path_in_working_path(path, get_original_cwd())


# ---------------------------------------------------------------------------
# Markdown scanner (faithful behavioral replacement for marked Lexer gfm:false)
# ---------------------------------------------------------------------------

_COMMENT_SPAN = re.compile(r"<!--[\s\S]*?-->")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def strip_html_comments(content: str) -> dict[str, Any]:
    """
    Strip block-level HTML comments (own-line `<!-- ... -->`), preserving
    comments inside fenced code blocks and inline code spans, and leaving inline
    (mid-paragraph) comments intact. Unclosed comments are left in place.
    Returns {'content', 'stripped'}.
    """
    if "<!--" not in content:
        return {"content": content, "stripped": False}

    lines = content.split("\n")
    out: list[str] = []
    stripped = False
    fence: Optional[str] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        fence_match = _FENCE_RE.match(line)
        if fence is None and fence_match:
            fence = fence_match.group(1)
            out.append(line)
            i += 1
            continue
        if fence is not None:
            out.append(line)
            if line.strip().startswith(fence):
                fence = None
            i += 1
            continue

        if line.lstrip().startswith("<!--"):
            # Block comment — accumulate until a line containing '-->'.
            block = line
            while "-->" not in block and i + 1 < len(lines):
                i += 1
                block += "\n" + lines[i]
            if "-->" in block:
                residue = _COMMENT_SPAN.sub("", block)
                stripped = True
                if residue.strip():
                    out.append(residue)
                i += 1
                continue
            # Unclosed comment — leave the original lines in place.
            out.append(block)
            i += 1
            continue

        out.append(line)
        i += 1

    return {"content": "\n".join(out), "stripped": stripped}


def _remove_code_regions(content: str) -> str:
    """Blank out fenced code blocks and inline code spans so @paths in code are ignored."""
    lines = content.split("\n")
    out: list[str] = []
    fence: Optional[str] = None
    for line in lines:
        fence_match = _FENCE_RE.match(line)
        if fence is None and fence_match:
            fence = fence_match.group(1)
            out.append("")
            continue
        if fence is not None:
            out.append("")
            if line.strip().startswith(fence):
                fence = None
            continue
        out.append(line)
    text = "\n".join(out)
    # Inline code spans (`...`) — blanked to keep offsets simple.
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


_INCLUDE_RE = re.compile(r"(?:^|\s)@((?:[^\s\\]|\\ )+)")


def _extract_include_paths(content: str, base_path: str) -> list[str]:
    """
    Extract @path include references from non-code regions, resolve to absolute
    paths. Comment blocks are stripped first (residue after `-->` is kept).
    """
    scrubbed = strip_html_comments(content)["content"]
    scrubbed = _remove_code_regions(scrubbed)

    absolute_paths: list[str] = []
    seen: set[str] = set()
    for match in _INCLUDE_RE.finditer(scrubbed):
        path = match.group(1)
        if not path:
            continue
        hash_index = path.find("#")
        if hash_index != -1:
            path = path[:hash_index]
        if not path:
            continue
        path = path.replace("\\ ", " ")
        if not path:
            continue
        is_valid = (
            path.startswith("./")
            or path.startswith("~/")
            or (path.startswith("/") and path != "/")
            or (
                not path.startswith("@")
                and not re.match(r"^[#%^&*()]+", path)
                and re.match(r"^[a-zA-Z0-9._-]", path) is not None
            )
        )
        if not is_valid:
            continue
        resolved = expand_path(path, os.path.dirname(base_path))
        if resolved not in seen:
            seen.add(resolved)
            absolute_paths.append(resolved)
    return absolute_paths


# ---------------------------------------------------------------------------
# Frontmatter paths
# ---------------------------------------------------------------------------


def _parse_frontmatter_paths(raw_content: str) -> dict[str, Any]:
    parsed = parse_frontmatter(raw_content)
    frontmatter = parsed["frontmatter"]
    content = parsed["content"]

    if not frontmatter.get("paths"):
        return {"content": content}

    patterns = [
        (p[:-3] if p.endswith("/**") else p)
        for p in split_path_in_frontmatter(frontmatter["paths"])
    ]
    patterns = [p for p in patterns if len(p) > 0]

    if len(patterns) == 0 or all(p == "**" for p in patterns):
        return {"content": content}
    return {"content": content, "paths": patterns}


# ---------------------------------------------------------------------------
# Parse a memory file's content (pure)
# ---------------------------------------------------------------------------


def _parse_memory_file_content(
    raw_content: str,
    file_path: str,
    type_: str,
    include_base_path: Optional[str] = None,
) -> dict[str, Any]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext and ext not in TEXT_FILE_EXTENSIONS:
        log_for_debugging(f"Skipping non-text file in @include: {file_path}")
        return {"info": None, "includePaths": []}

    parsed = _parse_frontmatter_paths(raw_content)
    without_frontmatter = parsed["content"]
    paths = parsed.get("paths")

    has_comment = "<!--" in without_frontmatter
    stripped_content = (
        strip_html_comments(without_frontmatter)["content"]
        if has_comment
        else without_frontmatter
    )

    include_paths = (
        _extract_include_paths(without_frontmatter, include_base_path)
        if include_base_path is not None
        else []
    )

    final_content = stripped_content
    if type_ in ("AutoMem", "TeamMem"):
        final_content = _truncate_entrypoint_content(stripped_content)["content"]

    content_differs_from_disk = final_content != raw_content
    return {
        "info": {
            "path": file_path,
            "type": type_,
            "content": final_content,
            "globs": paths,
            "contentDiffersFromDisk": content_differs_from_disk,
            "rawContent": raw_content if content_differs_from_disk else None,
        },
        "includePaths": include_paths,
    }


def _handle_memory_file_read_error(error: Exception, file_path: str) -> None:
    code = get_errno_code(error)
    if code in ("ENOENT", "EISDIR"):
        return
    # EACCES is actionable; logEvent dropped.


async def _safely_read_memory_file_async(
    file_path: str,
    type_: str,
    include_base_path: Optional[str] = None,
) -> dict[str, Any]:
    try:
        with open(file_path, encoding="utf-8") as f:
            raw_content = f.read()
        return _parse_memory_file_content(raw_content, file_path, type_, include_base_path)
    except OSError as error:
        _handle_memory_file_read_error(error, file_path)
        return {"info": None, "includePaths": []}


# ---------------------------------------------------------------------------
# safeResolvePath (fsOperations) — local faithful helper
# ---------------------------------------------------------------------------


def _safe_resolve_path(file_path: str) -> dict[str, Any]:
    """Resolve symlinks; return {'resolvedPath', 'isSymlink'}."""
    try:
        is_symlink = os.path.islink(file_path)
        resolved = os.path.realpath(file_path)
        return {"resolvedPath": resolved, "isSymlink": is_symlink}
    except OSError:
        return {"resolvedPath": file_path, "isSymlink": False}


# ---------------------------------------------------------------------------
# claudeMdExcludes
# ---------------------------------------------------------------------------


def _resolve_exclude_patterns(patterns: list[str]) -> list[str]:
    expanded = [p.replace("\\", "/") for p in patterns]
    for normalized in list(expanded):
        if not normalized.startswith("/"):
            continue
        glob_start = re.search(r"[*?{\[]", normalized)
        static_prefix = normalized[: glob_start.start()] if glob_start else normalized
        dir_to_resolve = os.path.dirname(static_prefix)
        try:
            resolved_dir = os.path.realpath(dir_to_resolve).replace("\\", "/")
            if resolved_dir != dir_to_resolve:
                expanded.append(resolved_dir + normalized[len(dir_to_resolve) :])
        except OSError:
            pass
    return expanded


def _is_claude_md_excluded(file_path: str, type_: str) -> bool:
    if type_ not in ("User", "Project", "Local"):
        return False
    patterns = _get_initial_settings().get("claudeMdExcludes")
    if not patterns:
        return False
    normalized_path = file_path.replace("\\", "/")
    expanded = [p for p in _resolve_exclude_patterns(patterns) if len(p) > 0]
    if len(expanded) == 0:
        return False
    spec = pathspec.PathSpec.from_lines("gitwildmatch", expanded)
    return spec.match_file(normalized_path)


# ---------------------------------------------------------------------------
# processMemoryFile / processMdRules
# ---------------------------------------------------------------------------


async def process_memory_file(
    file_path: str,
    type_: str,
    processed_paths: set[str],
    include_external: bool,
    depth: int = 0,
    parent: Optional[str] = None,
) -> list[MemoryFileInfo]:
    normalized_path = normalize_path_for_comparison(file_path)
    if normalized_path in processed_paths or depth >= MAX_INCLUDE_DEPTH:
        return []
    if _is_claude_md_excluded(file_path, type_):
        return []

    resolved = _safe_resolve_path(file_path)
    resolved_path = resolved["resolvedPath"]
    is_symlink = resolved["isSymlink"]

    processed_paths.add(normalized_path)
    if is_symlink:
        processed_paths.add(normalize_path_for_comparison(resolved_path))

    read = await _safely_read_memory_file_async(file_path, type_, resolved_path)
    memory_file = read["info"]
    resolved_include_paths = read["includePaths"]
    if not memory_file or not memory_file["content"].strip():
        return []

    if parent:
        memory_file["parent"] = parent

    result: list[MemoryFileInfo] = [memory_file]

    for resolved_include_path in resolved_include_paths:
        is_external = not _path_in_original_cwd(resolved_include_path)
        if is_external and not include_external:
            continue
        included = await process_memory_file(
            resolved_include_path,
            type_,
            processed_paths,
            include_external,
            depth + 1,
            file_path,
        )
        result.extend(included)

    return result


async def process_md_rules(
    *,
    rules_dir: str,
    type_: str,
    processed_paths: set[str],
    include_external: bool,
    conditional_rule: bool,
    visited_dirs: Optional[set[str]] = None,
) -> list[MemoryFileInfo]:
    if visited_dirs is None:
        visited_dirs = set()
    if rules_dir in visited_dirs:
        return []

    try:
        resolved = _safe_resolve_path(rules_dir)
        resolved_rules_dir = resolved["resolvedPath"]
        is_symlink = resolved["isSymlink"]

        visited_dirs.add(rules_dir)
        if is_symlink:
            visited_dirs.add(resolved_rules_dir)

        result: list[MemoryFileInfo] = []
        try:
            entries = list(os.scandir(resolved_rules_dir))
        except OSError as e:
            if get_errno_code(e) in ("ENOENT", "EACCES", "ENOTDIR"):
                return []
            raise

        for entry in entries:
            entry_path = os.path.join(rules_dir, entry.name)
            entry_resolved = _safe_resolve_path(entry_path)
            resolved_entry_path = entry_resolved["resolvedPath"]
            entry_is_symlink = entry_resolved["isSymlink"]

            if entry_is_symlink:
                is_directory = os.path.isdir(resolved_entry_path)
                is_file = os.path.isfile(resolved_entry_path)
            else:
                is_directory = entry.is_dir()
                is_file = entry.is_file()

            if is_directory:
                result.extend(
                    await process_md_rules(
                        rules_dir=resolved_entry_path,
                        type_=type_,
                        processed_paths=processed_paths,
                        include_external=include_external,
                        conditional_rule=conditional_rule,
                        visited_dirs=visited_dirs,
                    )
                )
            elif is_file and entry.name.endswith(".md"):
                files = await process_memory_file(
                    resolved_entry_path, type_, processed_paths, include_external
                )
                result.extend(
                    f for f in files if (f.get("globs") if conditional_rule else not f.get("globs"))
                )

        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Async memoize for get_memory_files
# ---------------------------------------------------------------------------


class _AsyncMemo:
    """Single-argument async memoize with a clearable cache (lodash memoize parity)."""

    def __init__(self, fn: Callable[..., Awaitable[Any]]) -> None:
        self._fn = fn
        self.cache: dict[Any, Any] = {}

    async def __call__(self, arg: Any = False) -> Any:
        if arg in self.cache:
            return self.cache[arg]
        value = await self._fn(arg)
        self.cache[arg] = value
        return value


# ---------------------------------------------------------------------------
# getMemoryFiles — the main discovery entry point
# ---------------------------------------------------------------------------


async def _get_memory_files_impl(force_include_external: bool = False) -> list[MemoryFileInfo]:
    global _has_logged_initial_load
    import time

    start_time = time.time()
    log_for_diagnostics_no_pii("info", "memory_files_started")

    result: list[MemoryFileInfo] = []
    processed_paths: set[str] = set()
    config = get_current_project_config()
    include_external = (
        force_include_external
        or bool(config.get("hasClaudeMdExternalIncludesApproved"))
        or False
    )

    # Managed (always loaded — policy settings).
    result.extend(
        await process_memory_file(
            get_memory_path("Managed"), "Managed", processed_paths, include_external
        )
    )
    result.extend(
        await process_md_rules(
            rules_dir=get_managed_claude_rules_dir(),
            type_="Managed",
            processed_paths=processed_paths,
            include_external=include_external,
            conditional_rule=False,
        )
    )

    # User.
    if _is_setting_source_enabled("userSettings"):
        result.extend(
            await process_memory_file(
                get_memory_path("User"), "User", processed_paths, True
            )
        )
        result.extend(
            await process_md_rules(
                rules_dir=get_user_claude_rules_dir(),
                type_="User",
                processed_paths=processed_paths,
                include_external=True,
                conditional_rule=False,
            )
        )

    # Project + Local: walk root→cwd.
    dirs: list[str] = []
    original_cwd = get_original_cwd()
    current_dir = original_cwd
    while current_dir != os.path.splitdrive(current_dir)[0] + os.sep and os.path.dirname(
        current_dir
    ) != current_dir:
        dirs.append(current_dir)
        current_dir = os.path.dirname(current_dir)

    git_root = find_git_root(original_cwd)
    canonical_root = find_canonical_git_root(original_cwd)
    is_nested_worktree = (
        git_root is not None
        and canonical_root is not None
        and normalize_path_for_comparison(git_root) != normalize_path_for_comparison(canonical_root)
        and path_in_working_path(git_root, canonical_root)
    )

    for dir_ in reversed(dirs):
        skip_project = (
            is_nested_worktree
            and path_in_working_path(dir_, canonical_root)
            and not path_in_working_path(dir_, git_root)
        )

        if _is_setting_source_enabled("projectSettings") and not skip_project:
            result.extend(
                await process_memory_file(
                    os.path.join(dir_, "CLAUDE.md"), "Project", processed_paths, include_external
                )
            )
            result.extend(
                await process_memory_file(
                    os.path.join(dir_, ".claude", "CLAUDE.md"),
                    "Project",
                    processed_paths,
                    include_external,
                )
            )
            result.extend(
                await process_md_rules(
                    rules_dir=os.path.join(dir_, ".claude", "rules"),
                    type_="Project",
                    processed_paths=processed_paths,
                    include_external=include_external,
                    conditional_rule=False,
                )
            )

        if _is_setting_source_enabled("localSettings"):
            result.extend(
                await process_memory_file(
                    os.path.join(dir_, "CLAUDE.local.md"), "Local", processed_paths, include_external
                )
            )

    # --add-dir additional directories (env-gated).
    if is_env_truthy(os.environ.get("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD")):
        for dir_ in get_additional_directories_for_claude_md():
            result.extend(
                await process_memory_file(
                    os.path.join(dir_, "CLAUDE.md"), "Project", processed_paths, include_external
                )
            )
            result.extend(
                await process_memory_file(
                    os.path.join(dir_, ".claude", "CLAUDE.md"),
                    "Project",
                    processed_paths,
                    include_external,
                )
            )
            result.extend(
                await process_md_rules(
                    rules_dir=os.path.join(dir_, ".claude", "rules"),
                    type_="Project",
                    processed_paths=processed_paths,
                    include_external=include_external,
                    conditional_rule=False,
                )
            )

    # Memdir (auto-memory) entrypoint.
    if _is_auto_memory_enabled():
        memdir = await _safely_read_memory_file_async(_get_auto_mem_entrypoint(), "AutoMem")
        memdir_entry = memdir["info"]
        if memdir_entry:
            normalized_path = normalize_path_for_comparison(memdir_entry["path"])
            if normalized_path not in processed_paths:
                processed_paths.add(normalized_path)
                result.append(memdir_entry)

    # feature('TEAMMEM') → False (team memory entrypoint omitted).

    total_content_length = sum(len(f["content"]) for f in result)
    log_for_diagnostics_no_pii(
        "info",
        "memory_files_completed",
        {
            "duration_ms": int((time.time() - start_time) * 1000),
            "file_count": len(result),
            "total_content_length": total_content_length,
        },
    )

    if not _has_logged_initial_load:
        _has_logged_initial_load = True
        # logEvent('tengu_claudemd__initial_load', ...) dropped.

    # InstructionsLoaded hook (fire-and-forget; AutoMem/TeamMem excluded).
    if not force_include_external:
        eager_load_reason = _consume_next_eager_load_reason()
        if eager_load_reason is not None and _has_instructions_loaded_hook():
            for file in result:
                if not _is_instructions_memory_type(file["type"]):
                    continue
                load_reason = "include" if file.get("parent") else eager_load_reason
                await _execute_instructions_loaded_hooks(
                    file["path"],
                    file["type"],
                    load_reason,
                    {"globs": file.get("globs"), "parentFilePath": file.get("parent")},
                )

    return result


get_memory_files = _AsyncMemo(_get_memory_files_impl)


def _is_instructions_memory_type(type_: str) -> bool:
    return type_ in ("User", "Project", "Local", "Managed")


# Instructions-loaded hook one-shot state.
_next_eager_load_reason = "session_start"
_should_fire_hook = True


def _consume_next_eager_load_reason() -> Optional[str]:
    global _should_fire_hook, _next_eager_load_reason
    if not _should_fire_hook:
        return None
    _should_fire_hook = False
    reason = _next_eager_load_reason
    _next_eager_load_reason = "session_start"
    return reason


def clear_memory_file_caches() -> None:
    """Clear the get_memory_files cache without firing the InstructionsLoaded hook."""
    get_memory_files.cache.clear()


def reset_get_memory_files_cache(reason: str = "session_start") -> None:
    global _next_eager_load_reason, _should_fire_hook
    _next_eager_load_reason = reason
    _should_fire_hook = True
    clear_memory_file_caches()


def get_large_memory_files(files: list[MemoryFileInfo]) -> list[MemoryFileInfo]:
    return [f for f in files if len(f["content"]) > MAX_MEMORY_CHARACTER_COUNT]


def filter_injected_memory_files(files: list[MemoryFileInfo]) -> list[MemoryFileInfo]:
    skip_memory_index = _get_feature_value_cached("tengu_moth_copse", False)
    if not skip_memory_index:
        return files
    return [f for f in files if f["type"] not in ("AutoMem", "TeamMem")]


# ---------------------------------------------------------------------------
# getClaudeMds — assemble the system-prompt instruction block
# ---------------------------------------------------------------------------


def get_claude_mds(
    memory_files: list[MemoryFileInfo],
    filter_fn: Optional[Callable[[str], bool]] = None,
) -> str:
    memories: list[str] = []
    skip_project_level = _get_feature_value_cached("tengu_paper_halyard", False)

    for file in memory_files:
        if filter_fn and not filter_fn(file["type"]):
            continue
        if skip_project_level and file["type"] in ("Project", "Local"):
            continue
        if file.get("content"):
            t = file["type"]
            if t == "Project":
                description = " (project instructions, checked into the codebase)"
            elif t == "Local":
                description = " (user's private project instructions, not checked in)"
            elif t == "AutoMem":
                description = " (user's auto-memory, persists across conversations)"
            else:
                description = " (user's private global instructions for all projects)"

            content = file["content"].strip()
            memories.append(f"Contents of {file['path']}{description}:\n\n{content}")

    if len(memories) == 0:
        return ""
    return f"{MEMORY_INSTRUCTION_PROMPT}\n\n" + "\n\n".join(memories)


# ---------------------------------------------------------------------------
# Conditional (path-scoped) rules
# ---------------------------------------------------------------------------


async def get_managed_and_user_conditional_rules(
    target_path: str, processed_paths: set[str]
) -> list[MemoryFileInfo]:
    result: list[MemoryFileInfo] = []
    result.extend(
        await process_conditioned_md_rules(
            target_path, get_managed_claude_rules_dir(), "Managed", processed_paths, False
        )
    )
    if _is_setting_source_enabled("userSettings"):
        result.extend(
            await process_conditioned_md_rules(
                target_path, get_user_claude_rules_dir(), "User", processed_paths, True
            )
        )
    return result


async def get_memory_files_for_nested_directory(
    dir_: str, target_path: str, processed_paths: set[str]
) -> list[MemoryFileInfo]:
    result: list[MemoryFileInfo] = []

    if _is_setting_source_enabled("projectSettings"):
        result.extend(
            await process_memory_file(
                os.path.join(dir_, "CLAUDE.md"), "Project", processed_paths, False
            )
        )
        result.extend(
            await process_memory_file(
                os.path.join(dir_, ".claude", "CLAUDE.md"), "Project", processed_paths, False
            )
        )

    if _is_setting_source_enabled("localSettings"):
        result.extend(
            await process_memory_file(
                os.path.join(dir_, "CLAUDE.local.md"), "Local", processed_paths, False
            )
        )

    rules_dir = os.path.join(dir_, ".claude", "rules")

    unconditional_processed_paths = set(processed_paths)
    result.extend(
        await process_md_rules(
            rules_dir=rules_dir,
            type_="Project",
            processed_paths=unconditional_processed_paths,
            include_external=False,
            conditional_rule=False,
        )
    )

    result.extend(
        await process_conditioned_md_rules(
            target_path, rules_dir, "Project", processed_paths, False
        )
    )

    for path in unconditional_processed_paths:
        processed_paths.add(path)

    return result


async def get_conditional_rules_for_cwd_level_directory(
    dir_: str, target_path: str, processed_paths: set[str]
) -> list[MemoryFileInfo]:
    rules_dir = os.path.join(dir_, ".claude", "rules")
    return await process_conditioned_md_rules(
        target_path, rules_dir, "Project", processed_paths, False
    )


async def process_conditioned_md_rules(
    target_path: str,
    rules_dir: str,
    type_: str,
    processed_paths: set[str],
    include_external: bool,
) -> list[MemoryFileInfo]:
    conditioned = await process_md_rules(
        rules_dir=rules_dir,
        type_=type_,
        processed_paths=processed_paths,
        include_external=include_external,
        conditional_rule=True,
    )

    matched: list[MemoryFileInfo] = []
    for file in conditioned:
        globs = file.get("globs")
        if not globs:
            continue
        base_dir = (
            os.path.dirname(os.path.dirname(rules_dir))  # parent of .claude
            if type_ == "Project"
            else get_original_cwd()
        )
        if os.path.isabs(target_path):
            try:
                relative_path = os.path.relpath(target_path, base_dir)
            except ValueError:
                continue
        else:
            relative_path = target_path
        if (
            not relative_path
            or relative_path.startswith("..")
            or os.path.isabs(relative_path)
        ):
            continue
        spec = pathspec.PathSpec.from_lines("gitwildmatch", globs)
        if spec.match_file(relative_path.replace("\\", "/")):
            matched.append(file)
    return matched


# ---------------------------------------------------------------------------
# External include approval helpers
# ---------------------------------------------------------------------------


def get_external_claude_md_includes(files: list[MemoryFileInfo]) -> list[dict[str, str]]:
    externals: list[dict[str, str]] = []
    for file in files:
        if file["type"] != "User" and file.get("parent") and not _path_in_original_cwd(file["path"]):
            externals.append({"path": file["path"], "parent": file["parent"]})
    return externals


def has_external_claude_md_includes(files: list[MemoryFileInfo]) -> bool:
    return len(get_external_claude_md_includes(files)) > 0


async def should_show_claude_md_external_includes_warning() -> bool:
    config = get_current_project_config()
    if config.get("hasClaudeMdExternalIncludesApproved") or config.get(
        "hasClaudeMdExternalIncludesWarningShown"
    ):
        return False
    return has_external_claude_md_includes(await get_memory_files(True))


# ---------------------------------------------------------------------------
# Memory file path helpers
# ---------------------------------------------------------------------------


def is_memory_file_path(file_path: str) -> bool:
    name = os.path.basename(file_path)
    if name in ("CLAUDE.md", "CLAUDE.local.md"):
        return True
    sep = os.sep
    if name.endswith(".md") and f"{sep}.claude{sep}rules{sep}" in file_path:
        return True
    return False


def get_all_memory_file_paths(
    files: list[MemoryFileInfo], read_file_state: dict[str, Any]
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for file in files:
        if len(file["content"].strip()) > 0 and file["path"] not in seen:
            seen.add(file["path"])
            paths.append(file["path"])
    for file_path in read_file_state.keys():
        if is_memory_file_path(file_path) and file_path not in seen:
            seen.add(file_path)
            paths.append(file_path)
    return paths
