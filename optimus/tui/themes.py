"""
optimus/tui/themes.py

Port of: utils/theme.ts — the six-theme palette system.

Theme dataclass mirrors the TS Theme type field-for-field (snake_cased).
THEME_NAMES / THEME_SETTINGS / get_theme() are the same API. Colours are
stored as hex (Textual/Rich take hex; the TS rgb(...) strings are converted).

Omitted per CLAUDE.md rules:
  - chalk/ANSI escape generation (themeColorToAnsi) — Rich handles colour
    downgrade itself; the ansi themes store "ansi_*" names that map to
    Rich's 16-colour names.
  - shimmer variants for the rainbow_* keys are kept (used by ultrathink
    highlighting when ported).

RE-ENTRY: the widget layer (theme.tcss + DEFAULT_CSS blocks) still hardcodes
darkTheme values. Wiring every widget through get_theme() is the follow-up;
new code should import colours from here.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional


def _rgb(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass(frozen=True)
class Theme:
    """utils/theme.ts Theme — one attribute per palette key."""
    auto_accept: str
    bash_border: str
    claude: str
    claude_shimmer: str
    claude_blue_for_system_spinner: str
    claude_blue_shimmer_for_system_spinner: str
    permission: str
    permission_shimmer: str
    plan_mode: str
    ide: str
    prompt_border: str
    prompt_border_shimmer: str
    text: str
    inverse_text: str
    inactive: str
    inactive_shimmer: str
    subtle: str
    suggestion: str
    remember: str
    background: str
    success: str
    error: str
    warning: str
    merged: str
    warning_shimmer: str
    diff_added: str
    diff_removed: str
    diff_added_dimmed: str
    diff_removed_dimmed: str
    diff_added_word: str
    diff_removed_word: str
    red_for_subagents_only: str
    blue_for_subagents_only: str
    green_for_subagents_only: str
    yellow_for_subagents_only: str
    purple_for_subagents_only: str
    orange_for_subagents_only: str
    pink_for_subagents_only: str
    cyan_for_subagents_only: str
    professional_blue: str
    chrome_yellow: str
    clawd_body: str
    clawd_background: str
    user_message_background: str
    user_message_background_hover: str
    message_actions_background: str
    selection_bg: str
    bash_message_background_color: str
    memory_background_color: str
    rate_limit_fill: str
    rate_limit_empty: str
    fast_mode: str
    fast_mode_shimmer: str
    brief_label_you: str
    brief_label_claude: str
    rainbow_red: str
    rainbow_orange: str
    rainbow_yellow: str
    rainbow_green: str
    rainbow_blue: str
    rainbow_indigo: str
    rainbow_violet: str
    rainbow_red_shimmer: str
    rainbow_orange_shimmer: str
    rainbow_yellow_shimmer: str
    rainbow_green_shimmer: str
    rainbow_blue_shimmer: str
    rainbow_indigo_shimmer: str
    rainbow_violet_shimmer: str


THEME_NAMES = (
    "dark",
    "light",
    "light-daltonized",
    "dark-daltonized",
    "light-ansi",
    "dark-ansi",
)
THEME_SETTINGS = ("auto",) + THEME_NAMES

# Shared rainbow block (identical across the four RGB themes)
_RAINBOW = dict(
    rainbow_red=_rgb(235, 95, 87),
    rainbow_orange=_rgb(245, 139, 87),
    rainbow_yellow=_rgb(250, 195, 95),
    rainbow_green=_rgb(145, 200, 130),
    rainbow_blue=_rgb(130, 170, 220),
    rainbow_indigo=_rgb(155, 130, 200),
    rainbow_violet=_rgb(200, 130, 180),
    rainbow_red_shimmer=_rgb(250, 155, 147),
    rainbow_orange_shimmer=_rgb(255, 185, 137),
    rainbow_yellow_shimmer=_rgb(255, 225, 155),
    rainbow_green_shimmer=_rgb(185, 230, 180),
    rainbow_blue_shimmer=_rgb(180, 205, 240),
    rainbow_indigo_shimmer=_rgb(195, 180, 230),
    rainbow_violet_shimmer=_rgb(230, 180, 210),
)

# Agent colours shared by dark + light RGB themes (Tailwind 600 series)
_AGENT_600 = dict(
    red_for_subagents_only=_rgb(220, 38, 38),
    blue_for_subagents_only=_rgb(37, 99, 235),
    green_for_subagents_only=_rgb(22, 163, 74),
    yellow_for_subagents_only=_rgb(202, 138, 4),
    purple_for_subagents_only=_rgb(147, 51, 234),
    orange_for_subagents_only=_rgb(234, 88, 12),
    pink_for_subagents_only=_rgb(219, 39, 119),
    cyan_for_subagents_only=_rgb(8, 145, 178),
)

DARK_THEME = Theme(
    auto_accept=_rgb(175, 135, 255),
    bash_border=_rgb(253, 93, 177),
    claude=_rgb(215, 119, 87),
    claude_shimmer=_rgb(235, 159, 127),
    claude_blue_for_system_spinner=_rgb(147, 165, 255),
    claude_blue_shimmer_for_system_spinner=_rgb(177, 195, 255),
    permission=_rgb(177, 185, 249),
    permission_shimmer=_rgb(207, 215, 255),
    plan_mode=_rgb(72, 150, 140),
    ide=_rgb(71, 130, 200),
    prompt_border=_rgb(136, 136, 136),
    prompt_border_shimmer=_rgb(166, 166, 166),
    text=_rgb(255, 255, 255),
    inverse_text=_rgb(0, 0, 0),
    inactive=_rgb(153, 153, 153),
    inactive_shimmer=_rgb(193, 193, 193),
    subtle=_rgb(80, 80, 80),
    suggestion=_rgb(177, 185, 249),
    remember=_rgb(177, 185, 249),
    background=_rgb(0, 204, 204),
    success=_rgb(78, 186, 101),
    error=_rgb(255, 107, 128),
    warning=_rgb(255, 193, 7),
    merged=_rgb(175, 135, 255),
    warning_shimmer=_rgb(255, 223, 57),
    diff_added=_rgb(34, 92, 43),
    diff_removed=_rgb(122, 41, 54),
    diff_added_dimmed=_rgb(71, 88, 74),
    diff_removed_dimmed=_rgb(105, 72, 77),
    diff_added_word=_rgb(56, 166, 96),
    diff_removed_word=_rgb(179, 89, 107),
    **_AGENT_600,
    professional_blue=_rgb(106, 155, 204),
    chrome_yellow=_rgb(251, 188, 4),
    clawd_body=_rgb(215, 119, 87),
    clawd_background=_rgb(0, 0, 0),
    user_message_background=_rgb(55, 55, 55),
    user_message_background_hover=_rgb(70, 70, 70),
    message_actions_background=_rgb(44, 50, 62),
    selection_bg=_rgb(38, 79, 120),
    bash_message_background_color=_rgb(65, 60, 65),
    memory_background_color=_rgb(55, 65, 70),
    rate_limit_fill=_rgb(177, 185, 249),
    rate_limit_empty=_rgb(80, 83, 112),
    fast_mode=_rgb(255, 120, 20),
    fast_mode_shimmer=_rgb(255, 165, 70),
    brief_label_you=_rgb(122, 180, 232),
    brief_label_claude=_rgb(215, 119, 87),
    **_RAINBOW,
)

LIGHT_THEME = Theme(
    auto_accept=_rgb(135, 0, 255),
    bash_border=_rgb(255, 0, 135),
    claude=_rgb(215, 119, 87),
    claude_shimmer=_rgb(245, 149, 117),
    claude_blue_for_system_spinner=_rgb(87, 105, 247),
    claude_blue_shimmer_for_system_spinner=_rgb(117, 135, 255),
    permission=_rgb(87, 105, 247),
    permission_shimmer=_rgb(137, 155, 255),
    plan_mode=_rgb(0, 102, 102),
    ide=_rgb(71, 130, 200),
    prompt_border=_rgb(153, 153, 153),
    prompt_border_shimmer=_rgb(183, 183, 183),
    text=_rgb(0, 0, 0),
    inverse_text=_rgb(255, 255, 255),
    inactive=_rgb(102, 102, 102),
    inactive_shimmer=_rgb(142, 142, 142),
    subtle=_rgb(175, 175, 175),
    suggestion=_rgb(87, 105, 247),
    remember=_rgb(0, 0, 255),
    background=_rgb(0, 153, 153),
    success=_rgb(44, 122, 57),
    error=_rgb(171, 43, 63),
    warning=_rgb(150, 108, 30),
    merged=_rgb(135, 0, 255),
    warning_shimmer=_rgb(200, 158, 80),
    diff_added=_rgb(105, 219, 124),
    diff_removed=_rgb(255, 168, 180),
    diff_added_dimmed=_rgb(199, 225, 203),
    diff_removed_dimmed=_rgb(253, 210, 216),
    diff_added_word=_rgb(47, 157, 68),
    diff_removed_word=_rgb(209, 69, 75),
    **_AGENT_600,
    professional_blue=_rgb(106, 155, 204),
    chrome_yellow=_rgb(251, 188, 4),
    clawd_body=_rgb(215, 119, 87),
    clawd_background=_rgb(0, 0, 0),
    user_message_background=_rgb(240, 240, 240),
    user_message_background_hover=_rgb(252, 252, 252),
    message_actions_background=_rgb(232, 236, 244),
    selection_bg=_rgb(180, 213, 255),
    bash_message_background_color=_rgb(250, 245, 250),
    memory_background_color=_rgb(230, 245, 250),
    rate_limit_fill=_rgb(87, 105, 247),
    rate_limit_empty=_rgb(39, 47, 111),
    fast_mode=_rgb(255, 106, 0),
    fast_mode_shimmer=_rgb(255, 150, 50),
    brief_label_you=_rgb(37, 99, 235),
    brief_label_claude=_rgb(215, 119, 87),
    **_RAINBOW,
)

LIGHT_DALTONIZED_THEME = Theme(
    auto_accept=_rgb(135, 0, 255),
    bash_border=_rgb(0, 102, 204),
    claude=_rgb(255, 153, 51),
    claude_shimmer=_rgb(255, 183, 101),
    claude_blue_for_system_spinner=_rgb(51, 102, 255),
    claude_blue_shimmer_for_system_spinner=_rgb(101, 152, 255),
    permission=_rgb(51, 102, 255),
    permission_shimmer=_rgb(101, 152, 255),
    plan_mode=_rgb(51, 102, 102),
    ide=_rgb(71, 130, 200),
    prompt_border=_rgb(153, 153, 153),
    prompt_border_shimmer=_rgb(183, 183, 183),
    text=_rgb(0, 0, 0),
    inverse_text=_rgb(255, 255, 255),
    inactive=_rgb(102, 102, 102),
    inactive_shimmer=_rgb(142, 142, 142),
    subtle=_rgb(175, 175, 175),
    suggestion=_rgb(51, 102, 255),
    remember=_rgb(51, 102, 255),
    background=_rgb(0, 153, 153),
    success=_rgb(0, 102, 153),
    error=_rgb(204, 0, 0),
    warning=_rgb(255, 153, 0),
    merged=_rgb(135, 0, 255),
    warning_shimmer=_rgb(255, 183, 50),
    diff_added=_rgb(153, 204, 255),
    diff_removed=_rgb(255, 204, 204),
    diff_added_dimmed=_rgb(209, 231, 253),
    diff_removed_dimmed=_rgb(255, 233, 233),
    diff_added_word=_rgb(51, 102, 204),
    diff_removed_word=_rgb(153, 51, 51),
    red_for_subagents_only=_rgb(204, 0, 0),
    blue_for_subagents_only=_rgb(0, 102, 204),
    green_for_subagents_only=_rgb(0, 204, 0),
    yellow_for_subagents_only=_rgb(255, 204, 0),
    purple_for_subagents_only=_rgb(128, 0, 128),
    orange_for_subagents_only=_rgb(255, 128, 0),
    pink_for_subagents_only=_rgb(255, 102, 178),
    cyan_for_subagents_only=_rgb(0, 178, 178),
    professional_blue=_rgb(106, 155, 204),
    chrome_yellow=_rgb(251, 188, 4),
    clawd_body=_rgb(215, 119, 87),
    clawd_background=_rgb(0, 0, 0),
    user_message_background=_rgb(220, 220, 220),
    user_message_background_hover=_rgb(232, 232, 232),
    message_actions_background=_rgb(210, 216, 226),
    selection_bg=_rgb(180, 213, 255),
    bash_message_background_color=_rgb(250, 245, 250),
    memory_background_color=_rgb(230, 245, 250),
    rate_limit_fill=_rgb(51, 102, 255),
    rate_limit_empty=_rgb(23, 46, 114),
    fast_mode=_rgb(255, 106, 0),
    fast_mode_shimmer=_rgb(255, 150, 50),
    brief_label_you=_rgb(37, 99, 235),
    brief_label_claude=_rgb(255, 153, 51),
    **_RAINBOW,
)

DARK_DALTONIZED_THEME = Theme(
    auto_accept=_rgb(175, 135, 255),
    bash_border=_rgb(51, 153, 255),
    claude=_rgb(255, 153, 51),
    claude_shimmer=_rgb(255, 183, 101),
    claude_blue_for_system_spinner=_rgb(153, 204, 255),
    claude_blue_shimmer_for_system_spinner=_rgb(183, 224, 255),
    permission=_rgb(153, 204, 255),
    permission_shimmer=_rgb(183, 224, 255),
    plan_mode=_rgb(102, 153, 153),
    ide=_rgb(71, 130, 200),
    prompt_border=_rgb(136, 136, 136),
    prompt_border_shimmer=_rgb(166, 166, 166),
    text=_rgb(255, 255, 255),
    inverse_text=_rgb(0, 0, 0),
    inactive=_rgb(153, 153, 153),
    inactive_shimmer=_rgb(193, 193, 193),
    subtle=_rgb(80, 80, 80),
    suggestion=_rgb(153, 204, 255),
    remember=_rgb(153, 204, 255),
    background=_rgb(0, 204, 204),
    success=_rgb(51, 153, 255),
    error=_rgb(255, 102, 102),
    warning=_rgb(255, 204, 0),
    merged=_rgb(175, 135, 255),
    warning_shimmer=_rgb(255, 234, 50),
    diff_added=_rgb(0, 68, 102),
    diff_removed=_rgb(102, 0, 0),
    diff_added_dimmed=_rgb(62, 81, 91),
    diff_removed_dimmed=_rgb(62, 44, 44),
    diff_added_word=_rgb(0, 119, 179),
    diff_removed_word=_rgb(179, 0, 0),
    red_for_subagents_only=_rgb(255, 102, 102),
    blue_for_subagents_only=_rgb(102, 178, 255),
    green_for_subagents_only=_rgb(102, 255, 102),
    yellow_for_subagents_only=_rgb(255, 255, 102),
    purple_for_subagents_only=_rgb(178, 102, 255),
    orange_for_subagents_only=_rgb(255, 178, 102),
    pink_for_subagents_only=_rgb(255, 153, 204),
    cyan_for_subagents_only=_rgb(102, 204, 204),
    professional_blue=_rgb(106, 155, 204),
    chrome_yellow=_rgb(251, 188, 4),
    clawd_body=_rgb(215, 119, 87),
    clawd_background=_rgb(0, 0, 0),
    user_message_background=_rgb(55, 55, 55),
    user_message_background_hover=_rgb(70, 70, 70),
    message_actions_background=_rgb(44, 50, 62),
    selection_bg=_rgb(38, 79, 120),
    bash_message_background_color=_rgb(65, 60, 65),
    memory_background_color=_rgb(55, 65, 70),
    rate_limit_fill=_rgb(153, 204, 255),
    rate_limit_empty=_rgb(69, 92, 115),
    fast_mode=_rgb(255, 120, 20),
    fast_mode_shimmer=_rgb(255, 165, 70),
    brief_label_you=_rgb(122, 180, 232),
    brief_label_claude=_rgb(255, 153, 51),
    **_RAINBOW,
)


def _ansi_theme(mapping: dict) -> Theme:
    """Build an ANSI theme from Rich 16-colour names."""
    return Theme(**mapping)


# ANSI themes use Rich's named 16 colours ("bright_red" etc. — the TS uses
# chalk names like ansi:redBright; the mapping is 1:1).
_LIGHT_ANSI = dict(
    auto_accept="magenta", bash_border="magenta",
    claude="bright_red", claude_shimmer="bright_yellow",
    claude_blue_for_system_spinner="blue",
    claude_blue_shimmer_for_system_spinner="bright_blue",
    permission="blue", permission_shimmer="bright_blue",
    plan_mode="cyan", ide="bright_blue",
    prompt_border="white", prompt_border_shimmer="bright_white",
    text="black", inverse_text="white",
    inactive="bright_black", inactive_shimmer="white",
    subtle="bright_black", suggestion="blue", remember="blue",
    background="cyan", success="green", error="red", warning="yellow",
    merged="magenta", warning_shimmer="bright_yellow",
    diff_added="green", diff_removed="red",
    diff_added_dimmed="green", diff_removed_dimmed="red",
    diff_added_word="bright_green", diff_removed_word="bright_red",
    red_for_subagents_only="red", blue_for_subagents_only="blue",
    green_for_subagents_only="green", yellow_for_subagents_only="yellow",
    purple_for_subagents_only="magenta", orange_for_subagents_only="bright_red",
    pink_for_subagents_only="bright_magenta", cyan_for_subagents_only="cyan",
    professional_blue="bright_blue", chrome_yellow="yellow",
    clawd_body="bright_red", clawd_background="black",
    user_message_background="white", user_message_background_hover="bright_white",
    message_actions_background="white", selection_bg="cyan",
    bash_message_background_color="bright_white",
    memory_background_color="white",
    rate_limit_fill="yellow", rate_limit_empty="black",
    fast_mode="red", fast_mode_shimmer="bright_red",
    brief_label_you="blue", brief_label_claude="bright_red",
    rainbow_red="red", rainbow_orange="bright_red", rainbow_yellow="yellow",
    rainbow_green="green", rainbow_blue="cyan", rainbow_indigo="blue",
    rainbow_violet="magenta",
    rainbow_red_shimmer="bright_red", rainbow_orange_shimmer="yellow",
    rainbow_yellow_shimmer="bright_yellow", rainbow_green_shimmer="bright_green",
    rainbow_blue_shimmer="bright_cyan", rainbow_indigo_shimmer="bright_blue",
    rainbow_violet_shimmer="bright_magenta",
)

_DARK_ANSI = dict(
    _LIGHT_ANSI,
    auto_accept="bright_magenta", bash_border="bright_magenta",
    claude_blue_for_system_spinner="bright_blue",
    permission="bright_blue", plan_mode="bright_cyan", ide="blue",
    text="bright_white", inverse_text="black",
    inactive="white", inactive_shimmer="bright_white", subtle="white",
    suggestion="bright_blue", remember="bright_blue",
    background="bright_cyan", success="bright_green", error="bright_red",
    warning="bright_yellow", merged="bright_magenta",
    red_for_subagents_only="bright_red", blue_for_subagents_only="bright_blue",
    green_for_subagents_only="bright_green", yellow_for_subagents_only="bright_yellow",
    purple_for_subagents_only="bright_magenta", orange_for_subagents_only="bright_red",
    pink_for_subagents_only="bright_magenta", cyan_for_subagents_only="bright_cyan",
    user_message_background="bright_black", user_message_background_hover="white",
    message_actions_background="bright_black", selection_bg="blue",
    bash_message_background_color="black", memory_background_color="bright_black",
    rate_limit_empty="white",
    brief_label_you="bright_blue",
)

LIGHT_ANSI_THEME = _ansi_theme(_LIGHT_ANSI)
DARK_ANSI_THEME = _ansi_theme(_DARK_ANSI)

_THEMES: dict[str, Theme] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "light-daltonized": LIGHT_DALTONIZED_THEME,
    "dark-daltonized": DARK_DALTONIZED_THEME,
    "light-ansi": LIGHT_ANSI_THEME,
    "dark-ansi": DARK_ANSI_THEME,
}


def get_theme(theme_name: str) -> Theme:
    """utils/theme.ts getTheme — unknown names fall back to dark."""
    return _THEMES.get(theme_name, DARK_THEME)


# ---------------------------------------------------------------------------
# Active-theme state (useTheme equivalent — module-level, no React context)
# ---------------------------------------------------------------------------

_active_name: str = "dark"


def set_active_theme(name: str) -> Theme:
    global _active_name
    if name in _THEMES:
        _active_name = name
    return _THEMES[_active_name]


def active_theme() -> Theme:
    return _THEMES[_active_name]


def active_theme_name() -> str:
    return _active_name
