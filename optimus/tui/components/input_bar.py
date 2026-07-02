"""
optimus/tui/components/input_bar.py

Input area with:
  - Single/multi-line input
  - Input history (up/down arrows)
  - Slash-command overlay (rendered at screen level — see SlashOverlay)
  - Ctrl+C to cancel current query
  - Shift+Enter for newline

Port of: components/PromptInput/PromptInput.tsx
         components/PromptInput/BaseTextInput.tsx
         commands/keybindings/
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from textual import on, events
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.message import Message as TMessage

from optimus.tui.brand import ACCENT, NAME


# ---------------------------------------------------------------------------
# Slash-command registry
# ---------------------------------------------------------------------------

@dataclass
class SlashCommand:
    name: str
    description: str
    aliases: list[str]


SLASH_COMMANDS: list[SlashCommand] = [
    # ── Navigation / session ──────────────────────────────────────────────
    SlashCommand("/help",           "Show help and keyboard shortcuts",         ["/h"]),
    SlashCommand("/exit",           "Exit Optimus",                             ["/quit", "/q"]),
    SlashCommand("/clear",          "Clear conversation history",               ["/c"]),
    SlashCommand("/compact",        "Compact conversation (summarise)",         []),
    SlashCommand("/rewind",         "Undo last exchange (remove last Q+A)",     []),
    SlashCommand("/resume",         "Resume a previous session by ID",          []),
    # ── Model / output ────────────────────────────────────────────────────
    SlashCommand("/model",          "Switch model",                             ["/m"]),
    SlashCommand("/effort",         "Set effort level: low|medium|high|max",    []),
    SlashCommand("/output-style",   "Change output style: verbose|concise|auto",[]),
    # ── Context / memory ──────────────────────────────────────────────────
    SlashCommand("/context",        "Show context window usage",                []),
    SlashCommand("/memory",         "Show or edit memory files",                []),
    SlashCommand("/add-dir",        "Add directory to allowed paths",           []),
    SlashCommand("/files",          "List files in current context",            []),
    # ── Information ───────────────────────────────────────────────────────
    SlashCommand("/status",         "Show session status",                      []),
    SlashCommand("/cost",           "Show token usage and cost",                []),
    SlashCommand("/stats",          "Show session statistics",                  []),
    SlashCommand("/session",        "Show session details and ID",              []),
    SlashCommand("/permissions",    "Show current permission state",            []),
    SlashCommand("/release-notes",  "Show recent changelog",                    []),
    # ── Git ───────────────────────────────────────────────────────────────
    SlashCommand("/diff",           "Show current git diff",                    []),
    SlashCommand("/branch",         "Show git branch info",                     []),
    SlashCommand("/pr-comments",    "Fetch and review PR comments",             []),
    # ── Code actions ──────────────────────────────────────────────────────
    SlashCommand("/review",         "Review a pull request",                    []),
    SlashCommand("/security-review","Run a security review on current code",    []),
    SlashCommand("/init",           "Initialise CLAUDE.md for this project",    []),
    SlashCommand("/plan",           "Enter planning/research mode",             []),
    # ── Config / tools ────────────────────────────────────────────────────
    SlashCommand("/config",         "Show or set configuration values",         []),
    SlashCommand("/mcp",            "List MCP servers and status",              []),
    SlashCommand("/vim",            "Toggle vim keybindings",                   []),
    SlashCommand("/keybindings",    "Show keyboard shortcut reference",         ["/keys"]),
    # ── Misc ─────────────────────────────────────────────────────────────
    SlashCommand("/export",         "Export conversation to file",              []),
    SlashCommand("/copy",           "Copy last response to clipboard",          []),
    SlashCommand("/doctor",         "Run diagnostics",                          []),
    SlashCommand("/feedback",       "Send feedback (opens issue tracker)",      []),
]


# ---------------------------------------------------------------------------
# Messages posted to the parent screen
# ---------------------------------------------------------------------------

class InputSubmitted(TMessage):
    """Posted when the user submits input."""
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class CancelRequested(TMessage):
    """Posted when the user presses Ctrl+C or Escape."""


class SlashInputChanged(TMessage):
    """
    Posted on every keystroke while the input starts with '/'.
    The screen-level SlashOverlay subscribes to this.
    value="" means hide the overlay.
    """
    def __init__(self, value: str) -> None:
        super().__init__()
        self.value = value


# ---------------------------------------------------------------------------
# SlashOverlay — floats above the input bar at the Screen level
# ---------------------------------------------------------------------------

class SlashOverlay(Widget):
    """
    Floating autocomplete list for slash commands.
    Mounted directly on ReplScreen (NOT inside InputBar) so it can
    float freely over the message list without disturbing the input layout.
    """

    DEFAULT_CSS = """
    SlashOverlay {
        dock: bottom;
        margin-bottom: 5;
        margin-left: 2;
        width: 62;
        height: auto;
        max-height: 16;
        background: #262626;
        border: solid #888888;
        display: none;
        layer: overlay;
    }
    SlashOverlay.visible {
        display: block;
    }
    SlashOverlay .slash-header {
        background: #1a1a1a;
        color: #505050;
        height: 1;
        padding: 0 1;
    }
    SlashOverlay .slash-item {
        height: 1;
        padding: 0 1;
        color: #999999;
    }
    SlashOverlay .slash-item--selected {
        background: #2c323e;
        color: #ffffff;
    }
    SlashOverlay .slash-item--selected .slash-name {
        color: #d77757;
    }
    """.replace("#d77757", ACCENT)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[SlashCommand] = []
        self._selected = 0
        self._prefix = ""

    # Max items shown at once (max-height:16 minus 1 header row minus 2 border rows)
    _MAX_VISIBLE = 13

    def compose(self) -> ComposeResult:
        if not self._items:
            return

        total = len(SLASH_COMMANDS)
        shown = len(self._items)

        # ── Sliding window ────────────────────────────────────────────────
        # Keep the selected item visible by scrolling the window.
        max_vis = self._MAX_VISIBLE
        if shown <= max_vis:
            start = 0
        else:
            # Centre the selection in the window; clamp to valid range.
            start = self._selected - max_vis // 2
            start = max(0, min(start, shown - max_vis))
        visible = self._items[start : start + max_vis]

        # Scroll indicator suffix in header when list is truncated
        scroll_hint = ""
        if shown > max_vis:
            if start > 0 and start + max_vis < shown:
                scroll_hint = " ↑↓"
            elif start > 0:
                scroll_hint = " ↑"
            elif start + max_vis < shown:
                scroll_hint = " ↓"

        yield Static(
            f" [dim]{shown}/{total} commands{scroll_hint}  [/dim]"
            "[dim]↑↓ navigate  Tab/Enter select  Esc close[/dim]",
            classes="slash-header",
        )

        for i, cmd in enumerate(visible):
            actual_idx = start + i
            is_sel = actual_idx == self._selected
            sel_cls = " slash-item--selected" if is_sel else ""

            # ── Command name with typed-prefix highlight ──────────────────
            # Pad using the PLAIN name length (not the markup string) so
            # the column gap between name and description stays fixed.
            name = cmd.name
            name_col_width = 20          # fixed visual column for the name
            padding = " " * max(2, name_col_width - len(name) + 2)

            if self._prefix and name.startswith(self._prefix):
                name_markup = (
                    f"[bold {ACCENT}]{self._prefix}[/bold {ACCENT}]"
                    f"[{'bold #ffffff' if is_sel else '#999999'}]{name[len(self._prefix):]}"
                    f"[/{'bold #ffffff' if is_sel else '#999999'}]"
                )
            else:
                name_markup = f"[{'bold ' + ACCENT if is_sel else '#999999'}]{name}[/]"

            desc_colour = "#ffffff" if is_sel else "#505050"
            yield Static(
                f" {name_markup}{padding}[{desc_colour}]{cmd.description[:30]}[/{desc_colour}]",
                classes=f"slash-item{sel_cls}",
            )

    def update(self, prefix: str) -> None:
        """Filter commands matching *prefix* and redisplay."""
        self._prefix = prefix
        pl = prefix.lower()
        self._items = [
            cmd for cmd in SLASH_COMMANDS
            if cmd.name.startswith(pl)
            or any(a.startswith(pl) for a in cmd.aliases)
        ]
        self._selected = min(self._selected, max(0, len(self._items) - 1))
        if self._items:
            self.add_class("visible")
        else:
            self.remove_class("visible")
        self.refresh(recompose=True)

    def hide(self) -> None:
        self._items = []
        self._selected = 0
        self._prefix = ""
        self.remove_class("visible")
        self.refresh(recompose=True)

    def move_selection(self, delta: int) -> None:
        if not self._items:
            return
        self._selected = (self._selected + delta) % len(self._items)
        self.refresh(recompose=True)

    def get_selected(self) -> Optional[str]:
        if self._items:
            return self._items[self._selected].name
        return None

    def is_visible(self) -> bool:
        return bool(self._items)


# ---------------------------------------------------------------------------
# InputBar — main input widget (no longer owns the slash overlay)
# ---------------------------------------------------------------------------

class InputBar(Widget):
    """
    The bottom input bar.  Handles text entry, history, and key routing.
    The slash-command overlay is owned by the parent Screen — InputBar
    communicates with it via SlashInputChanged messages and reads it
    back through self.screen.
    """

    DEFAULT_CSS = """
    InputBar {
        height: 4;
        background: #1a1a1a;
        border-top: solid #888888;
        layout: vertical;
        padding: 0;
    }
    InputBar #input-area {
        height: 3;
        padding: 1 0;
        background: #1a1a1a;
        layout: horizontal;
    }
    InputBar #input-prefix {
        width: 3;
        height: 1;
        color: #d77757;
        content-align: left middle;
        background: #1a1a1a;
    }
    InputBar Input {
        border: none;
        background: #1a1a1a;
        color: #ffffff;
        height: 1;
        width: 1fr;
        padding: 0 1;
        margin: 0;
    }
    InputBar Input:focus {
        border: none;
        background: #1a1a1a;
        color: #ffffff;
    }
    InputBar Input>.input--placeholder {
        color: #505050;
        text-style: italic;
    }
    InputBar Input>.input--cursor {
        background: #d77757;
        color: #000000;
    }
    """.replace("#d77757", ACCENT)

    is_waiting: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_pos: int = -1
        self._saved_input: str = ""
        self._vim_mode: bool = False

    def compose(self) -> ComposeResult:
        # SlashOverlay is NOT here — it lives on the parent Screen
        with Horizontal(id="input-area"):
            yield Static("> ", id="input-prefix")
            yield Input(
                placeholder=f"Talk to {NAME} (/? for help)",
                id="input-field",
            )

    # ------------------------------------------------------------------
    # Overlay accessor — safe reference to the screen-level overlay
    # ------------------------------------------------------------------

    def _overlay(self) -> Optional[SlashOverlay]:
        try:
            return self.screen.query_one("#slash-overlay", SlashOverlay)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_waiting(self, waiting: bool) -> None:
        self.is_waiting = waiting
        field = self.query_one("#input-field", Input)
        field.disabled = waiting
        prefix = self.query_one("#input-prefix", Static)
        if waiting:
            prefix.update(f"[blink bold {ACCENT}]>[/] ")
        else:
            prefix.update(f"[bold {ACCENT}]>[/] ")
            field.focus()

    def clear_input(self) -> None:
        self.query_one("#input-field", Input).value = ""

    def focus_input(self) -> None:
        self.query_one("#input-field", Input).focus()

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#input-field")
    def handle_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self.is_waiting:
            return
        event.stop()

        ov = self._overlay()
        if ov:
            ov.hide()

        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_pos = -1
        self._saved_input = ""

        self.query_one("#input-field", Input).value = ""
        # Signal overlay gone
        self.post_message(SlashInputChanged(""))
        self.post_message(InputSubmitted(text))

    @on(Input.Changed, "#input-field")
    def handle_change(self, event: Input.Changed) -> None:
        val = event.value
        if val.startswith("/") and " " not in val:
            self.post_message(SlashInputChanged(val))
        else:
            self.post_message(SlashInputChanged(""))

    # ------------------------------------------------------------------
    # Key routing
    # ------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        field = self.query_one("#input-field", Input)
        ov = self._overlay()
        overlay_open = ov is not None and ov.is_visible()

        # ── Ctrl+C — cancel ──────────────────────────────────────────────
        if event.key == "ctrl+c":
            event.stop()
            if ov:
                ov.hide()
            self.post_message(CancelRequested())
            return

        # ── Escape — close overlay or cancel ─────────────────────────────
        if event.key == "escape":
            event.stop()
            if overlay_open:
                ov.hide()
                self.post_message(SlashInputChanged(""))
            else:
                self.post_message(CancelRequested())
            return

        # ── Up — overlay navigation or history ───────────────────────────
        if event.key == "up":
            if overlay_open:
                ov.move_selection(-1)
                event.stop()
            elif self._history:
                event.stop()
                if self._history_pos == -1:
                    self._saved_input = field.value
                    self._history_pos = len(self._history) - 1
                elif self._history_pos > 0:
                    self._history_pos -= 1
                field.value = self._history[self._history_pos]
                field.cursor_position = len(field.value)
            return

        # ── Down — overlay navigation or history ─────────────────────────
        if event.key == "down":
            if overlay_open:
                ov.move_selection(1)
                event.stop()
            elif self._history_pos >= 0:
                event.stop()
                self._history_pos += 1
                if self._history_pos >= len(self._history):
                    self._history_pos = -1
                    field.value = self._saved_input
                else:
                    field.value = self._history[self._history_pos]
                field.cursor_position = len(field.value)
            return

        # ── Tab — autocomplete ────────────────────────────────────────────
        if event.key == "tab":
            if overlay_open:
                event.stop()
                selected = ov.get_selected()
                if selected:
                    field.value = selected + " "
                    field.cursor_position = len(field.value)
                    ov.hide()
                    self.post_message(SlashInputChanged(""))
            return

        # ── Enter with overlay open — pick selected item ──────────────────
        if event.key == "enter" and overlay_open:
            selected = ov.get_selected()
            if selected:
                event.stop()
                ov.hide()
                self.post_message(SlashInputChanged(""))
                field.value = ""
                self.post_message(InputSubmitted(selected))
            return
