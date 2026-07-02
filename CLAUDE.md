# OPTIMUS MARK I
## Python port of Claude Code (TypeScript/Bun)

**Author:** Ahmet Erol Bayrak

---

## What this project is

A 1:1 Python port of Claude Code. Every TypeScript file becomes a Python file.
Same functions. Same features. Same behaviour. Language differences are acceptable
as long as both variants do the same thing the same way.

---

## Source

```
claude_code_src/src/   ← the TypeScript source. This is the spec.
```

When in doubt: read the source. The source is always right.

---

## Rules

### 1. Read before you write
Read the full TypeScript file before writing a single line of Python.
Understand what every function does. Then port it.

### 2. Same functions, same features
Every exported function, class, and constant in the TS file must have
a Python equivalent that does the same thing.

Acceptable omissions (document in PORTING_NOTES.md):
- React render methods (no UI layer yet) — keep as `return None` stubs
- Analytics / telemetry (`logEvent`) — drop entirely, they are no-op
- Feature-gated code (`feature('X') → False`) — omit the branch body,
  leave a comment marking where it plugs in when ported

### 3. No stubs
A stub is a function that exists but does nothing:
```python
# WRONG
async def call(self, args, context): pass
async def call(self, args, context): return None
async def call(self, args, context): ...
```
Every function must have real logic that matches the TS source.

### 4. Line ratio check
Before moving to the next file, check:

```
TS lines / Python lines
```

If the ratio is worse than 1:5 (e.g. 500 TS lines → less than 100 Python lines),
go back and finish it.

Legitimate compression sources (do not pad artificially):
- TypeScript import blocks → fewer Python imports
- TypeScript generic type machinery → not needed in Python
- JSDoc verbosity → Python docstrings are more concise
- `export type` re-exports → not needed

### 5. One file at a time
No agents. No parallelism. Port one file here, verify it, then move on.
The user reviews each file before we continue.

### 6. Dependency stubs
When a function depends on a module not yet ported, write a minimal
stub with a comment:
```python
# Stub — mirrors getMessagesAfterCompactBoundary() from utils/messages.ts
# Replace when messages.ts is ported.
def get_messages_after_compact_boundary(messages): return messages
```

### 7. TUI rules (Textual)
The TUI layer replaces Claude Code's React/Ink UI entirely.
These rules govern the `optimus/tui/` subtree:

- **Framework:** Textual (Python) — not Ink (TypeScript/React).
- **Theme:** JARVIS blue. Background `#050a1e`, accent `#00d4ff`, text `#e0e8ff`.
  All colours live in `optimus/tui/theme.tcss`. Never hardcode colours in Python.
- **No blocking in widgets.** Widget handlers must be sync or use `asyncio.create_task()`.
  Never `await` inside an `on_*` handler directly.
- **Streaming:** append text with `MessageWidget.append_text()` per delta;
  call `finish_streaming()` once the turn ends.
- **Permissions:** every tool call that is not pre-approved must go through
  `PermissionModal`. Never silently skip or auto-approve without user consent.
- **Component ownership:**
  - `MessageList` owns scroll and message history display.
  - `InputBar` owns text entry, history navigation, slash-command overlay.
  - `StatusBar` owns model / token / cost / branch / mode display.
  - `ReplScreen` owns the query loop and wires all components together.
  - `OptimusApp` owns screen lifecycle only.
- **CSS location:** all widget-local CSS goes in `DEFAULT_CSS`; global theming
  goes in `theme.tcss`. Do not mix them.
- **Refresh strategy:** prefer `reactive` watchers over `refresh(recompose=True)`.
  Use `recompose=True` only when child widget count changes (e.g. adding a tool panel).

---

## Tech mapping

| TypeScript | Python |
|---|---|
| `async function*` generator | `async def` with `yield` |
| `yield*` | `async for x in gen: yield x` |
| Zod schema | Pydantic v2 `BaseModel` or `dict` |
| `z.infer<Input>` | `dict[str, Any]` |
| `camelCase` | `snake_case` |
| `AbortController` | `asyncio.Event` |
| `Map<K,V>` | `dict[K, V]` |
| `readonly T[]` | `list[T]` |
| `feature('X')` | `False` (always) |
| Analytics / telemetry | Drop entirely |
| `index.ts` | `__init__.py` |
| React render methods | `return None` stub |
| React/Ink components | Textual `Widget` subclasses |
| React hooks (`useQuery`, `useApp`) | Methods on `ReplScreen` |
| `EventEmitter` | `pyee.AsyncIOEventEmitter` |
| `Promise.all` | `asyncio.gather` |

---

## File order

Work through files in dependency order — port what a file depends on
before porting the file itself.

### Core (done ✅)
1. `src/Tool.ts`   → `optimus/Tool.py` ✅
2. `src/query.ts`  → `optimus/query.py` ✅
3. `src/index.ts`  → `optimus/__main__.py` ✅
4. `src/main.tsx`  → `optimus/main.py` ✅

### Constants & utilities (done ✅)
5. `src/constants/*.ts` → `optimus/constants.py` ✅
6. `src/utils/envUtils.ts` → `optimus/env_utils.py` ✅
7. `src/context.ts` → `optimus/context.py` ✅
8. `src/prompts.ts` + `systemPromptSections.ts` → `optimus/prompts.py` ✅

### TUI layer (done ✅)
9. Theme CSS → `optimus/tui/theme.tcss` ✅
10. `components/Message.tsx` + `VirtualMessageList.tsx` → `optimus/tui/components/messages.py` ✅
11. `components/PromptInput/*.tsx` → `optimus/tui/components/input_bar.py` ✅
12. `components/StatusBar.tsx` → `optimus/tui/components/status_bar.py` ✅
13. `components/permissions/*.tsx` → `optimus/tui/components/permission.py` ✅
14. `App.tsx` + hooks → `optimus/tui/screens/repl.py` ✅
15. Root app → `optimus/tui/app.py` ✅

### Next targets
- `src/utils/claudeMd.ts`   → `optimus/claudemd.py`
- `src/bootstrap/state.ts`  → `optimus/bootstrap/state.py`
- `src/utils/config.ts`     → `optimus/utils/config.py`
- `src/services/mcp/`       → `optimus/services/mcp/`
- `src/tools/`              → `optimus/tools/`

### Tools ported so far
Glob, Grep, FileRead, FileWrite, FileEdit, PowerShell, TodoWrite, WebFetch,
WebSearch, NotebookEdit, **AskUserQuestion** ✅ (11/40). Remaining: AgentTool,
Bash, Brief, Config, EnterPlanMode, EnterWorktree, ExitPlanMode, ExitWorktree,
LSP, ListMcpResources, MCP, McpAuth, REPL, ReadMcpResource, RemoteTrigger,
ScheduleCron, SendMessage, Skill, Sleep, SyntheticOutput, TaskCreate/Get/List/
Output/Stop/Update, TeamCreate, TeamDelete, ToolSearch.

---

## After each file

1. State the TS line count and Python line count
2. State the ratio
3. Explain any legitimate compression
4. Wait for user review before continuing

---

## PORTING_NOTES.md

Document every deviation from strict 1:1 in PORTING_NOTES.md:
- Which file
- What was omitted or changed
- Why
