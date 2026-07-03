"""
tools/web_fetch_tool/web_fetch_tool.py — port of src/tools/WebFetchTool/WebFetchTool.ts

Fetch a URL, convert HTML→markdown, and answer a prompt about it using a small
fast model. Read-only.

Porting notes:
  - axios + LRUCache → httpx with a simple 15-min in-process TTL cache.
  - htmlToMarkdown (turndown-ish) → bs4 text extraction with light structure
    (headings/links/code preserved as markdown-ish). Not a full turndown port.
  - queryHaiku → optimus.api.query_fast_model.
  - Cross-host redirect detection preserved (returns a REDIRECT message).
  - Domain blocklist / permission preapproval rules → RE-ENTRY (preapproved-host
    list kept for the summary guidelines toggle). check_permissions returns
    'allow' (read-only); the loop's can_use_tool is the outer gate.
"""
from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from optimus.api import query_fast_model
from optimus.tool import PermissionResult, ToolResult, ToolUseContext, ValidationResult, build_tool
from optimus.tools.web_fetch_tool.prompt import (
    DESCRIPTION,
    WEB_FETCH_TOOL_NAME,
    make_secondary_model_prompt,
)

MAX_MARKDOWN_LENGTH = 100_000
_CACHE_TTL = 15 * 60  # 15 minutes
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

_PREAPPROVED_HOSTS = {
    "platform.claude.com", "code.claude.com", "modelcontextprotocol.io", "agentskills.io",
    "docs.python.org", "en.cppreference.com", "docs.oracle.com", "learn.microsoft.com",
    "developer.mozilla.org", "go.dev", "pkg.go.dev", "www.php.net", "docs.swift.org",
    "kotlinlang.org", "ruby-doc.org", "doc.rust-lang.org", "www.typescriptlang.org",
    "react.dev", "angular.io",
}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "The URL to fetch content from"},
        "prompt": {"type": "string", "description": "What information to extract from the page"},
    },
    "required": ["url", "prompt"],
    "additionalProperties": False,
}


def _is_preapproved(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) or url.find(h) >= 0 for h in _PREAPPROVED_HOSTS)


def _html_to_markdown(html: str, content_type: str) -> str:
    if "text/html" not in content_type and "<html" not in html[:2000].lower():
        return html  # already text/markdown/plain
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    parts: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code", "a"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        name = el.name
        if name in ("h1", "h2", "h3", "h4"):
            parts.append("#" * int(name[1]) + " " + text)
        elif name == "li":
            parts.append("- " + text)
        elif name in ("pre", "code"):
            parts.append("`" + text + "`")
        else:
            parts.append(text)
    md = "\n\n".join(parts)
    return md or soup.get_text("\n", strip=True)


@build_tool
class WebFetchTool:
    name = WEB_FETCH_TOOL_NAME
    search_hint = "fetch and summarize a web page"
    max_result_size_chars = 100_000
    input_schema = _INPUT_SCHEMA

    async def description(self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        return DESCRIPTION

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return input.get("url", "")

    def get_activity_description(self, input: Optional[dict[str, Any]] = None) -> Optional[str]:
        return "Fetching web content"

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        url = input.get("url", "")
        parsed = urlparse(url if "://" in url else "https://" + url)
        if not parsed.hostname:
            return ValidationResult.fail("The URL must be a fully-formed valid URL.", error_code=1)
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="allow", updated_input=input)

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        url = input["url"]
        prompt = input["prompt"]
        start = time.time()

        # Upgrade http → https.
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        elif "://" not in url:
            url = "https://" + url

        original_host = urlparse(url).hostname

        cached = _cache.get(url)
        if cached and time.time() - cached[0] < _CACHE_TTL:
            fetched = cached[1]
        else:
            try:
                async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
                    resp = await client.get(url, headers={"User-Agent": "Optimus/0.1 (+webfetch)"})
            except httpx.HTTPError as e:
                return ToolResult(data={"result": f"Failed to fetch {url}: {e}", "url": url, "durationMs": int((time.time() - start) * 1000)})

            # Cross-host redirect → return a message for the model to re-fetch.
            if resp.status_code in (301, 302, 307, 308):
                location = resp.headers.get("location", "")
                redirect_host = urlparse(location).hostname
                if redirect_host and redirect_host != original_host:
                    status_text = {301: "Moved Permanently", 308: "Permanent Redirect", 307: "Temporary Redirect"}.get(resp.status_code, "Found")
                    message = (
                        "REDIRECT DETECTED: The URL redirects to a different host.\n\n"
                        f"Original URL: {url}\nRedirect URL: {location}\nStatus: {resp.status_code} {status_text}\n\n"
                        f'To complete your request, use WebFetch again with:\n- url: "{location}"\n- prompt: "{prompt}"'
                    )
                    return ToolResult(data={"result": message, "url": url, "code": resp.status_code, "durationMs": int((time.time() - start) * 1000)})
                # Same-host redirect — follow it once.
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    resp = await client.get(url, headers={"User-Agent": "Optimus/0.1 (+webfetch)"})

            content_type = resp.headers.get("content-type", "")
            markdown = _html_to_markdown(resp.text, content_type)[:MAX_MARKDOWN_LENGTH]
            fetched = {"content": markdown, "content_type": content_type, "code": resp.status_code, "bytes": len(resp.content)}
            _cache[url] = (time.time(), fetched)

        is_preapproved = _is_preapproved(url)
        if is_preapproved and "text/markdown" in fetched["content_type"] and len(fetched["content"]) < MAX_MARKDOWN_LENGTH:
            result = fetched["content"]
        else:
            secondary = make_secondary_model_prompt(fetched["content"], prompt, is_preapproved)
            try:
                result = await query_fast_model(secondary)
            except Exception as e:  # noqa: BLE001
                # Network/model error — fall back to the raw markdown so the call
                # still yields something useful.
                result = f"[Summarization unavailable: {e}]\n\n{fetched['content'][:4000]}"

        return ToolResult(
            data={
                "result": result,
                "url": url,
                "code": fetched.get("code"),
                "bytes": fetched.get("bytes"),
                "durationMs": int((time.time() - start) * 1000),
            }
        )

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        return {"tool_use_id": tool_use_id, "type": "tool_result", "content": data["result"]}
