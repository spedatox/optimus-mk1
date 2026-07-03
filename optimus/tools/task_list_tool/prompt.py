"""Prompt text for TaskListTool — port of src/tools/TaskListTool/prompt.ts."""

from optimus.utils.tasks import is_agent_swarms_enabled

TASK_LIST_TOOL_NAME = "TaskList"

DESCRIPTION = "List all tasks in the task list"


def get_prompt() -> str:
    teammate_use_case = (
        "- Before assigning tasks to teammates, to see what's available\n"
        if is_agent_swarms_enabled()
        else ""
    )
    teammate_workflow = (
        """
## Teammate Workflow

When working as a teammate:
1. After completing your current task, call TaskList to find available work
2. Look for tasks with status 'pending', no owner, and empty blockedBy
3. **Prefer tasks in ID order** (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones
4. Claim an available task using TaskUpdate (set `owner` to your name), or wait for leader assignment
5. If blocked, focus on unblocking tasks or notify the team lead
"""
        if is_agent_swarms_enabled()
        else ""
    )

    return f"""Use this tool to list all tasks in the task list.

## When to Use This Tool

- To see what tasks are available to work on (status: 'pending', no owner, not blocked)
- To check overall progress on the project
- To find tasks that are blocked and need dependencies resolved
{teammate_use_case}- After completing a task, to check for newly unblocked work or claim the next available task
- **Prefer working on tasks in ID order** (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones

## Output

Returns a summary of each task:
- **id**: Task identifier (use with TaskGet, TaskUpdate)
- **subject**: Brief description of the task
- **status**: 'pending', 'in_progress', or 'completed'
- **owner**: Agent ID if assigned, empty if available
- **blockedBy**: List of open task IDs that must be resolved first (tasks with blockedBy cannot be claimed until dependencies resolve)

Use TaskGet with a specific task ID to view full details including description and comments.
{teammate_workflow}"""
