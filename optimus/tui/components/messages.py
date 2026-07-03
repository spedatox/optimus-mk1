"""
optimus/tui/components/messages.py

Message list and individual message widgets.
Port of:  components/messages/UserPromptMessage.tsx
          components/messages/AssistantTextMessage.tsx
          components/VirtualMessageList.tsx

Claude Code UI replicated AS IS (dark theme):
  - User messages:
      • backgroundColor = userMessageBackground = rgb(55,55,55) = #373737
      • paddingRight = 1
      • NO label — just the raw text (HighlightedThinkingText renders text only)
  - Assistant messages:
      • NO label
      • ● BLACK_CIRCLE dot (NoSelect, fromLeftEdge, minWidth=2) + Markdown
      • No background (transparent)
  - Truncation: MAX_DISPLAY_CHARS=10_000, head 2_500 + tail 2_500
  - Tool panels: bashMessageBackgroundColor rgb(65,60,65) = #413c41
  - No "You" or "Claude" labels anywhere (Claude Code has none)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from optimus.tui.brand import ACCENT

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static
from textual.containers import VerticalScroll, Vertical, Horizontal
from textual.reactive import reactive


# ---------------------------------------------------------------------------
# Claude Code constants — mirrored from constants/figures.ts + UserPromptMessage.tsx
# ---------------------------------------------------------------------------

BLACK_CIRCLE = "●"     # ● — used as the assistant dot indicator (NoSelect, minWidth=2)
MAX_DISPLAY_CHARS  = 10_000      # hard cap on displayed prompt text
TRUNCATE_HEAD_CHARS = 2_500      # chars to show from the head
TRUNCATE_TAIL_CHARS = 2_500      # chars to show from the tail

# Spinner glyph frames from Spinner/utils.ts getDefaultCharacters(), played
# forward then reversed (Spinner.tsx SPINNER_FRAMES). NOT braille — Claude
# Code has never used braille frames.
from optimus.tui.components.spinner import SPINNER_FRAMES, FRAME_MS


# ---------------------------------------------------------------------------
# Spinner — animated single-cell glyph (SpinnerGlyph.tsx subset, used by
# ToolPanel headers). The full verb/status line is SpinnerLine in spinner.py.
# ---------------------------------------------------------------------------

class Spinner(Static):
    """A tiny animated spinner. Cycles SPINNER_FRAMES every 120 ms until stopped."""

    DEFAULT_CSS = """
    Spinner {
        width: 1;
        min-width: 1;
        height: 1;
        padding: 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._frame = 0
        self._timer = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(FRAME_MS / 1000, self._tick)
        self._tick()

    def _tick(self) -> None:
        ch = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        self.update(f"[bold {ACCENT}]{ch}[/bold {ACCENT}]")
        self._frame += 1

    def stop(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    def on_unmount(self) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Assistant special-text handling — port of AssistantTextMessage.tsx's
# switch(text). Each API-layer sentinel string maps to a dedicated rendering
# (or to None → render nothing). Constants mirror services/api/errors.ts,
# utils/messages.ts, services/compact/compact.ts so the display layer lines
# up when those modules are ported.
# ---------------------------------------------------------------------------

API_ERROR_MESSAGE_PREFIX = "API Error"
PROMPT_TOO_LONG_ERROR_MESSAGE = "Prompt is too long"
CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE = "Credit balance is too low"
INVALID_API_KEY_ERROR_MESSAGE = "Not logged in · Please run /login"
INVALID_API_KEY_ERROR_MESSAGE_EXTERNAL = "Invalid API key · Fix external API key"
API_TIMEOUT_ERROR_MESSAGE = "Request timed out"
NO_RESPONSE_REQUESTED = "No response requested."
ERROR_MESSAGE_USER_ABORT = "API Error: Request was aborted."
INTERRUPT_MESSAGE = "[Request interrupted by user]"

MAX_API_ERROR_CHARS = 1000     # AssistantTextMessage.tsx

_ERROR_COLOUR = "#ff6b80"      # theme.error


def render_special_assistant_text(text: str, verbose: bool = False) -> Optional[str]:
    """
    Returns Rich markup for API-layer sentinel strings, "" for
    render-nothing sentinels, or None when the text is a normal response
    (caller renders Markdown as usual).
    """
    stripped = text.strip()
    if stripped == NO_RESPONSE_REQUESTED:
        return ""
    if stripped in (ERROR_MESSAGE_USER_ABORT, INTERRUPT_MESSAGE):
        # InterruptedByUser.tsx (external branch)
        return "[#999999]Interrupted · What should Optimus do instead?[/#999999]"
    if stripped == PROMPT_TOO_LONG_ERROR_MESSAGE:
        return (f"[{_ERROR_COLOUR}]Context limit reached · "
                f"/compact or /clear to continue[/{_ERROR_COLOUR}]")
    if stripped == CREDIT_BALANCE_TOO_LOW_ERROR_MESSAGE:
        return (f"[{_ERROR_COLOUR}]Credit balance too low · Add funds: "
                f"https://platform.claude.com/settings/billing[/{_ERROR_COLOUR}]")
    if stripped in (INVALID_API_KEY_ERROR_MESSAGE, INVALID_API_KEY_ERROR_MESSAGE_EXTERNAL):
        return (f"[{_ERROR_COLOUR}]Invalid or missing API key · "
                f"Set ANTHROPIC_API_KEY[/{_ERROR_COLOUR}]")
    if stripped.startswith(API_TIMEOUT_ERROR_MESSAGE):
        hint = ""
        timeout_env = os.environ.get("API_TIMEOUT_MS")
        if timeout_env:
            hint = f" (API_TIMEOUT_MS={timeout_env}ms, try increasing it)"
        return f"[{_ERROR_COLOUR}]{API_TIMEOUT_ERROR_MESSAGE}{hint}[/{_ERROR_COLOUR}]"
    if stripped.startswith(API_ERROR_MESSAGE_PREFIX):
        if stripped == API_ERROR_MESSAGE_PREFIX:
            body = f"{API_ERROR_MESSAGE_PREFIX}: Please wait a moment and try again."
        elif not verbose and len(stripped) > MAX_API_ERROR_CHARS:
            body = stripped[:MAX_API_ERROR_CHARS] + "…"
        else:
            body = stripped
        return f"[{_ERROR_COLOUR}]{body}[/{_ERROR_COLOUR}]"
    return None


def extract_tag(text: str, tag: str) -> Optional[str]:
    """utils/messages.ts extractTag — pull <tag>…</tag> content from text."""
    import re as _re
    m = _re.search(rf"<{tag}>(.*?)</{tag}>", text, _re.DOTALL)
    return m.group(1) if m else None


def _truncate_user_text(text: str) -> str:
    """
    Replicates UserPromptMessage's head+tail truncation.
    Head+tail because `{ cat file; echo prompt; } | claude` puts the
    user's actual question at the end.
    """
    if len(text) <= MAX_DISPLAY_CHARS:
        return text
    head = text[:TRUNCATE_HEAD_CHARS]
    tail = text[-TRUNCATE_TAIL_CHARS:]
    hidden_lines = (
        text[:TRUNCATE_HEAD_CHARS].count("\n")
        - tail.count("\n")
    )
    return f"{head}\n… +{hidden_lines} lines …\n{tail}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    result: Optional[str] = None
    is_error: bool = False
    is_running: bool = True


@dataclass
class MessageData:
    role: str                          # 'user' | 'assistant' | 'system' | 'error'
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: str = ""
    is_streaming: bool = False


# ---------------------------------------------------------------------------
# ToolPanel — tool call display
# Port of: ToolUseMessage / tool renderToolUseMessage rows.
#
# Claude Code renders tool calls flat on the terminal background:
#
#   ● Write(index.html)
#     ⎿  File created successfully at: …
#
# No background block, no border. Dot is green on success, red on error,
# the spinner glyph while running. Name is bold default-text with the args
# summary in parens (not a coloured chip).
# ---------------------------------------------------------------------------

class ToolPanel(Widget):
    """Displays a single tool call and its result. Click to toggle."""

    DEFAULT_CSS = """
    ToolPanel {
        height: auto;
        margin: 0;
        padding: 0;
    }
    ToolPanel .tp-header {
        height: auto;
        min-height: 1;
    }
    ToolPanel .tp-spinner-slot {
        width: 2;
        content-align: left middle;
        padding: 0;
    }
    ToolPanel .tp-status-icon {
        width: 2;
        content-align: left middle;
        padding: 0;
    }
    ToolPanel .tp-title {
        width: 1fr;
        content-align: left middle;
    }
    ToolPanel .tp-result {
        height: auto;
        margin: 0 0 0 2;
        padding: 0 0;
        color: #999999;
    }
    ToolPanel .tp-result.tool-result-error {
        color: #ff6b80;
    }
    """

    expanded: reactive[bool] = reactive(True)

    def __init__(self, tool_call: ToolCall, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool = tool_call
        self._spinner: Optional[Spinner] = None
        # ctrl+o (CtrlOToExpand): show the full result instead of the
        # truncated preview.
        self._verbose = False

    def compose(self) -> ComposeResult:
        tool = self._tool
        args_summary = self._summarise_args(tool.input, tool.name)

        # ── Header row: ● Name(args) ────────────────────────────────────
        with Horizontal(classes="tp-header"):
            if tool.is_running:
                # Animated Spinner — mounts, starts ticking, stops on unmount
                yield Spinner(classes="tp-spinner-slot")
            elif tool.is_error:
                yield Static(
                    "[#ff6b80]●[/#ff6b80]",
                    classes="tp-status-icon",
                )
            else:
                yield Static(
                    "[#4eba65]●[/#4eba65]",
                    classes="tp-status-icon",
                )

            title = f"[bold]{tool.name}[/bold]"
            if args_summary:
                title += f"([#999999]{args_summary[:80]}[/#999999])"
            yield Static(title, classes="tp-title")

        # ── Edit/Write results: diff summary + StructuredDiff ───────────
        # (FileEditToolResultMessage: "Updated <file> with N additions and
        #  M removals" followed by the word-level diff.)
        if (self.expanded and tool.result is not None and not tool.is_error
                and tool.name in ("Edit", "FileEdit", "MultiEdit")
                and isinstance(tool.input.get("old_string"), str)
                and isinstance(tool.input.get("new_string"), str)):
            summary, diff_markup = self._render_edit_result()
            yield Static(
                f"[dim #777777]⎿[/dim #777777] [#999999]{summary}[/#999999]",
                classes="tp-result",
            )
            if diff_markup:
                yield Static(diff_markup, classes="tp-result")
            return

        if (self.expanded and tool.result is not None and not tool.is_error
                and tool.name in ("Write", "FileWrite")
                and isinstance(tool.input.get("content"), str)):
            path = self._summarise_args(tool.input, tool.name) or "file"
            n_lines = tool.input["content"].count("\n") + 1
            yield Static(
                f"[dim #777777]⎿[/dim #777777] [#999999]Wrote {n_lines} "
                f"lines to {path}[/#999999]",
                classes="tp-result",
            )
            return

        # ── Result row (⎿ prefix — Claude Code style) ──────────────────
        if self.expanded and tool.result is not None:
            if self._verbose:
                result_text = tool.result
            else:
                result_text = tool.result[:2000]
                if len(tool.result) > 2000:
                    result_text += (
                        f"\n… ({len(tool.result) - 2000} chars truncated"
                        f" · ctrl+o to expand)"
                    )
            # Claude Code shows tool results with a ⎿ prefix
            cls = "tool-result-error" if tool.is_error else "tool-result-success"
            yield Static(
                f"[dim #777777]⎿[/dim #777777] {result_text}",
                classes=f"tp-result {cls}",
            )

    def on_click(self) -> None:
        self.expanded = not self.expanded
        self.refresh(recompose=True)

    def update_result(self, result: str, is_error: bool = False) -> None:
        self._tool.result = result
        self._tool.is_error = is_error
        self._tool.is_running = False
        self.refresh(recompose=True)

    def mark_running(self, running: bool = True) -> None:
        self._tool.is_running = running
        self.refresh(recompose=True)

    def set_verbose(self, verbose: bool) -> None:
        if self._verbose != verbose:
            self._verbose = verbose
            self.refresh(recompose=True)

    def _render_edit_result(self) -> tuple[str, str]:
        """FileEditToolResultMessage: '(Updated <file> with N additions and
        M removals', word-level diff markup). Diff capped at 12 rows unless
        ctrl+o verbose."""
        from optimus.tui.components.diff import build_patch_lines, format_structured_diff  # noqa: PLC0415
        old = self._tool.input["old_string"]
        new = self._tool.input["new_string"]
        path = self._summarise_args(self._tool.input, self._tool.name) or "file"
        patch_lines, old_start = build_patch_lines(old, new)
        additions = sum(1 for l in patch_lines if l.startswith("+"))
        removals = sum(1 for l in patch_lines if l.startswith("-"))

        def plural(n: int, word: str) -> str:
            return f"{n} {word}{'' if n == 1 else 's'}"

        summary = (f"Updated {path} with {plural(additions, 'addition')} "
                   f"and {plural(removals, 'removal')}")
        rows = format_structured_diff(patch_lines, old_start, width=68)
        if not self._verbose and len(rows) > 12:
            rows = rows[:12] + [f"[#999999]… +{len(rows) - 12} lines (ctrl+o to expand)[/#999999]"]
        return summary, "\n".join(rows)

    # Primary display argument per tool — renderToolUseMessage shows just
    # the meaningful value: Write(index.html), Bash(ls -la), Grep(pattern).
    _PRIMARY_ARG = {
        "Bash": "command", "PowerShell": "command",
        "Read": "file_path", "FileRead": "file_path",
        "Write": "file_path", "FileWrite": "file_path",
        "Edit": "file_path", "FileEdit": "file_path",
        "MultiEdit": "file_path", "NotebookEdit": "notebook_path",
        "Glob": "pattern", "Grep": "pattern",
        "WebFetch": "url", "WebSearch": "query",
        "Agent": "description", "Skill": "skill",
    }

    @classmethod
    def _summarise_args(cls, input_dict: dict, tool_name: str = "") -> str:
        """renderToolUseMessage-style one-line arg display: the primary
        argument's bare value; file paths shortened relative to cwd."""
        if not input_dict:
            return ""
        key = cls._PRIMARY_ARG.get(tool_name)
        val = input_dict.get(key) if key else None
        if val is None:
            # Fall back to the first string value
            for v in input_dict.values():
                if isinstance(v, str) and v:
                    val = v
                    break
        if not isinstance(val, str):
            return ""
        # Relativise absolute paths against cwd (renderToolUseMessage shows
        # relative paths in the transcript)
        if key and "path" in key:
            try:
                cwd = os.getcwd()
                if val.lower().startswith(cwd.lower()):
                    val = val[len(cwd):].lstrip("\\/")
            except Exception:
                pass
        val = val.replace("\n", " ")
        return val if len(val) <= 80 else val[:77] + "…"


# ---------------------------------------------------------------------------
# MessageWidget — renders a single user or assistant message
# Port of: UserPromptMessage.tsx + AssistantTextMessage.tsx
#
# USER:
#   <Box flexDirection="column" backgroundColor="userMessageBackground" paddingRight={1}>
#     <HighlightedThinkingText text={displayText} />   ← just renders the text
#   </Box>
#   No label. No "You". Just text on #373737 background.
#
# ASSISTANT:
#   <Box flexDirection="row">
#     <NoSelect fromLeftEdge minWidth={2}>
#       <Text color="text">{BLACK_CIRCLE}</Text>
#     </NoSelect>
#     <Box flexDirection="column">
#       <Markdown>{text}</Markdown>
#     </Box>
#   </Box>
#   No label. No "Claude". Just ● (2-col) + Markdown.
# ---------------------------------------------------------------------------

class MessageWidget(Widget):
    """A single chat message (user, assistant, system, or error).

    Streaming strategy (avoids per-token Markdown re-parse):
      - While waiting for first token: "Thinking…" Spinner row.
      - First token arrives → recompose to swap spinner for a plain Static.
      - Subsequent tokens → update the Static's text in-place (no recompose).
      - finish_streaming() → recompose one final time: Static → Markdown.
    """

    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        margin: 1 0 0 0;
    }
    .message-dot {
        width: 2;
        min-width: 2;
        height: auto;
        color: #ffffff;
        padding: 0;
    }
    .message-assistant-body {
        height: auto;
        width: 1fr;
    }
    .thinking-row {
        height: 1;
        margin: 0;
        padding: 0;
    }
    .thinking-label {
        color: #888888;
        text-style: italic;
        content-align: left middle;
        width: 1fr;
    }
    .streaming-text {
        height: auto;
        color: #e0e0e0;
        padding: 0;
        margin: 0;
    }
    .thinking-block {
        height: auto;
        color: #666666;
        text-style: dim italic;
        margin: 0 0 0 0;
        padding: 0 0 0 0;
    }
    .bash-input-message {
        background: #413c41;
        padding: 0 1 0 0;
        margin: 1 0 0 0;
        height: auto;
    }
    .bash-output-message {
        height: auto;
        margin: 0;
        padding: 0;
    }
    .compact-boundary-message {
        height: auto;
        margin: 1 0 1 0;
        padding: 0;
    }
    .interrupted-message {
        height: 1;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, message: MessageData, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._tool_panels: dict[str, ToolPanel] = {}
        self._thinking_shown = False

    def compose(self) -> ComposeResult:
        msg = self._message

        if msg.role == "user":
            # UserPromptMessage:
            #   backgroundColor = userMessageBackground (#373737)
            #   paddingRight = 1
            #   NO label — just raw text via HighlightedThinkingText
            display_text = _truncate_user_text(msg.content)
            yield Static(display_text, classes="message-user-content")

        elif msg.role == "assistant":
            # AssistantTextMessage:
            #   ● (BLACK_CIRCLE, NoSelect, fromLeftEdge, minWidth=2) + Markdown
            #   NO "Claude" label anywhere
            with Horizontal(classes="message-assistant-row"):
                # The dot: NoSelect, fromLeftEdge, minWidth=2
                yield Static(
                    f"[#ffffff]{BLACK_CIRCLE}[/]",
                    classes="message-dot",
                )
                # Thinking block — shown collapsed (first 200 chars)
                with Vertical(classes="message-assistant-body"):
                    if msg.thinking:
                        thinking_short = msg.thinking[:200].replace("\n", " ")
                        yield Static(
                            f"[dim italic]{thinking_short}…[/dim italic]",
                            classes="thinking-block",
                        )

                    # Tool call panels (Claude Code renders these before the text)
                    for tc in msg.tool_calls:
                        panel = ToolPanel(tc, id=f"tool-{tc.id}")
                        self._tool_panels[tc.id] = panel
                        yield panel

                    # ── Main content area ──────────────────────────────
                    if msg.content:
                        # Has text: Markdown if final, else plain Static
                        if msg.is_streaming:
                            yield Static(
                                msg.content,
                                classes="streaming-text",
                                id="streaming-text",
                            )
                        else:
                            # AssistantTextMessage.tsx switch(text): API-layer
                            # sentinels render as dedicated error/interrupt
                            # lines, not Markdown.
                            special = render_special_assistant_text(msg.content)
                            if special == "":
                                pass  # NO_RESPONSE_REQUESTED → render nothing
                            elif special is not None:
                                yield Static(special, classes="message-assistant-content")
                            else:
                                yield Markdown(msg.content, classes="message-assistant-content")

                    # No content yet while streaming: render nothing. The
                    # loading state is the SpinnerLine below the message list
                    # (SpinnerWithVerb) — AssistantTextMessage renders null
                    # for empty text (isEmptyMessageText → null).

        elif msg.role == "system":
            yield Static(
                f"[dim italic]{msg.content}[/dim italic]",
                classes="system-message",
            )

        elif msg.role == "error":
            yield Static(
                f"[bold #ff6b80]✗[/bold #ff6b80] {msg.content}",
                classes="error-message",
            )

        elif msg.role == "bash-input":
            # UserBashInputMessage.tsx: "! " prefix in bashBorder pink on the
            # bash message background, paddingRight 1.
            yield Static(
                f"[#fd5db1]! [/#fd5db1][#ffffff]{msg.content}[/#ffffff]",
                classes="bash-input-message",
            )

        elif msg.role == "bash-output":
            # UserBashOutputMessage.tsx → BashToolResultMessage: stdout plain,
            # stderr in error colour, both dimmed and truncated when long.
            stdout = extract_tag(msg.content, "bash-stdout")
            stderr = extract_tag(msg.content, "bash-stderr")
            if stdout is None and stderr is None:
                stdout = msg.content
            parts: list[str] = []
            if stdout and stdout.strip():
                out = stdout.strip()
                lines = out.splitlines()
                if len(lines) > 10:
                    out = "\n".join(lines[:10]) + f"\n… +{len(lines) - 10} lines"
                parts.append(f"[#999999]{out}[/#999999]")
            if stderr and stderr.strip():
                parts.append(f"[#ff6b80]{stderr.strip()}[/#ff6b80]")
            if not parts:
                parts.append("[#999999](no output)[/#999999]")
            yield Static("\n".join(parts), classes="bash-output-message")

        elif msg.role == "compact-boundary":
            # CompactBoundaryMessage.tsx
            yield Static(
                "[#999999]✻ Conversation compacted (ctrl+o for history)[/#999999]",
                classes="compact-boundary-message",
            )

        elif msg.role == "interrupted":
            # InterruptedByUser.tsx
            yield Static(
                "[#999999]Interrupted · What should Optimus do instead?[/#999999]",
                classes="interrupted-message",
            )

    # ------------------------------------------------------------------
    # Streaming API (called by ReplScreen._stream_query)
    # ------------------------------------------------------------------

    def append_text(self, text: str) -> None:
        """Append streamed text — in-place Static update, no Markdown re-parse."""
        was_empty = not self._message.content
        self._message.content += text

        if was_empty:
            # First token — recompose to swap Thinking… spinner → text Static
            self._thinking_shown = False
            self.refresh(recompose=True)
        else:
            # Subsequent token — update the Static in-place (fast path)
            try:
                st = self.query_one("#streaming-text", Static)
                st.update(self._message.content)
            except Exception:
                self.refresh(recompose=True)

    def set_content(self, content: str) -> None:
        """Replace full content (on final assistant message)."""
        self._message.content = content
        self._message.is_streaming = False
        self.refresh(recompose=True)

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a new tool call panel — recompose (child count changes)."""
        was_thinking = self._thinking_shown
        self._message.tool_calls.append(tool_call)
        self._thinking_shown = False
        if was_thinking:
            # Remove thinking row, add tool panel — must recompose
            self.refresh(recompose=True)
        else:
            # Append the new ToolPanel directly (fast path)
            try:
                body = self.query_one(".message-assistant-body", Vertical)
                panel = ToolPanel(tool_call, id=f"tool-{tool_call.id}")
                self._tool_panels[tool_call.id] = panel
                body.mount(panel)
            except Exception:
                self.refresh(recompose=True)

    def update_tool_result(
        self, tool_id: str, result: str, is_error: bool = False
    ) -> None:
        """Update the result of a specific tool call — delegates to ToolPanel."""
        for tc in self._message.tool_calls:
            if tc.id == tool_id:
                tc.result = result
                tc.is_error = is_error
                tc.is_running = False
        panel = self._tool_panels.get(tool_id)
        if panel:
            panel.update_result(result, is_error)
        else:
            self.refresh(recompose=True)

    def finish_streaming(self, final_content: str) -> None:
        """End streaming — recompose once to swap Static → Markdown."""
        self._message.is_streaming = False
        self._message.content = final_content
        self.refresh(recompose=True)

    def set_thinking(self, thinking: str) -> None:
        self._message.thinking = thinking
        self.refresh(recompose=True)


# ---------------------------------------------------------------------------
# MessageList — scrollable container for all messages
# Port of: components/VirtualMessageList.tsx
# Sticky-scroll: pinned to bottom by default; detaches when user scrolls up.
# ---------------------------------------------------------------------------

class MessageList(VerticalScroll):
    """
    Scrollable container that holds all MessageWidgets.
    Auto-scrolls to bottom on new content unless user has scrolled up.
    """

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        background: #1a1a1a;
        border: none;
        scrollbar-color: #505050;
        scrollbar-size: 1 1;
    }
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        cwd: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._messages: list[MessageWidget] = []
        self._pinned_to_bottom = True
        self._current_assistant_widget: Optional[MessageWidget] = None
        self._welcome_model = model
        self._welcome_cwd = cwd or os.getcwd()
        self._welcome_shown = True

    def compose(self) -> ComposeResult:
        # Lazy import to avoid circular-import at module load time
        from optimus.tui.components.welcome import WelcomeWidget  # noqa: PLC0415
        with Vertical(id="message-container"):
            if self._welcome_shown:
                yield WelcomeWidget(
                    model=self._welcome_model,
                    cwd=self._welcome_cwd,
                    id="welcome-widget",
                )

    # ------------------------------------------------------------------
    # Welcome widget helpers
    # ------------------------------------------------------------------

    def _remove_welcome(self) -> None:
        """Dismiss the welcome screen on the first real interaction."""
        if not self._welcome_shown:
            return
        self._welcome_shown = False
        try:
            from optimus.tui.components.welcome import WelcomeWidget  # noqa: PLC0415
            w = self.query_one("#welcome-widget", WelcomeWidget)
            w.remove()
        except Exception:
            pass

    def update_welcome_model(self, model: str) -> None:
        """Forward model change to the welcome widget while it is still visible."""
        self._welcome_model = model
        if not self._welcome_shown:
            return
        try:
            from optimus.tui.components.welcome import WelcomeWidget  # noqa: PLC0415
            w = self.query_one("#welcome-widget", WelcomeWidget)
            w.update_model(model)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_user_message(self, content: str) -> MessageWidget:
        """Append a user message and return the widget."""
        self._pinned_to_bottom = True
        msg = MessageData(role="user", content=content)
        widget = MessageWidget(msg, classes="message-user")
        self._messages.append(widget)
        self._current_assistant_widget = None
        container = self.query_one("#message-container")
        container.mount(widget)
        self._scroll_to_bottom()
        return widget

    def add_assistant_message(self, streaming: bool = True) -> MessageWidget:
        """Append an (initially empty) assistant message for streaming into."""
        self._pinned_to_bottom = True
        msg = MessageData(role="assistant", content="", is_streaming=streaming)
        widget = MessageWidget(msg, classes="message-assistant")
        self._messages.append(widget)
        self._current_assistant_widget = widget
        container = self.query_one("#message-container")
        container.mount(widget)
        self._scroll_to_bottom()
        return widget

    def add_system_message(self, content: str) -> MessageWidget:
        msg = MessageData(role="system", content=content)
        widget = MessageWidget(msg, classes="system-message")
        self._messages.append(widget)
        container = self.query_one("#message-container")
        container.mount(widget)
        self._scroll_to_bottom()
        return widget

    def add_error_message(self, content: str) -> MessageWidget:
        msg = MessageData(role="error", content=content)
        widget = MessageWidget(msg, classes="message-assistant")
        self._messages.append(widget)
        container = self.query_one("#message-container")
        container.mount(widget)
        self._scroll_to_bottom()
        return widget

    def _add_simple(self, role: str, content: str = "", classes: str = "") -> MessageWidget:
        msg = MessageData(role=role, content=content)
        widget = MessageWidget(msg, classes=classes or f"message-{role}")
        self._messages.append(widget)
        container = self.query_one("#message-container")
        container.mount(widget)
        self._scroll_to_bottom()
        return widget

    def add_bash_input(self, command: str) -> MessageWidget:
        """UserBashInputMessage — the '! command' echo for bash-mode input."""
        return self._add_simple("bash-input", command)

    def add_bash_output(self, content: str) -> MessageWidget:
        """UserBashOutputMessage — stdout/stderr of a bash-mode command."""
        return self._add_simple("bash-output", content)

    def add_compact_boundary(self) -> MessageWidget:
        """CompactBoundaryMessage — '✻ Conversation compacted' divider."""
        return self._add_simple("compact-boundary")

    def add_interrupted(self) -> MessageWidget:
        """InterruptedByUser — dim 'Interrupted · …' line after Esc/Ctrl+C."""
        return self._add_simple("interrupted")

    def get_current_assistant(self) -> Optional[MessageWidget]:
        return self._current_assistant_widget

    # ------------------------------------------------------------------
    # ctrl+o — toggle full tool output on every ToolPanel (CtrlOToExpand)
    # ------------------------------------------------------------------

    def toggle_verbose(self) -> bool:
        self._verbose_output = not getattr(self, "_verbose_output", False)
        for panel in self.query(ToolPanel):
            panel.set_verbose(self._verbose_output)
        return self._verbose_output

    def clear_messages(self) -> None:
        """Remove all messages from the list."""
        self._welcome_shown = False
        self._messages.clear()
        self._current_assistant_widget = None
        container = self.query_one("#message-container")
        for child in list(container.children):
            child.remove()

    # ------------------------------------------------------------------
    # Scroll behaviour — mirrors VirtualMessageList sticky-scroll
    # ------------------------------------------------------------------

    def _scroll_to_bottom(self) -> None:
        """Schedule a scroll-to-end after the current layout pass completes."""
        if self._pinned_to_bottom:
            # call_after_refresh defers until Textual has finished laying out
            # the newly-mounted / recomposed widget, so max_scroll_y is correct.
            self.call_after_refresh(self.scroll_end, animate=False)

    def on_layout(self) -> None:
        """Re-scroll after every layout pass (catches streaming text growth)."""
        if self._pinned_to_bottom:
            self.scroll_end(animate=False)

    def watch_scroll_y(self, value: float) -> None:
        """Unpin when the user manually scrolls up; re-pin at the bottom."""
        if self.max_scroll_y == 0:
            return  # nothing to scroll yet
        if value < self.max_scroll_y - 2:
            self._pinned_to_bottom = False
        else:
            self._pinned_to_bottom = True

    def scroll_to_bottom(self) -> None:
        """Public: force scroll to bottom and repin."""
        self._pinned_to_bottom = True
        self.scroll_end(animate=True)
