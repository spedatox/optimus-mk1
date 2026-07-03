"""Prompt text for TeamCreateTool."""

TEAM_CREATE_TOOL_NAME = "TeamCreate"

DESCRIPTION = "Create a new swarm team with a lead agent for coordinated multi-agent work."

PROMPT = """\
Create a new swarm team for coordinated multi-agent work. The team gets a
persisted team file and a lead agent id. Teammates communicate via SendMessage
and the team is disbanded with TeamDelete.
"""
