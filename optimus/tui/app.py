"""
optimus/tui/app.py

Textual Application entry point for Optimus Mark I.

Port of: the React/Ink App.tsx root component + the useApp() / useRepl() hooks.

The app:
  - Loads the JARVIS theme CSS
  - Mounts the ReplScreen as the initial screen
  - Exports OptimusApp for use by main.py's launch_repl()
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any

from textual.app import App

from optimus.tui.screens.repl import ReplScreen
from optimus.tui.brand import ACCENT, NAME


# ---------------------------------------------------------------------------
# Dynamic theme — load theme.tcss and substitute the accent colour so that
# OPTIMUS_ACCENT_COLOR takes effect without touching any CSS file.
# The canonical placeholder colour in theme.tcss is #d77757 (Claude orange).
# ---------------------------------------------------------------------------
_THEME_PATH = Path(__file__).parent / "theme.tcss"

def _load_css() -> str:
    if _THEME_PATH.exists():
        return _THEME_PATH.read_text(encoding="utf-8").replace("#d77757", ACCENT)
    # Minimal fallback when theme.tcss is absent
    return f"""
    Screen {{ background: #1a1a1a; color: #ffffff; }}
    """


class OptimusApp(App):
    """
    The root Textual application for Optimus Mark I.

    All chat interaction happens inside ReplScreen.  Additional screens
    (settings, help overlay, session picker) can be pushed on top of it
    as the feature set grows.
    """

    # Theme CSS with accent colour substituted from OPTIMUS_ACCENT_COLOR
    CSS = _load_css()

    TITLE = NAME
    SUB_TITLE = "Mark I"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        prompt: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        tool_permission_context: dict,
        mcp_clients: list,
        tools: list,
        system_prompt: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
        verbose: bool = False,
        debug: bool = False,
        session_id: str,
        initial_messages: Optional[list] = None,
        thinking_config: Optional[dict] = None,
        betas: Optional[list] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._repl_kwargs = dict(
            prompt=prompt,
            model=model,
            tool_permission_context=tool_permission_context,
            mcp_clients=mcp_clients,
            tools=tools,
            system_prompt=system_prompt,
            append_system_prompt=append_system_prompt,
            verbose=verbose,
            debug=debug,
            session_id=session_id,
            initial_messages=initial_messages or [],
            thinking_config=thinking_config or {"type": "adaptive"},
            betas=betas or [],
            name=name,
        )

    def on_mount(self) -> None:
        """Push the REPL screen immediately after the app mounts."""
        self.push_screen(ReplScreen(**self._repl_kwargs))

    def action_quit(self) -> None:
        self.exit()
