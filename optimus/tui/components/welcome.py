"""
optimus/tui/components/welcome.py

Welcome screen shown before the first message — mirrors LogoV2.tsx / WelcomeV2.tsx.

Layout (horizontal, two columns separated by a vertical rule):

  ┌─ Claude Code v…  ──────────────────────────────────┐
  │                    │                                │
  │  Welcome back!     │  Tips for getting started      │
  │                    │  Run /init to create …         │
  │  [robot art]       │                                │
  │                    │  Recent activity               │
  │  Sonnet 4.6 · API  │  No recent activity            │
  │  ~/projects/foo    │  /resume for more              │
  │                    │                                │
  └────────────────────────────────────────────────────┘

Colors: all from Claude Code darkTheme.
Port of: components/LogoV2/LogoV2.tsx
         components/LogoV2/WelcomeV2.tsx
         components/LogoV2/feedConfigs.tsx
"""
from __future__ import annotations

import os
import re
from typing import Optional

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal, Vertical

from optimus.tui.brand import ACCENT, NAME

# ---------------------------------------------------------------------------
# Robot art — user-supplied ASCII figure, claude orange body.
# '─' (U+2500) acts as transparent spacing; everything else is orange.
# ---------------------------------------------------------------------------

_RAW_ROBOT = """\
───────────▄▄▄▄▄▄▄▄▄───────────
────────▄█████████████▄────────
█████──█████████████████──█████
▐████▌─▀███▄───────▄███▀─▐████▌
─█████▄──▀███▄───▄███▀──▄█████─
─▐██▀███▄──▀███▄███▀──▄███▀██▌─
──███▄▀███▄──▀███▀──▄███▀▄███──
──▐█▄▀█▄▀███─▄─▀─▄─███▀▄█▀▄█▌──
───███▄▀█▄██─██▄██─██▄█▀▄███───
────▀███▄▀██─█████─██▀▄███▀────
───█▄─▀█████─█████─█████▀─▄█───
───███────────███────────███───
───███▄────▄█─███─█▄────▄███───
───█████─▄███─███─███▄─█████───
───█████─████─███─████─█████───
───█████─████─███─████─█████───
───█████─████─███─████─█████───
───█████─████▄▄▄▄▄████─█████───
────▀███─█████████████─███▀────
──────▀█─███─▄▄▄▄▄─███─█▀──────
─────────▀█▌▐█████▌▐█▀─────────
────────────███████────────────"""


def _markup_art(raw: str) -> list[str]:
    """
    Split each line into orange block-char segments and background-coloured
    '─' segments so the dashes disappear against the #1a1a1a background.
    """
    DASH = "─"   # ─
    BG   = "#1a1a1a"
    FG   = ACCENT
    lines = []
    for line in raw.splitlines():
        parts: list[str] = []
        i = 0
        while i < len(line):
            if line[i] == DASH:
                j = i
                while j < len(line) and line[j] == DASH:
                    j += 1
                parts.append(f"[{BG}]{'─' * (j - i)}[/{BG}]")
                i = j
            else:
                j = i
                while j < len(line) and line[j] != DASH:
                    j += 1
                parts.append(f"[bold {FG}]{line[i:j]}[/bold {FG}]")
                i = j
        lines.append("".join(parts))
    return lines


_ROBOT_LINES = _markup_art(_RAW_ROBOT)
ROBOT_ART = "\n".join(_ROBOT_LINES)

# ---------------------------------------------------------------------------
# Tips for getting started — mirrors createProjectOnboardingFeed()
# ---------------------------------------------------------------------------

_TIPS = [
    "Run /init to create a CLAUDE.md file",
    "Ask Claude to edit files, run tests,",
    "  or explore your codebase",
    "Use /help to see all commands",
]

# ---------------------------------------------------------------------------
# Helper: shorten model name (mirrors renderModelName / getEffortSuffix)
# ---------------------------------------------------------------------------

def _short_model(model: str) -> str:
    """'claude-sonnet-4-6-20250514' → 'Sonnet 4.6'"""
    m = model.lower()
    for prefix in ("anthropic/claude-", "claude-", "anthropic/"):
        if m.startswith(prefix):
            m = m[len(prefix):]
            break
    m = re.sub(r"-\d{8}$", "", m)
    m = re.sub(r"[-_]", " ", m).title()
    return m


def _short_cwd(cwd: str) -> str:
    """Abbreviate home dir and truncate long paths."""
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    max_len = 34
    if len(cwd) > max_len:
        cwd = "…" + cwd[-(max_len - 1):]
    return cwd


# ---------------------------------------------------------------------------
# WelcomeWidget
# ---------------------------------------------------------------------------

class WelcomeWidget(Widget):
    """
    Welcome screen mirroring Claude Code's LogoV2 / WelcomeV2.
    Shown in the message list until the first user message is submitted.
    """

    DEFAULT_CSS = """
    WelcomeWidget {
        height: auto;
        margin: 1 2 1 2;
        background: #1a1a1a;
        border: round #d77757;
        padding: 0;
    }
    WelcomeWidget .welcome-row {
        height: auto;
    }
    WelcomeWidget .welcome-left {
        width: 37;
        min-width: 37;
        height: auto;
        padding: 1 1 1 2;
        background: #1a1a1a;
    }
    WelcomeWidget .welcome-sep {
        width: 1;
        height: auto;
        background: #d77757;
        color: #d77757;
    }
    WelcomeWidget .welcome-right {
        width: 1fr;
        height: auto;
        padding: 1 2 1 2;
        background: #1a1a1a;
    }
    WelcomeWidget .welcome-title {
        color: #ffffff;
        text-style: bold;
        margin-bottom: 1;
    }
    WelcomeWidget .welcome-robot {
        height: auto;
        margin-bottom: 1;
    }
    WelcomeWidget .welcome-meta {
        color: #999999;
    }
    WelcomeWidget .feed-title {
        color: #d77757;
        text-style: bold;
        margin-bottom: 0;
    }
    WelcomeWidget .feed-item {
        color: #ffffff;
    }
    WelcomeWidget .feed-empty {
        color: #999999;
    }
    WelcomeWidget .feed-footer {
        color: #505050;
        margin-top: 0;
    }
    WelcomeWidget .feed-section {
        height: auto;
        margin-bottom: 1;
    }
    """.replace("#d77757", ACCENT)

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        cwd: Optional[str] = None,
        recent_sessions: Optional[list[str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model = model
        self._cwd = cwd or os.getcwd()
        self._recent: list[str] = recent_sessions or []

    def compose(self) -> ComposeResult:
        model_label = _short_model(self._model)
        cwd_label = _short_cwd(self._cwd)

        with Horizontal(classes="welcome-row"):
            # ── Left panel ────────────────────────────────────────────────
            with Vertical(classes="welcome-left"):
                yield Static(
                    "[bold #ffffff]Welcome back![/bold #ffffff]",
                    classes="welcome-title",
                )
                yield Static(ROBOT_ART, classes="welcome-robot")
                yield Static(
                    f"[#999999]{model_label} · API Usage[/#999999]",
                    classes="welcome-meta",
                )
                yield Static(
                    f"[dim #999999]{cwd_label}[/dim #999999]",
                    classes="welcome-meta",
                )

            # ── Vertical separator ────────────────────────────────────────
            yield Static(
                "\n".join(["│"] * 28),
                classes="welcome-sep",
            )

            # ── Right panel ───────────────────────────────────────────────
            with Vertical(classes="welcome-right"):
                # Tips for getting started
                with Vertical(classes="feed-section"):
                    yield Static(
                        f"[bold {ACCENT}]Tips for getting started[/bold {ACCENT}]",
                        classes="feed-title",
                    )
                    for tip in _TIPS:
                        yield Static(tip, classes="feed-item")

                # Recent activity
                with Vertical(classes="feed-section"):
                    yield Static(
                        f"[bold {ACCENT}]Recent activity[/bold {ACCENT}]",
                        classes="feed-title",
                    )
                    if self._recent:
                        for session in self._recent[:3]:
                            yield Static(
                                f"[#ffffff]{session[:40]}[/#ffffff]",
                                classes="feed-item",
                            )
                        yield Static(
                            "[dim]/resume for more[/dim]",
                            classes="feed-footer",
                        )
                    else:
                        yield Static(
                            "[#999999]No recent activity[/#999999]",
                            classes="feed-empty",
                        )

    def update_model(self, model: str) -> None:
        """Called when model switches — refresh meta label."""
        self._model = model
        self.refresh(recompose=True)
