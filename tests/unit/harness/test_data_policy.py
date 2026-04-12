"""Tests for DataPolicy."""

from __future__ import annotations

from agenticapi.harness.policy.data_policy import DataPolicy


class TestDataPolicyDDL:
    def test_deny_drop_table(self) -> None:
        policy = DataPolicy()
        code = "db.execute('DROP TABLE users')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("DDL" in v for v in result.violations)

    def test_deny_alter_table(self) -> None:
        policy = DataPolicy()
        code = "db.execute('ALTER TABLE users ADD COLUMN age INT')"
        result = policy.evaluate(code=code)
        assert result.allowed is False

    def test_deny_truncate_table(self) -> None:
        policy = DataPolicy()
        code = "db.execute('TRUNCATE TABLE orders')"
        result = policy.evaluate(code=code)
        assert result.allowed is False

    def test_allow_ddl_when_disabled(self) -> None:
        policy = DataPolicy(deny_ddl=False)
        code = "db.execute('DROP TABLE users')"
        result = policy.evaluate(code=code)
        # DDL check itself should pass (other checks may still apply)
        ddl_violations = [v for v in result.violations if "DDL" in v]
        assert len(ddl_violations) == 0


class TestDataPolicyRestrictedColumns:
    def test_detect_restricted_column(self) -> None:
        policy = DataPolicy(restricted_columns=["users.password_hash"])
        code = "SELECT users.password_hash FROM users"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("restricted column" in v.lower() for v in result.violations)

    def test_allow_unrestricted_column(self) -> None:
        policy = DataPolicy(restricted_columns=["users.password_hash"])
        code = "SELECT users.name FROM users"
        result = policy.evaluate(code=code)
        # Should not have violations about restricted columns
        restricted_violations = [v for v in result.violations if "restricted" in v.lower()]
        assert len(restricted_violations) == 0

    def test_case_insensitive_match(self) -> None:
        policy = DataPolicy(restricted_columns=["Users.Password_Hash"])
        code = "SELECT users.password_hash FROM users"
        result = policy.evaluate(code=code)
        assert result.allowed is False


class TestDataPolicyWritableTables:
    def test_deny_write_to_non_writable_table(self) -> None:
        policy = DataPolicy(writable_tables=["orders"])
        code = "db.execute('INSERT INTO users VALUES (1, 2)')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("writable" in v.lower() for v in result.violations)

    def test_allow_write_to_writable_table(self) -> None:
        policy = DataPolicy(writable_tables=["orders"])
        code = "db.execute('INSERT INTO orders VALUES (1, 2)')"
        result = policy.evaluate(code=code)
        writable_violations = [v for v in result.violations if "writable" in v.lower()]
        assert len(writable_violations) == 0

    def test_update_to_non_writable(self) -> None:
        policy = DataPolicy(writable_tables=["orders"])
        code = "db.execute('UPDATE users SET name = \"x\"')"
        result = policy.evaluate(code=code)
        assert result.allowed is False

    def test_delete_from_non_writable(self) -> None:
        policy = DataPolicy(writable_tables=["orders"])
        code = "db.execute('DELETE FROM users WHERE id = 1')"
        result = policy.evaluate(code=code)
        assert result.allowed is False


class TestDataPolicyReadableTables:
    def test_deny_select_from_non_readable(self) -> None:
        policy = DataPolicy(readable_tables=["products"])
        code = "db.execute('SELECT * FROM secrets')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("readable" in v.lower() for v in result.violations)

    def test_allow_select_from_readable(self) -> None:
        policy = DataPolicy(readable_tables=["products"])
        code = "db.execute('SELECT * FROM products')"
        result = policy.evaluate(code=code)
        readable_violations = [v for v in result.violations if "readable" in v.lower()]
        assert len(readable_violations) == 0


class TestDataPolicyJoinTables:
    """Tests for JOIN and subquery table detection."""

    def test_deny_join_to_non_readable_table(self) -> None:
        policy = DataPolicy(readable_tables=["orders"])
        code = "db.execute('SELECT * FROM orders JOIN secrets ON orders.id = secrets.order_id')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("JOIN" in v and "secrets" in v for v in result.violations)

    def test_allow_join_to_readable_table(self) -> None:
        policy = DataPolicy(readable_tables=["orders", "products"])
        code = "db.execute('SELECT * FROM orders JOIN products ON orders.product_id = products.id')"
        result = policy.evaluate(code=code)
        join_violations = [v for v in result.violations if "readable" in v.lower() or "JOIN" in v]
        assert len(join_violations) == 0

    def test_deny_left_join_to_non_readable(self) -> None:
        policy = DataPolicy(readable_tables=["orders"])
        code = "db.execute('SELECT * FROM orders LEFT JOIN users ON orders.user_id = users.id')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("users" in v for v in result.violations)

    def test_deny_subquery_from_non_readable(self) -> None:
        policy = DataPolicy(readable_tables=["orders"])
        code = "db.execute('UPDATE orders SET total = (SELECT max(id) FROM secrets)')"
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("secrets" in v for v in result.violations)


class TestDataPolicyResultLimits:
    def test_warn_select_without_limit(self) -> None:
        policy = DataPolicy()
        code = "db.execute('SELECT * FROM orders')"
        result = policy.evaluate(code=code)
        assert len(result.warnings) > 0
        assert any("LIMIT" in w for w in result.warnings)

    def test_no_warn_with_limit(self) -> None:
        policy = DataPolicy()
        code = "db.execute('SELECT * FROM orders LIMIT 100')"
        result = policy.evaluate(code=code)
        limit_warnings = [w for w in result.warnings if "LIMIT" in w]
        assert len(limit_warnings) == 0


class TestDataPolicyPolicyName:
    def test_result_has_policy_name(self) -> None:
        policy = DataPolicy()
        result = policy.evaluate(code="x = 1")
        assert result.policy_name == "DataPolicy"
