"""Bridge AgenticAPI policies into the Claude Agent SDK permission system.

The Claude Agent SDK gates every tool invocation through two
mechanisms:

1. ``can_use_tool``: an async callback that returns either
   ``PermissionResultAllow`` or ``PermissionResultDeny`` for each
   tool call. This is the user-facing permission API.
2. Hooks: ``PreToolUse`` / ``PostToolUse`` / ``Stop`` callbacks that
   fire around tool execution and can mutate inputs, deny operations,
   add audit context, or trigger external systems.

Both fire for every tool call (built-in and MCP). We use them
together for defence in depth: ``can_use_tool`` for declarative
policy decisions, and a ``PreToolUse`` hook for AST-based static
analysis of generated shell/Python code.

The :class:`HarnessPermissionAdapter` is a small, *stateful* helper
that tracks every permission decision so the runner can later
attach them to the audit trace.
"""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import PolicyViolation
from agenticapi.ext.claude_agent_sdk._imports import load_sdk
from agenticapi.harness.policy.evaluator import PolicyEvaluator
from agenticapi.harness.sandbox.static_analysis import check_code_safety

if TYPE_CHECKING:
    from agenticapi.harness.policy.base import Policy

logger = structlog.get_logger(__name__)


# Tool names whose ``input`` field carries Python or shell code that we
# want to push through the static analyser. Mapping is ``tool_name`` →
# ``input field that holds code``.
_CODE_CARRYING_TOOLS: dict[str, str] = {
    "Bash": "command",
    "Write": "content",
    "Edit": "new_string",
}

# Subset of code-carrying tools whose payload is *Python source*. The
# AgenticAPI :class:`PolicyEvaluator` parses the payload as Python, so
# applying it to shell commands would always fail with a syntax error.
# Bash payloads are guarded by :func:`_detect_risky_shell` in the
# ``PreToolUse`` hook instead.
_PYTHON_CODE_TOOLS: frozenset[str] = frozenset({"Write", "Edit"})


@dataclass(slots=True)
class PermissionDecision:
    """A single permission decision recorded by the adapter.

    Attributes:
        tool_name: Name of the tool the model tried to call.
        allowed: Final decision after all policies and analysers ran.
        reason: Human-readable explanation. Empty string when allowed.
        violations: Detailed violation strings (for denials).
    """

    tool_name: str
    allowed: bool
    reason: str = ""
    violations: list[str] = field(default_factory=list)


class HarnessPermissionAdapter:
    """Bridge AgenticAPI policies into the Claude Agent SDK permission API.

    The adapter is constructed with the AgenticAPI policies and tool
    allow-list, and exposes:

    - :meth:`can_use_tool` — pass to ``ClaudeAgentOptions.can_use_tool``.
    - :meth:`pre_tool_use_hook` — pass inside ``HookMatcher`` for
      ``PreToolUse``.
    - :attr:`decisions` — accumulated audit log.

    Example:
        adapter = HarnessPermissionAdapter(
            policies=[CodePolicy(denied_modules=["os"])],
            allowed_tool_names=["Read", "Glob", "Grep", "mcp__agenticapi__db"],
        )
        options = ClaudeAgentOptions(
            can_use_tool=adapter.can_use_tool,
            hooks={"PreToolUse": [HookMatcher(hooks=[adapter.pre_tool_use_hook])]},
        )
    """

    def __init__(
        self,
        *,
        policies: Sequence[Policy] = (),
        allowed_tool_names: Sequence[str] = (),
        denied_tool_names: Sequence[str] = (),
        deny_unknown_tools: bool = False,
    ) -> None:
        """Initialize the adapter.

        Args:
            policies: AgenticAPI policies to enforce.
            allowed_tool_names: Tool names the runner explicitly allows.
                ``can_use_tool`` returns ``Allow`` for these without
                consulting policies (the model already had to negotiate
                static AgenticAPI permissions to get the tool listed).
            denied_tool_names: Tool names always denied. Takes precedence
                over ``allowed_tool_names``.
            deny_unknown_tools: When True, any tool name not in
                ``allowed_tool_names`` is denied — strict mode for
                production endpoints.
        """
        self._policies: list[Policy] = list(policies)
        self._evaluator = PolicyEvaluator(policies=self._policies)
        self._allowed: set[str] = set(allowed_tool_names)
        self._denied: set[str] = set(denied_tool_names)
        self._deny_unknown = deny_unknown_tools
        self._decisions: list[PermissionDecision] = []

    @property
    def decisions(self) -> list[PermissionDecision]:
        """Return a copy of all permission decisions made so far."""
        return list(self._decisions)

    def reset(self) -> None:
        """Forget previous decisions. Call between independent sessions."""
        self._decisions.clear()

    # ------------------------------------------------------------------
    # can_use_tool callback
    # ------------------------------------------------------------------

    async def can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: Any,  # ToolPermissionContext from the SDK
    ) -> Any:
        """Permission callback for ``ClaudeAgentOptions.can_use_tool``.

        Returns ``PermissionResultAllow`` or ``PermissionResultDeny``
        from the SDK. The exact types are imported lazily so the
        adapter can be constructed without the SDK installed.
        """
        del context  # unused but part of the SDK contract

        sdk = load_sdk()

        if tool_name in self._denied:
            return self._record_deny(
                sdk,
                tool_name=tool_name,
                reason=f"Tool '{tool_name}' is on the deny list",
            )

        if self._deny_unknown and tool_name not in self._allowed:
            return self._record_deny(
                sdk,
                tool_name=tool_name,
                reason=(f"Tool '{tool_name}' is not on the allow list (strict mode active)"),
            )

        # Run AgenticAPI policies for Python-source-carrying tools so that
        # CodePolicy.denied_modules etc. apply to Write/Edit. Bash payloads
        # are guarded by the PreToolUse hook because PolicyEvaluator parses
        # its input as Python and would always reject shell commands.
        if tool_name in _PYTHON_CODE_TOOLS and self._policies:
            field_name = _CODE_CARRYING_TOOLS[tool_name]
            code = str(tool_input.get(field_name, ""))
            file_path = str(tool_input.get("file_path", ""))
            # Only run AST policies on payloads that look like Python.
            if code and file_path.endswith(".py"):
                try:
                    evaluation = self._evaluator.evaluate(
                        code=code,
                        intent_action="write",
                        intent_domain="agent",
                    )
                except PolicyViolation as exc:
                    violations = [exc.violation]
                    return self._record_deny(
                        sdk,
                        tool_name=tool_name,
                        reason=f"Policy violation: {exc.violation}",
                        violations=violations,
                    )
                if not evaluation.allowed:
                    violations = [v for r in evaluation.results if not r.allowed for v in r.violations]
                    return self._record_deny(
                        sdk,
                        tool_name=tool_name,
                        reason=f"Policy violation: {'; '.join(violations)}",
                        violations=violations,
                    )

        self._decisions.append(PermissionDecision(tool_name=tool_name, allowed=True))
        return sdk.PermissionResultAllow(updated_input=tool_input)

    def _record_deny(
        self,
        sdk: Any,
        *,
        tool_name: str,
        reason: str,
        violations: list[str] | None = None,
    ) -> Any:
        decision = PermissionDecision(
            tool_name=tool_name,
            allowed=False,
            reason=reason,
            violations=violations or [],
        )
        self._decisions.append(decision)
        logger.warning("claude_sdk_permission_denied", tool=tool_name, reason=reason)
        return sdk.PermissionResultDeny(message=reason, interrupt=False)

    # ------------------------------------------------------------------
    # PreToolUse hook
    # ------------------------------------------------------------------

    async def pre_tool_use_hook(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        """``PreToolUse`` hook callback.

        Runs AST static analysis on Python ``Write``/``Edit`` payloads
        and applies a small heuristic shell parser to ``Bash`` commands.
        Returns the SDK's hook output dict — empty for "no opinion",
        or a deny decision if a violation is detected.
        """
        del tool_use_id, context  # unused

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if tool_name not in _CODE_CARRYING_TOOLS:
            return {}

        field_name = _CODE_CARRYING_TOOLS[tool_name]
        payload = str(tool_input.get(field_name, ""))
        if not payload:
            return {}

        # ``Write``/``Edit`` carry Python source frequently — try AST analysis.
        if tool_name in ("Write", "Edit"):
            file_path = str(tool_input.get("file_path", ""))
            if file_path.endswith(".py"):
                safety = check_code_safety(payload)
                if not safety.safe:
                    descriptions = [v.description for v in safety.violations if v.severity == "error"]
                    if descriptions:
                        return self._deny_hook_output(
                            tool_name=tool_name,
                            reason=f"Static analysis: {'; '.join(descriptions)}",
                            violations=descriptions,
                        )

        # ``Bash`` shell payloads — refuse the obvious stuff.
        if tool_name == "Bash":
            risky = _detect_risky_shell(payload)
            if risky is not None:
                return self._deny_hook_output(
                    tool_name=tool_name,
                    reason=f"Bash safety check: {risky}",
                    violations=[risky],
                )

        return {}

    def _deny_hook_output(
        self,
        *,
        tool_name: str,
        reason: str,
        violations: list[str],
    ) -> dict[str, Any]:
        self._decisions.append(
            PermissionDecision(
                tool_name=tool_name,
                allowed=False,
                reason=reason,
                violations=violations,
            )
        )
        logger.warning("claude_sdk_pre_tool_hook_denied", tool=tool_name, reason=reason)
        return {
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }


# Default-deny shell patterns. Conservative — false positives are
# acceptable here because the runner only invokes this when the user
# has opted into shell access by allowing the ``Bash`` tool at all.
_RISKY_TOKENS: tuple[str, ...] = (
    "rm -rf /",
    "mkfs",
    ":(){",  # fork bomb
    "dd if=/dev/zero of=/",
    "shutdown",
    "reboot",
    "curl | sh",
    "wget | sh",
)


def _detect_risky_shell(command: str) -> str | None:
    """Return a description of a risky shell pattern, or ``None`` if safe.

    This is intentionally simple. It exists to catch obvious harmful
    payloads from a hallucinating model, not to be a complete shell
    sandbox — that's the OS / container's job.
    """
    lowered = command.lower()
    for token in _RISKY_TOKENS:
        if token in lowered:
            return f"matched risky token '{token}'"

    # ``rm -rf`` followed by anything looking like a root path.
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for i, token in enumerate(tokens):
        if token == "rm" and "-rf" in tokens[i:] and any(t.startswith("/") for t in tokens[i:]):
            return "rm -rf targeting an absolute path"
    return None


CanUseToolType = Callable[[str, dict[str, Any], Any], Awaitable[Any]]
"""Type alias matching the SDK's ``can_use_tool`` signature."""
