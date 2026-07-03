"""
commands/__init__.py — slash-command (skill) discovery and lookup.

Replaces the legacy commands module removed in the restructure. Loads markdown
commands the way Claude Code does for custom commands:

    <project>/.claude/commands/**/*.md     (scope: project)
    ~/.claude/commands/**/*.md             (scope: user)

Each file's YAML frontmatter may set `name` and `description`; otherwise the
file stem is the command name (subdirectories become namespaced names, e.g.
`frontend/deploy.md` → "frontend:deploy"). The markdown body is the prompt
template; `$ARGUMENTS` (and the legacy `$ARGS`) are substituted at invocation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from optimus.env_utils import get_claude_config_home_dir
from optimus.utils.cwd import get_cwd
from optimus.utils.frontmatter_parser import parse_frontmatter


@dataclass
class Command:
    name: str
    description: str
    prompt_template: str
    scope: str  # 'project' | 'user'
    path: str
    aliases: list[str] = field(default_factory=list)


def _command_dirs() -> list[tuple[str, Path]]:
    dirs: list[tuple[str, Path]] = []
    try:
        dirs.append(("project", Path(get_cwd()) / ".claude" / "commands"))
    except Exception:
        pass
    dirs.append(("user", Path(get_claude_config_home_dir()) / "commands"))
    return dirs


def _load_command(scope: str, root: Path, file: Path) -> Command | None:
    try:
        # utf-8-sig: strip the BOM that Windows editors (Notepad) prepend —
        # a leading ﻿ breaks YAML frontmatter detection.
        parsed = parse_frontmatter(file.read_text(encoding="utf-8-sig"), str(file))
    except OSError:
        return None
    fm = parsed.get("frontmatter") or {}
    body = (parsed.get("content") or "").strip()
    if not body:
        return None
    rel = file.relative_to(root).with_suffix("")
    default_name = ":".join(rel.parts)
    return Command(
        name=str(fm.get("name") or default_name),
        description=str(fm.get("description") or f"Custom command from {file.name}"),
        prompt_template=body,
        scope=scope,
        path=str(file),
    )


def get_commands() -> list[Command]:
    """All discovered commands. Project-scope wins on name collision."""
    commands: dict[str, Command] = {}
    for scope, root in _command_dirs():
        if not root.is_dir():
            continue
        for file in sorted(root.rglob("*.md")):
            cmd = _load_command(scope, root, file)
            if cmd and cmd.name not in commands:
                commands[cmd.name] = cmd
    return list(commands.values())


def find_command(name: str, commands: list[Command] | None = None) -> Command | None:
    name = name.lstrip("/")
    for cmd in commands if commands is not None else get_commands():
        if cmd.name == name or name in cmd.aliases:
            return cmd
    return None


def expand_command(command: Command, args: str) -> str:
    """Substitute arguments into the prompt template."""
    prompt = command.prompt_template
    if "$ARGUMENTS" in prompt or "$ARGS" in prompt:
        return prompt.replace("$ARGUMENTS", args).replace("$ARGS", args)
    if args:
        return f"{prompt}\n\n{args}"
    return prompt
