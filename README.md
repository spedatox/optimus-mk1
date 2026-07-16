# Optimus Mark I

Python port of Claude Code with a Textual terminal UI, a FastAPI backend, and an Electron desktop client.

> Status: active porting project. Core agent loop and tool system are implemented; some CLI subcommands and integrations are intentionally marked `RE-ENTRY` and are not wired yet.

## What this project does

Optimus Mark I provides an autonomous coding-agent runtime that can:

- run an interactive coding REPL,
- call a large built-in toolset (read/write/edit/search/shell/web/tasks/MCP/worktrees/swarm),
- stream model output and tool activity,
- expose a backend API for a desktop UI.

## Repository layout

```text
optimus/                 # Python package (CLI, query loop, tools, TUI, backend)
optimus/__main__.py      # CLI bootstrap entrypoint
optimus/main.py          # Click CLI commands + setup flow
optimus/query.py         # core model↔tool query loop
optimus/tools/           # built-in tool implementations
optimus/tui/             # Textual UI (JARVIS theme)
optimus/server/          # FastAPI backend for desktop UI
optimus/peer/            # SPEDA websocket peer client
heartbreaker/            # Electron + React desktop client
docs/                    # architecture and porting docs
PORTING_NOTES.md         # strict TS→Python deviation log
```

## Requirements

- Python 3.12+
- Node.js 18+ (for desktop client development)
- Anthropic API key or auth token for model calls

## Installation

### Python package

```bash
cd optimus-mk1
python -m pip install -e .
```

Alternative (Poetry):

```bash
poetry install
```

### Desktop client (optional)

```bash
cd heartbreaker
npm install
```

## Running

### CLI / TUI

After installation:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
optimus
```

Useful commands:

```bash
optimus -p "Summarize this repository"
optimus --help
optimus doctor
optimus auth status
```

### Backend API for desktop UI

```bash
cd optimus-mk1
python -m pip install -r optimus/server/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export OPTIMUS_WORKSPACE=/absolute/path/to/target/project
python -m optimus.server
```

Backend default endpoint: `http://127.0.0.1:8000`

### Electron desktop UI

```bash
cd heartbreaker
npm run dev      # Electron desktop
# or
npm run web:dev  # Browser-only renderer
```

## Configuration

### Primary config files

- User config dir: `~/.claude` (override with `CLAUDE_CONFIG_DIR`)
- Global config file: `~/.claude.json` (legacy fallback: `~/.claude/.config.json`)
- Project commands: `.claude/commands/`

### Common environment variables

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key authentication |
| `ANTHROPIC_AUTH_TOKEN` | OAuth-style auth token alternative |
| `CLAUDE_CONFIG_DIR` | Override config directory |
| `CLAUDE_CODE_SIMPLE` | Bare mode (minimal tool/runtime path) |
| `OPTIMUS_DEBUG` | Enable debug logging |
| `OPTIMUS_WORKSPACE` | Backend/peer workspace root |
| `OPTIMUS_OWNER_PASSWORD` | Backend login password (default `optimus`) |
| `OPTIMUS_SERVICE_KEY` | Backend service key (default `dev-key`) |
| `OPTIMUS_JWT_SECRET` | Backend JWT secret |
| `SPEDA_API_KEY` | Required for `python -m optimus.peer` |
| `SPEDA_WS_URL` | WebSocket URL for peer mode |

## Development workflow

### Python

```bash
cd optimus-mk1
python -m ruff check .
python -m mypy optimus
python -m pytest
```

### Desktop client

```bash
cd heartbreaker
npm run typecheck
npm run build
```

## Known issue in current snapshot

At the time of writing, entrypoints that import the `optimus` package fail early with:

```text
ImportError: cannot import name 'Tool' from partially initialized module 'optimus'
```

This is caused by the alias wiring in `optimus/__init__.py`. The runtime architecture and commands above describe the intended flow, but this import regression currently blocks normal startup (`optimus`, `python -m optimus.server`, etc.) until fixed.

## Implemented vs pending areas

Implemented core areas include:

- bootstrap and CLI entry flow,
- query loop and tool execution cycle,
- Textual TUI components and screen wiring,
- broad built-in tool surface,
- backend bridge used by the desktop UI.

Still in progress (explicit `RE-ENTRY` markers in code):

- portions of MCP command management,
- updater and auth command internals,
- selected security hardening and advanced tool/runtime integrations,
- remaining strict 1:1 source parity tasks listed in `CLAUDE.md` and `PORTING_NOTES.md`.

## Related docs

- `PORTING_NOTES.md`
- `docs/PORTING_NOTES.md`
- `docs/TUI.md`
- `heartbreaker/OPTIMUS.md`
