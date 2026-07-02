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
