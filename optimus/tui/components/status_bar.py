"""
optimus/tui/components/status_bar.py

Bottom status bar — mirrors Claude Code's footer line.
Shows: model name | tokens used | cost | git branch | permission mode | working dir.

Port of: components/StatusBar.tsx (JARVIS blue theme variant).
"""
from __future__ import annotations

import os
from typing import Optional

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal
from textual.reactive import reactive

from optimus.tui.brand import ACCENT


class StatusBar(Widget):
    """
    Single-row status bar rendered at the bottom of the screen.

    Reactive attributes are updated by the REPL screen as the session
    progresses (model switches, token counts, git branch detection, etc.).
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #2c323e;
        layout: horizontal;
        dock: bottom;
    }
    StatusBar Static {
        height: 1;
        content-align: left middle;
        color: #999999;
    }
    StatusBar .status-sep {
        width: 3;
        content-align: center middle;
        color: #505050;
    }
    StatusBar .status-model {
        color: #d77757;
        width: auto;
        min-width: 18;
    }
    StatusBar .status-tokens {
        color: #999999;
        width: auto;
        min-width: 12;
    }
    StatusBar .status-cost {
        color: #999999;
        width: auto;
        min-width: 9;
    }
    StatusBar .status-branch {
        color: #4eba65;
        width: auto;
        min-width: 12;
    }
    StatusBar .status-mode {
        color: #ffc107;
        width: auto;
        min-width: 8;
    }
    StatusBar .status-cwd {
        color: #999999;
        width: 1fr;
    }
    StatusBar .status-session {
        color: #505050;
        width: auto;
        min-width: 10;
    }
    """.replace("#d77757", ACCENT)

    # Reactive fields — updating these auto-refreshes the bar.
    model: reactive[str] = reactive("claude-sonnet-4-6")
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    cost_usd: reactive[float] = reactive(0.0)
    git_branch: reactive[str] = reactive("")
    permission_mode: reactive[str] = reactive("default")
    session_id: reactive[str] = reactive("")
    is_streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cwd = os.getcwd()

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self._model_label(), classes="status-model", id="sb-model")
            yield Static(" │ ", classes="status-sep")
            yield Static(self._tokens_label(), classes="status-tokens", id="sb-tokens")
            yield Static(" │ ", classes="status-sep")
            yield Static(self._cost_label(), classes="status-cost", id="sb-cost")
            yield Static(" │ ", classes="status-sep")
            yield Static(self._branch_label(), classes="status-branch", id="sb-branch")
            yield Static(" │ ", classes="status-sep")
            yield Static(self._mode_label(), classes="status-mode", id="sb-mode")
            yield Static(" │ ", classes="status-sep")
            yield Static(self._cwd_label(), classes="status-cwd", id="sb-cwd")
            yield Static(self._session_label(), classes="status-session", id="sb-session")

    # ------------------------------------------------------------------
    # Label builders
    # ------------------------------------------------------------------

    def _model_label(self) -> str:
        # Claude Code: claude orange for model label, ● dot when streaming
        streaming_dot = f"[blink bold {ACCENT}]●[/] " if self.is_streaming else ""
        short = self._shorten_model(self.model)
        return f"{streaming_dot}[bold {ACCENT}]{short}[/bold {ACCENT}]"

    def _tokens_label(self) -> str:
        total = self.input_tokens + self.output_tokens
        if total == 0:
            return "0 tok"
        if total >= 1_000_000:
            return f"{total / 1_000_000:.1f}M tok"
        if total >= 1_000:
            return f"{total / 1_000:.1f}k tok"
        return f"{total} tok"

    def _cost_label(self) -> str:
        if self.cost_usd < 0.001:
            return "$0.000"
        if self.cost_usd < 1.0:
            return f"${self.cost_usd:.4f}"
        return f"${self.cost_usd:.2f}"

    def _branch_label(self) -> str:
        if not self.git_branch:
            return ""
        return f"⎇ {self.git_branch}"

    def _mode_label(self) -> str:
        mode_map = {
            "default": "default",
            "auto": "auto-approve",
            "bypassPermissions": "[bold red]bypass[/bold red]",
        }
        return mode_map.get(self.permission_mode, self.permission_mode)

    def _cwd_label(self) -> str:
        cwd = self._cwd
        # Abbreviate home dir
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        # Truncate long paths from the left
        max_len = 40
        if len(cwd) > max_len:
            cwd = "…" + cwd[-(max_len - 1):]
        return cwd

    def _session_label(self) -> str:
        if not self.session_id:
            return ""
        return f" {self.session_id[:8]}"

    @staticmethod
    def _shorten_model(model: str) -> str:
        """Turn 'claude-sonnet-4-6-20250514' → 'Sonnet 4.6'."""
        import re
        m = model.lower()
        # Strip provider prefix
        for prefix in ("claude-", "anthropic/claude-", "anthropic/"):
            if m.startswith(prefix):
                m = m[len(prefix):]
                break
        # Strip trailing date like -20250514
        m = re.sub(r"-\d{8}$", "", m)
        # Normalise separators
        m = re.sub(r"[-_]", " ", m).title()
        return m

    # ------------------------------------------------------------------
    # Watchers — update individual Static widgets without full recompose
    # ------------------------------------------------------------------

    def watch_model(self, value: str) -> None:
        self._safe_update("sb-model", self._model_label())

    def watch_is_streaming(self, value: bool) -> None:
        self._safe_update("sb-model", self._model_label())

    def watch_input_tokens(self, value: int) -> None:
        self._safe_update("sb-tokens", self._tokens_label())
        self._safe_update("sb-cost", self._cost_label())

    def watch_output_tokens(self, value: int) -> None:
        self._safe_update("sb-tokens", self._tokens_label())
        self._safe_update("sb-cost", self._cost_label())

    def watch_cost_usd(self, value: float) -> None:
        self._safe_update("sb-cost", self._cost_label())

    def watch_git_branch(self, value: str) -> None:
        self._safe_update("sb-branch", self._branch_label())

    def watch_permission_mode(self, value: str) -> None:
        self._safe_update("sb-mode", self._mode_label())

    def watch_session_id(self, value: str) -> None:
        self._safe_update("sb-session", self._session_label())

    def _safe_update(self, widget_id: str, text: str) -> None:
        try:
            widget = self.query_one(f"#{widget_id}", Static)
            widget.update(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_cwd(self, cwd: str) -> None:
        self._cwd = cwd
        self._safe_update("sb-cwd", self._cwd_label())

    def add_tokens(self, input_tokens: int, output_tokens: int, cost: float = 0.0) -> None:
        """Accumulate token usage from a completed query turn."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost

    def reset_for_new_session(self) -> None:
        """Called after /clear — resets counts."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
