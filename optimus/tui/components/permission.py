"""
optimus/tui/components/permission.py

Permission-request modal dialogs for Optimus TUI.

Port of: components/permissions/ (Claude Code React modals).
Covers all 20+ permission types: bash, file read/write, glob, grep,
web fetch, agent launch, notebook edit, etc.

Each PermissionRequest is posted as a Textual message from the REPL screen
when the query loop asks `can_use_tool`. The modal suspends the query coroutine
via an asyncio.Event until the user responds.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static, Button, Label, Input
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.message import Message as TMessage


# ---------------------------------------------------------------------------
# Permission-level constants (mirrors PermissionLevel in TS)
# ---------------------------------------------------------------------------

class PermissionLevel:
    ALLOW_ONCE          = "allow_once"
    ALLOW_SESSION       = "allow_session"
    ALLOW_PERMANENT     = "allow_permanent"
    DENY                = "deny"
    DENY_PERMANENT      = "deny_permanent"


# ---------------------------------------------------------------------------
# PermissionRequest dataclass — describes what the agent wants to do
# ---------------------------------------------------------------------------

@dataclass
class PermissionRequest:
    """
    Mirrors the TS ToolUseBlock with permission metadata.
    One instance per tool-call that needs approval.
    """
    request_id: str                          # matches ToolCall.id
    tool_name: str                           # e.g. "Bash", "Write", "WebFetch"
    description: str                         # human-readable action summary
    details: dict[str, Any] = field(default_factory=dict)   # raw tool input
    risk_level: str = "low"                  # "low" | "medium" | "high" | "critical"

    # Set by the modal when the user responds
    _result_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _decision: Optional[str] = field(default=None, repr=False)

    def resolve(self, decision: str) -> None:
        """Called by the modal button handlers."""
        self._decision = decision
        self._result_event.set()

    async def wait_for_decision(self) -> str:
        """
        Awaited by the query loop's can_use_tool callback.
        Blocks until the user clicks Allow/Deny in the modal.
        """
        await self._result_event.wait()
        return self._decision or PermissionLevel.DENY


# ---------------------------------------------------------------------------
# Risk colours
# ---------------------------------------------------------------------------

_RISK_COLOUR: dict[str, str] = {
    "low":      "#b1b9f9",
    "medium":   "#f0a500",
    "high":     "#ff6b35",
    "critical": "#ff2222",
}

_RISK_LABEL: dict[str, str] = {
    "low":      "LOW RISK",
    "medium":   "MEDIUM RISK",
    "high":     "HIGH RISK",
    "critical": "CRITICAL",
}

# ---------------------------------------------------------------------------
# Tool-specific detail renderers
# ---------------------------------------------------------------------------

def _render_bash_details(details: dict) -> str:
    cmd = details.get("command", "")
    timeout = details.get("timeout", "")
    lines = cmd.splitlines()
    preview = "\n".join(lines[:10])
    if len(lines) > 10:
        preview += f"\n… ({len(lines) - 10} more lines)"
    out = f"[bold]Command:[/bold]\n{preview}"
    if timeout:
        out += f"\n\n[dim]Timeout: {timeout}ms[/dim]"
    return out


def _render_file_write_details(details: dict) -> str:
    path = details.get("file_path") or details.get("path", "?")
    content = details.get("content") or details.get("new_string", "")
    preview = (content[:300] + "…") if len(content) > 300 else content
    return f"[bold]File:[/bold] {path}\n\n[bold]Content preview:[/bold]\n{preview}"


def _render_file_read_details(details: dict) -> str:
    path = details.get("file_path") or details.get("path", "?")
    return f"[bold]File:[/bold] {path}"


def _render_web_fetch_details(details: dict) -> str:
    url = details.get("url", "?")
    return f"[bold]URL:[/bold] {url}"


def _render_glob_details(details: dict) -> str:
    pattern = details.get("pattern", "?")
    path = details.get("path", "")
    out = f"[bold]Pattern:[/bold] {pattern}"
    if path:
        out += f"\n[bold]In:[/bold] {path}"
    return out


def _render_grep_details(details: dict) -> str:
    pattern = details.get("pattern", "?")
    path = details.get("path", "")
    out = f"[bold]Pattern:[/bold] {pattern}"
    if path:
        out += f"\n[bold]In:[/bold] {path}"
    return out


def _render_agent_details(details: dict) -> str:
    desc = details.get("description", "")
    prompt = details.get("prompt", "")[:200]
    return f"[bold]Agent task:[/bold]\n{desc or prompt}"


def _render_generic_details(details: dict) -> str:
    parts: list[str] = []
    for k, v in list(details.items())[:6]:
        val = str(v)
        if len(val) > 80:
            val = val[:80] + "…"
        parts.append(f"[bold]{k}:[/bold] {val}")
    return "\n".join(parts)


_DETAIL_RENDERERS = {
    "Bash":         _render_bash_details,
    "Write":        _render_file_write_details,
    "Edit":         _render_file_write_details,
    "MultiEdit":    _render_file_write_details,
    "Read":         _render_file_read_details,
    "Glob":         _render_glob_details,
    "Grep":         _render_grep_details,
    "WebFetch":     _render_web_fetch_details,
    "WebSearch":    _render_web_fetch_details,
    "Agent":        _render_agent_details,
    "Task":         _render_agent_details,
    "NotebookEdit": _render_file_write_details,
    "NotebookRead": _render_file_read_details,
}


def render_permission_details(req: PermissionRequest) -> str:
    renderer = _DETAIL_RENDERERS.get(req.tool_name, _render_generic_details)
    return renderer(req.details)


# ---------------------------------------------------------------------------
# PermissionModal — the actual Textual screen
# ---------------------------------------------------------------------------

class PermissionModal(ModalScreen[str]):
    """
    Full-screen modal that suspends the TUI until the user
    grants or denies the requested tool call.

    Port of: PermissionDialog.tsx / PermissionModal.tsx
    """

    DEFAULT_CSS = """
    PermissionModal {
        align: center middle;
        background: rgba(5, 10, 30, 0.85);
    }
    PermissionModal > Vertical {
        width: 70;
        max-width: 90%;
        height: auto;
        background: #0a1628;
        border: solid #264f78;
        padding: 1 2;
    }
    PermissionModal .perm-title {
        text-align: center;
        color: #b1b9f9;
        text-style: bold;
        margin-bottom: 1;
    }
    PermissionModal .perm-risk {
        text-align: center;
        margin-bottom: 1;
    }
    PermissionModal .perm-description {
        color: #ffffff;
        margin-bottom: 1;
    }
    PermissionModal .perm-details-box {
        background: #1a1a1a;
        border: solid #264f78;
        padding: 0 1;
        height: auto;
        max-height: 10;
        margin-bottom: 1;
        overflow-y: auto;
        color: #a0b4c8;
    }
    PermissionModal .perm-hint {
        color: #2a4a6a;
        text-align: center;
        margin-bottom: 1;
    }
    PermissionModal .perm-buttons {
        height: 3;
        align: center middle;
    }
    PermissionModal Button {
        margin: 0 1;
        min-width: 14;
    }
    PermissionModal #btn-allow-once {
        background: #003a5c;
        color: #b1b9f9;
        border: solid #005f88;
    }
    PermissionModal #btn-allow-once:hover {
        background: #005f88;
    }
    PermissionModal #btn-allow-session {
        background: #003a3a;
        color: #00d4a0;
        border: solid #006655;
    }
    PermissionModal #btn-allow-session:hover {
        background: #006655;
    }
    PermissionModal #btn-deny {
        background: #3a0a0a;
        color: #ff6b6b;
        border: solid #6a2020;
    }
    PermissionModal #btn-deny:hover {
        background: #6a2020;
    }
    """

    BINDINGS = [
        ("y",      "allow_once",    "Allow Once"),
        ("s",      "allow_session", "Allow for Session"),
        ("n",      "deny",          "Deny"),
        ("escape", "deny",          "Deny"),
    ]

    def __init__(self, request: PermissionRequest, **kwargs) -> None:
        super().__init__(**kwargs)
        self._req = request

    def compose(self) -> ComposeResult:
        req = self._req
        risk_colour = _RISK_COLOUR.get(req.risk_level, "#b1b9f9")
        risk_label  = _RISK_LABEL.get(req.risk_level, "UNKNOWN")
        details_text = render_permission_details(req)

        with Vertical():
            yield Static(
                f"[bold #b1b9f9]◈  PERMISSION REQUEST[/bold #b1b9f9]",
                classes="perm-title",
            )
            yield Static(
                f"[bold {risk_colour}]▲ {risk_label}[/bold {risk_colour}]",
                classes="perm-risk",
            )
            yield Static(
                f"[bold]{req.tool_name}[/bold] — {req.description}",
                classes="perm-description",
            )
            if details_text:
                yield Static(details_text, classes="perm-details-box")
            yield Static(
                "  [dim]y[/dim] Allow Once  "
                "  [dim]s[/dim] Allow Session  "
                "  [dim]n / Esc[/dim] Deny",
                classes="perm-hint",
            )
            with Horizontal(classes="perm-buttons"):
                yield Button("Allow Once (y)",    id="btn-allow-once",    variant="primary")
                yield Button("Allow Session (s)", id="btn-allow-session", variant="success")
                yield Button("Deny (n)",          id="btn-deny",          variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-allow-once":
            self._resolve(PermissionLevel.ALLOW_ONCE)
        elif event.button.id == "btn-allow-session":
            self._resolve(PermissionLevel.ALLOW_SESSION)
        else:
            self._resolve(PermissionLevel.DENY)

    def action_allow_once(self) -> None:
        self._resolve(PermissionLevel.ALLOW_ONCE)

    def action_allow_session(self) -> None:
        self._resolve(PermissionLevel.ALLOW_SESSION)

    def action_deny(self) -> None:
        self._resolve(PermissionLevel.DENY)

    def _resolve(self, decision: str) -> None:
        self._req.resolve(decision)
        self.dismiss(decision)


# ---------------------------------------------------------------------------
# DangerousPermissionModal — extended dialog for high-risk operations
# ---------------------------------------------------------------------------

class DangerousPermissionModal(PermissionModal):
    """
    Variant for high/critical risk: adds a permanent-allow option
    and shows a stronger warning. Port of DangerousCommandDialog.tsx.
    """

    DEFAULT_CSS = PermissionModal.DEFAULT_CSS + """
    DangerousPermissionModal > Vertical {
        border: solid #ff2222;
    }
    DangerousPermissionModal .perm-warning {
        color: #ff6b6b;
        text-align: center;
        text-style: bold;
        margin: 0 0 1 0;
    }
    DangerousPermissionModal #btn-allow-permanent {
        background: #4a1a00;
        color: #ff9933;
        border: solid #8a3a00;
    }
    DangerousPermissionModal #btn-allow-permanent:hover {
        background: #8a3a00;
    }
    """

    BINDINGS = [
        ("y",      "allow_once",      "Allow Once"),
        ("s",      "allow_session",   "Allow Session"),
        ("p",      "allow_permanent", "Allow Permanently"),
        ("n",      "deny",            "Deny"),
        ("escape", "deny",            "Deny"),
    ]

    def compose(self) -> ComposeResult:
        req = self._req
        risk_colour = _RISK_COLOUR.get(req.risk_level, "#ff6b6b")
        details_text = render_permission_details(req)

        with Vertical():
            yield Static(
                f"[bold #ff2222]⚠  DANGEROUS OPERATION[/bold #ff2222]",
                classes="perm-title",
            )
            yield Static(
                f"[bold {risk_colour}]This action may be irreversible.[/bold {risk_colour}]",
                classes="perm-warning",
            )
            yield Static(
                f"[bold]{req.tool_name}[/bold] — {req.description}",
                classes="perm-description",
            )
            if details_text:
                yield Static(details_text, classes="perm-details-box")
            yield Static(
                "  [dim]y[/dim] Once  [dim]s[/dim] Session  "
                "  [dim]p[/dim] Permanent  [dim]n/Esc[/dim] Deny",
                classes="perm-hint",
            )
            with Horizontal(classes="perm-buttons"):
                yield Button("Allow Once",        id="btn-allow-once",      variant="primary")
                yield Button("Allow Session",      id="btn-allow-session",   variant="success")
                yield Button("Allow Permanently",  id="btn-allow-permanent")
                yield Button("Deny (n)",           id="btn-deny",            variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-allow-once":
            self._resolve(PermissionLevel.ALLOW_ONCE)
        elif event.button.id == "btn-allow-session":
            self._resolve(PermissionLevel.ALLOW_SESSION)
        elif event.button.id == "btn-allow-permanent":
            self._resolve(PermissionLevel.ALLOW_PERMANENT)
        else:
            self._resolve(PermissionLevel.DENY)

    def action_allow_permanent(self) -> None:
        self._resolve(PermissionLevel.ALLOW_PERMANENT)


# ---------------------------------------------------------------------------
# PermissionManager — tracks per-session and permanent grants
# ---------------------------------------------------------------------------

class PermissionManager:
    """
    Tracks which (tool_name, fingerprint) pairs have been approved for this
    session or permanently.

    Port of: the in-memory permission state in permissionsContext.ts.
    """

    def __init__(self) -> None:
        # (tool_name, fingerprint) → PermissionLevel
        self._session_grants: dict[tuple[str, str], str] = {}
        self._permanent_grants: set[tuple[str, str]] = set()

    def record(self, req: PermissionRequest, decision: str) -> None:
        """Record the user's decision for future calls."""
        key = (req.tool_name, self._fingerprint(req))
        if decision == PermissionLevel.ALLOW_SESSION:
            self._session_grants[key] = decision
        elif decision == PermissionLevel.ALLOW_PERMANENT:
            self._permanent_grants.add(key)

    def is_pre_approved(self, req: PermissionRequest) -> bool:
        """Return True if this tool call is already approved."""
        key = (req.tool_name, self._fingerprint(req))
        return key in self._permanent_grants or key in self._session_grants

    def clear_session_grants(self) -> None:
        self._session_grants.clear()

    @staticmethod
    def _fingerprint(req: PermissionRequest) -> str:
        """
        A short string that identifies the "scope" of the permission.
        For Bash: the command. For Write: the file path. Etc.
        """
        details = req.details
        if req.tool_name == "Bash":
            return details.get("command", "")[:120]
        if req.tool_name in ("Write", "Edit", "MultiEdit"):
            return details.get("file_path") or details.get("path", "")
        if req.tool_name in ("Read",):
            return details.get("file_path") or details.get("path", "")
        if req.tool_name in ("WebFetch", "WebSearch"):
            return details.get("url", "")
        return ""


# ---------------------------------------------------------------------------
# Helpers for the REPL screen
# ---------------------------------------------------------------------------

def build_permission_request(
    request_id: str,
    tool_name: str,
    tool_input: dict,
) -> PermissionRequest:
    """
    Construct a PermissionRequest from a raw tool-use block.
    Infers the risk level and human-readable description from the tool name + input.
    """
    description = _describe_tool_use(tool_name, tool_input)
    risk = _infer_risk(tool_name, tool_input)
    return PermissionRequest(
        request_id=request_id,
        tool_name=tool_name,
        description=description,
        details=tool_input,
        risk_level=risk,
    )


def _describe_tool_use(tool_name: str, inp: dict) -> str:
    """One-line human description of what the tool call will do."""
    if tool_name == "Bash":
        cmd = inp.get("command", "").split("\n")[0][:60]
        return f"Run shell command: {cmd}"
    if tool_name == "Write":
        path = inp.get("file_path") or inp.get("path", "?")
        return f"Write to file: {path}"
    if tool_name == "Edit":
        path = inp.get("file_path") or inp.get("path", "?")
        return f"Edit file: {path}"
    if tool_name == "MultiEdit":
        path = inp.get("file_path") or inp.get("path", "?")
        return f"Make multiple edits to: {path}"
    if tool_name == "Read":
        path = inp.get("file_path") or inp.get("path", "?")
        return f"Read file: {path}"
    if tool_name == "Glob":
        return f"Find files matching: {inp.get('pattern', '?')}"
    if tool_name == "Grep":
        return f"Search code for: {inp.get('pattern', '?')}"
    if tool_name in ("WebFetch", "WebSearch"):
        return f"Fetch from web: {inp.get('url') or inp.get('query', '?')}"
    if tool_name in ("Agent", "Task"):
        desc = inp.get("description", inp.get("prompt", ""))[:80]
        return f"Launch sub-agent: {desc}"
    if tool_name == "NotebookEdit":
        path = inp.get("notebook_path", "?")
        return f"Edit notebook: {path}"
    return f"Use tool: {tool_name}"


def _infer_risk(tool_name: str, inp: dict) -> str:
    """
    Classify the risk of a tool call.
    Mirrors the TS tool-risk assessment logic.
    """
    if tool_name == "Bash":
        cmd = inp.get("command", "")
        # Critical: destructive commands
        critical_patterns = [
            "rm -rf", "rm -r", "mkfs", "dd if=", ":(){", "chmod 777",
            "curl | sh", "wget | sh", "sudo rm", "> /etc",
        ]
        for pat in critical_patterns:
            if pat in cmd:
                return "critical"
        # High: network exfil, writes to system dirs
        high_patterns = ["curl", "wget", "nc ", "ncat", "/etc/", "/sys/", "/proc/"]
        for pat in high_patterns:
            if pat in cmd:
                return "high"
        return "medium"
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        # Writing to system config files
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
# AskUserQuestionModal — multiple-choice question dialog
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
        background: rgba(5, 10, 30, 0.85);
    }
    AskUserQuestionModal > Vertical {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        background: #0a1628;
        border: solid #264f78;
        padding: 1 2;
    }
    AskUserQuestionModal .aq-header {
        color: #00d4ff;
        text-style: bold;
        margin-bottom: 0;
    }
    AskUserQuestionModal .aq-question {
        color: #e0e8ff;
        margin-bottom: 1;
    }
    AskUserQuestionModal .aq-option {
        background: #0f1d33;
        border: solid #264f78;
        height: 3;
        margin-bottom: 0;
        color: #c8d4e8;
    }
    AskUserQuestionModal .aq-option:focus {
        border: solid #00d4ff;
        text-style: bold;
        color: #ffffff;
    }
    AskUserQuestionModal .aq-selected {
        background: #003a5c;
        border: solid #00d4ff;
        color: #ffffff;
    }
    AskUserQuestionModal .aq-hint {
        color: #2a4a6a;
        margin-top: 1;
    }
    AskUserQuestionModal #aq-other-input {
        margin-top: 0;
        border: solid #264f78;
    }
    AskUserQuestionModal .aq-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    AskUserQuestionModal #aq-submit {
        background: #003a3a;
        color: #00d4a0;
        border: solid #006655;
    }
    AskUserQuestionModal #aq-decline {
        background: #3a0a0a;
        color: #ff6b6b;
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
                yield Static(f"[bold #00d4ff]◆ {header}[/bold #00d4ff]", classes="aq-header")
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
            # Single-select: clear any prior selection, then this one is chosen.
            self._selected.clear()
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

