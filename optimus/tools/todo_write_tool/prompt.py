"""tools/todo_write_tool/prompt.py — port of src/tools/TodoWriteTool/prompt.ts"""
from __future__ import annotations

TODO_WRITE_TOOL_NAME = "TodoWrite"

DESCRIPTION = (
    "Update the todo list for the current session. To be used proactively and "
    "often to track progress and pending tasks. Make sure that at least one task "
    "is in_progress at all times. Always provide both content (imperative) and "
    "activeForm (present continuous) for each task."
)

PROMPT = """Use this tool to create and manage a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.

## When to Use This Tool
Use this tool proactively when:
1. A task requires 3 or more distinct steps
2. The task is non-trivial and requires careful planning
3. The user explicitly requests a todo list
4. The user provides multiple tasks (numbered or comma-separated)
5. After receiving new instructions — capture requirements as todos
6. When you start working on a task — mark it in_progress BEFORE beginning (only one in_progress at a time)
7. After completing a task — mark it completed and add follow-ups discovered

## When NOT to Use This Tool
Skip when there is a single straightforward task, the task is trivial, it takes fewer than 3 steps, or it is purely conversational.

## Task States and Management
1. Each task has two forms:
   - content: imperative ("Run tests")
   - activeForm: present continuous ("Running tests")
2. Update status in real-time; mark complete IMMEDIATELY after finishing (don't batch).
3. Exactly ONE task in_progress at any time.
4. ONLY mark completed when fully accomplished — never if tests fail, implementation is partial, or errors are unresolved. Keep blocked tasks in_progress and add a new task describing the blocker.

When in doubt, use this tool. Being proactive with task management ensures you complete all requirements."""
