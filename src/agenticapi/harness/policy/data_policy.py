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
_JOIN_PATTERN = re.compile(r"\bJOIN\b\s+(\w+)", re.IGNORECASE)
_INSERT_PATTERN = re.compile(r"\bINSERT\b\s+INTO\s+(\w+)", re.IGNORECASE)
_UPDATE_PATTERN = re.compile(r"\bUPDATE\b\s+(\w+)\s+SET\b", re.IGNORECASE)
_DELETE_PATTERN = re.compile(r"\bDELETE\b\s+FROM\s+(\w+)", re.IGNORECASE)
_DDL_PATTERN = re.compile(r"\b(DROP|ALTER|CREATE|TRUNCATE)\b\s+(TABLE|INDEX|DATABASE|SCHEMA)\s+(\w+)", re.IGNORECASE)
_SUBQUERY_FROM_PATTERN = re.compile(r"\bFROM\b\s+(\w+)", re.IGNORECASE)

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

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Block destructive tool calls and forbidden tables (Phase E4).

        Enforcement layers:

        1. ``deny_ddl=True`` blocks any tool whose *name* starts with
           ``drop_``, ``truncate_``, ``alter_``, or ``create_table``
           regardless of arguments. This is the "stop someone from
           exposing a ``drop_table`` tool" safety net.
        2. When ``readable_tables`` is set and the call looks like a
           read (``intent_action in {"read","search","aggregate"}``
           or the argument dict contains a ``table`` key), the table
           name is checked against the whitelist.
        3. When ``writable_tables`` is set and the argument dict
           contains a ``table`` key (common for tool shapes like
           ``insert_row(table=..., row=...)``), the table name is
           checked against the write whitelist.
        4. ``restricted_columns`` matches ``<table>.<column>`` in any
           argument value that's a string (handy for free-form SQL
           passed as a parameter).

        The default shape (no lists configured) is permissive except
        for the DDL name check, so turning on DataPolicy for a
        tool-first endpoint does not silently break unrelated
        tools.
        """
        del kwargs
        violations: list[str] = []
        warnings: list[str] = []
        name_lower = tool_name.lower()

        # (1) Destructive name patterns.
        if self.deny_ddl and (
            name_lower.startswith(("drop_", "truncate_", "alter_"))
            or name_lower in {"drop_table", "truncate_table", "create_table"}
        ):
            violations.append(f"DDL tool call not allowed: {tool_name}")

        # (2) / (3) Table whitelist enforcement.
        maybe_table = arguments.get("table") if isinstance(arguments, dict) else None
        if isinstance(maybe_table, str):
            lowered = maybe_table.lower()
            is_read = intent_action in {"read", "search", "aggregate", "analyze"} or name_lower.startswith(
                ("get_", "list_", "search_", "query_", "select_", "read_", "find_")
            )
            is_write = intent_action in {"write", "create", "update", "delete"} or name_lower.startswith(
                ("insert_", "update_", "delete_", "upsert_", "write_", "create_")
            )
            if is_read and self.readable_tables and lowered not in [t.lower() for t in self.readable_tables]:
                violations.append(f"Tool call reads table not in readable_tables: {maybe_table}")
            if is_write and self.writable_tables and lowered not in [t.lower() for t in self.writable_tables]:
                violations.append(f"Tool call writes table not in writable_tables: {maybe_table}")

        # (4) Restricted column references inside string arguments.
        if self.restricted_columns:
            restricted_lower = {ref.lower() for ref in self.restricted_columns}
            for arg_value in (arguments or {}).values():
                if not isinstance(arg_value, str):
                    continue
                for match in _TABLE_COLUMN_PATTERN.findall(arg_value):
                    table = match[0] or match[1] or match[2]
                    column = match[3] or match[4] or match[5]
                    if f"{table}.{column}".lower() in restricted_lower:
                        violations.append(f"Tool call references restricted column: {table}.{column}")

        del intent_domain
        return PolicyResult(
            allowed=not violations,
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
        """Check SELECT queries against readable_tables whitelist.

        Checks tables referenced in FROM clauses, JOIN clauses, and
        subqueries so that table whitelist enforcement is not limited
        to the primary FROM table.
        """
        if not self.readable_tables:
            return

        allowed = {t.lower() for t in self.readable_tables}

        # Primary FROM tables
        for table_name in _SELECT_PATTERN.findall(code):
            if table_name.lower() not in allowed:
                violations.append(f"SELECT from table not in readable list: {table_name}")

        # JOIN tables (LEFT JOIN, INNER JOIN, CROSS JOIN, etc.)
        for table_name in _JOIN_PATTERN.findall(code):
            if table_name.lower() not in allowed:
                violations.append(f"JOIN references table not in readable list: {table_name}")

        # Subquery FROM clauses — extract all FROM <table> references
        # and check any that weren't already caught by _SELECT_PATTERN.
        primary_tables = {t.lower() for t in _SELECT_PATTERN.findall(code)}
        join_tables = {t.lower() for t in _JOIN_PATTERN.findall(code)}
        already_checked = primary_tables | join_tables
        for table_name in _SUBQUERY_FROM_PATTERN.findall(code):
            if table_name.lower() not in already_checked and table_name.lower() not in allowed:
                violations.append(f"Subquery references table not in readable list: {table_name}")

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
