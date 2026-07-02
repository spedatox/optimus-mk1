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

# Braille spinner frames — the same set Claude Code uses for its loaders.
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ---------------------------------------------------------------------------
# Spinner — animated single-cell loader (mirrors Claude Code's ToolUseLoader)
# ---------------------------------------------------------------------------

class Spinner(Static):
    """A tiny animated spinner. Cycles SPINNER_FRAMES at ~12fps until stopped."""

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
        self._timer = self.set_interval(1 / 12, self._tick)
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
# ToolPanel — collapsible tool call display
# Port of: various tool-use message components
# Background: bashMessageBackgroundColor = rgb(65,60,65) = #413c41
# ---------------------------------------------------------------------------

class ToolPanel(Widget):
    """Displays a single tool call and its result. Click to toggle.

    Claude Code replication:
      - Header row: Spinner (animated, while running) or ✓/✗ (when done),
        tool name in bold #b1b9f9, args summary.
      - Result row: ⎿ prefix (Claude Code style), truncated at 2000 chars.
      - Background: bashMessageBackgroundColor = #413c41
      - Border-left: thick #b1b9f9
    """

    DEFAULT_CSS = """
    ToolPanel {
        height: auto;
        margin: 0 0 0 2;
        background: #413c41;
        border-left: thick #b1b9f9;
        padding: 0 1;
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
    ToolPanel .tp-name {
        width: auto;
        min-width: 12;
        color: #b1b9f9;
        text-style: bold;
        content-align: left middle;
    }
    ToolPanel .tp-args {
        width: 1fr;
        color: #999999;
        text-style: dim;
        content-align: left middle;
    }
    ToolPanel .tp-result {
        height: auto;
        margin: 0 0 0 2;
        padding: 0 0;
        color: #cccccc;
    }
    ToolPanel .tp-result.tool-result-error {
        color: #ff6b80;
    }
    ToolPanel .tp-result.tool-result-success {
        color: #a0d9a0;
    }
    """

    expanded: reactive[bool] = reactive(True)

    def __init__(self, tool_call: ToolCall, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool = tool_call
        self._spinner: Optional[Spinner] = None

    def compose(self) -> ComposeResult:
        tool = self._tool
        args_summary = self._summarise_args(tool.input)

        # ── Header row ──────────────────────────────────────────────────
        with Horizontal(classes="tp-header"):
            if tool.is_running:
                # Animated Spinner — mounts, starts ticking, stops on unmount
                yield Spinner(classes="tp-spinner-slot")
            elif tool.is_error:
                yield Static(
                    "[bold #ff6b80]✗[/bold #ff6b80]",
                    classes="tp-status-icon",
                )
            else:
                yield Static(
                    "[bold #4eba65]✓[/bold #4eba65]",
                    classes="tp-status-icon",
                )

            yield Static(
                f"[bold #b1b9f9]{tool.name}[/bold #b1b9f9]",
                classes="tp-name",
            )

            if args_summary:
                yield Static(
                    f"[dim #999999]{args_summary[:60]}[/dim #999999]",
                    classes="tp-args",
                )

        # ── Result row (⎿ prefix — Claude Code style) ──────────────────
        if self.expanded and tool.result is not None:
            result_text = tool.result[:2000]
            if len(tool.result) > 2000:
                result_text += f"\n… ({len(tool.result) - 2000} chars truncated)"
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

    @staticmethod
    def _summarise_args(input_dict: dict) -> str:
        """One-line summary of tool arguments."""
        if not input_dict:
            return ""
        parts: list[str] = []
        for key, val in list(input_dict.items())[:3]:
            if isinstance(val, str):
                short = val[:40].replace("\n", " ")
                parts.append(f"{key}={short!r}")
            elif isinstance(val, (int, float, bool)):
                parts.append(f"{key}={val}")
            else:
                parts.append(f"{key}=…")
        return "  ".join(parts)


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
                            yield Markdown(msg.content, classes="message-assistant-content")

                    elif msg.is_streaming and not msg.tool_calls:
                        # Waiting for first token or tool — show Thinking… spinner
                        self._thinking_shown = True
                        with Horizontal(classes="thinking-row"):
                            yield Spinner()
                            yield Static(
                                "Thinking…",
                                classes="thinking-label",
                            )

                    elif msg.is_streaming:
                        # No text yet but tools are running — cursor
                        yield Static(
                            f"[blink bold {ACCENT}]▋[/]",
                            classes="message-assistant-content",
                        )

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

    def get_current_assistant(self) -> Optional[MessageWidget]:
        return self._current_assistant_widget

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
