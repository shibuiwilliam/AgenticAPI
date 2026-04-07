"""Prompt building for intent parsing.

Constructs LLM prompts that instruct the model to parse natural
language requests into structured intent representations.
"""

from __future__ import annotations

import html

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

# Default actions if none are specified
_DEFAULT_ACTIONS: list[str] = ["read", "write", "analyze", "execute", "clarify"]

# Default JSON output schema description
_OUTPUT_SCHEMA = """\
{
    "action": "<one of the allowed actions>",
    "domain": "<domain of the request, e.g. 'order', 'product', 'user'>",
    "parameters": {
        "<key>": "<value>"
    },
    "confidence": <float 0.0-1.0>,
    "ambiguities": ["<list of ambiguous aspects, if any>"]
}"""


def build_intent_parsing_prompt(
    raw_request: str,
    allowed_actions: list[str] | None = None,
    domain_hints: list[str] | None = None,
) -> LLMPrompt:
    """Build an LLM prompt for parsing a natural language intent.

    Instructs the LLM to parse the raw request into structured JSON
    with action, domain, parameters, confidence, and ambiguities.

    Args:
        raw_request: The raw natural language request from the user.
        allowed_actions: List of allowed action types. Defaults to
                         ["read", "write", "analyze", "execute", "clarify"].
        domain_hints: Optional list of known domain names to help classification.

    Returns:
        An LLMPrompt ready to send to an LLM backend.
    """
    actions = allowed_actions or _DEFAULT_ACTIONS
    system = _build_system_prompt(actions, domain_hints)
    user = _build_user_prompt(raw_request)
    return LLMPrompt(
        system=system,
        messages=[LLMMessage(role="user", content=user)],
        temperature=0.0,
        max_tokens=1024,
    )


def _build_system_prompt(
    allowed_actions: list[str],
    domain_hints: list[str] | None,
) -> str:
    """Build the system prompt for intent parsing.

    Args:
        allowed_actions: List of allowed action types.
        domain_hints: Optional domain name hints.

    Returns:
        The system prompt string.
    """
    actions_str = ", ".join(f'"{a}"' for a in allowed_actions)

    domain_section = ""
    if domain_hints:
        domains_str = ", ".join(f'"{d}"' for d in domain_hints)
        domain_section = (
            f"\n\n## Known Domains\n{domains_str}\n"
            "Use these domain names when the request matches. For unknown domains, infer the most appropriate name."
        )

    return f"""\
You are an intent parsing agent for AgenticAPI. Your task is to parse a natural language \
request into a structured JSON representation.

## Rules

1. Classify the action as one of: {actions_str}
2. Extract the domain (the area of the system the request relates to).
3. Extract any parameters mentioned in the request.
4. Estimate your confidence (0.0 to 1.0) in the parsing accuracy.
5. List any ambiguities that may need clarification.
6. If the request is unclear or could be interpreted multiple ways, set action to "clarify" \
and list the ambiguities.
7. Output ONLY valid JSON. No explanations or markdown formatting.{domain_section}

## Output Schema

{_OUTPUT_SCHEMA}"""


def _build_user_prompt(raw_request: str) -> str:
    """Build the user prompt from the raw request.

    Args:
        raw_request: The user's natural language request.

    Returns:
        The user prompt string.
    """
    # Escape user input to prevent XML tag injection
    safe_request = html.escape(raw_request)
    return f"<request>\n{safe_request}\n</request>\n\nParse this request into the structured JSON format."
