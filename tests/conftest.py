"""Shared pytest fixtures for AgenticAPI tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_intent_raw() -> str:
    """Sample raw intent string for testing."""
    return "今月の注文数を教えて"


@pytest.fixture
def sample_code() -> str:
    """Sample generated code for testing."""
    return "result = await db.execute('SELECT COUNT(*) FROM orders')"


@pytest.fixture
def dangerous_code() -> str:
    """Dangerous code that should be blocked by policies."""
    return "import os; os.system('rm -rf /')"
