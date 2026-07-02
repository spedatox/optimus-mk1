# Optimus Mark I — TUI Architecture

**Last updated:** 2026-04-20

---

## Overview

The Optimus TUI is a full-featured terminal chat interface built with
[Textual](https://github.com/Textualize/textual).  It is a 1:1 feature port of
the Claude Code React/Ink UI, restyled with a JARVIS navy-and-cyan colour
scheme.

```
optimus/tui/
├── __init__.py              # exports OptimusApp
├── app.py                   # Textual App root — loads theme, mounts ReplScreen
├── theme.tcss               # JARVIS CSS theme (global)
├── components/
│   ├── __init__.py
│   ├── messages.py          # MessageData, ToolCall, ToolPanel, MessageWidget, MessageList
│   ├── input_bar.py         # SlashCommand registry, SlashOverlay, InputBar
│   ├── status_bar.py        # StatusBar (model, tokens, cost, branch, mode)
│   └── permission.py        # PermissionRequest, PermissionModal, PermissionManager
└── screens/
    ├── __init__.py
    └── repl.py              # ReplScreen — main REPL logic
```

---

## Entry point

`main.py` → `launch_repl()` → `OptimusApp.run_async()`

```python
from optimus.tui import OptimusApp

app = OptimusApp(
    model="claude-sonnet-4-6",
    tool_permission_context={},
    mcp_clients=[],
    tools=[],
    session_id="<uuid>",
)
await app.run_async()
```

---

## Component guide

### `OptimusApp` (`app.py`)
- Root `textual.App` subclass.
- Loads `theme.tcss` from the same directory.
- Pushes `ReplScreen` on mount.
- Handles `ctrl+q` / `ctrl+c` → `app.exit()`.

---

### `ReplScreen` (`screens/repl.py`)
The brain of the TUI.  Owns:

| Responsibility | How |
|---|---|
| User input | Listens for `InputSubmitted` from `InputBar` |
| Slash commands | `_handle_slash_command()` — 10 built-in commands |
| Query loop | `_run_query()` → `_stream_query()` drives `query()` |
| Streaming | `MessageWidget.append_text()` per delta |
| Tool calls | `MessageWidget.add_tool_call()` → `update_tool_result()` |
| Permissions | `_show_permission_modal()` awaits `PermissionModal` |
| Cancellation | `asyncio.Event` + task `.cancel()` on Ctrl+C / Esc |
| Token tracking | `StatusBar.add_tokens()` after each turn |

**Slash commands:**

| Command | Action |
|---|---|
| `/help`, `/h` | Print keyboard shortcut guide |
| `/clear`, `/c` | Clear all messages and history |
| `/compact` | Ask Claude to summarise the conversation |
| `/model [name]` | Show or switch current model |
| `/status` | Show session stats |
| `/vim` | Toggle vim keybindings (TODO) |
| `/export [file]` | Write conversation to Markdown file |
| `/review [PR]` | Start a PR review query |
| `/init` | Ask Claude to generate a `CLAUDE.md` |
| `/exit`, `/quit`, `/q` | Exit Optimus |

---

### `MessageList` + `MessageWidget` (`components/messages.py`)

```
MessageList (VerticalScroll)
└── Vertical#message-container
    ├── MessageWidget (user)
    ├── MessageWidget (assistant)
    │   ├── Static  [label]
    │   ├── Static  [thinking block — collapsed]
    │   ├── ToolPanel × N
    │   └── Markdown [content]
    └── …
```

**Key methods:**

| Method | Description |
|---|---|
| `add_user_message(content)` | Appends a user bubble |
| `add_assistant_message(streaming=True)` | Appends an empty assistant bubble |
| `add_system_message(content)` | Dim italic system info line |
| `add_error_message(content)` | Red error line |
| `clear_messages()` | Removes all children |
| `MessageWidget.append_text(text)` | Streams a delta into the assistant bubble |
| `MessageWidget.finish_streaming(text)` | Finalises the bubble, hides cursor |
| `MessageWidget.add_tool_call(tc)` | Mounts a new `ToolPanel` |
| `MessageWidget.update_tool_result(id, result, is_error)` | Updates tool panel state |

**Sticky scroll:** `MessageList._pinned_to_bottom` is `True` by default.
Scrolling up detaches the pin; new content will not auto-scroll.
Scrolling back to the bottom re-pins.

---

### `InputBar` (`components/input_bar.py`)

Single-line `textual.Input` with:

- **Input history** — Up/Down arrows navigate past submissions.
- **Slash-command overlay** — types starting with `/` open `SlashOverlay`.
  Tab autocompletes; Enter selects; Escape dismisses.
- **Ctrl+C** — posts `CancelRequested` to cancel the current query.
- **Escape** — hides overlay if open, otherwise posts `CancelRequested`.
- **`set_waiting(True/False)`** — disables input and pulses the `◈` prefix.

---

### `StatusBar` (`components/status_bar.py`)

1-row footer bar.  All fields are `reactive` — set them and the bar updates
immediately without a full recompose:

```python
sb = self.query_one("#status-bar", StatusBar)
sb.model          = "claude-opus-4"
sb.git_branch     = "feat/my-branch"
sb.permission_mode = "auto"
sb.add_tokens(input_tokens=1200, output_tokens=340, cost=0.0021)
sb.reset_for_new_session()   # after /clear
```

---

### `PermissionModal` + `PermissionManager` (`components/permission.py`)

All tool calls that are not pre-approved go through a blocking modal:

```
┌─────────────────────────────────────────┐
│   ◈  PERMISSION REQUEST                 │
│         ▲ MEDIUM RISK                   │
│  Bash — Run shell command: git status   │
│  ┌────────────────────────────────┐     │
│  │ command="git status --short"   │     │
│  └────────────────────────────────┘     │
│  y Allow Once  s Allow Session  n Deny  │
│  [ Allow Once (y) ] [Session (s)] [Deny]│
└─────────────────────────────────────────┘
```

**Risk levels:**

| Level | Trigger examples |
|---|---|
| `low` | Read, Glob, Grep |
| `medium` | Write, Edit, Bash (non-destructive), WebFetch |
| `high` | Bash with curl/wget, Agent launch, system-dir writes |
| `critical` | `rm -rf`, `mkfs`, fork bombs, sudo rm |

High/critical risk shows `DangerousPermissionModal` with an extra
"Allow Permanently" button and a red border.

`PermissionManager` tracks per-session and permanent grants so the modal
is not shown again for the same (tool, input fingerprint) pair.

---

## JARVIS theme (`theme.tcss`)

Key CSS variables:

```css
$bg:           #050a1e   /* navy background */
$bg-panel:     #0a1628   /* slightly lighter panels */
$bg-input:     #0a1830   /* input area */
$accent:       #00d4ff   /* primary cyan */
$accent-green: #00b890   /* git branch, success */
$accent-amber: #f0a500   /* warnings, permission mode */
$accent-red:   #ff6b35   /* errors, high risk */
$text:         #e0e8ff   /* primary text */
$text-dim:     #4a7fa5   /* secondary / muted text */
$border:       #1a3a5c   /* panel borders */
```

---

## Adding a new slash command

1. Add a `SlashCommand` entry to `SLASH_COMMANDS` in `input_bar.py`.
2. Add a branch in `ReplScreen._handle_slash_command()` in `repl.py`.
3. Document it in the `/help` text inside `_show_help()`.

---

## Known limitations / TODO

- `Shift+Enter` for multi-line input not yet implemented.
- Vim keybindings (`/vim`) not yet implemented.
- Session picker screen (list past sessions to resume) not yet implemented.
- Settings screen not yet implemented.
- MCP client startup not yet wired in (placeholder in `main.py`).
