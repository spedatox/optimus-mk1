"""tools/web_fetch_tool/prompt.py — port of src/tools/WebFetchTool/prompt.ts"""
from __future__ import annotations

WEB_FETCH_TOOL_NAME = "WebFetch"

DESCRIPTION = """
- Fetches content from a specified URL and processes it using an AI model
- Takes a URL and a prompt as input
- Fetches the URL content, converts HTML to markdown
- Processes the content with the prompt using a small, fast model
- Returns the model's response about the content
- Use this tool when you need to retrieve and analyze web content

Usage notes:
  - The URL must be a fully-formed valid URL
  - HTTP URLs will be automatically upgraded to HTTPS
  - The prompt should describe what information you want to extract from the page
  - This tool is read-only and does not modify any files
  - When a URL redirects to a different host, the tool will inform you and provide the redirect URL; make a new WebFetch request with the redirect URL.
  - For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, gh issue view, gh api).
"""


def make_secondary_model_prompt(markdown_content: str, prompt: str, is_preapproved_domain: bool) -> str:
    if is_preapproved_domain:
        guidelines = (
            "Provide a concise response based on the content above. Include relevant "
            "details, code examples, and documentation excerpts as needed."
        )
    else:
        guidelines = (
            "Provide a concise response based only on the content above. In your response:\n"
            " - Enforce a strict 125-character maximum for quotes from any source document.\n"
            " - Use quotation marks for exact language; paraphrase otherwise.\n"
            " - You are not a lawyer and never comment on legality.\n"
            " - Never reproduce exact song lyrics."
        )
    return f"\nWeb page content:\n---\n{markdown_content}\n---\n\n{prompt}\n\n{guidelines}\n"
