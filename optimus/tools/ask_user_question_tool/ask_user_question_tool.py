"""
tools/ask_user_question_tool/ask_user_question_tool.py — port of
src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx

Asks the user multiple-choice questions (1-4 questions, each 2-4 options).
Answers are collected by the permission flow (the ask-user-questions callback on
ToolUseContext) and injected into the tool input as `answers` before call() —
mirroring the TS flow where the AskUserQuestionFrame writes answers into
updatedInput. call() itself just echoes the questions + collected answers.

Porting notes:
  - React render fns (AskUserQuestionResultMessage etc.) → return None (no UI
    layer); the TUI has its own AskUserQuestionModal.
  - feature('KAIROS'/'KAIROS_CHANNELS') → False, so is_enabled → True.
  - Zod `.refine(UNIQUENESS_REFINE)` → enforced in validate_input (JSON schema
    can't express cross-field uniqueness).
  - getQuestionPreviewFormat / getAllowedChannels → bootstrap state (ported).
  - HTML preview validation (validateHtmlPreview) → ported verbatim.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from optimus.Tool import (
    PermissionResult,
    ToolResult,
    ToolUseContext,
    ValidationResult,
    build_tool,
)
from optimus.bootstrap.state import get_allowed_channels, get_question_preview_format
from optimus.tools.ask_user_question_tool.prompt import (
    ASK_USER_QUESTION_TOOL_CHIP_WIDTH,
    ASK_USER_QUESTION_TOOL_NAME,
    ASK_USER_QUESTION_TOOL_PROMPT,
    DESCRIPTION,
    PREVIEW_FEATURE_PROMPT,
)

# ---------------------------------------------------------------------------
# JSON schemas (mirror the Zod schemas)
# ---------------------------------------------------------------------------

_QUESTION_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "description": (
                "The display text for this option that the user will see and "
                "select. Should be concise (1-5 words) and clearly describe the choice."
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "Explanation of what this option means or what will happen if "
                "chosen. Useful for providing context about trade-offs or implications."
            ),
        },
        "preview": {
            "type": "string",
            "description": (
                "Optional preview content rendered when this option is focused. "
                "Use for mockups, code snippets, or visual comparisons that help "
                "users compare options. See the tool description for the expected "
                "content format."
            ),
        },
    },
    "required": ["label", "description"],
    "additionalProperties": False,
}

_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": (
                "The complete question to ask the user. Should be clear, specific, "
                'and end with a question mark. Example: "Which library should we '
                'use for date formatting?" If multiSelect is true, phrase it '
                'accordingly, e.g. "Which features do you want to enable?"'
            ),
        },
        "header": {
            "type": "string",
            "description": (
                "Very short label displayed as a chip/tag (max "
                f"{ASK_USER_QUESTION_TOOL_CHIP_WIDTH} chars). Examples: "
                '"Auth method", "Library", "Approach".'
            ),
        },
        "options": {
            "type": "array",
            "items": _QUESTION_OPTION_SCHEMA,
            "minItems": 2,
            "maxItems": 4,
            "description": (
                "The available choices for this question. Must have 2-4 options. "
                "Each option should be a distinct, mutually exclusive choice "
                "(unless multiSelect is enabled). There should be no 'Other' "
                "option, that will be provided automatically."
            ),
        },
        "multiSelect": {
            "type": "boolean",
            "default": False,
            "description": (
                "Set to true to allow the user to select multiple options instead "
                "of just one. Use when choices are not mutually exclusive."
            ),
        },
    },
    "required": ["question", "header", "options"],
    "additionalProperties": False,
}

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": _QUESTION_SCHEMA,
            "minItems": 1,
            "maxItems": 4,
            "description": "Questions to ask the user (1-4 questions)",
        },
        "answers": {
            "type": "object",
            "description": "User answers collected by the permission component",
            "additionalProperties": {"type": "string"},
        },
        "annotations": {
            "type": "object",
            "description": (
                "Optional per-question annotations from the user (e.g., notes on "
                "preview selections). Keyed by question text."
            ),
        },
        "metadata": {
            "type": "object",
            "description": "Optional metadata for tracking and analytics purposes. Not displayed to user.",
            "properties": {
                "source": {
                    "type": "string",
                    "description": 'Optional identifier for the source of this question (e.g., "remember" for /remember command). Used for analytics tracking.',
                },
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": _QUESTION_SCHEMA, "description": "The questions that were asked"},
        "answers": {
            "type": "object",
            "description": "The answers provided by the user (question text -> answer string; multi-select answers are comma-separated)",
            "additionalProperties": {"type": "string"},
        },
        "annotations": {
            "type": "object",
            "description": "Optional per-question annotations from the user, keyed by question text.",
        },
    },
    "required": ["questions", "answers"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Uniqueness check (mirrors UNIQUENESS_REFINE)
# ---------------------------------------------------------------------------

def _check_uniqueness(questions: list[dict[str, Any]]) -> bool:
    """Question texts must be unique; option labels unique within each question."""
    q_texts = [q.get("question") for q in questions]
    if len(q_texts) != len(set(q_texts)):
        return False
    for q in questions:
        labels = [opt.get("label") for opt in q.get("options", [])]
        if len(labels) != len(set(labels)):
            return False
    return True


# ---------------------------------------------------------------------------
# HTML preview validation (verbatim port of validateHtmlPreview)
# ---------------------------------------------------------------------------

_HTML_DOC_RE = re.compile(r"<\s*(html|body|!doctype)\b", re.IGNORECASE)
_HTML_SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style)\b", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[a-z][^>]*>", re.IGNORECASE)


def _validate_html_preview(preview: Optional[str]) -> Optional[str]:
    """Return an error message string, or None if valid."""
    if preview is None:
        return None
    if _HTML_DOC_RE.search(preview):
        return "preview must be an HTML fragment, not a full document (no <html>, <body>, or <!DOCTYPE>)"
    if _HTML_SCRIPT_STYLE_RE.search(preview):
        return "preview must not contain <script> or <style> tags. Use inline styles via the style attribute if needed."
    if not _HTML_TAG_RE.search(preview):
        return 'preview must contain HTML (previewFormat is set to "html"). Wrap content in a tag like <div> or <pre>.'
    return None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@build_tool
class AskUserQuestionTool:
    name = ASK_USER_QUESTION_TOOL_NAME
    search_hint = "prompt the user with a multiple-choice question"
    max_result_size_chars = 100_000
    strict = True
    should_defer = True
    input_schema = _INPUT_SCHEMA
    output_schema = _OUTPUT_SCHEMA

    async def description(
        self, input: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None
    ) -> str:
        return DESCRIPTION

    async def prompt(self, options: Optional[dict[str, Any]] = None) -> str:
        fmt = get_question_preview_format()
        if fmt is None:
            # SDK consumer that hasn't opted into a preview format — omit guidance.
            return ASK_USER_QUESTION_TOOL_PROMPT
        return ASK_USER_QUESTION_TOOL_PROMPT + PREVIEW_FEATURE_PROMPT[fmt]

    def user_facing_name(self, input: Optional[dict[str, Any]] = None) -> str:
        return ""

    def is_enabled(self) -> bool:
        # feature('KAIROS'/'KAIROS_CHANNELS') → False, so the channels branch is
        # never taken. Kept structurally to mirror the TS guard.
        if get_allowed_channels():
            return False
        return True

    def is_concurrency_safe(self, input: dict[str, Any]) -> bool:
        return True

    def is_read_only(self, input: dict[str, Any]) -> bool:
        return True

    def to_auto_classifier_input(self, input: dict[str, Any]) -> str:
        return " | ".join(q.get("question", "") for q in input.get("questions", []))

    def requires_user_interaction(self) -> bool:
        return True

    async def validate_input(self, input: dict[str, Any], context: ToolUseContext) -> ValidationResult:
        questions = input.get("questions", [])
        if not _check_uniqueness(questions):
            return ValidationResult.fail(
                "Question texts must be unique, option labels must be unique within each question",
                error_code=1,
            )
        if get_question_preview_format() != "html":
            return ValidationResult.ok()
        for q in questions:
            for opt in q.get("options", []):
                err = _validate_html_preview(opt.get("preview"))
                if err:
                    return ValidationResult.fail(
                        f'Option "{opt.get("label")}" in question "{q.get("question")}": {err}',
                        error_code=1,
                    )
        return ValidationResult.ok()

    async def check_permissions(self, input: dict[str, Any], context: ToolUseContext) -> PermissionResult:
        return PermissionResult(behavior="ask", message="Answer questions?", updated_input=input)

    def map_tool_result_to_tool_result_block_param(self, data: Any, tool_use_id: str) -> dict[str, Any]:
        answers: dict[str, str] = data.get("answers") or {}
        annotations: dict[str, Any] = data.get("annotations") or {}
        parts_list = []
        for question_text, answer in answers.items():
            annotation = annotations.get(question_text) or {}
            parts = [f'"{question_text}"="{answer}"']
            if annotation.get("preview"):
                parts.append(f"selected preview:\n{annotation['preview']}")
            if annotation.get("notes"):
                parts.append(f"user notes: {annotation['notes']}")
            parts_list.append(" ".join(parts))
        answers_text = ", ".join(parts_list)
        return {
            "type": "tool_result",
            "content": (
                f"User has answered your questions: {answers_text}. "
                "You can now continue with the user's answers in mind."
            ),
            "tool_use_id": tool_use_id,
        }

    async def call(
        self,
        input: dict[str, Any],
        context: ToolUseContext,
        can_use_tool: Any = None,
        parent_message: Any = None,
        on_progress: Any = None,
    ) -> ToolResult:
        questions = input["questions"]
        answers = input.get("answers") or {}
        data: dict[str, Any] = {"questions": questions, "answers": answers}
        annotations = input.get("annotations")
        if annotations:
            data["annotations"] = annotations
        return ToolResult(data=data)
