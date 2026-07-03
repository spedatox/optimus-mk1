"""Prompt text for the ScheduleCron tool family (CronCreate/CronDelete/CronList)."""

CRON_CREATE_TOOL_NAME = "CronCreate"
CRON_DELETE_TOOL_NAME = "CronDelete"
CRON_LIST_TOOL_NAME = "CronList"

MAX_CRON_JOBS = 50

CRON_CREATE_DESCRIPTION = "Schedule a recurring or one-shot prompt using a cron expression."
CRON_DELETE_DESCRIPTION = "Cancel a scheduled cron job by ID."
CRON_LIST_DESCRIPTION = "List all active scheduled cron jobs."

CRON_CREATE_PROMPT = """\
Schedule a prompt to fire on a cron cadence within this session.

- `cron` is a standard 5-field expression (e.g. "*/5 * * * *").
- `recurring` true (default) fires every match; false fires once, then the job
  auto-deletes.
- `durable` true persists the job to disk so it survives restarts; false
  (default) keeps it in memory for this session only.

Use CronList to review jobs and CronDelete to cancel one.
"""

CRON_DELETE_PROMPT = "Cancel a scheduled cron job using the ID returned by CronCreate."

CRON_LIST_PROMPT = "List all active scheduled cron jobs with their schedule and prompt."
