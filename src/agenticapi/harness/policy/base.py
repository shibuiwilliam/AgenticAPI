"""Base policy classes for harness evaluation.

Provides the Policy base class and PolicyResult model used by all
concrete policy implementations. Policies evaluate generated code
against configurable constraints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyResult(BaseModel):
    """Result of a policy evaluation.

    Attributes:
        allowed: Whether the code is allowed under this policy.
        violations: List of violation descriptions if not allowed.
        warnings: List of non-blocking warnings.
        policy_name: Name of the policy that produced this result.
    """

    allowed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_name: str = ""


class Policy(BaseModel):
    """Base class for all harness policies.

    Subclasses implement evaluate() to check generated code against
    their specific constraints. Policies are pure computation (sync,
    no I/O) and must be deterministic for a given input.

    Example:
        class MyPolicy(Policy):
            max_lines: int = 100

            def evaluate(self, *, code: str, **kwargs: Any) -> PolicyResult:
                lines = code.count("\\n") + 1
                if lines > self.max_lines:
                    return PolicyResult(
                        allowed=False,
                        violations=[f"Code has {lines} lines, max is {self.max_lines}"],
                        policy_name="MyPolicy",
                    )
                return PolicyResult(allowed=True, policy_name="MyPolicy")
    """

    model_config = {"extra": "forbid"}

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Evaluate generated code against this policy.

        Args:
            code: The generated Python source code to evaluate.
            intent_action: The classified action type (read, write, etc.).
            intent_domain: The domain of the request (order, product, etc.).
            **kwargs: Additional context for evaluation.

        Returns:
            PolicyResult indicating whether the code is allowed.
        """
        return PolicyResult(allowed=True, policy_name=self.__class__.__name__)

    def evaluate_intent_text(
        self,
        *,
        intent_text: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Evaluate raw user intent text before it reaches the LLM.

        Called by the framework **before** the LLM fires, so policies
        can block prompt injection, PII, or other unsafe content at
        the earliest possible point. Policies whose domain is generated
        code leave the default allow-everything implementation.

        Args:
            intent_text: The raw natural-language string from the request.
            intent_action: The classified intent action, if available.
            intent_domain: The classified intent domain, if available.
            **kwargs: Additional context for evaluation.

        Returns:
            :class:`PolicyResult` — default allows every input.
        """
        del intent_text, intent_action, intent_domain, kwargs
        return PolicyResult(allowed=True, policy_name=self.__class__.__name__)

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Evaluate a direct tool call against this policy (Phase E4).

        The harness's **tool-first execution path** skips code
        generation entirely when the LLM returns a structured
        function call. In that case there's no generated code to run
        through :meth:`evaluate`; instead, every registered policy is
        asked whether the *call itself* — identified by the tool's
        name plus the keyword arguments the model produced — is
        allowed.

        Subclasses override this hook to enforce constraints at the
        tool-call boundary. ``CodePolicy`` uses the default
        allow-everything behaviour (its domain is AST analysis of
        generated code, not tool arguments). ``DataPolicy`` uses it
        to block DDL tool names (``drop_*``, ``truncate_*``) and
        argument values that match restricted tables.

        Args:
            tool_name: The name of the tool the model wants to call.
            arguments: The keyword arguments the model produced for
                the tool. Always a dict.
            intent_action: The classified intent action. Available
                for rules that care about read/write/destructive.
            intent_domain: The classified intent domain.
            **kwargs: Additional context for evaluation.

        Returns:
            :class:`PolicyResult` — default implementation allows
            every tool call. Subclasses narrow as needed.
        """
        del tool_name, arguments, intent_action, intent_domain, kwargs
        return PolicyResult(allowed=True, policy_name=self.__class__.__name__)
