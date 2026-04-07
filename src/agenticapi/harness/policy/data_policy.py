"""Data policy for validating SQL and data access patterns.

Uses regex-based detection of SQL statements to enforce table access
controls, column restrictions, and DDL prevention.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field

from agenticapi.harness.policy.base import Policy, PolicyResult

# SQL pattern detection regexes (case-insensitive)
_SELECT_PATTERN = re.compile(r"\bSELECT\b\s+.+?\bFROM\b\s+(\w+)", re.IGNORECASE | re.DOTALL)
_INSERT_PATTERN = re.compile(r"\bINSERT\b\s+INTO\s+(\w+)", re.IGNORECASE)
_UPDATE_PATTERN = re.compile(r"\bUPDATE\b\s+(\w+)\s+SET\b", re.IGNORECASE)
_DELETE_PATTERN = re.compile(r"\bDELETE\b\s+FROM\s+(\w+)", re.IGNORECASE)
_DDL_PATTERN = re.compile(r"\b(DROP|ALTER|CREATE|TRUNCATE)\b\s+(TABLE|INDEX|DATABASE|SCHEMA)\s+(\w+)", re.IGNORECASE)

# Column reference patterns: table.column with optional quoting (backticks, double quotes)
_TABLE_COLUMN_PATTERN = re.compile(r"""(?:`(\w+)`|"(\w+)"|(\w+))\s*\.\s*(?:`(\w+)`|"(\w+)"|(\w+))""")

# Write operation patterns
_WRITE_PATTERNS: list[re.Pattern[str]] = [_INSERT_PATTERN, _UPDATE_PATTERN, _DELETE_PATTERN]


class DataPolicy(Policy):
    """Policy that validates SQL and data access patterns in generated code.

    Enforces table-level access controls, column restrictions, and
    DDL prevention through regex-based SQL pattern detection.

    Attributes:
        readable_tables: Tables allowed for SELECT queries (empty = all allowed).
        writable_tables: Tables allowed for INSERT/UPDATE/DELETE (empty = all allowed).
        restricted_columns: Column references to deny, e.g. ["users.password_hash"].
        max_query_duration_ms: Maximum allowed query duration hint.
        max_result_rows: Maximum result rows hint.
        deny_ddl: Whether to deny DDL statements (DROP, ALTER, CREATE, TRUNCATE).
    """

    readable_tables: list[str] = Field(default_factory=list)
    writable_tables: list[str] = Field(default_factory=list)
    restricted_columns: list[str] = Field(default_factory=list)
    max_query_duration_ms: int = Field(default=5000, ge=1)
    max_result_rows: int = Field(default=10000, ge=1)
    deny_ddl: bool = True

    def evaluate(self, *, code: str, **kwargs: Any) -> PolicyResult:
        """Evaluate generated code for data access policy violations.

        Args:
            code: The generated Python source code containing SQL.
            **kwargs: Additional context (ignored).

        Returns:
            PolicyResult with any violations found.
        """
        violations: list[str] = []
        warnings: list[str] = []

        self._check_ddl(code, violations)
        self._check_select_tables(code, violations)
        self._check_write_tables(code, violations)
        self._check_restricted_columns(code, violations)
        self._check_result_limits(code, warnings)

        allowed = len(violations) == 0
        return PolicyResult(
            allowed=allowed,
            violations=violations,
            warnings=warnings,
            policy_name="DataPolicy",
        )

    def _check_ddl(self, code: str, violations: list[str]) -> None:
        """Check for DDL statements."""
        if not self.deny_ddl:
            return

        matches = _DDL_PATTERN.findall(code)
        for operation, obj_type, name in matches:
            violations.append(f"DDL statement not allowed: {operation} {obj_type} {name}")

    def _check_select_tables(self, code: str, violations: list[str]) -> None:
        """Check SELECT queries against readable_tables whitelist."""
        if not self.readable_tables:
            return

        matches = _SELECT_PATTERN.findall(code)
        for table_name in matches:
            if table_name.lower() not in [t.lower() for t in self.readable_tables]:
                violations.append(f"SELECT from table not in readable list: {table_name}")

    def _check_write_tables(self, code: str, violations: list[str]) -> None:
        """Check write operations against writable_tables whitelist."""
        for pattern in _WRITE_PATTERNS:
            matches = pattern.findall(code)
            for table_name in matches:
                if self.writable_tables and table_name.lower() not in [t.lower() for t in self.writable_tables]:
                    violations.append(f"Write to table not in writable list: {table_name}")

    def _check_restricted_columns(self, code: str, violations: list[str]) -> None:
        """Check for references to restricted columns."""
        if not self.restricted_columns:
            return

        # Build a set of restricted references in lowercase for matching
        restricted_lower = {ref.lower() for ref in self.restricted_columns}

        matches = _TABLE_COLUMN_PATTERN.findall(code)
        for groups in matches:
            # Each match has 6 groups: 3 for table (backtick, quote, bare), 3 for column
            table = groups[0] or groups[1] or groups[2]
            column = groups[3] or groups[4] or groups[5]
            ref = f"{table}.{column}".lower()
            if ref in restricted_lower:
                violations.append(f"Access to restricted column: {table}.{column}")

    def _check_result_limits(self, code: str, warnings: list[str]) -> None:
        """Check for potential unlimited result sets."""
        # Warn if SELECT without LIMIT is found
        select_matches = _SELECT_PATTERN.findall(code)
        if select_matches:
            has_limit = re.search(r"\bLIMIT\b", code, re.IGNORECASE)
            if not has_limit:
                warnings.append(
                    f"SELECT query without LIMIT clause detected. "
                    f"Consider adding LIMIT {self.max_result_rows} to prevent large result sets."
                )
