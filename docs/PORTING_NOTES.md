# Optimus Mark I — Porting Notes

Deviations from a strict 1:1 port of Claude Code (TypeScript → Python).
Every entry says which file, what changed, and why.

---

## Session log

### 2026-04-20  — TUI layer

| Python file | TS source equivalent | Notes |
|---|---|---|
| `optimus/tui/theme.tcss` | `components/*.tsx` CSS-in-JS | All React `sx`/`styled-components` CSS consolidated into a single TCSS file. |
| `optimus/tui/components/messages.py` | `components/Message.tsx`, `VirtualMessageList.tsx` | React virtual list → Textual `VerticalScroll`. No virtualisation needed at TUI scale. |
| `optimus/tui/components/input_bar.py` | `components/PromptInput/PromptInput.tsx`, `BaseTextInput.tsx`, `commands/keybindings/` | Shift+Enter multi-line omitted (Textual `Input` doesn't natively support it — TODO). |
| `optimus/tui/components/status_bar.py` | `components/StatusBar.tsx` | Direct port; reactive watchers replace React `useState`. |
| `optimus/tui/components/permission.py` | `components/permissions/*.tsx` | 20+ TS React modal components consolidated into two Textual modal classes (`PermissionModal`, `DangerousPermissionModal`) plus a `PermissionManager`. `PermissionLevel.DENY_PERMANENT` exists but no UI button for it yet (rarely used in original). |
| `optimus/tui/screens/repl.py` | `App.tsx`, `hooks/useQuery.ts`, `hooks/useApp.ts` | React hooks → methods on `ReplScreen`. `useQuery` streaming loop ported into `_stream_query()`. Cancellation via `asyncio.Event` + task cancel instead of `AbortController`. |
| `optimus/tui/app.py` | `App.tsx` (root) | Thin wrapper; screen lifecycle only. |

---

### Earlier sessions

| Python file | TS source equivalent | Notes |
|---|---|---|
| `optimus/constants.py` | `src/constants/*.ts` (10 files) | All 10 constants files batch-ported into one Python module. Legitimate: TS has one file per export group; Python doesn't need that split. |
| `optimus/env_utils.py` | `src/utils/envUtils.ts` | Direct port. `is_running_on_homespace()` and `is_in_protected_namespace()` → `False` (Anthropic-internal feature). |
| `optimus/context.py` | `src/context.ts` | Git helpers inlined (no separate git util module yet). `get_memory_files`, `get_claude_mds`, `set_cached_claude_md_content` → stubs with RE-ENTRY comments pending `claudemd.ts` port. |
| `optimus/prompts.py` | `src/prompts.ts`, `systemPromptSections.ts`, `outputStyles.ts`, `cyberRiskInstruction.ts` | Four TS files merged (they are co-dependent). `ISSUES_EXPLAINER` URL changed to the Optimus repo. `DEFAULT_AGENT_PROMPT` updated to identify Optimus Mark I and Ahmet Erol Bayrak. `_get_skill_tool_commands` and `_load_memory_prompt` → stubs (depend on unported modules). |
| `optimus/main.py` | `src/main.tsx` | Analytics (`logEvent`) dropped throughout. `launchRepl()` routes to `optimus.tui.OptimusApp` (Textual) instead of Ink. `optimus.repl` import is the primary; fallback is `_run_minimal_repl()`. |
| `optimus/Tool.py` | `src/Tool.ts` | Direct port. |
| `optimus/query.py` | `src/query.ts` | Direct port. |
| `optimus/__main__.py` | `src/index.ts` | Direct port. |

---

## Permanent omissions

| Feature | Reason |
|---|---|
| Analytics / telemetry (`logEvent`, `logSkillsLoaded`, …) | Dropped entirely per project rules. No-ops would add noise. |
| All `feature('X')` gates | Evaluated as `False`. Branch bodies kept with `# RE-ENTRY` comment. |
| Anthropic-internal features (`is_running_on_homespace`, `is_in_protected_namespace`, `FEATURE_LODESTONE`, …) | Always `False`; not applicable outside Anthropic infra. |
| Crash reporter / Sentry | Dropped. No telemetry in this build. |
| Auto-updater | `cmd_update` stub present; logic not yet ported. |

---

## RE-ENTRY comments

Throughout the codebase you will see:
```python
# RE-ENTRY: from optimus.X import Y
# RE-ENTRY: await some_function()
```
These mark exactly where a real implementation plugs in once the
corresponding TS module is ported. They are not stubs — the surrounding
code is real; only the dependency is missing.
