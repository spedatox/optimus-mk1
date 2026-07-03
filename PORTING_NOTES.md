# PORTING NOTES

Every deviation from strict 1:1 with the TypeScript source. Format: file → what
changed → why.

---

## bootstrap/state.ts → optimus/bootstrap/state.py
- **OpenTelemetry counters/providers** (`meter`, `*Counter`, `loggerProvider`,
  `meterProvider`, `tracerProvider`) — state fields and accessors kept, but typed
  `Any`/`None`; the OTel pipeline itself is dropped. Non-telemetry code reads
  these fields, so the structure stays.
- **`createSignal`** (src/utils/signal.ts) — ported faithfully inline as `Signal`
  (8-line leaf), not stubbed.
- **`resetSettingsCache`** (settings/settingsCache.ts) — dependency stub
  `_reset_settings_cache`, marked RE-ENTRY. Only caller: `set_use_cowork_plugins`.
- `Date.now()`→`_now_ms()`; `realpathSync`→`os.path.realpath`;
  `.normalize('NFC')`→`unicodedata.normalize`; `setTimeout().unref()`→daemon
  `threading.Timer`; `process.env.USER_TYPE==='ant'` spread (`replBridgeActive`)
  omitted — not part of the `State` type.

## utils/cwd.ts → optimus/utils/cwd.py
- `AsyncLocalStorage<string>` → `contextvars.ContextVar`. Verified equivalent:
  async descendants spawned inside `run_with_cwd_override` keep the override
  after the outer call resets it.

## utils/config.ts → optimus/utils/config.py
- **GlobalConfig / ProjectConfig** TS object types → plain dicts with factory
  defaults. The ~440 lines of optional-field interface declarations have no
  Python equivalent (legitimate type-machinery compression → 1817:1086 ratio).
- **`getFsImplementation()`** abstraction → Python `os`/`open` directly. The FS
  indirection exists in TS for the browser-sdk build; not needed here.
- **`lockfile.lockSync`** → `_config_lock()`: atomic `O_EXCL` creation of
  `${file}.lock` with bounded retry + 60s stale reclaim. `onCompromised` logging
  collapses to debug log.
- **`fs.watchFile`** poll watcher → daemon thread polling `st_mtime` every 1s.
- `lodash memoize`→`functools.lru_cache`; `lodash pickBy`→dict comprehension;
  `randomBytes(32).hex`→`secrets.token_hex(32)`; `logEvent`/analytics → dropped.
- **Inline RE-ENTRY stubs** (peripheral leaves, ported later):
  `_get_essential_traffic_only_reason` (privacyLevel.ts),
  `_get_managed_file_path` (settings/managedPath.ts),
  `_get_auto_mem_entrypoint` (memdir/paths.ts).

## New leaf modules (partial ports — only exports needed so far)
- **utils/errors.py** — ConfigParseError, get_errno_code, AbortError,
  is_abort_error (+CancelledError), ClaudeError, to_error. Rest of errors.ts later.
- **utils/json.py** — safe_parse_json, strip_bom, json_parse, json_stringify.
  slowOperations perf-timing wrapper dropped (parse semantics identical).
- **utils/path.py** — normalize_path_for_config_key only.
- **utils/env.py** — get_global_claude_file, file_suffix_for_oauth_config.
  `hasInternetAccess`/command-probe helpers not yet ported.
- **utils/git.py** — find_canonical_git_root: common-path worktree resolution.
  Full adversarial back-link security verification marked RE-ENTRY.
- **utils/cleanup_registry.py** — full faithful port.
- **utils/debug.py / log.py / diag_logs.py** — logging shims; telemetry sinks
  dropped, in-memory error log preserved.

## utils/api.ts → optimus/api.py (pragmatic bridge, not full 1:1 yet)
- api.py is a working streaming bridge over the `anthropic` AsyncAnthropic SDK,
  not a complete port of api.ts/services/api/*. Full client matrix
  (Bedrock/Vertex/Foundry), retries (withRetry.ts), and usage/cost accounting
  are RE-ENTRY.
- **Key resolution** — partial port of getAnthropicApiKey / isClaudeAISubscriber:
  oauth bearer (`ANTHROPIC_AUTH_TOKEN` env or FD-sourced token in bootstrap
  state) → `auth_token`; else `ANTHROPIC_API_KEY` env or `config.primaryApiKey`
  → `api_key`. Keychain / apiKeyHelper / scope gating are RE-ENTRY (auth.ts).
- **Fix:** `_convert_messages` now unwraps the internal message envelope
  (`{'type','message':{'role','content'}}`) the query loop carries — previously
  it read top-level role/content and silently dropped every message.

## optimus/llm_client.py (NEW — not in the TS source)
- Multi-provider routing ported from **SPEDA Mark VI**
  (`packages/api/app/services/llm_client.py`), not from Claude Code. Claude Code
  is Anthropic-only (plus Bedrock/Vertex/Foundry, which are still Anthropic
  models); this is a deliberate feature addition requested for optimus.
- Model refs are `"provider:model"` — `openai:`, `gemini:`, `zai:`, `deepseek:`,
  `ollama:` — bare names stay Anthropic, so all existing refs keep working.
  All five non-Anthropic providers share one OpenAI chat-completions adapter
  (Gemini/z.ai/DeepSeek/Ollama expose OpenAI-compatible endpoints).
- Internal format stays Anthropic content blocks everywhere; translation
  happens at the wire boundary only. Responses come back as attribute-
  compatible dataclasses (`LLMMessage`/`TextBlock`/`ToolUseBlock`/`Usage`), so
  `call_model()`'s block-conversion loop is provider-agnostic.
- speda's `settings` object → environment variables (`OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `ZAI_API_KEY`, `DEEPSEEK_API_KEY`, `OLLAMA_BASE_URL`,
  `LLM_FALLBACK_CHAIN`); speda's `LLMClient` class + `_StreamHandle` →
  module-level functions (`fallback_chain`, `create_via_compat`,
  `open_compat_stream`) because optimus/api.py owns the Anthropic path and
  the fallback loop directly.
- **api.py integration:** `call_model()` and `query_fast_model()` iterate the
  fallback chain; extended-thinking kwargs apply to the Anthropic branch only
  (GLM/DeepSeek thinking is toggled per-provider in `to_openai_params`).
  `run_web_search()` remains Anthropic-only (server-side tool).
- New dependency: `openai>=1.50` (imported lazily — only loaded when a
  non-Anthropic provider is actually used).

## Tool restoration (28 tools) — 2026-07-03
The a719409 restructure dropped 28 of the 40 tools ported at f696afe (plus
their support modules). The TS source tree is no longer on disk, so the
f696afe implementations served as the spec; every tool was rewritten to the
current `@build_tool` protocol (prompt.py split, ToolResult returns,
check_permissions → PermissionResult, map_tool_result_to_tool_result_block_param).
- **Support modules restored:** `tasks/task_registry.py` (background handles),
  `utils/tasks.py` (task list store, + metadata merge & dependency links),
  `services/mcp.py` (MCP manager), `utils/swarm/` (mailbox, team helpers).
- **`commands/__init__.py` rewritten** (legacy module was removed): markdown
  slash-command loader over `.claude/commands/**/*.md` + `~/.claude/commands/`,
  frontmatter via utils/frontmatter_parser, `$ARGUMENTS`/`$ARGS` expansion.
  Backs SkillTool.
- **BashTool:** the 7588b87 bash security infrastructure (heredoc rewriting,
  command parsing, sandbox) was also dropped in the restructure and remains
  RE-ENTRY. Bash mirrors PowerShellTool's subprocess machinery; fail-safe
  `check_permissions='ask'`. Shell resolution prefers $SHELL/PATH bash, then
  Git-for-Windows install paths.
- **AgentTool:** wired to the real query loop (QueryParams + production_deps +
  api.call_model). Explore/Plan agents get a read-only tool pool; nesting is
  blocked; parent abort_controller and permission context are inherited.
  Parallel/background agents → RE-ENTRY.
- **ExitPlanModeTool:** plan approval rides the permission gate
  (`check_permissions='ask'`) instead of the TS PlanApprovalDialog; restores
  `pre_plan_mode` recorded by EnterPlanModeTool.
- **REPLTool:** upgraded from eval-or-exec to AST splitting so the trailing
  expression of a multi-statement snippet is echoed (true REPL semantics).
- **LSPTool:** enabled only when a language server client is registered via
  `register_lsp_client()` (mirrors per-server LSP tools in the source); the
  connection stack is RE-ENTRY.
- **SyntheticOutputTool:** schema registered via `set_output_schema()`;
  validation degrades from jsonschema to required-property checks when the
  package is missing. `is_enabled()` False until a schema is registered.
- **CronCreate/Delete/List:** in-memory registry (50-job cap) with durable
  jobs persisted to `~/.optimus/cron_jobs.json`; the firing loop is RE-ENTRY.
- **RemoteTrigger:** aiohttp → httpx (already a dependency); oauth bearer from
  optimus.api; base URL via `CLAUDE_AI_API_URL` env.
- **optimus/__init__.py:** registers `optimus.Tool` as an alias of
  `optimus.tool` in sys.modules — the whole codebase imports `optimus.Tool`
  (mirroring src/Tool.ts) but Python imports are case-sensitive even on
  Windows; without the alias nothing imported.
- **pyproject:** added `pathspec`, `beautifulsoup4` (used by utils/glob.py and
  WebFetchTool but previously undeclared) and `jsonschema`.

## utils/claudeMd.ts → optimus/claudemd.py
- **marked Lexer (gfm:false)** → a focused markdown scanner: `strip_html_comments`
  + `_remove_code_regions`/`_extract_include_paths` track fenced code blocks and
  inline code spans so HTML comments and `@include` directives inside code are
  preserved, and block-level comments are stripped — matching the behaviors the
  source depends on. (Not a general CommonMark lexer; scoped to these two tasks.)
- **`ignore` / `picomatch`** glob matching → `pathspec` (gitwildmatch).
- **lodash memoize** → `_AsyncMemo` (single-arg async cache with `.clear()`).
- **RE-ENTRY stubs** (ported later): settings (`getInitialSettings.claudeMdExcludes`),
  hooks (InstructionsLoaded), memdir (`truncateEntrypointContent`, auto-memory),
  growthbook feature values, team memory. `is_setting_source_enabled` is wired to
  bootstrap state's `allowed_setting_sources`.
- **New leaves:** `utils/file.py` (normalize_path_for_comparison),
  `utils/frontmatter_parser.py` (pyyaml-backed), `utils/permissions/filesystem.py`
  (path_in_working_path); `expand_path`/`contains_path_traversal` added to path.py;
  `find_git_root` added to git.py.
- `getClaudeMds` TEAMMEM branch omitted (feature off).

## tools/GlobTool → optimus/tools/glob_tool/ (first tool — establishes the pattern)
- Pattern: `@build_tool` class implementing the snake_case Tool protocol +
  `prompt.py` (DESCRIPTION/NAME) + package `__init__.py`. UI.tsx render fns → None.
- **utils/glob.py** — port of glob.ts. ripgrep used when `rg` is on PATH; pure
  Python fallback (pathspec match + mtime sort) otherwise. `--sort=modified`
  → st_mtime ascending. RE-ENTRY: getFileReadIgnorePatterns /
  plugin-cache exclusions (return []).
- **checkReadPermissionForTool** → allow (read-only); full read gating RE-ENTRY.
  The query loop's can_use_tool remains the outer gate.
- New path/file leaves: `to_relative_path`, `suggest_path_under_cwd`,
  `FILE_NOT_FOUND_CWD_NOTE`.
- Verified directly and end-to-end through the real query_loop (model → Glob →
  results → model).

## Project-creation toolset (Grep, Read, Write, Edit, PowerShell)
All follow the GlobTool pattern (@build_tool class + prompt.py + __init__). Shared
read_file_state lives on ToolUseContext and is threaded through the query loop
(dataclasses.replace shares the dict ref), enforcing read-before-write/edit.

- **GrepTool** (GrepTool.ts) — full port. utils/ripgrep.py: `rg` when present,
  else a Python fallback emulating -i/-l/-c/-n/-C/-A/-B/--glob/--type/-U over a
  filesystem walk. Three output modes (content/count/files_with_matches).
- **FileWriteTool** (FileWriteTool.ts) — core: read-before-overwrite + staleness,
  LF write, structured patch for updates. RE-ENTRY: LSP, skills, diagnostics,
  fileHistory, gitDiff, teamMemSecrets.
- **FileReadTool** (FileReadTool.ts) — text path full (offset/limit, cat -n via
  add_line_numbers, byte cap, dedup stub, empty/short-file reminders). RE-ENTRY:
  image / PDF / notebook readers (raise a clear "not yet supported" error).
- **FileEditTool** (FileEditTool.ts) — full core: same-string check, new-file via
  empty old_string, .ipynb reject, read-before-edit + staleness, uniqueness
  (replace_all), structured patch. RE-ENTRY: findActualString/preserveQuoteStyle
  quote-normalization, LSP, fileHistory, gitDiff.
- **PowerShellTool** (PowerShellTool.tsx) — core subprocess exec (pwsh →
  powershell → sh fallback), timeout, 30K output cap, stdout/stderr/interrupted.
  check_permissions returns 'ask' (fail-safe). RE-ENTRY: the ~7800 lines of
  security/permissions/pathValidation/readOnlyValidation/gitSafety/sandbox and
  run_in_background / output persistence.
- **New utils:** ripgrep.py, diff.py (difflib-based structured patch +
  count_lines_changed), file_read.py (ReadFileState, read_file_sync_with_metadata,
  line-ending detection); file.py gained add_line_numbers / write_text_content /
  get_file_modification_time / MAX_OUTPUT_SIZE.
- **tools/__init__.py** exposes get_project_tools(). Verified: full Write→Read→
  Edit→Grep→Glob→PowerShell workflow + staleness guards, and a multi-tool build
  driven through the real query_loop.

## Planning + web tools (TodoWrite, WebFetch, WebSearch)
- **TodoWriteTool** (TodoWriteTool.ts) — full port. appState.todos → a
  session/agent-keyed store added to bootstrap/state.py (get_todos/set_todos/
  clear_all_todos). All-completed list clears the store (matches TS).
  VERIFICATION_AGENT nudge omitted (feature off).
- **WebFetchTool** (WebFetchTool.ts) — fetch URL → HTML→markdown → summarize via
  a fast model. axios+LRUCache → httpx + 15-min TTL dict cache. turndown →
  bs4 text extraction (headings/links/code preserved; not a full turndown port).
  queryHaiku → api.query_fast_model. Cross-host redirect detection preserved.
  Domain blocklist/permission preapproval → RE-ENTRY (preapproved-host list kept
  for the summary-guidelines toggle).
- **WebSearchTool** (WebSearchTool.ts) — Anthropic server-side web_search tool.
  queryModelWithStreaming(extraToolSchemas) → api.run_web_search() (one
  non-streaming call); makeOutputFromSearchResponse block-parsing preserved.
  check_permissions 'passthrough' → 'ask'.
- **api.py** gained query_fast_model() (haiku one-shot) and run_web_search().
- get_project_tools() now returns 9 tools. Verified: TodoWrite through the real
  query_loop; WebFetch html→md + redirect/preapproval logic; WebSearch block
  parsing + markdown-link rendering.

## AskUserQuestionTool → optimus/tools/ask_user_question_tool/ (full core)
Port of AskUserQuestionTool.tsx: 1-4 multiple-choice questions (2-4 options
each), single- or multi-select, optional "Other" free text. Faithful: schemas,
uniqueness refine (UNIQUENESS_REFINE → validate_input), HTML preview validation
(validateHtmlPreview verbatim), check_permissions→'ask', call() echoes the
answers injected by the permission flow, map_tool_result_to_tool_result_block_param
builds the "User has answered your questions: …" string. prompt() appends
PREVIEW_FEATURE_PROMPT only when getQuestionPreviewFormat() is set. Verified
end-to-end: model→AskUserQuestion→answers collected→tool_result→model reply.

- **React render fns** → return None (no UI layer); the TUI has its own modal.
- **Permission/answer flow**: the TS AskUserQuestionFrame writes answers into
  updatedInput before call(). Python mirrors this via a new
  `ToolUseContext.ask_user_questions` callback: `_run_tools` collects answers
  for any tool where `requires_user_interaction()` is True and merges them into
  the input before call(). Headless wires a stdin collector; the TUI wires an
  `AskUserQuestionModal`.
- **RE-ENTRY**: option `preview` rendering, per-question `annotations` (notes),
  and the side-by-side preview layout (TUI modal subset only). SDK
  `_sdkInputSchema`/`_sdkOutputSchema` exports not needed (no SDK layer yet).

## _run_tools permission flow (query.py) — was a stub, now wired
`_run_tools` previously called `tool.call()` directly — `validate_input` and
`check_permissions` were never invoked, and `can_use_tool` was passed in but
unused (no tool's permissions were ever checked; validation like NotebookEdit's
read-before-edit guard was bypassed). Now mirrors runTools(): validate_input →
check_permissions (allow/deny/ask) → for 'ask', gate via can_use_tool, or for
requires_user_interaction tools collect answers via ctx.ask_user_questions →
call(updated_input). Benefits every tool. Headless `can_use_tool=lambda *_:True`
so behavior is unchanged there; the TUI now actually prompts for 'ask' tools
(PowerShell/WebSearch) via its modal — the intended Claude Code UX.

## Fixes — "optimus mk1 is not working" (agent had zero tools)
- **`optimus/tools/__init__.py`** — `main.py` imports `get_tools` from
  `optimus.tools`, but only `get_project_tools` existed → the `except ImportError`
  fallback returned `[]`, so the agent ran with **no tools** (no Read/Write/Edit/
  Bash/search). Added `get_tools(permission_context, mcp_clients)` — a faithful
  port of `getTools()` (src/tools.ts): CLAUDE_CODE_SIMPLE → shell+read+edit only,
  else the full base toolset, `is_enabled()`-filtered. `filterToolsByDenyRules`
  is a no-op until deny-rule machinery is ported; `assembleToolPool` (MCP merge)
  is RE-ENTRY. Verified: 10 tools now reach the model; Write→Edit multi-tool turn
  succeeds end-to-end against the Z.ai GLM endpoint.
- **`optimus/api.py`** — `_convert_tools` called `tool.description()` which is an
  `async` method, so it captured a **coroutine** as the tool's `description`
  string — every tool definition sent to the API was malformed. Made
  `_convert_tools` async and `await tool.description()`. (Only surfaced once
  tools were actually wired in, since the no-tools path never hit it.)

## NotebookEditTool → optimus/tools/notebook_edit_tool/ (full core)
Full port of NotebookEditTool.ts: replace / insert / delete a single cell in a
Jupyter (.ipynb) notebook. Cell addressing matches the source — first a real
`cell.id` lookup, then a numeric `cell-N` index fallback (parseCellId). Insert
generates a random base36 id for nbformat ≥ 4.5 (mirrors
`Math.random().toString(36).substring(2,15)`); replace on a code cell resets
`execution_count`/`outputs`; replace-one-past-end auto-converts to insert.
Read-before-edit + staleness enforced via read_file_state (error codes 9/10),
identical to FileEditTool/FileWriteTool. Post-write readFileState updated with
`offset=None`/`limit=None` to break FileRead's same-ms dedup. UNC paths skip
filesystem validation (NTLM-credential-leak guard). Verified replace/insert/
delete + all validate_input branches + block-param rendering end-to-end.

- **UI.tsx render fns** (React) → `return None` (no UI layer). `getToolUseSummary`
  is pure logic (getDisplayPath) and kept — `getActivityDescription` builds on it.
- **fileHistory** (fileHistoryEnabled/fileHistoryTrackEdit) → omitted, matches
  the other file tools; hook point marked in `call`.
- **checkWritePermissionForTool** → `allow`; the query loop's `can_use_tool`
  remains the outer permission gate (same convention as FileEdit/FileWrite).
- **utils/notebook.py** (new) — faithful `parse_cell_id`. The rest of notebook.ts
  (readNotebook, mapNotebookCellsToToolResult, processCell/processOutput — the
  FileRead .ipynb reader) is RE-ENTRY.
- **utils/file.py** — added `get_display_path` (faithful getDisplayPath).
- **utils/file_read.py** — `read_file_sync_with_metadata` now returns
  `line_endings` too (faithful to readFileSyncWithMetadata's
  `{content, encoding, lineEndings}`); backward-compatible (existing callers
  read only `content`/`encoding`).

## query.ts → optimus/query.py (fix)
- Tool-returned new context was built as a plain dict via `.__dict__`, then later
  accessed as `.options` (AttributeError). Replaced with `dataclasses.replace`
  (`_update_context`) so the value stays a `ToolUseContext` — matching the TS
  object-spread `{ ...update.newContext, queryTracking }`. Verified by a full
  model→tool→model→Terminal loop test.

## 2026-07-03 audit fixes
- **tui/screens/repl.py** — `_run_query` / `_handle_slash_command` were launched
  with `asyncio.create_task`; `push_screen_wait` (PermissionModal,
  AskUserQuestionModal) requires an active Textual worker, so every
  non-pre-approved tool call raised `NoActiveWorker` and killed the turn.
  Now launched via `self.run_worker(..., exclusive=False)`. Verified headlessly:
  input → tool_use(Bash) → modal → approve → tool runs → final answer renders.
- **`optimus.Tool` → `optimus.tool`** (46 files) — the module file is `tool.py`;
  the capitalized import only worked on Windows' case-insensitive filesystem and
  would break the entire package on Linux/macOS.
- **`optimus/__main__.py`** — force UTF-8 on stdout/stderr on Windows; legacy
  console codepages rendered em-dashes/box chars in the banner and doctor
  output as `?`.
- **Known gaps (not fixed):** `optimus/peer/client.py` is missing —
  `optimus.peer` (`python -m optimus.peer`) cannot import; `handlers.py` and
  `config.py` exist, the WebSocket client itself was never written.
  `optimus.server` requires the `fastapi` extra (not installed).
  `optimus/print.py` not ported — `-p/--print` uses the minimal fallback in
  main.py (works).

## 2026-07-03 — TUI 1:1 porting pass (session 2)

### tui/components/permission.py — rewritten against source
- Replaced the invented "Allow Once / Allow Session / Allow Permanently /
  Deny" button dialog with the real 2–3 row Select: **Yes / Yes, and don't
  ask again for `<rule>` / No** (PermissionDialog.tsx + bashToolUseOptions.tsx
  + shellPermissionHelpers.tsx). The remember row only appears when a rule
  can be generated (Bash prefix, file directory, web domain) — Agent/MCP
  tools get Yes/No only, matching `suggestions.length > 0` gating.
- Rule matching is prefix/dir/domain-scoped (subcommand-scoped for git/npm/
  cargo/… like the real `npm run:*` rules). Rules survive /clear.
- Escape resolves to No (`onCancel={() => handleReject()}`).
- NOT ported (RE-ENTRY): settings.json rule persistence, Haiku classifier
  descriptions, editable-prefix input mode, PermissionRuleExplanation banner.

### tui/components/spinner.py — new (Spinner.tsx port)
- SpinnerWithVerb line: `✻ Pondering… (esc to interrupt · 32s · ↓ 1.2k tokens
  · thinking)`. Glyphs ·✢*✶✻✽ forward+reversed @120ms (getDefaultCharacters);
  204 SPINNER_VERBS verbatim; glimmer sweep (width+20 cycle, 200ms step,
  right-to-left); stall→error-red fade after 3s idle (useStalledAnimation,
  0.1 smoothing per 50ms tick); smooth token counter (3/15%/50 increments);
  timer+tokens gated behind 30s (SHOW_TOKENS_AFTER_MS) or verbose; thinking
  status with 2s-minimum display windows.
- NOT ported: teammate spinner tree, brief-mode spinner, TaskListV2 panel
  (multi-agent SaaS), per-char shimmer (approximated as 3-char highlight).

### tui/components/messages.py
- Spinner frames corrected: braille (never used by Claude Code) → asterisk set.
- `render_special_assistant_text`: AssistantTextMessage.tsx switch(text) —
  NO_RESPONSE_REQUESTED renders nothing; user-abort → InterruptedByUser line;
  prompt-too-long, credit-low, invalid-key, timeout, API-error-prefix (1000
  char truncation) render as error lines, not Markdown. Sentinel strings
  mirror services/api/errors.ts for when the api layer is ported.
- New renderers: bash-input (`! cmd` on bashMessageBackground), bash-output
  (stdout dim / stderr error, 10-line truncation), compact-boundary
  (`✻ Conversation compacted`), interrupted. extract_tag ports
  utils/messages.ts extractTag.
- Removed invented "Thinking…" in-message placeholder — empty streaming
  assistant messages render nothing (isEmptyMessageText → null); loading
  state lives in the SpinnerLine mounted below the list.

### tui/components/diff.py — new (StructuredDiff/Fallback.tsx port)
- transformLinesToObjects / processAdjacentLines (k-th remove ↔ k-th add
  pairing) / numberDiffLines / word-level diff with CHANGE_THRESHOLD=0.4
  fallback to whole-line. difflib.SequenceMatcher over words+whitespace
  tokens replaces jsdiff diffWordsWithSpace. darkTheme diff colours exact.
- Wired into Edit (old/new diff) and Write (diff vs existing file) permission
  previews. NOT ported: Rust colorDiff syntax highlighting (fallback IS the
  spec here), per-part wrap (Textual wraps).

### tui/components/input_bar.py — footer row (PromptInputFooterLeftSide)
- `? for shortcuts` idle hint; `! for bash mode` when input starts with `!`;
  mode indicator `⏵⏵ accept edits on (shift+tab to cycle)` / `⏸ plan mode on`
  with PermissionMode.ts config (titles/symbols/colours); `Press ctrl+c
  again to exit` ExitFlow with 2s window.
- shift+tab cycles default → acceptEdits → plan; bash mode `!cmd` posts
  BashInputSubmitted (runs in shell, echoes as bash-input/output messages,
  recorded in history for the model).
- repl.py: acceptEdits auto-approves edit tools; plan refuses them.

### optimus/__init__.py — startup fix
- `from optimus import tool` → `from optimus import Tool`: the file on disk
  is Tool.py; the lowercase import made `import optimus` fail everywhere.

## 2026-07-03 — TUI 1:1 porting pass (session 3)

### tui/themes.py — new (utils/theme.ts port)
- Theme dataclass with all 69 palette keys, snake_cased 1:1. All six themes:
  dark, light, light-daltonized, dark-daltonized, light-ansi, dark-ansi.
  RGB values converted to hex; ansi themes use Rich 16-colour names
  (chalk `ansi:redBright` → `bright_red`). get_theme() falls back to dark.
- set_active_theme/active_theme replace the useTheme React context.
- /theme command lists + switches. RE-ENTRY: widgets still load darkTheme
  hex values at import time — live restyle needs a widget-layer refresh pass.
- Omitted: themeColorToAnsi (chalk escape generation — Rich downgrades
  colours itself), Apple_Terminal 256-colour special case.

### tui/components/input_bar.py — ctrl+r reverse history search
- Port of PromptInput.tsx isSearchingHistory/historyQuery/historyFailedMatch
  + HistorySearchInput.tsx: footer shows `search prompts: <query>` /
  `no matching prompt: <query>`; the input displays the newest matching
  history entry (case-insensitive substring); ctrl+r again cycles older
  (clamps at oldest); Enter accepts the match; Escape restores what was
  typed before searching; typing edits the query.
- Textual-specific: focus moves to InputBar during search because Input
  consumes printable keys before they bubble (source equivalent:
  focus={!isSearchingHistory}). Input.Changed is suppressed while searching
  (suppressSuggestions).
- RE-ENTRY: cross-session persistent history (utils/history storage not
  ported; search covers the in-session history list).

### tui/components/input_bar.py — @-file mentions
- complete_file_paths ports the unified-suggestions file source: completes
  relative to cwd, directories suffixed '/', hidden entries only when the
  typed segment starts with '.', 13-item cap.
- Trailing '@token' opens the overlay in mention mode (SlashOverlay grew a
  generic items mode reusing the slash rendering); Tab/Enter replaces the
  token; directory completions keep the overlay open one level deeper.
- RE-ENTRY: mentions stay literal '@path' text in the prompt; converting to
  file-content attachments needs utils/attachments.ts.

### ctrl+o expand (CtrlOToExpand)
- Screen binding toggles full tool output on every ToolPanel; truncation
  notice now says "ctrl+o to expand". The screen-level ctrl+r binding was
  removed (ctrl+r is history search, as in source).
- RE-ENTRY: full transcript mode (ctrl+o in fullscreen flips to a separate
  transcript view) — this port only expands tool results.

## 2026-07-03 — visual-fidelity fixes from live screenshots (session 4)

### ToolPanel de-blocked (messages.py)
- Removed the invented background `#413c41` + thick purple border-left —
  Claude Code renders tool calls flat on the terminal background.
- Header is now `● Name(primary-arg)`: dot green/red/spinner, name bold
  default-colour, primary arg only (renderToolUseMessage style — e.g.
  `Write(index.html)`, not `file_path='C:\…'`). Paths relativised to cwd.
- Result row `⎿ …` in inactive grey (was green); errors stay red.

### Spinner pinned above the input bar (repl.py)
- SpinnerLine no longer mounts inside the scrollable message container; a
  fixed `#spinner-slot` sits between MessageList and InputBar, matching
  REPL.tsx (<Spinner> renders above <PromptInput>, outside the transcript).
  Screen owns _show_spinner/_hide_spinner; MessageList versions removed.

### Edit/Write tool results (messages.py)
- Edit family: `⎿ Updated <file> with N additions and M removals` +
  word-level StructuredDiff (12-row cap, ctrl+o expands) —
  FileEditToolResultMessage.
- Write: `⎿ Wrote N lines to <file>` — FileWriteToolResultMessage.
