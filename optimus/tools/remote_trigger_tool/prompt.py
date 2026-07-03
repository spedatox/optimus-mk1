"""Prompt text for RemoteTriggerTool."""

REMOTE_TRIGGER_TOOL_NAME = "RemoteTrigger"

DESCRIPTION = "Manage scheduled remote agent triggers (list, get, create, update, run)."

PROMPT = """\
Manage scheduled remote agent triggers via the claude.ai API.

Actions:
- list: list all triggers
- get: fetch one trigger (requires trigger_id)
- create: create a trigger (requires body)
- update: update a trigger (requires trigger_id and body)
- run: fire a trigger immediately (requires trigger_id)

Requires an authenticated session (oauth token); requests carry the triggers
beta header.
"""
