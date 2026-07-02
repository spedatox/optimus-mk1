"""
optimus/tui/screens/repl.py

Main REPL screen — the central Textual screen that:
  - Displays the MessageList + InputBar + StatusBar
  - Drives the async query() loop
  - Handles slash commands (/help, /clear, /compact, /model, /exit, …)
  - Shows permission modals when the agent needs approval
  - Manages streaming: append_text per delta, finish on turn end

Port of: components/App.tsx + hooks/useQuery.ts + commands/keybindings/
"""
from __future__ import annotations

import asyncio
import os
import traceback
import uuid
from typing import Optional, Any

from textual import on
from textual.app import ComposeResult
from textual.screen import Screen

from optimus.tui.components.messages import (
    MessageList, MessageWidget, ToolCall,
)
from optimus.tui.components.input_bar import (
    InputBar, InputSubmitted, CancelRequested, SlashInputChanged,
    SlashOverlay,
)
from optimus.tui.components.status_bar import StatusBar
from optimus.tui.brand import ACCENT, NAME
from optimus.tui.components.permission import (
    PermissionRequest, PermissionModal, DangerousPermissionModal,
    PermissionManager, PermissionLevel,
    build_permission_request, AskUserQuestionModal,
)


# ---------------------------------------------------------------------------
# REPL Screen
# ---------------------------------------------------------------------------

class ReplScreen(Screen):
    """
    The main chat REPL screen.  All layout lives here; every interactive event
    is handled here and forwarded to the appropriate sub-widget.
    """

    CSS = """
    ReplScreen {
        layout: vertical;
        background: #1a1a1a;
        layers: base overlay;
    }
    /* Slash overlay floats above InputBar via layer + dock:bottom */
    SlashOverlay {
        layer: overlay;
    }
    """

    BINDINGS = [
        ("ctrl+c",   "request_cancel",   "Cancel"),
        ("ctrl+l",   "clear_screen",     "Clear"),
        ("f1",       "show_help",        "Help"),
        ("ctrl+r",   "focus_input",      "Focus Input"),
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
        initial_messages: list,
        thinking_config: dict,
        betas: list,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._prompt           = prompt
        self._model            = model
        self._tool_perm_ctx    = tool_permission_context
        self._mcp_clients      = mcp_clients
        self._tools            = tools
        self._system_prompt    = system_prompt
        self._append_system_prompt = append_system_prompt
        self._verbose          = verbose
        self._debug            = debug
        self._session_id       = session_id
        self._initial_messages = initial_messages
        self._thinking_config  = thinking_config
        self._betas            = betas
        self._name             = name

        # Runtime state
        self._history: list[dict]         = list(initial_messages)
        self._perm_manager                = PermissionManager()
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._query_task: Optional[asyncio.Task] = None
        self._session_grants: set[str]    = set()

        # User-configurable session preferences
        self._effort_level: str           = "medium"
        self._output_style: str           = "auto"
        self._allowed_dirs: set[str]      = {os.getcwd()}

        # Pre-built system prompt (populated in on_mount)
        self._built_system: list[str] = []
        self._system_ctx: dict = {}
        self._user_ctx: dict = {}

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        # Claude Code has no top header bar
        yield MessageList(model=self._model, cwd=os.getcwd(), id="message-list")
        yield SlashOverlay(id="slash-overlay")   # floats above InputBar via layer/dock
        yield InputBar(id="input-bar")
        yield StatusBar(id="status-bar")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        # Update status bar
        sb = self.query_one("#status-bar", StatusBar)
        sb.model = self._model
        sb.session_id = self._session_id
        sb.update_cwd(os.getcwd())

        # Detect git branch
        asyncio.create_task(self._detect_git_branch())

        # Build system prompt in background (doesn't block first paint)
        asyncio.create_task(self._prefetch_system_prompt())

        # Replay initial messages (--resume / --continue)
        if self._initial_messages:
            ml = self.query_one("#message-list", MessageList)
            for msg in self._initial_messages:
                role = msg.get("role", "user")
                content = ""
                raw_content = msg.get("content", "")
                if isinstance(raw_content, str):
                    content = raw_content
                elif isinstance(raw_content, list):
                    for block in raw_content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content += block.get("text", "")
                if role == "user" and content:
                    ml.add_user_message(content)
                elif role == "assistant" and content:
                    w = ml.add_assistant_message(streaming=False)
                    w.set_content(content)

        # Focus input
        self.query_one("#input-bar", InputBar).focus_input()

        # If --prompt was passed, fire it immediately
        if self._prompt:
            asyncio.create_task(self._run_query(self._prompt))

    async def _detect_git_branch(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--abbrev-ref", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                branch = stdout.decode().strip()
                sb = self.query_one("#status-bar", StatusBar)
                sb.git_branch = branch
        except Exception:
            pass

    async def _prefetch_system_prompt(self) -> None:
        try:
            from optimus.prompts import get_system_prompt
            from optimus.context import get_system_context, get_user_context
            built, sys_ctx, usr_ctx = await asyncio.gather(
                get_system_prompt(self._tools, self._model),
                get_system_context(),
                get_user_context(),
            )
            self._built_system = built
            self._system_ctx = sys_ctx
            self._user_ctx = usr_ctx
            if self._append_system_prompt:
                self._built_system.append(self._append_system_prompt)
            if self._system_prompt:
                self._built_system = [self._system_prompt] + self._built_system
        except Exception as exc:
            if self._debug:
                self._post_system(f"System prompt prefetch failed: {exc}")

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------

    @on(InputSubmitted)
    def on_input_submitted(self, event: InputSubmitted) -> None:
        text = event.text.strip()
        if not text:
            return
        event.stop()
        if text.startswith("/"):
            asyncio.create_task(self._handle_slash_command(text))
        else:
            asyncio.create_task(self._run_query(text))

    @on(CancelRequested)
    def on_cancel_requested(self, event: CancelRequested) -> None:
        event.stop()
        self._cancel_event.set()
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
        self._set_waiting(False)
        self._post_system("Cancelled.")

    @on(SlashInputChanged)
    def on_slash_input_changed(self, event: SlashInputChanged) -> None:
        """Relay slash-key input to the screen-level overlay."""
        event.stop()
        try:
            ov = self.query_one("#slash-overlay", SlashOverlay)
            if event.value:
                ov.update(event.value)
            else:
                ov.hide()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------

    def action_request_cancel(self) -> None:
        self._cancel_event.set()
        if self._query_task and not self._query_task.done():
            self._query_task.cancel()
        self._set_waiting(False)

    def action_clear_screen(self) -> None:
        asyncio.create_task(self._handle_slash_command("/clear"))

    def action_show_help(self) -> None:
        asyncio.create_task(self._handle_slash_command("/help"))

    def action_focus_input(self) -> None:
        self.query_one("#input-bar", InputBar).focus_input()

    # ------------------------------------------------------------------
    # Slash command handler
    # ------------------------------------------------------------------

    async def _handle_slash_command(self, text: str) -> None:  # noqa: C901
        parts = text.strip().split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # ── Navigation / session ──────────────────────────────────────────
        if cmd in ("/exit", "/quit", "/q"):
            self.app.exit()

        elif cmd in ("/clear", "/c"):
            ml = self.query_one("#message-list", MessageList)
            ml.clear_messages()
            self._history.clear()
            self._perm_manager.clear_session_grants()
            sb = self.query_one("#status-bar", StatusBar)
            sb.reset_for_new_session()
            self._post_system("Conversation cleared.")

        elif cmd in ("/help", "/h"):
            self._show_help()

        elif cmd == "/compact":
            await self._compact_conversation()

        elif cmd == "/rewind":
            self._cmd_rewind()

        elif cmd == "/resume":
            if arg:
                self._post_system(
                    f"Session resume not yet fully implemented.\n"
                    f"Requested session: {arg}\n"
                    "RE-ENTRY: optimus.utils.session_storage"
                )
            else:
                self._post_system("Usage: /resume <session-id>")

        # ── Model / output ────────────────────────────────────────────────
        elif cmd in ("/model", "/m"):
            if arg:
                self._switch_model(arg)
            else:
                self._post_system(
                    f"Current model: [bold]{self._model}[/bold]\n"
                    "Usage: /model <name>\n"
                    "Examples: /model claude-haiku-4-5  /model claude-sonnet-4-6  /model claude-opus-4"
                )

        elif cmd == "/effort":
            self._cmd_effort(arg)

        elif cmd == "/output-style":
            self._cmd_output_style(arg)

        # ── Context / memory ─────────────────────────────────────────────
        elif cmd == "/context":
            self._cmd_context()

        elif cmd == "/memory":
            self._post_system(
                "Memory management not yet implemented.\n"
                "RE-ENTRY: optimus.claudemd — port claudeMd.ts to unlock this."
            )

        elif cmd == "/add-dir":
            if arg:
                self._cmd_add_dir(arg)
            else:
                self._post_system("Usage: /add-dir <path>")

        elif cmd == "/files":
            await self._cmd_files()

        # ── Information ──────────────────────────────────────────────────
        elif cmd == "/status":
            self._show_status()

        elif cmd in ("/cost",):
            self._cmd_cost()

        elif cmd == "/stats":
            self._cmd_stats()

        elif cmd == "/session":
            self._cmd_session()

        elif cmd == "/permissions":
            self._cmd_permissions()

        elif cmd == "/release-notes":
            self._post_system(
                f"[bold {ACCENT}]Optimus Mark I — Recent Changes[/bold {ACCENT}]\n\n"
                "  v0.1.0 — TUI layer complete (JARVIS theme, streaming, permission modals)\n"
                "  v0.0.9 — Full system prompt wired (prompts.ts port)\n"
                "  v0.0.8 — Context / env utils ported\n"
                "  v0.0.7 — Constants (10 TS files) ported\n"
                "  v0.0.6 — query.py + Tool.py core loop working\n\n"
                "Source: https://github.com/spedatox/optimus-mark1"
            )

        # ── Git ──────────────────────────────────────────────────────────
        elif cmd == "/diff":
            await self._cmd_diff(arg)

        elif cmd == "/branch":
            await self._cmd_branch()

        elif cmd == "/pr-comments":
            if arg:
                await self._run_query(
                    f"Fetch and summarise the pull request comments for: {arg}\n"
                    "List open review threads, unresolved comments, and any requested changes."
                )
            else:
                self._post_system("Usage: /pr-comments <PR-URL or number>")

        # ── Code actions ─────────────────────────────────────────────────
        elif cmd == "/review":
            if arg:
                await self._run_query(
                    f"Please review this pull request thoroughly: {arg}\n"
                    "Cover: correctness, security, performance, style, and test coverage."
                )
            else:
                self._post_system("Usage: /review <PR-URL or branch>")

        elif cmd == "/security-review":
            target = arg or "the current codebase"
            await self._run_query(
                f"Perform a thorough security review of {target}.\n"
                "Check for: injection vulnerabilities, auth issues, secrets in code, "
                "insecure dependencies, path traversal, and OWASP Top 10."
            )

        elif cmd == "/init":
            await self._run_query(
                "Initialise a CLAUDE.md file for this project. "
                "Inspect the directory structure, key source files, and existing docs, "
                "then create a comprehensive CLAUDE.md that describes the project, "
                "its architecture, build commands, and guidelines for AI assistants."
            )

        elif cmd == "/plan":
            topic = arg or "the current task"
            await self._run_query(
                f"Enter planning mode for: {topic}\n"
                "Think step by step. Produce a numbered plan with clear milestones "
                "before writing any code. Ask clarifying questions if requirements are unclear."
            )

        # ── Config / tools ────────────────────────────────────────────────
        elif cmd == "/config":
            self._cmd_config(arg)

        elif cmd == "/mcp":
            self._cmd_mcp()

        elif cmd == "/vim":
            self._post_system("Vim keybindings: not yet implemented.\nRE-ENTRY: optimus.utils.vim_mode")

        elif cmd in ("/keybindings", "/keys"):
            self._cmd_keybindings()

        # ── Misc ─────────────────────────────────────────────────────────
        elif cmd == "/export":
            await self._export_conversation(arg or "conversation.md")

        elif cmd == "/copy":
            self._cmd_copy()

        elif cmd == "/doctor":
            self._cmd_doctor()

        elif cmd == "/feedback":
            self._post_system(
                "To report a bug or request a feature, open an issue at:\n"
                f"[bold {ACCENT}]https://github.com/spedatox/optimus-mark1/issues[/bold {ACCENT}]"
            )

        else:
            self._post_system(f"Unknown command: [bold]{cmd}[/bold]  — type /help for a list")

    def _show_help(self) -> None:
        help_text = (
            f"[bold {ACCENT}]Optimus Mark I — Commands[/bold {ACCENT}]\n\n"
            "[bold]Session[/bold]\n"
            "  /clear, /c              Clear conversation history\n"
            "  /compact                Summarise and compress conversation\n"
            "  /rewind                 Remove last exchange (Q + A)\n"
            "  /resume <id>            Resume a previous session\n"
            "  /export [file]          Export conversation to Markdown\n"
            "  /copy                   Copy last response to clipboard\n"
            "  /exit, /quit, /q        Exit Optimus\n\n"
            "[bold]Model[/bold]\n"
            "  /model [name]           Show or switch model\n"
            "  /effort <level>         Set effort: low|medium|high|max\n"
            "  /output-style <style>   Set style: verbose|concise|auto\n\n"
            "[bold]Context[/bold]\n"
            "  /context                Show context window usage\n"
            "  /memory                 Show memory files (requires claudemd.py port)\n"
            "  /add-dir <path>         Add directory to allowed paths\n"
            "  /files                  List files in current context\n\n"
            "[bold]Information[/bold]\n"
            "  /status                 Full session status\n"
            "  /cost                   Token usage and cost summary\n"
            "  /stats                  Session statistics\n"
            "  /session                Session ID and details\n"
            "  /permissions            Current permission state\n"
            "  /release-notes          Recent changelog\n\n"
            "[bold]Git[/bold]\n"
            "  /diff [file]            Show git diff\n"
            "  /branch                 Show git branch info\n"
            "  /pr-comments <PR>       Fetch PR review comments\n\n"
            "[bold]Code Actions[/bold]\n"
            "  /review <PR>            Review a pull request\n"
            "  /security-review [tgt]  Security audit\n"
            "  /init                   Initialise CLAUDE.md\n"
            "  /plan [topic]           Enter planning mode\n\n"
            "[bold]Config[/bold]\n"
            "  /config [key[=val]]     Show or set config\n"
            "  /mcp                    List MCP servers\n"
            "  /vim                    Toggle vim keybindings\n"
            "  /keybindings, /keys     Keyboard shortcut reference\n\n"
            "[bold]Misc[/bold]\n"
            "  /doctor                 Run diagnostics\n"
            "  /feedback               Open issue tracker\n"
            "  /help, /h               Show this help\n\n"
            "[bold]Keyboard Shortcuts[/bold]\n"
            "  Ctrl+C / Esc            Cancel current query\n"
            "  Ctrl+L                  Clear screen\n"
            "  F1                      Show help\n"
            "  Up / Down               Input history\n"
            "  Tab                     Autocomplete slash command"
        )
        self._post_system(help_text)

    def _show_status(self) -> None:
        sb = self.query_one("#status-bar", StatusBar)
        status = (
            f"[bold {ACCENT}]Session Status[/bold {ACCENT}]\n"
            f"  Model   : {self._model}\n"
            f"  Session : {self._session_id}\n"
            f"  Tokens  : {sb.input_tokens + sb.output_tokens:,} "
            f"(in {sb.input_tokens:,} / out {sb.output_tokens:,})\n"
            f"  Cost    : ${sb.cost_usd:.4f}\n"
            f"  Branch  : {sb.git_branch or '(not a git repo)'}\n"
            f"  Mode    : {sb.permission_mode}\n"
            f"  CWD     : {os.getcwd()}"
        )
        self._post_system(status)

    # ------------------------------------------------------------------
    # Individual command implementations
    # ------------------------------------------------------------------

    def _cmd_rewind(self) -> None:
        """Remove the last user+assistant exchange from history and the message list."""
        if len(self._history) < 2:
            self._post_system("Nothing to rewind.")
            return
        # Pop the last assistant reply, then the last user message
        removed: list[str] = []
        while self._history and self._history[-1]["role"] in ("assistant", "tool"):
            self._history.pop()
            removed.append("assistant")
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
            removed.append("user")
        # Rebuild the visible message list from remaining history
        ml = self.query_one("#message-list", MessageList)
        ml.clear_messages()
        for msg in self._history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if role == "user":
                ml.add_user_message(content)
            elif role == "assistant":
                w = ml.add_assistant_message(streaming=False)
                w.set_content(content)
        self._post_system(f"Rewound {len(removed)} message(s).")

    def _cmd_effort(self, arg: str) -> None:
        levels = {"low", "medium", "high", "max"}
        if arg not in levels:
            self._post_system(
                f"Current effort: [bold]{self._effort_level}[/bold]\n"
                f"Usage: /effort <low|medium|high|max>"
            )
            return
        self._effort_level = arg
        # Map effort to thinking budget
        budget_map = {"low": 0, "medium": 5000, "high": 10000, "max": 20000}
        budget = budget_map[arg]
        if budget > 0:
            self._thinking_config = {"type": "enabled", "budget_tokens": budget}
        else:
            self._thinking_config = {"type": "disabled"}
        self._post_system(f"Effort set to: [bold]{arg}[/bold]  (thinking budget: {budget:,} tokens)")

    def _cmd_output_style(self, arg: str) -> None:
        styles = {"verbose", "concise", "auto"}
        if arg not in styles:
            self._post_system(
                f"Current output style: [bold]{self._output_style}[/bold]\n"
                f"Usage: /output-style <verbose|concise|auto>"
            )
            return
        self._output_style = arg
        style_prompts = {
            "verbose": "From now on, give detailed, thorough responses with full explanations.",
            "concise": "From now on, be as brief and direct as possible. No filler text.",
            "auto":    "From now on, calibrate response length to the complexity of the question.",
        }
        self._post_system(f"Output style set to: [bold]{arg}[/bold]")
        # Inject a system message into history so the model follows it
        self._history.append({"role": "user",      "content": style_prompts[arg]})
        self._history.append({"role": "assistant",  "content": "Understood."})

    def _cmd_context(self) -> None:
        """Estimate context window usage from current history."""
        total_chars = sum(
            len(str(m.get("content", ""))) for m in self._history
        )
        # Rough token estimate: ~4 chars per token
        est_tokens = total_chars // 4
        context_limit = 200_000  # Claude 3/4 default
        pct = (est_tokens / context_limit) * 100
        bar_width = 30
        filled = int(bar_width * est_tokens / context_limit)
        bar = "█" * filled + "░" * (bar_width - filled)
        colour = ACCENT if pct < 60 else "#f0a500" if pct < 85 else "#ff6b35"
        self._post_system(
            f"[bold {ACCENT}]Context Window[/bold {ACCENT}]\n\n"
            f"  [{colour}]{bar}[/{colour}]  {pct:.1f}%\n\n"
            f"  Messages  : {len(self._history)}\n"
            f"  Est tokens: ~{est_tokens:,} / {context_limit:,}\n"
            f"  Est chars : {total_chars:,}\n\n"
            f"  [dim]Run /compact to compress when > 80%[/dim]"
        )

    def _cmd_add_dir(self, path: str) -> None:
        expanded = os.path.expanduser(os.path.expandvars(path))
        if not os.path.isdir(expanded):
            self._post_system(f"[red]Not a directory:[/red] {expanded}")
            return
        self._allowed_dirs.add(os.path.abspath(expanded))
        self._post_system(f"Added to allowed paths: [bold]{os.path.abspath(expanded)}[/bold]")

    async def _cmd_files(self) -> None:
        """List files recently mentioned in the conversation."""
        import re
        file_pattern = re.compile(r"[`'\"]([/\\][\w./\\-]+\.\w+)[`'\"]|([A-Za-z]:\\[\w./\\-]+\.\w+)")
        seen: set[str] = set()
        for msg in self._history:
            content = str(msg.get("content", ""))
            for m in file_pattern.finditer(content):
                f = m.group(1) or m.group(2)
                if f:
                    seen.add(f)
        if not seen:
            self._post_system("No specific files mentioned in this conversation yet.")
        else:
            lines = "\n".join(f"  {f}" for f in sorted(seen))
            self._post_system(f"[bold {ACCENT}]Files referenced in conversation:[/bold {ACCENT}]\n{lines}")

    def _cmd_cost(self) -> None:
        sb = self.query_one("#status-bar", StatusBar)
        in_tok  = sb.input_tokens
        out_tok = sb.output_tokens
        cost    = sb.cost_usd
        # Per-model pricing hints
        self._post_system(
            f"[bold {ACCENT}]Token Usage & Cost[/bold {ACCENT}]\n\n"
            f"  Input tokens  : {in_tok:>10,}\n"
            f"  Output tokens : {out_tok:>10,}\n"
            f"  Total tokens  : {in_tok + out_tok:>10,}\n"
            f"  ─────────────────────────────\n"
            f"  Estimated cost: ${cost:.4f} USD\n\n"
            f"  [dim]Pricing: ~$3/M in · ~$15/M out (Sonnet 4.x)[/dim]"
        )

    def _cmd_stats(self) -> None:
        sb = self.query_one("#status-bar", StatusBar)
        user_turns = sum(1 for m in self._history if m.get("role") == "user")
        asst_turns = sum(1 for m in self._history if m.get("role") == "assistant")
        self._post_system(
            f"[bold {ACCENT}]Session Statistics[/bold {ACCENT}]\n\n"
            f"  User messages      : {user_turns}\n"
            f"  Assistant messages : {asst_turns}\n"
            f"  Total exchanges    : {min(user_turns, asst_turns)}\n"
            f"  Input tokens       : {sb.input_tokens:,}\n"
            f"  Output tokens      : {sb.output_tokens:,}\n"
            f"  Total cost         : ${sb.cost_usd:.4f}\n"
            f"  Model              : {self._model}\n"
            f"  Effort level       : {self._effort_level}\n"
            f"  Output style       : {self._output_style}"
        )

    def _cmd_session(self) -> None:
        import datetime
        self._post_system(
            f"[bold {ACCENT}]Session Details[/bold {ACCENT}]\n\n"
            f"  Session ID : {self._session_id}\n"
            f"  Name       : {self._name or '(unnamed)'}\n"
            f"  Model      : {self._model}\n"
            f"  CWD        : {os.getcwd()}\n"
            f"  Started    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  Messages   : {len(self._history)}"
        )

    def _cmd_permissions(self) -> None:
        mode = self.query_one("#status-bar", StatusBar).permission_mode
        session_grants = list(self._perm_manager._session_grants.keys())
        permanent_grants = list(self._perm_manager._permanent_grants)
        lines = [
            f"[bold {ACCENT}]Permission State[/bold {ACCENT}]\n",
            f"  Mode : [bold]{mode}[/bold]\n",
            f"  Allowed dirs : {', '.join(self._allowed_dirs) or os.getcwd()}",
        ]
        if session_grants:
            lines.append("\n  Session approvals:")
            for tool, fp in session_grants:
                lines.append(f"    {tool} — {fp[:50] or '(any)'}")
        if permanent_grants:
            lines.append("\n  Permanent approvals:")
            for tool, fp in permanent_grants:
                lines.append(f"    {tool} — {fp[:50] or '(any)'}")
        if not session_grants and not permanent_grants:
            lines.append("\n  No pre-approvals recorded yet.")
        self._post_system("\n".join(lines))

    async def _cmd_diff(self, path: str) -> None:
        try:
            cmd_args = ["git", "diff", "--stat"]
            if path:
                cmd_args.append(path)
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                self._post_system(f"[red]git diff failed:[/red] {stderr.decode().strip()}")
                return
            output = stdout.decode().strip()
            if not output:
                self._post_system("No changes in working tree.")
            else:
                # Also get full diff if stat is short
                proc2 = await asyncio.create_subprocess_exec(
                    "git", "diff", *(["--", path] if path else []),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout2, _ = await proc2.communicate()
                full = stdout2.decode()
                # Truncate at 3000 chars
                preview = full[:3000] + ("\n…(truncated)" if len(full) > 3000 else "")
                self._post_system(
                    f"[bold {ACCENT}]git diff[/bold {ACCENT}]\n\n"
                    f"[bold]Stat:[/bold]\n{output}\n\n"
                    f"[bold]Diff:[/bold]\n{preview}"
                )
        except FileNotFoundError:
            self._post_system("[red]git not found in PATH.[/red]")

    async def _cmd_branch(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "branch", "-vv",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                self._post_system(f"[red]Not a git repo.[/red] {stderr.decode().strip()}")
                return
            output = stdout.decode().strip()
            sb = self.query_one("#status-bar", StatusBar)
            self._post_system(
                f"[bold {ACCENT}]Git Branches[/bold {ACCENT}]\n\n"
                f"  Current : [bold #4eba65]{sb.git_branch or '(detached)'}[/bold #4eba65]\n\n"
                f"{output}"
            )
        except FileNotFoundError:
            self._post_system("[red]git not found in PATH.[/red]")

    def _cmd_config(self, arg: str) -> None:
        if not arg:
            self._post_system(
                f"[bold {ACCENT}]Configuration[/bold {ACCENT}]\n\n"
                f"  model        = {self._model}\n"
                f"  effort       = {self._effort_level}\n"
                f"  output-style = {self._output_style}\n"
                f"  session-id   = {self._session_id}\n"
                f"  cwd          = {os.getcwd()}\n\n"
                "  Usage: /config <key>=<value>\n"
                "  RE-ENTRY: full config persistence via optimus.utils.config"
            )
            return
        if "=" in arg:
            key, _, val = arg.partition("=")
            key, val = key.strip(), val.strip()
            if key == "model":
                self._switch_model(val)
            elif key == "effort":
                self._cmd_effort(val)
            elif key == "output-style":
                self._cmd_output_style(val)
            else:
                self._post_system(
                    f"Unknown config key: [bold]{key}[/bold]\n"
                    "Available: model, effort, output-style"
                )
        else:
            self._post_system(f"Usage: /config <key>=<value>")

    def _cmd_mcp(self) -> None:
        if self._mcp_clients:
            lines = "\n".join(f"  {c}" for c in self._mcp_clients)
            self._post_system(f"[bold {ACCENT}]MCP Servers[/bold {ACCENT}]\n{lines}")
        else:
            self._post_system(
                f"[bold {ACCENT}]MCP Servers[/bold {ACCENT}]\n\n"
                "  No MCP servers connected.\n\n"
                "  RE-ENTRY: optimus.services.mcp — port services/mcp/ to enable."
            )

    def _cmd_keybindings(self) -> None:
        self._post_system(
            f"[bold {ACCENT}]Keyboard Shortcuts[/bold {ACCENT}]\n\n"
            "  [bold]Input[/bold]\n"
            "  Enter              Submit message\n"
            "  Up / Down          Navigate input history\n"
            "  Tab                Autocomplete slash command\n"
            "  Esc                Cancel query / close overlay\n"
            "  Ctrl+C             Cancel running query\n\n"
            "  [bold]Screen[/bold]\n"
            "  Ctrl+L             Clear screen\n"
            "  F1                 Show help\n"
            "  Ctrl+R             Focus input\n"
            "  Ctrl+Q             Quit\n\n"
            "  [bold]Slash overlay[/bold]\n"
            "  /...               Open command overlay\n"
            "  Up / Down          Navigate overlay items\n"
            "  Tab / Enter        Select command\n"
            "  Esc                Dismiss overlay"
        )

    def _cmd_copy(self) -> None:
        """Copy the last assistant response to the system clipboard."""
        last_asst = next(
            (m for m in reversed(self._history) if m.get("role") == "assistant"), None
        )
        if not last_asst:
            self._post_system("No assistant response to copy yet.")
            return
        content = last_asst.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        try:
            import subprocess
            if os.name == "nt":
                proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                proc.communicate(input=content.encode("utf-16"))
            else:
                # macOS
                try:
                    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                    proc.communicate(input=content.encode())
                except FileNotFoundError:
                    # Linux / xclip / xsel
                    proc = subprocess.Popen(
                        ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                    )
                    proc.communicate(input=content.encode())
            self._post_system(f"Copied {len(content):,} chars to clipboard.")
        except Exception as exc:
            self._post_system(f"[red]Copy failed:[/red] {exc}")

    def _cmd_doctor(self) -> None:
        import platform
        import sys as _sys
        lines = [
            f"[bold {ACCENT}]Optimus Mark I — Diagnostics[/bold {ACCENT}]\n",
            f"  Python   : {platform.python_version()} ({_sys.executable})",
            f"  Platform : {_sys.platform} / {platform.machine()}",
            f"  CWD      : {os.getcwd()}",
        ]
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            lines.append(f"  API Key  : set (…{api_key[-4:]})")
        else:
            lines.append("  API Key  : [red]NOT SET — set ANTHROPIC_API_KEY[/red]")
        try:
            import anthropic  # type: ignore[import]
            lines.append(f"  anthropic: {anthropic.__version__}")
        except ImportError:
            lines.append("  anthropic: [red]NOT INSTALLED[/red]")
        try:
            import textual  # type: ignore[import]
            lines.append(f"  textual  : {textual.__version__}")
        except ImportError:
            lines.append("  textual  : [red]NOT INSTALLED[/red]")
        lines.append(f"  Model    : {self._model}")
        lines.append(f"  Session  : {self._session_id}")
        self._post_system("\n".join(lines))

    def _switch_model(self, model_name: str) -> None:
        self._model = model_name
        sb = self.query_one("#status-bar", StatusBar)
        sb.model = model_name
        # Update welcome widget if still visible
        ml = self.query_one("#message-list", MessageList)
        ml.update_welcome_model(model_name)
        # Invalidate cached system prompt so it's rebuilt with the new model
        self._built_system = []
        asyncio.create_task(self._prefetch_system_prompt())
        self._post_system(f"Model switched to: {model_name}")

    async def _compact_conversation(self) -> None:
        if not self._history:
            self._post_system("Nothing to compact.")
            return
        self._post_system("Compacting conversation…")
        compact_prompt = (
            "Please summarise the conversation so far into a concise context block "
            "that captures all important decisions, code changes, and open questions. "
            "This summary will replace the current history."
        )
        await self._run_query(compact_prompt)

    async def _export_conversation(self, filename: str) -> None:
        try:
            lines: list[str] = [f"# Optimus Conversation Export\n\n"]
            for msg in self._history:
                role = msg.get("role", "user").title()
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                lines.append(f"## {role}\n\n{content}\n\n")
            with open(filename, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            self._post_system(f"Exported to: {os.path.abspath(filename)}")
        except Exception as exc:
            self._post_system(f"Export failed: {exc}")

    # ------------------------------------------------------------------
    # Query runner
    # ------------------------------------------------------------------

    async def _run_query(self, user_text: str) -> None:
        """Drive a full query turn: display user message, stream response."""
        ml = self.query_one("#message-list", MessageList)
        input_bar = self.query_one("#input-bar", InputBar)

        # Show user message
        ml.add_user_message(user_text)
        self._history.append({"role": "user", "content": user_text})

        # Lock input
        self._set_waiting(True)
        self._cancel_event.clear()

        # Create assistant message placeholder
        assistant_widget = ml.add_assistant_message(streaming=True)

        try:
            self._query_task = asyncio.create_task(
                self._stream_query(user_text, assistant_widget)
            )
            await self._query_task
        except asyncio.CancelledError:
            assistant_widget.finish_streaming("[dim italic]Cancelled.[/dim italic]")
        except Exception as exc:
            err_msg = f"Query error: {exc}"
            if self._debug:
                err_msg += f"\n{traceback.format_exc()}"
            ml.add_error_message(err_msg)
        finally:
            self._set_waiting(False)
            self._query_task = None
            input_bar.focus_input()

    async def _stream_query(
        self,
        user_text: str,
        assistant_widget: MessageWidget,
    ) -> None:
        """
        Inner coroutine: imports query() and streams events into assistant_widget.

        Event types from query_loop → action:
          stream_request_start   → (no-op — status bar already shows streaming)
          stream_delta           → append_text (plain Static in-place update)
          assistant              → parse tool_use / thinking, extract usage
          user                   → parse tool_result blocks → update_tool_result
          attachment             → log only
          Terminal               → extract final usage, break
          error                  → finish with error message
        """
        try:
            from optimus.query import (
                query, QueryParams, production_deps, Terminal,
            )
            from optimus.Tool import ToolUseContext, ToolUseContextOptions
            from optimus.api import call_model
        except ImportError as exc:
            assistant_widget.finish_streaming(f"[red]Import error: {exc}[/red]")
            return

        # Ensure system prompt is built
        if not self._built_system:
            await self._prefetch_system_prompt()

        messages = list(self._history)

        ctx = ToolUseContext(
            options=ToolUseContextOptions(
                main_loop_model=self._model,
                tools=self._tools,
                mcp_clients=self._mcp_clients,
                verbose=self._verbose,
                debug=self._debug,
            ),
        )
        ctx.ask_user_questions = self._ask_user_questions

        params = QueryParams(
            messages=messages,
            system_prompt=self._built_system,
            user_context=self._user_ctx,
            system_context=self._system_ctx,
            can_use_tool=self._make_can_use_tool(),
            tool_use_context=ctx,
            query_source="repl",
            deps=production_deps(call_model=call_model),
        )

        output_parts: list[str] = []
        current_tool_id: Optional[str] = None
        # Accumulate token usage across assistant messages in this turn
        total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        async for event in query(params):
            # Check for cancellation
            if self._cancel_event.is_set():
                break

            # ── Terminal — loop return value (dataclass, not dict) ─────
            if isinstance(event, Terminal):
                # Extract token usage accumulated during this turn
                self._update_token_usage(total_usage)
                break

            if not isinstance(event, dict):
                continue

            etype = event.get("type")

            # ── Turn start marker ─────────────────────────────────────
            if etype == "stream_request_start":
                # Status bar already shows streaming via _set_waiting(True).
                # This marker signals count-of-turns; we track it for debug.
                pass

            # ── Streaming text delta ──────────────────────────────────
            elif etype == "stream_delta":
                text = event.get("text", "")
                if text:
                    assistant_widget.append_text(text)
                    output_parts.append(text)

            # ── Complete assistant message ────────────────────────────
            elif etype == "assistant":
                msg = event.get("message", {})
                content_blocks = msg.get("content", [])
                full_text = ""
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_val = block.get("text", "")
                        full_text += text_val
                        if text_val and not output_parts:
                            # First text arrived — ensure widget shows it
                            assistant_widget.append_text(text_val)
                            output_parts.append(text_val)
                    elif btype == "thinking":
                        thinking = block.get("thinking", "")
                        assistant_widget.set_thinking(thinking)
                    elif btype == "tool_use":
                        tool_id = block.get("id", str(uuid.uuid4()))
                        tool_name = block.get("name", "Unknown")
                        tool_input = block.get("input", {})
                        tc = ToolCall(
                            id=tool_id,
                            name=tool_name,
                            input=tool_input,
                            is_running=True,
                        )
                        assistant_widget.add_tool_call(tc)
                        current_tool_id = tool_id

                # Accumulate token usage from this assistant message
                usage = msg.get("usage", {})
                if usage:
                    total_usage["input_tokens"] += usage.get("input_tokens", 0)
                    total_usage["output_tokens"] += usage.get("output_tokens", 0)

            # ── User message — contains tool_result blocks ─────────────
            elif etype == "user":
                # Tool results from _run_tools come wrapped as user messages:
                #   {'type':'user', 'message':{'role':'user','content':[
                #       {'type':'tool_result','tool_use_id':'...','content':'...','is_error':bool}
                #   ]}}
                msg = event.get("message", {})
                inner_content = msg.get("content", [])
                if isinstance(inner_content, str):
                    inner_content = [{"type": "text", "text": inner_content}]
                for block in inner_content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", current_tool_id or "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                b.get("text", "") for b in result_content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        is_error = block.get("is_error", False)
                        assistant_widget.update_tool_result(
                            tool_id, str(result_content), is_error=is_error,
                        )

            # ── Attachment message ────────────────────────────────────
            elif etype == "attachment":
                # attachment messages (max_turns_reached, hook_stopped, etc.)
                # are informational; log them to the message list.
                att = event.get("attachment", {})
                att_type = att.get("type", "unknown")
                self._post_system(f"[dim]ⓘ {att_type}[/dim]")

            # ── Error ─────────────────────────────────────────────────
            elif etype == "error":
                err = event.get("error", event)
                msg = (
                    err.get("message", str(err))
                    if isinstance(err, dict)
                    else str(err)
                )
                assistant_widget.finish_streaming(f"[bold red]Error:[/bold red] {msg}")
                return

        # Finalise assistant message — one-shot Markdown render
        final_content = "".join(output_parts)
        assistant_widget.finish_streaming(final_content)

        # Record the exchange in history
        if final_content:
            self._history.append({"role": "assistant", "content": final_content})

    # ------------------------------------------------------------------
    # Permission gating
    # ------------------------------------------------------------------

    def _make_can_use_tool(self):
        """
        Returns a callable suitable for QueryParams.can_use_tool.
        Checks the permission manager; if no pre-approval, shows a modal.
        """
        async def can_use_tool(tool_name: str, tool_input: dict) -> bool:
            req = build_permission_request(
                request_id=str(uuid.uuid4()),
                tool_name=tool_name,
                tool_input=tool_input,
            )

            # Pre-approved?
            if self._perm_manager.is_pre_approved(req):
                return True

            # Show modal and await decision
            decision = await self._show_permission_modal(req)
            self._perm_manager.record(req, decision)
            return decision in (
                PermissionLevel.ALLOW_ONCE,
                PermissionLevel.ALLOW_SESSION,
                PermissionLevel.ALLOW_PERMANENT,
            )

        return can_use_tool

    async def _show_permission_modal(self, req: PermissionRequest) -> str:
        """Push the appropriate modal and await the user's decision."""
        if req.risk_level in ("high", "critical"):
            modal = DangerousPermissionModal(req)
        else:
            modal = PermissionModal(req)
        # push_screen_wait suspends until modal is dismissed
        result = await self.app.push_screen_wait(modal)
        return result or PermissionLevel.DENY

    async def _ask_user_questions(self, questions: list) -> dict:
        """
        AskUserQuestion collector: push one modal per question, accumulate
        {question_text: answer_string}. Returns {} if the user declines any
        question (the caller treats that as a declined tool call).
        """
        answers: dict[str, str] = {}
        for q in questions:
            question_text = q.get("question", "")
            answer = await self.app.push_screen_wait(AskUserQuestionModal(q))
            if answer is None:
                return {}
            answers[question_text] = answer
        return answers

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_waiting(self, waiting: bool) -> None:
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.set_waiting(waiting)
        sb = self.query_one("#status-bar", StatusBar)
        sb.is_streaming = waiting

    def _post_system(self, content: str) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.add_system_message(content)

    def _update_token_usage(self, usage: dict) -> None:
        if not usage:
            return
        input_tok  = usage.get("input_tokens", 0)
        output_tok = usage.get("output_tokens", 0)
        # Rough cost estimate (Sonnet 4.x pricing)
        cost = (input_tok / 1_000_000) * 3.0 + (output_tok / 1_000_000) * 15.0
        sb = self.query_one("#status-bar", StatusBar)
        sb.add_tokens(input_tok, output_tok, cost)
