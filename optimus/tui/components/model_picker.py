"""
optimus/tui/components/model_picker.py

ModelPickerModal — interactive model selection menu for /model.

Shows every model the configured provider endpoints report (fetched by
llm_client.available_models() before the modal is pushed), grouped by
provider, with the active model highlighted. Arrow keys / j k to move,
Enter to select, Esc to cancel. Dismisses with the chosen routing id
("claude-sonnet-5", "openai:gpt-5-mini", …) or None on cancel.
"""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

_PROVIDER_ORDER = ("anthropic", "openai", "gemini", "zai", "deepseek", "ollama")


class ModelPickerModal(ModalScreen[Optional[str]]):
    """Full-screen modal listing selectable models grouped by provider."""

    DEFAULT_CSS = """
    ModelPickerModal {
        align: center middle;
        background: rgba(5, 10, 30, 0.85);
    }
    ModelPickerModal > Vertical {
        width: 84;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        background: #0a1628;
        border: solid #264f78;
        padding: 1 2;
    }
    ModelPickerModal .picker-title {
        text-align: center;
        color: #b1b9f9;
        text-style: bold;
        margin-bottom: 1;
    }
    ModelPickerModal OptionList {
        height: auto;
        max-height: 24;
        background: #0a1628;
        border: solid #264f78;
        margin-bottom: 1;
    }
    ModelPickerModal .picker-hint {
        color: #2a4a6a;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]

    def __init__(self, models: list[dict], current: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._models = models
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("◈  SELECT MODEL", classes="picker-title")
            yield OptionList(*self._build_options(), id="model-options")
            yield Static(
                "[dim]↑/↓ or j/k[/dim] move   [dim]Enter[/dim] select   "
                "[dim]Esc[/dim] cancel",
                classes="picker-hint",
            )

    def _build_options(self) -> list:
        by_provider: dict[str, list[dict]] = {}
        for m in self._models:
            by_provider.setdefault(m.get("provider", "?"), []).append(m)

        options: list = []
        providers = [p for p in _PROVIDER_ORDER if p in by_provider]
        providers += [p for p in by_provider if p not in _PROVIDER_ORDER]
        for provider in providers:
            entries = by_provider[provider]
            options.append(
                Option(
                    f"[bold underline]{provider}[/bold underline] "
                    f"[dim]({len(entries)})[/dim]",
                    disabled=True,
                )
            )
            for m in sorted(entries, key=lambda x: x["id"]):
                marker = "▶ " if m["id"] == self._current else "  "
                desc = f" [dim]— {m['description']}[/dim]" if m.get("description") else ""
                tags = (
                    f"  [dim]\\[{', '.join(m['tags'])}][/dim]"
                    if m.get("tags") else ""
                )
                options.append(
                    Option(f"{marker}[bold]{m['id']}[/bold]{desc}{tags}", id=m["id"])
                )
        return options

    def on_mount(self) -> None:
        ol = self.query_one("#model-options", OptionList)
        ol.focus()
        # Land the cursor on the active model so Enter with no movement is a
        # no-op switch, not a surprise. Deferred: OptionList resets its
        # highlight to 0 during its own mount refresh.
        def _highlight_current() -> None:
            try:
                ol.highlighted = ol.get_option_index(self._current)
            except Exception:
                pass  # current model not listed (e.g. key removed) — top is fine

        self.call_after_refresh(_highlight_current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_cursor_down(self) -> None:
        self.query_one("#model-options", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#model-options", OptionList).action_cursor_up()
