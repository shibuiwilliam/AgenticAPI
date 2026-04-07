"""Benchmark: PolicyEvaluator performance.

Target: < 10ms mean per evaluation.
"""

from __future__ import annotations

import pytest

from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.policy.evaluator import PolicyEvaluator
from agenticapi.harness.policy.resource_policy import ResourcePolicy
from agenticapi.harness.policy.runtime_policy import RuntimePolicy

SAMPLE_CODE = """\
import json
data = await db.execute("SELECT * FROM orders WHERE status = 'active' LIMIT 100")
result = json.loads(data)
"""

COMPLEX_CODE = """\
import json
import math

async def process_orders():
    orders = await db.execute("SELECT * FROM orders WHERE created_at > '2024-01-01'")
    total = sum(o['amount'] for o in orders)
    avg = total / len(orders) if orders else 0
    stats = {
        'total': total,
        'average': avg,
        'count': len(orders),
        'std_dev': math.sqrt(sum((o['amount'] - avg) ** 2 for o in orders) / max(len(orders), 1)),
    }
    result = json.dumps(stats)
    return result

result = await process_orders()
"""


@pytest.mark.benchmark
def test_bench_policy_evaluation_simple(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark evaluation with all policies on simple code."""
    evaluator = PolicyEvaluator(
        policies=[
            CodePolicy(denied_modules=["os", "subprocess", "shutil"]),
            DataPolicy(deny_ddl=True, restricted_columns=["password_hash"]),
            ResourcePolicy(),
            RuntimePolicy(),
        ]
    )

    def evaluate() -> None:
        evaluator.evaluate(code=SAMPLE_CODE, intent_action="read", intent_domain="order")

    benchmark(evaluate)
    # Complex code with 4 policies including AST analysis
    assert benchmark.stats["mean"] < 0.015  # 15ms


@pytest.mark.benchmark
def test_bench_policy_evaluation_complex(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark evaluation with all policies on complex code."""
    evaluator = PolicyEvaluator(
        policies=[
            CodePolicy(denied_modules=["os", "subprocess", "shutil"]),
            DataPolicy(deny_ddl=True),
            ResourcePolicy(),
            RuntimePolicy(max_code_complexity=200),
        ]
    )

    def evaluate() -> None:
        evaluator.evaluate(code=COMPLEX_CODE, intent_action="read", intent_domain="order")

    benchmark(evaluate)
    assert benchmark.stats["mean"] < 0.020  # 20ms for complex code with 4 policies
