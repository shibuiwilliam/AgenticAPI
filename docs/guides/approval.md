# Approval Workflows

Sensitive operations can require human approval before execution.

## Setup

```python
from agenticapi import ApprovalRule, ApprovalWorkflow, HarnessEngine

workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="write_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["order"],
            approvers=["db_admin"],
            timeout_seconds=1800,
        ),
    ]
)

harness = HarnessEngine(
    policies=[...],
    approval_workflow=workflow,
)
```

## How It Works

1. When the harness detects a matching rule, it raises `ApprovalRequired`
2. The HTTP handler returns **202 Accepted** with a `request_id`
3. An external system (Slack bot, admin UI, etc.) resolves the request:

```python
await workflow.resolve(request_id, approved=True, approver="admin@example.com")
```

## ApprovalRule Options

| Field | Default | Description |
|---|---|---|
| `require_for_actions` | `["write", "execute"]` | Actions that trigger approval |
| `require_for_domains` | `[]` (all) | Domains to match (empty = all) |
| `approvers` | `[]` | Approver IDs/roles |
| `timeout_seconds` | `3600` | Approval timeout (min 60) |
| `require_all_approvers` | `False` | All vs. any approver |

## States

`PENDING` -> `APPROVED` / `REJECTED` / `EXPIRED` / `ESCALATED`
