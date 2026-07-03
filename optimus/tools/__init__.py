"""
Optimus tools package.

get_tools() is the single source of truth for the built-in tool pool, mirroring
getTools() in src/tools.ts. get_project_tools() instantiates the core toolset.
"""
import os

from optimus.tools.agent_tool import AgentTool
from optimus.tools.ask_user_question_tool import AskUserQuestionTool
from optimus.tools.bash_tool import BashTool
from optimus.tools.brief_tool import BriefTool
from optimus.tools.config_tool import ConfigTool
from optimus.tools.enter_plan_mode_tool import EnterPlanModeTool
from optimus.tools.enter_worktree_tool import EnterWorktreeTool
from optimus.tools.exit_plan_mode_tool import ExitPlanModeTool
from optimus.tools.exit_worktree_tool import ExitWorktreeTool
from optimus.tools.file_edit_tool import FileEditTool
from optimus.tools.file_read_tool import FileReadTool
from optimus.tools.file_write_tool import FileWriteTool
from optimus.tools.glob_tool import GlobTool
from optimus.tools.grep_tool import GrepTool
from optimus.tools.list_mcp_resources_tool import ListMcpResourcesTool
from optimus.tools.lsp_tool import LSPTool
from optimus.tools.mcp_auth_tool import McpAuthTool
from optimus.tools.mcp_tool import MCPTool, make_mcp_tool
from optimus.tools.notebook_edit_tool import NotebookEditTool
from optimus.tools.powershell_tool import PowerShellTool
from optimus.tools.read_mcp_resource_tool import ReadMcpResourceTool
from optimus.tools.remote_trigger_tool import RemoteTriggerTool
from optimus.tools.repl_tool import REPLTool
from optimus.tools.schedule_cron_tool import CronCreateTool, CronDeleteTool, CronListTool
from optimus.tools.send_message_tool import SendMessageTool
from optimus.tools.skill_tool import SkillTool
from optimus.tools.sleep_tool import SleepTool
from optimus.tools.synthetic_output_tool import SyntheticOutputTool
from optimus.tools.task_create_tool import TaskCreateTool
from optimus.tools.task_get_tool import TaskGetTool
from optimus.tools.task_list_tool import TaskListTool
from optimus.tools.task_output_tool import TaskOutputTool
from optimus.tools.task_stop_tool import TaskStopTool
from optimus.tools.task_update_tool import TaskUpdateTool
from optimus.tools.team_create_tool import TeamCreateTool
from optimus.tools.team_delete_tool import TeamDeleteTool
from optimus.tools.todo_write_tool import TodoWriteTool
from optimus.tools.tool_search_tool import ToolSearchTool
from optimus.tools.web_fetch_tool import WebFetchTool
from optimus.tools.web_search_tool import WebSearchTool

__all__ = [
    "AgentTool",
    "AskUserQuestionTool",
    "BashTool",
    "BriefTool",
    "ConfigTool",
    "CronCreateTool",
    "CronDeleteTool",
    "CronListTool",
    "EnterPlanModeTool",
    "EnterWorktreeTool",
    "ExitPlanModeTool",
    "ExitWorktreeTool",
    "FileEditTool",
    "FileReadTool",
    "FileWriteTool",
    "GlobTool",
    "GrepTool",
    "LSPTool",
    "ListMcpResourcesTool",
    "MCPTool",
    "McpAuthTool",
    "NotebookEditTool",
    "PowerShellTool",
    "REPLTool",
    "ReadMcpResourceTool",
    "RemoteTriggerTool",
    "SendMessageTool",
    "SkillTool",
    "SleepTool",
    "SyntheticOutputTool",
    "TaskCreateTool",
    "TaskGetTool",
    "TaskListTool",
    "TaskOutputTool",
    "TaskStopTool",
    "TaskUpdateTool",
    "TeamCreateTool",
    "TeamDeleteTool",
    "TodoWriteTool",
    "ToolSearchTool",
    "WebFetchTool",
    "WebSearchTool",
    "get_project_tools",
    "get_tools",
    "make_mcp_tool",
]


def get_project_tools() -> list:
    """Instantiate the full agent toolset: file ops, search, shell, planning,
    web, agents, tasks, MCP, scheduling, and swarm coordination."""
    return [
        # File ops & search
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        GlobTool(),
        GrepTool(),
        NotebookEditTool(),
        # Shells
        BashTool(),
        PowerShellTool(),
        # Planning & interaction
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        AskUserQuestionTool(),
        # Web
        WebFetchTool(),
        WebSearchTool(),
        # Agents & skills
        AgentTool(),
        SkillTool(),
        ToolSearchTool(),
        SleepTool(),
        REPLTool(),
        BriefTool(),
        ConfigTool(),
        SyntheticOutputTool(),
        # Structured task list
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskUpdateTool(),
        # Background tasks
        TaskOutputTool(),
        TaskStopTool(),
        # Worktrees
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        # MCP
        ListMcpResourcesTool(),
        ReadMcpResourceTool(),
        McpAuthTool(),
        # Scheduling & remote
        CronCreateTool(),
        CronDeleteTool(),
        CronListTool(),
        RemoteTriggerTool(),
        # Swarm
        TeamCreateTool(),
        TeamDeleteTool(),
        SendMessageTool(),
        # LSP (enabled only when a language server is registered)
        LSPTool(),
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
      - Otherwise the full base toolset.
      - filterToolsByDenyRules → no-op until deny-rule machinery is ported.
      - is_enabled() filter is applied (SyntheticOutput appears only when a
        caller registered an output schema; LSP only when a language server
        is connected).
    """
    if _is_env_truthy(os.environ.get("CLAUDE_CODE_SIMPLE")):
        tools = [BashTool(), PowerShellTool(), FileReadTool(), FileEditTool()]
    else:
        tools = get_project_tools()

    # filterToolsByDenyRules(tools, permissionContext) — RE-ENTRY: deny-rule
    # filtering is a no-op until utils/permissions deny-rule machinery is ported.
    return [t for t in tools if t.is_enabled()]
