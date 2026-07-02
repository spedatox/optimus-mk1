# Optimus Mark I — Desktop UI

Forked from **Project Heartbreaker** (Stark/Iron-Man-2 holographic FUI) and
repurposed to drive **Optimus Mark I**, the Python port of Claude Code. The shell
was designed to be rebranded, so wiring it to a new agent only touches two seams:

1. **Branding** — `src/renderer/src/profile/optimus.ts` (name, model number,
   JARVIS-blue accent `#00d4ff`, tagline, suggested prompts). `App.tsx` imports it.
2. **Backend** — the Optimus FastAPI server at `optimus/server/` (see below). The
   UI talks to it over the same contract the old client used.

## Running

### 1. Backend (the Optimus agent)
From the repo root (`Optimus_mk1/`):

```bash
pip install -r optimus/server/requirements.txt   # fastapi, uvicorn, pyjwt, sse-starlette
export ANTHROPIC_API_KEY=sk-ant-...               # or ANTHROPIC_AUTH_TOKEN for oauth
export OPTIMUS_WORKSPACE=/path/to/your/project    # the dir the agent reads/edits (default: cwd)
python -m optimus.server                          # serves http://127.0.0.1:8000
```

Owner login password defaults to `optimus` (`OPTIMUS_OWNER_PASSWORD` to change).
Service key defaults to `dev-key` (`OPTIMUS_SERVICE_KEY`).

### 2. Frontend (this app)
From `heartbreaker/`:

```bash
npm install                  # once — node_modules is not committed
npm run dev                  # Electron app  (renderer :5274)
npm run web:dev              # browser-only  (:5273)
```

The app defaults to `http://localhost:8000` with key `dev-key`, which matches the
backend defaults — it connects out of the box. Log in with password `optimus`.

## What the agent can do

The chat drives the real Optimus query loop with the project toolset — **Read,
Write, Edit, Glob, Grep, PowerShell** — operating on `OPTIMUS_WORKSPACE`. Tool
calls show up as live badges in the UI; text streams token-by-token.

## API contract (UI ↔ backend)

`optimus/server/app.py` implements: `POST /auth/login`, `GET /auth/me`,
`GET /models`, `GET /sessions`, `GET /sessions/{id}/messages`,
`DELETE`/`PATCH /sessions/{id}`, and `POST /chat` (SSE: `start`/`chunk`/`tool`/
`tool_result`/`done`/`error`). Peripheral panels (connections, automations,
memory, budget-mode) are stubbed so they render empty rather than error.
