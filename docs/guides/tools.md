# Tools

Tools provide agents with access to external systems like databases, caches, HTTP APIs, and message queues.

## Built-in Tools

### DatabaseTool

```python
from agenticapi.runtime.tools import DatabaseTool

db = DatabaseTool(
    name="main_db",
    execute_fn=my_async_db_execute,  # async (query, params) -> Any
    read_only=True,  # Blocks INSERT/UPDATE/DELETE/DROP
)
```

### CacheTool

```python
from agenticapi.runtime.tools import CacheTool

cache = CacheTool(name="app_cache", default_ttl_seconds=300, max_size=1000)
# Actions: get, set, delete, exists
```

### HttpClientTool

```python
from agenticapi.runtime.tools import HttpClientTool

http = HttpClientTool(
    name="api_client",
    allowed_hosts=["api.internal.example.com"],
    timeout=30.0,
)
# Methods: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
```

### QueueTool

```python
from agenticapi.runtime.tools import QueueTool

queue = QueueTool(name="task_queue", max_size=1000)
# Actions: enqueue, dequeue, peek, size
```

## ToolRegistry

```python
from agenticapi.runtime.tools import ToolRegistry

registry = ToolRegistry()
registry.register(db)
registry.register(cache)
registry.register(http)
registry.register(queue)
```

## Custom Tools

Implement the `Tool` protocol:

```python
from agenticapi.runtime.tools.base import Tool, ToolDefinition, ToolCapability

class MyTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="Does something useful",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs) -> Any:
        ...
```
