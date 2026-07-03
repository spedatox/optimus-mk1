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
    SlashCommand("/theme",          "List or switch colour theme",              []),
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


class BashInputSubmitted(TMessage):
    """Posted when the user submits a bash-mode command ('!cmd')."""
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class CancelRequested(TMessage):
    """Posted when the user presses Ctrl+C or Escape."""


class PermissionModeChanged(TMessage):
    """Posted when shift+tab cycles the permission mode."""
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode


class ExitRequested(TMessage):
    """Posted on the second ctrl+c/ctrl+d press within the exit window."""


class SlashInputChanged(TMessage):
    """
    Posted on every keystroke while the input starts with '/'.
    The screen-level SlashOverlay subscribes to this.
    value="" means hide the overlay.
    """
    def __init__(self, value: str) -> None:
        super().__init__()
        self.value = value


class MentionInputChanged(TMessage):
    """
    Posted while the trailing token of the input is an '@path' file mention.
    prefix is the partial path after '@'; None means no active mention.
    """
    def __init__(self, prefix: Optional[str]) -> None:
        super().__init__()
        self.prefix = prefix


# ---------------------------------------------------------------------------
# @-mention file completion — port of the unified-suggestions file source
# (utils/suggestions directoryCompletion): complete paths relative to cwd,
# directories suffixed with '/', hidden entries only when the typed segment
# starts with '.'.
# ---------------------------------------------------------------------------

def complete_file_paths(prefix: str, cwd: Optional[str] = None, limit: int = 13) -> list[str]:
    import os
    base_dir = cwd or os.getcwd()
    # Split the typed prefix into directory part + partial name
    prefix = prefix.replace("\\", "/")
    if "/" in prefix:
        dir_part, _, name_part = prefix.rpartition("/")
        search_dir = os.path.join(base_dir, dir_part)
        rel_prefix = dir_part + "/"
    else:
        dir_part, name_part = "", prefix
        search_dir = base_dir
        rel_prefix = ""
    try:
        entries = sorted(os.scandir(search_dir), key=lambda e: e.name.lower())
    except OSError:
        return []
    show_hidden = name_part.startswith(".")
    out: list[str] = []
    for entry in entries:
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue
        if not name.lower().startswith(name_part.lower()):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            is_dir = False
        out.append(rel_prefix + name + ("/" if is_dir else ""))
        if len(out) >= limit:
            break
    return out


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
        self._kind = "slash"
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

    def update_mentions(self, prefix: str, completions: list[str]) -> None:
        """Show @-mention file completions (unified-suggestions file source).
        Items reuse the SlashCommand rendering: name = completion path."""
        self._prefix = ""            # no typed-prefix highlight for paths
        self._kind = "mention"
        self._items = [
            SlashCommand(name=c, description="", aliases=[]) for c in completions
        ]
        self._selected = min(self._selected, max(0, len(self._items) - 1))
        if self._items:
            self.add_class("visible")
        else:
            self.remove_class("visible")
        self.refresh(recompose=True)

    def get_kind(self) -> str:
        return getattr(self, "_kind", "slash")

    def hide(self) -> None:
        self._items = []
        self._selected = 0
        self._prefix = ""
        self._kind = "slash"
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

# ---------------------------------------------------------------------------
# Permission-mode config — port of utils/permissions/PermissionMode.ts
# PERMISSION_MODE_CONFIG (title/symbol/color per mode). shift+tab cycles
# default → acceptEdits → plan → default.
# ---------------------------------------------------------------------------

PAUSE_ICON = "⏸"  # constants/figures.ts PAUSE_ICON

PERMISSION_MODE_CONFIG: dict[str, dict] = {
    "default":           {"title": "Default",            "symbol": "",         "color": "#ffffff"},
    "plan":              {"title": "Plan Mode",          "symbol": PAUSE_ICON, "color": "#48968c"},   # planMode
    "acceptEdits":       {"title": "Accept edits",       "symbol": "⏵⏵",       "color": "#af87ff"},   # autoAccept
    "bypassPermissions": {"title": "Bypass Permissions", "symbol": "⏵⏵",       "color": "#ff6b80"},   # error
}

_MODE_CYCLE = ["default", "acceptEdits", "plan"]


class InputBar(Widget):
    """
    The bottom input bar.  Handles text entry, history, and key routing.
    The slash-command overlay is owned by the parent Screen — InputBar
    communicates with it via SlashInputChanged messages and reads it
    back through self.screen.

    Footer row (PromptInputFooterLeftSide):
      - bash mode:            "! for bash mode" in bashBorder pink
      - active mode:          "⏵⏵ accept edits on (shift+tab to cycle)"
      - exit confirm pending: "Press ctrl+c again to exit"
      - otherwise:            "? for shortcuts" (dim)
    """

    DEFAULT_CSS = """
    InputBar {
        height: 5;
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
    InputBar #input-footer {
        height: 1;
        padding: 0 2;
        background: #1a1a1a;
        color: #999999;
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
    permission_mode: reactive[str] = reactive("default")

    # Focusable so ctrl+r search can steal focus from the Input — the Input
    # consumes printable keys itself, so query keystrokes must land here.
    can_focus = True

    # Exit-confirm window (ExitFlow): second ctrl+c within 2 s exits
    _EXIT_WINDOW_S = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_pos: int = -1
        self._saved_input: str = ""
        self._vim_mode: bool = False
        self._exit_pending_at: float = 0.0
        self._exit_reset_timer = None
        # Ctrl+R reverse history search (isSearchingHistory / historyQuery /
        # historyFailedMatch in PromptInput.tsx)
        self._searching: bool = False
        self._search_query: str = ""
        self._search_skip: int = 0        # ctrl+r again → next older match
        self._search_failed: bool = False
        self._saved_before_search: str = ""

    def compose(self) -> ComposeResult:
        # SlashOverlay is NOT here — it lives on the parent Screen
        with Horizontal(id="input-area"):
            yield Static("> ", id="input-prefix")
            yield Input(
                placeholder=f"Talk to {NAME} (/? for help)",
                id="input-field",
            )
        yield Static(self._footer_markup(), id="input-footer")

    # ------------------------------------------------------------------
    # Footer — PromptInputFooterLeftSide
    # ------------------------------------------------------------------

    def _footer_markup(self) -> str:
        import time as _t
        # History search label (HistorySearchInput): shows the live query;
        # "no matching prompt:" when nothing in history matches.
        if self._searching:
            label = "no matching prompt:" if self._search_failed else "search prompts:"
            return f"[#999999]{label}[/#999999] {self._search_query}"
        # Exit-confirm message wins over everything else (exitMessage.show)
        if self._exit_pending_at and (_t.monotonic() - self._exit_pending_at) < self._EXIT_WINDOW_S:
            return "[#999999]Press ctrl+c again to exit[/#999999]"
        # Bash mode: input starts with "!"
        try:
            if self.query_one("#input-field", Input).value.startswith("!"):
                return "[#fd5db1]! for bash mode[/#fd5db1]"
        except Exception:
            pass
        # Active permission mode indicator
        if self.permission_mode != "default":
            cfg = PERMISSION_MODE_CONFIG.get(self.permission_mode, PERMISSION_MODE_CONFIG["default"])
            c = cfg["color"]
            return (f"[{c}]{cfg['symbol']} {cfg['title'].lower()} on[/{c}]"
                    f" [#505050](shift+tab to cycle)[/#505050]")
        return "[#505050]? for shortcuts[/#505050]"

    def _refresh_footer(self) -> None:
        try:
            self.query_one("#input-footer", Static).update(self._footer_markup())
        except Exception:
            pass

    def watch_permission_mode(self, value: str) -> None:
        self._refresh_footer()

    # ------------------------------------------------------------------
    # Ctrl+R reverse history search
    # ------------------------------------------------------------------

    def _find_history_match(self) -> Optional[str]:
        """Newest-first substring match (case-insensitive), skipping
        _search_skip earlier matches (ctrl+r cycling)."""
        if not self._search_query:
            return None
        q = self._search_query.lower()
        skip = self._search_skip
        for entry in reversed(self._history):
            if q in entry.lower():
                if skip == 0:
                    return entry
                skip -= 1
        return None

    def _update_search(self) -> None:
        field = self.query_one("#input-field", Input)
        match = self._find_history_match()
        if match is not None:
            self._search_failed = False
            field.value = match
            field.cursor_position = len(match)
        else:
            self._search_failed = bool(self._search_query)
        self._refresh_footer()

    def _start_search(self) -> None:
        field = self.query_one("#input-field", Input)
        self._searching = True
        self._search_query = ""
        self._search_skip = 0
        self._search_failed = False
        self._saved_before_search = field.value
        # Take focus away from the Input: it consumes printable keys, so the
        # search query is typed against this widget's on_key instead
        # (PromptInput.tsx: focus={!isSearchingHistory}).
        self.focus()
        self._refresh_footer()

    def _end_search(self, accept: bool) -> None:
        """Accept keeps the matched text in the input; cancel restores what
        the user had typed before ctrl+r."""
        field = self.query_one("#input-field", Input)
        if not accept:
            field.value = self._saved_before_search
        field.cursor_position = len(field.value)
        self._searching = False
        self._search_query = ""
        self._search_skip = 0
        self._search_failed = False
        field.focus()
        self._refresh_footer()

    def cycle_permission_mode(self) -> None:
        """shift+tab: default → acceptEdits → plan → default."""
        try:
            idx = _MODE_CYCLE.index(self.permission_mode)
        except ValueError:
            idx = 0
        self.permission_mode = _MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)]
        self.post_message(PermissionModeChanged(self.permission_mode))

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
        self._refresh_footer()

    def _clear_exit_pending(self) -> None:
        self._exit_pending_at = 0.0
        self._exit_reset_timer = None
        self._refresh_footer()

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
        # Bash mode: "!command" runs directly in the shell (PromptInput
        # mode === 'bash'), it is not sent to the model.
        if text.startswith("!") and len(text) > 1:
            self.post_message(BashInputSubmitted(text[1:].strip()))
        else:
            self.post_message(InputSubmitted(text))

    @on(Input.Changed, "#input-field")
    def handle_change(self, event: Input.Changed) -> None:
        val = event.value
        # suppressSuggestions while searching history — programmatic value
        # updates from the search match must not pop the overlay.
        if self._searching:
            return
        if val.startswith("/") and " " not in val:
            self.post_message(SlashInputChanged(val))
            self.post_message(MentionInputChanged(None))
        else:
            self.post_message(SlashInputChanged(""))
            # @-mention: trailing token starting with '@' opens file completion
            token = val.rsplit(" ", 1)[-1] if val else ""
            if token.startswith("@") and not self.is_waiting:
                self.post_message(MentionInputChanged(token[1:]))
            else:
                self.post_message(MentionInputChanged(None))
        self._refresh_footer()   # bash-mode "!" hint tracks the input live

    def insert_mention_completion(self, completion: str) -> None:
        """Replace the trailing '@token' with '@completion' (plus a trailing
        space for files so the user keeps typing; directories stay open for
        deeper completion)."""
        field = self.query_one("#input-field", Input)
        val = field.value
        head, sep, _token = val.rpartition(" ")
        prefix = head + sep if sep else ""
        suffix = "" if completion.endswith("/") else " "
        field.value = f"{prefix}@{completion}{suffix}"
        field.cursor_position = len(field.value)

    # ------------------------------------------------------------------
    # Key routing
    # ------------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        import time as _t
        field = self.query_one("#input-field", Input)
        ov = self._overlay()
        overlay_open = ov is not None and ov.is_visible()

        # ── Ctrl+R — start / cycle reverse history search ────────────────
        if event.key == "ctrl+r" and not self.is_waiting:
            event.stop()
            if self._searching:
                # cycle to next older match
                self._search_skip += 1
                if self._find_history_match() is None and self._search_skip > 0:
                    self._search_skip -= 1   # stay on the oldest match
                self._update_search()
            else:
                self._start_search()
            return

        # ── While searching, keys edit the query, not the input ─────────
        if self._searching:
            key = event.key
            if key == "escape":
                event.stop()
                self._end_search(accept=False)
                return
            if key == "enter":
                event.stop()
                self._end_search(accept=True)
                return
            if key == "backspace":
                event.stop()
                self._search_query = self._search_query[:-1]
                self._search_skip = 0
                if not self._search_query:
                    self._search_failed = False
                self._update_search()
                return
            if event.is_printable and event.character:
                event.stop()
                self._search_query += event.character
                self._search_skip = 0
                self._update_search()
                return
            # Navigation keys accept the current match and fall through
            if key in ("up", "down", "left", "right", "home", "end"):
                self._end_search(accept=True)
            # anything else: leave search silently
            else:
                self._end_search(accept=True)
                return

        # ── Shift+Tab — cycle permission mode ────────────────────────────
        if event.key == "shift+tab":
            event.stop()
            self.cycle_permission_mode()
            return

        # ── Ctrl+C — cancel query, or double-press to exit when idle ────
        if event.key == "ctrl+c":
            event.stop()
            if ov:
                ov.hide()
            if self.is_waiting or field.value:
                # Cancel the running query / clear typed input first
                self._exit_pending_at = 0.0
                self.post_message(CancelRequested())
                self._refresh_footer()
                return
            # Idle with empty input — ExitFlow: first press arms the
            # 2 s window, second press exits.
            now = _t.monotonic()
            if self._exit_pending_at and (now - self._exit_pending_at) < self._EXIT_WINDOW_S:
                self.post_message(ExitRequested())
                return
            self._exit_pending_at = now
            self._refresh_footer()
            if self._exit_reset_timer is not None:
                try:
                    self._exit_reset_timer.stop()
                except Exception:
                    pass
            self._exit_reset_timer = self.set_timer(
                self._EXIT_WINDOW_S, self._clear_exit_pending
            )
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
                    if ov.get_kind() == "mention":
                        self.insert_mention_completion(selected)
                        # Directory completions keep the overlay open one
                        # level deeper; Input.Changed re-triggers it.
                        if not selected.endswith("/"):
                            ov.hide()
                    else:
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
                if ov.get_kind() == "mention":
                    self.insert_mention_completion(selected)
                    if not selected.endswith("/"):
                        ov.hide()
                    return
                ov.hide()
                self.post_message(SlashInputChanged(""))
                field.value = ""
                self.post_message(InputSubmitted(selected))
            return
