"""tools/web_search_tool/prompt.py — port of src/tools/WebSearchTool/prompt.ts"""
from __future__ import annotations

import time

WEB_SEARCH_TOOL_NAME = "WebSearch"


def get_web_search_prompt() -> str:
    current_month_year = time.strftime("%B %Y")
    return f"""
- Allows the agent to search the web and use the results to inform responses
- Provides up-to-date information for current events and recent data
- Returns search result information formatted as search result blocks, including links as markdown hyperlinks
- Use this tool for accessing information beyond the model's knowledge cutoff
- Searches are performed automatically within a single API call

CRITICAL REQUIREMENT:
  - After answering the user's question, you MUST include a "Sources:" section at the end of your response
  - In the Sources section, list all relevant URLs as markdown hyperlinks: [Title](URL)

Usage notes:
  - Domain filtering is supported to include or block specific websites
  - The current month is {current_month_year}. Use the correct year in search queries.
"""
