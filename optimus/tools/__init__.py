"""
Optimus tools package.

get_tools() is the single source of truth for the built-in tool pool, mirroring
getTools() in src/tools.ts. get_project_tools() instantiates the core toolset.
"""
import os

from optimus.tools.ask_user_question_tool import AskUserQuestionTool
from optimus.tools.file_edit_tool import FileEditTool
from optimus.tools.file_read_tool import FileReadTool
from optimus.tools.file_write_tool import FileWriteTool
from optimus.tools.glob_tool import GlobTool
from optimus.tools.grep_tool import GrepTool
from optimus.tools.notebook_edit_tool import NotebookEditTool
from optimus.tools.powershell_tool import PowerShellTool
from optimus.tools.todo_write_tool import TodoWriteTool
from optimus.tools.web_fetch_tool import WebFetchTool
from optimus.tools.web_search_tool import WebSearchTool

__all__ = [
    "AskUserQuestionTool",
    "FileEditTool",
    "FileReadTool",
    "FileWriteTool",
    "GlobTool",
    "GrepTool",
    "NotebookEditTool",
    "PowerShellTool",
    "TodoWriteTool",
    "WebFetchTool",
    "WebSearchTool",
    "get_project_tools",
    "get_tools",
]


def get_project_tools() -> list:
    """Instantiate the full agent toolset: file ops, search, shell, planning, web."""
    return [
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        GlobTool(),
        GrepTool(),
        NotebookEditTool(),
        PowerShellTool(),
        TodoWriteTool(),
        WebFetchTool(),
        WebSearchTool(),
        AskUserQuestionTool(),
    ]


def _is_env_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in ("1", "true", "yes")


def get_tools(permission_context: dict | None = None, mcp_clients: list | None = None) -> list:
    """
    Port of getTools() from src/tools.ts.

    Returns the enabled built-in tool pool for the given permission context.
    MCP tools are merged by assembleToolPool() upstream (RE-ENTRY: not yet
    ported), so mcp_clients is accepted but not used here — matching the TS
    split where getTools() handles only built-ins.

    Behavior mirrors the source:
      - CLAUDE_CODE_SIMPLE (--bare) → shell + read + edit only.
      - Otherwise the full base toolset, minus not-yet-ported special tools
        (ListMcpResources / ReadMcpResource / SyntheticOutput — none ported,
        so the exclusion is a no-op today).
      - filterToolsByDenyRules → no-op until deny-rule machinery is ported.
      - is_enabled() filter is applied (every ported tool is enabled).
    """
    if _is_env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE")):
        tools = [PowerShellTool(), FileReadTool(), FileEditTool()]
    else:
        tools = get_project_tools()

    # filterToolsByDenyRules(tools, permissionContext) — RE-ENTRY: deny-rule
    # filtering is a no-op until utils/permissions deny-rule machinery is ported.
    return [t for t in tools if t.is_enabled()]

