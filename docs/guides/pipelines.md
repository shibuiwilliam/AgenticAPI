# Dynamic Pipelines

Dynamic pipelines let you compose middleware-like processing stages at runtime, selected per request.

## Usage

```python
from agenticapi.application import DynamicPipeline, PipelineStage

pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage("auth", handler=auth_handler, required=True, order=10),
        PipelineStage("rate_limit", handler=rate_limiter, required=True, order=20),
    ],
    available_stages=[
        PipelineStage("cache", description="Cache lookup", handler=cache_handler),
        PipelineStage("fraud_check", description="Fraud detection", handler=fraud_checker),
    ],
    max_stages=10,
)

result = await pipeline.execute(
    context={"user": "alice", "amount": 50000},
    selected_stages=["fraud_check"],
)
# result.stages_executed: ["auth", "rate_limit", "fraud_check"]
# result.stage_timings_ms: {"auth": 1.2, "rate_limit": 0.3, "fraud_check": 5.1}
```

## How It Works

- **Base stages** always run on every request
- **Available stages** are selected dynamically per request
- Stages are sorted by `order` (lower runs first)
- Each stage handler receives and returns a context dict
- Both sync and async handlers are supported
- `max_stages` prevents unbounded pipeline growth
