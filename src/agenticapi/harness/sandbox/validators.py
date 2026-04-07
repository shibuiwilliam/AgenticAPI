"""Post-execution validators for sandbox results.

Validators check execution results before they are returned to the
user. They ensure output correctness and detect unintended side effects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from agenticapi.harness.sandbox.base import SandboxResult

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of a post-execution validation.

    Attributes:
        valid: Whether the result passed validation.
        errors: Blocking errors.
        warnings: Non-blocking warnings.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class ResultValidator(Protocol):
    """Protocol for post-execution result validators.

    Validators check the sandbox execution result for correctness
    and safety before it is returned to the caller.
    """

    async def validate(
        self,
        result: SandboxResult,
        *,
        code: str,
        intent_action: str,
    ) -> ValidationResult:
        """Validate the execution result.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.
            intent_action: The intent action type.

        Returns:
            ValidationResult indicating pass or fail.
        """
        ...


class OutputTypeValidator:
    """Validates that execution output is JSON-serializable.

    Ensures the return value can be safely serialized for API responses.

    Example:
        validator = OutputTypeValidator()
        result = await validator.validate(sandbox_result, code="...", intent_action="read")
    """

    async def validate(
        self,
        result: SandboxResult,
        *,
        code: str,
        intent_action: str,
    ) -> ValidationResult:
        """Check that the return value is JSON-serializable.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.
            intent_action: The intent action type.

        Returns:
            ValidationResult with errors if output cannot be serialized.
        """
        if result.return_value is None:
            return ValidationResult(valid=True)

        try:
            json.dumps(result.return_value, default=str)
            return ValidationResult(valid=True)
        except (TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "output_type_validation_failed",
                error=str(exc),
            )
            return ValidationResult(
                valid=False,
                errors=[f"Return value is not JSON-serializable: {exc}"],
            )


class ReadOnlyValidator:
    """Validates that read intents did not produce write-like output.

    Checks stderr and stdout for patterns that suggest write operations
    occurred during what should have been a read-only operation.

    Example:
        validator = ReadOnlyValidator()
        result = await validator.validate(sandbox_result, code="...", intent_action="read")
    """

    WRITE_PATTERNS: ClassVar[list[str]] = [
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "DROP TABLE",
        "ALTER TABLE",
        "CREATE TABLE",
        "TRUNCATE",
    ]

    async def validate(
        self,
        result: SandboxResult,
        *,
        code: str,
        intent_action: str,
    ) -> ValidationResult:
        """Check for write patterns in read-only operations.

        Only validates when intent_action is "read". Other actions
        are allowed to have write-like output.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.
            intent_action: The intent action type.

        Returns:
            ValidationResult with warnings if write patterns detected.
        """
        if intent_action != "read":
            return ValidationResult(valid=True)

        warnings: list[str] = []
        combined_output = f"{result.stdout} {result.stderr}".upper()

        for pattern in self.WRITE_PATTERNS:
            if pattern in combined_output:
                warnings.append(f"Read-only operation produced write-like output containing '{pattern}'")

        if warnings:
            logger.warning(
                "read_only_validation_warning",
                warnings=warnings,
                intent_action=intent_action,
            )

        return ValidationResult(valid=True, warnings=warnings)
