"""
optimus/tui/components/permission.py

Port of: components/permissions/PermissionDialog.tsx (shared chrome),
         components/permissions/PermissionRequestTitle.tsx,
         components/permissions/shellPermissionHelpers.tsx (generateShellSuggestionsLabel),
         components/permissions/BashPermissionRequest/bashToolUseOptions.tsx,
         components/permissions/FileEditPermissionRequest, WebFetchPermissionRequest, etc.

Real Claude Code never shows "Allow Once / Allow Session / Allow Permanently /
Deny" buttons. Every permission dialog is an arrow-key Select with exactly two
or three rows:

    Yes
    Yes, and don't ask again for <rule>      (only when a rule can be generated
                                               for this tool — bashToolUseOptions
                                               only adds it when suggestions exist)
    No

Escape / Ctrl+C on the Select resolves to "No" (PermissionRequest onCancel in
BashPermissionRequest.tsx: `onCancel={() => handleReject()}`).

The chrome is PermissionDialog.tsx: a Box with a ROUND border but only the top
edge drawn (borderLeft/Right/Bottom={false}), title bold-colored "permission"
(#b1b9f9) by default, an optional dim subtitle (command/path preview, truncated
from the start), and padded body content.

RE-ENTRY: real "don't ask again" writes a PermissionRule into settings.json
(project or user scope) via utils/permissions/permissionsLoader.ts. Optimus has
no settings persistence yet, so remembered rules live only for the process
lifetime (not cleared by /clear, matching the fact that real permission rules
survive /clear too). Also not ported: the Haiku-generated classifier
descriptions, editable-prefix input mode, and hook/rule "why am I being asked"
explanation banner (PermissionRuleExplanation.tsx) — Optimus's permission
requests are all mode='ask', so there is no persisted-rule/hook reason to show.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Any
from urllib.parse import urlparse

from textual.app import ComposeResult
from textual.widgets import Static, Button, Input
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option


# ---------------------------------------------------------------------------
# Permission-level constants
# ---------------------------------------------------------------------------

class PermissionLevel:
    ALLOW_ONCE      = "allow_once"       # "Yes"
    ALLOW_REMEMBER  = "allow_remember"   # "Yes, and don't ask again for <rule>"
    DENY            = "deny"             # "No" / Escape / Ctrl+C


# ---------------------------------------------------------------------------
# PermissionRequest dataclass — one instance per tool-call needing approval
# ---------------------------------------------------------------------------

@dataclass
class PermissionRequest:
    request_id: str
    tool_name: str
    description: str                                   # PermissionRequestTitle "title"
    details: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"                             # low | medium | high | critical

    # A "don't ask again" rule, if one can be generated for this tool/input.
    rule_label: Optional[str] = None                    # e.g. "git commands in ~/proj"
    rule_key: Optional[str] = None                       # the prefix/dir/domain to match against
    rule_scope: Optional[str] = None                     # the subject checked against rule_key


# ---------------------------------------------------------------------------
# Rule generation — mirrors shellPermissionHelpers.generateShellSuggestionsLabel
# ---------------------------------------------------------------------------

_MULTI_WORD_TOOLS = {
    "npm", "yarn", "pnpm", "bun", "deno",
    "git", "cargo", "go", "docker", "kubectl", "poetry", "pip",
}


def _bash_prefix(command: str) -> Optional[str]:
    """Mirrors getSimpleCommandPrefix (simplified): first token, plus the
    immediate subcommand for well-known multi-word CLIs (git, npm run, ...)."""
    first_line = command.strip().splitlines()[0] if command.strip() else ""
    tokens = first_line.split()
    if not tokens:
        return None
    head = tokens[0].rsplit("/", 1)[-1]
    if head in _MULTI_WORD_TOOLS and len(tokens) > 1:
        return f"{head} {tokens[1]}"
    return head


def _domain_of(url: str) -> Optional[str]:
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None


def _short_cwd() -> str:
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    return cwd


def _build_rule(tool_name: str, details: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (rule_label, rule_key, rule_scope) or (None, None, None) if this
    tool/input doesn't support a "don't ask again" suggestion — matching real
    Claude Code where bashToolUseOptions only adds the option when
    suggestions.length > 0.
    """
    if tool_name == "Bash":
        command = details.get("command", "")
        prefix = _bash_prefix(command)
        if not prefix:
            return None, None, None
        label = f"Yes, and don't ask again for `{prefix}` commands in {_short_cwd()}"
        return label, prefix, command

    if tool_name in ("Read", "Glob", "Grep", "NotebookRead"):
        path = details.get("file_path") or details.get("path", "")
        if not path:
            return None, None, None
        directory = os.path.dirname(path) or path
        dirname = os.path.basename(directory) or directory
        label = f"Yes, and allow reading from {dirname}/ from this project"
        return label, directory, path

    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = details.get("file_path") or details.get("path", "")
        if not path:
            return None, None, None
        directory = os.path.dirname(path) or path
        dirname = os.path.basename(directory) or directory
        label = f"Yes, and always allow access to {dirname}/ from this project"
        return label, directory, path

    if tool_name in ("WebFetch", "WebSearch"):
        url = details.get("url") or details.get("query", "")
        domain = _domain_of(url)
        if not domain:
            return None, None, None
        label = f"Yes, and always allow requests to {domain}"
        return label, domain, url

    # Agent/Task/MCP/other tools: no rule suggestion (matches real behaviour —
    # only Bash/file/web tools produce PermissionUpdate suggestions).
    return None, None, None


def build_permission_request(
    request_id: str,
    tool_name: str,
    tool_input: dict,
) -> PermissionRequest:
    """Construct a PermissionRequest from a raw tool-use block."""
    description = _describe_tool_use(tool_name, tool_input)
    risk = _infer_risk(tool_name, tool_input)
    rule_label, rule_key, rule_scope = _build_rule(tool_name, tool_input)
    return PermissionRequest(
        request_id=request_id,
        tool_name=tool_name,
        description=description,
        details=tool_input,
        risk_level=risk,
        rule_label=rule_label,
        rule_key=rule_key,
        rule_scope=rule_scope,
    )


def _describe_tool_use(tool_name: str, inp: dict) -> str:
    """PermissionRequestTitle's bold title line."""
    if tool_name == "Bash":
        cmd = inp.get("command", "").split("\n")[0][:60]
        return f"Bash command: {cmd}"
    if tool_name == "Write":
        return f"Write file: {inp.get('file_path') or inp.get('path', '?')}"
    if tool_name == "Edit":
        return f"Edit file: {inp.get('file_path') or inp.get('path', '?')}"
    if tool_name == "MultiEdit":
        return f"Edit file: {inp.get('file_path') or inp.get('path', '?')}"
    if tool_name == "Read":
        return f"Read file: {inp.get('file_path') or inp.get('path', '?')}"
    if tool_name == "Glob":
        return f"Find files: {inp.get('pattern', '?')}"
    if tool_name == "Grep":
        return f"Search code: {inp.get('pattern', '?')}"
    if tool_name in ("WebFetch", "WebSearch"):
        return f"Fetch from web: {inp.get('url') or inp.get('query', '?')}"
    if tool_name in ("Agent", "Task"):
        desc = inp.get("description", inp.get("prompt", ""))[:80]
        return f"Launch sub-agent: {desc}"
    if tool_name == "NotebookEdit":
        return f"Edit notebook: {inp.get('notebook_path', '?')}"
    return f"Use tool: {tool_name}"


def _infer_risk(tool_name: str, inp: dict) -> str:
    if tool_name == "Bash":
        cmd = inp.get("command", "")
        critical_patterns = [
            "rm -rf", "rm -r", "mkfs", "dd if=", ":(){", "chmod 777",
            "curl | sh", "wget | sh", "sudo rm", "> /etc",
        ]
        if any(pat in cmd for pat in critical_patterns):
            return "critical"
        high_patterns = ["curl", "wget", "nc ", "ncat", "/etc/", "/sys/", "/proc/"]
        if any(pat in cmd for pat in high_patterns):
            return "high"
        return "medium"
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(inp.get("file_path") or inp.get("path", ""))
        if any(path.startswith(p) for p in ("/etc/", "/sys/", "/boot/")):
            return "high"
        return "low"
    if tool_name in ("WebFetch", "WebSearch"):
        return "medium"
    if tool_name in ("Agent", "Task"):
        return "high"
    return "low"


# ---------------------------------------------------------------------------
# Tool-specific detail renderers (the dim details box under the description)
# ---------------------------------------------------------------------------

def _render_bash_details(details: dict) -> str:
    cmd = details.get("command", "")
    lines = cmd.splitlines()
    preview = "\n".join(lines[:10])
    if len(lines) > 10:
        preview += f"\n… ({len(lines) - 10} more lines)"
    return preview


def _render_edit_details(details: dict) -> str:
    """FileEditPermissionRequest: word-level StructuredDiff of the edit."""
    old = details.get("old_string")
    new = details.get("new_string")
    if old is not None and new is not None:
        from optimus.tui.components.diff import render_edit_diff  # noqa: PLC0415
        rendered = render_edit_diff(old, new, width=68)
        if rendered:
            lines = rendered.splitlines()
            if len(lines) > 12:
                rendered = "\n".join(lines[:12]) + f"\n[#999999]… +{len(lines) - 12} lines[/#999999]"
            return rendered
    content = details.get("new_string", "")
    return (content[:300] + "…") if len(content) > 300 else content


def _render_file_write_details(details: dict) -> str:
    """FileWritePermissionRequest: diff against the existing file when it
    exists, otherwise a plain content preview."""
    path = details.get("file_path") or details.get("path", "")
    content = details.get("content", "")
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                old = fh.read()
            from optimus.tui.components.diff import render_edit_diff  # noqa: PLC0415
            rendered = render_edit_diff(old, content, width=68)
            if rendered:
                lines = rendered.splitlines()
                if len(lines) > 12:
                    rendered = "\n".join(lines[:12]) + f"\n[#999999]… +{len(lines) - 12} lines[/#999999]"
                return rendered
        except OSError:
            pass
    return (content[:300] + "…") if len(content) > 300 else content


def _render_generic_details(details: dict) -> str:
    parts: list[str] = []
    for k, v in list(details.items())[:6]:
        if k in ("file_path", "path", "command", "pattern", "url", "query"):
            continue
        val = str(v)
        if len(val) > 80:
            val = val[:80] + "…"
        parts.append(f"[bold]{k}:[/bold] {val}")
    return "\n".join(parts)


_DETAIL_RENDERERS = {
    "Bash":         _render_bash_details,
    "Write":        _render_file_write_details,
    "Edit":         _render_edit_details,
    "MultiEdit":    _render_edit_details,
    "NotebookEdit": _render_edit_details,
}


def render_permission_details(req: PermissionRequest) -> str:
    renderer = _DETAIL_RENDERERS.get(req.tool_name, _render_generic_details)
    return renderer(req.details)


_RISK_COLOUR: dict[str, str] = {
    "low":      "#b1b9f9",   # theme.permission
    "medium":   "#b1b9f9",
    "high":     "#ffc107",   # theme.warning
    "critical": "#ff6b80",   # theme.error
}


# ---------------------------------------------------------------------------
# PermissionModal — port of PermissionDialog.tsx chrome + the Select options
# ---------------------------------------------------------------------------

class PermissionModal(ModalScreen[str]):
    """
    Suspends the TUI until the user picks Yes / Yes-remember / No.

    Layout mirrors PermissionDialog.tsx: a box with only a top border (colored
    by risk), a bold title + dim subtitle, and a body — here the body is the
    details box followed by an OptionList (the CustomSelect port).
    """

    DEFAULT_CSS = """
    PermissionModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    PermissionModal > Vertical {
        width: 74;
        max-width: 92%;
        height: auto;
        max-height: 30;
        background: #1a1a1a;
        padding: 1 2;
    }
    PermissionModal .perm-title {
        text-style: bold;
        margin-bottom: 0;
    }
    PermissionModal .perm-subtitle {
        color: #999999;
        margin-bottom: 1;
    }
    PermissionModal .perm-details-box {
        background: #262626;
        padding: 0 1;
        height: auto;
        max-height: 10;
        margin-bottom: 1;
        overflow-y: auto;
        color: #999999;
    }
    PermissionModal OptionList {
        height: auto;
        max-height: 6;
        background: #1a1a1a;
        border: none;
    }
    """

    BINDINGS = [
        ("escape", "deny", "No"),
    ]

    def __init__(self, request: PermissionRequest, **kwargs) -> None:
        super().__init__(**kwargs)
        self._req = request
        self._option_values: list[str] = []

    def compose(self) -> ComposeResult:
        req = self._req
        colour = _RISK_COLOUR.get(req.risk_level, "#b1b9f9")
        details_text = render_permission_details(req)

        with Vertical():
            yield Static(
                f"[bold {colour}]▔▔▔ PERMISSION[/bold {colour}]",
                classes="perm-title",
            )
            yield Static(
                f"[bold {colour}]{req.description}[/bold {colour}]",
                classes="perm-subtitle",
            )
            if details_text:
                yield Static(details_text, classes="perm-details-box")

            options: list[Option] = [Option("Yes", id="allow_once")]
            self._option_values = ["allow_once"]
            if req.rule_label:
                options.append(Option(req.rule_label, id="allow_remember"))
                self._option_values.append("allow_remember")
            options.append(Option("No", id="deny"))
            self._option_values.append("deny")

            yield OptionList(*options, id="perm-options")

    def on_mount(self) -> None:
        self.query_one("#perm-options", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._resolve(event.option.id or PermissionLevel.DENY)

    def action_deny(self) -> None:
        self._resolve(PermissionLevel.DENY)

    def _resolve(self, decision: str) -> None:
        self.dismiss(decision)


# ---------------------------------------------------------------------------
# PermissionManager — tracks remembered ("don't ask again") rules
# ---------------------------------------------------------------------------

class PermissionManager:
    """
    Prefix/dir/domain rule matching, mirroring utils/permissions/permissionsLoader.ts
    at the in-memory level: a remembered rule for Bash prefix "git" matches any
    future command starting with "git", not just the exact original command.

    Not cleared by /clear — real permission rules survive /clear too.
    """

    def __init__(self) -> None:
        self._remembered: dict[str, set[str]] = {}   # tool_name -> {rule_key, ...}

    def record(self, req: PermissionRequest, decision: str) -> None:
        if decision == PermissionLevel.ALLOW_REMEMBER and req.rule_key:
            self._remembered.setdefault(req.tool_name, set()).add(req.rule_key)

    def is_pre_approved(self, req: PermissionRequest) -> bool:
        keys = self._remembered.get(req.tool_name)
        if not keys or req.rule_scope is None:
            return False
        return any(req.rule_scope.startswith(key) for key in keys)

    def remembered_rules(self) -> list[tuple[str, str]]:
        return [
            (tool, key)
            for tool, keys in self._remembered.items()
            for key in keys
        ]


# ---------------------------------------------------------------------------
# AskUserQuestionModal — multiple-choice question dialog (unrelated to the
# Yes/No permission flow above; unchanged by this port pass).
# ---------------------------------------------------------------------------

class AskUserQuestionModal(ModalScreen[Optional[str]]):
    """
    Modal that asks the user a single multiple-choice question.

    Pushed once per question by the REPL's ask_user_questions callback. Returns
    the selected answer as a string (multi-select answers are comma-joined), or
    None when the user declines (Enter/Esc with nothing chosen).

    Port of: components/permissions/AskUserQuestionFrame.tsx (functional subset).
    RE-ENTRY: option `preview` rendering, per-question `annotations` (notes),
    and the side-by-side preview layout are not yet ported.
    """

    DEFAULT_CSS = """
    AskUserQuestionModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    AskUserQuestionModal > Vertical {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        background: #1a1a1a;
        border: solid #b1b9f9;
        padding: 1 2;
    }
    AskUserQuestionModal .aq-header {
        color: #b1b9f9;
        text-style: bold;
        margin-bottom: 0;
    }
    AskUserQuestionModal .aq-question {
        color: #ffffff;
        margin-bottom: 1;
    }
    AskUserQuestionModal .aq-option {
        background: #262626;
        border: solid #505050;
        height: 3;
        margin-bottom: 0;
        color: #cccccc;
    }
    AskUserQuestionModal .aq-option:focus {
        border: solid #b1b9f9;
        text-style: bold;
        color: #ffffff;
    }
    AskUserQuestionModal .aq-selected {
        background: #2c323e;
        border: solid #b1b9f9;
        color: #ffffff;
    }
    AskUserQuestionModal .aq-hint {
        color: #505050;
        margin-top: 1;
    }
    AskUserQuestionModal #aq-other-input {
        margin-top: 0;
        border: solid #505050;
    }
    AskUserQuestionModal .aq-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    AskUserQuestionModal #aq-submit {
        background: #1a3a30;
        color: #4eba65;
        border: solid #2a5a45;
    }
    AskUserQuestionModal #aq-decline {
        background: #2a0a0e;
        color: #ff6b80;
        border: solid #6a2020;
    }
    """

    BINDINGS = [
        ("escape", "decline", "Decline"),
    ]

    def __init__(self, question: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self._question = question
        self._multi = bool(question.get("multiSelect"))
        self._options: list[dict] = question.get("options", []) or []
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        header = self._question.get("header", "")
        with Vertical():
            if header:
                yield Static(f"[bold #b1b9f9]◆ {header}[/bold #b1b9f9]", classes="aq-header")
            yield Static(self._question.get("question", ""), classes="aq-question")
            for i, opt in enumerate(self._options):
                label = opt.get("label", "")
                desc = opt.get("description", "")
                text = f"{i + 1}. {label}"
                if desc:
                    text += f"  — {desc}"
                yield Button(text, id=f"aq-opt-{i}", classes="aq-option")
            yield Input(id="aq-other-input", placeholder="Other (type here, then press Enter)")
            hint = "Toggle options, type Other, then Submit" if self._multi else "Click an option, or type Other + Enter"
            yield Static(f"  [dim]{hint}  ·  Esc to decline[/dim]", classes="aq-hint")
            with Horizontal(classes="aq-buttons"):
                if self._multi:
                    yield Button("Submit", id="aq-submit")
                yield Button("Decline", id="aq-decline", variant="error")

    def _option_index(self, button_id: str) -> Optional[int]:
        try:
            return int(button_id.replace("aq-opt-", ""))
        except (ValueError, AttributeError):
            return None

    def _toggle(self, idx: int) -> None:
        if not self._multi:
            self._selected.clear()
            self._selected.add(idx)
            self._submit()
            return
        if idx in self._selected:
            self._selected.discard(idx)
        else:
            self._selected.add(idx)
        for i in range(len(self._options)):
            btn = self.query_one(f"#aq-opt-{i}", Button)
            if i in self._selected:
                btn.add_class("aq-selected")
            else:
                btn.remove_class("aq-selected")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid == "aq-decline":
            self.dismiss(None)
            return
        if bid == "aq-submit":
            self._submit()
            return
        idx = self._option_index(bid)
        if idx is not None:
            self._toggle(idx)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "aq-other-input":
            return
        text = (event.value or "").strip()
        if not text:
            return
        self.dismiss(text)

    def _submit(self) -> None:
        if not self._selected:
            self.dismiss(None)
            return
        labels = [self._options[i].get("label", "") for i in sorted(self._selected)]
        self.dismiss(",".join(labels))

    def action_decline(self) -> None:
        self.dismiss(None)
