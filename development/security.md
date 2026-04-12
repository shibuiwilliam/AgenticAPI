# Security Model for Contributors

Defense-in-depth security architecture. For contributors implementing new features or modifying the harness.

---

## Seven Defense Layers

### Layer 1: Prompt Design

User input is XML-escaped (`html.escape()`) before embedding in LLM prompts. This prevents basic prompt injection at the template level.

### Layer 2: Pre-LLM Text Policy Invocation (Increment 9)

**Before the LLM fires**, `HarnessEngine.evaluate_intent_text()` runs every registered policy's `evaluate_intent_text()` hook against the raw intent string:

- `PromptInjectionPolicy` — 10 built-in regex rules detect common injection patterns (instruction override, system prompt leak, role hijack, code execution, encoded payloads). Shadow mode (`record_warnings_only=True`) for gradual rollout.
- `PIIPolicy` — 6 detectors (email, US phone NANP, US SSN, Luhn-validated credit card, IBAN, IPv4) with 3 modes (detect/redact/block). `disabled_detectors` + `extra_patterns` for customization.
- Other policies (`CodePolicy`, `DataPolicy`, etc.) default to allow at this hook — they scan generated code, not user text.

**Key invariant:** The LLM never sees text that a policy would block. This is enforced in `app.py::_execute_intent()` before the branch into handler/harness/streaming paths.

### Layer 3: Static AST Analysis

Generated code passes through `harness/sandbox/static_analysis.py::check_code_safety()`:
- Forbidden imports (`os`, `subprocess`, `sys`, `importlib`, etc.)
- Forbidden builtins (`eval`, `exec`, `getattr`, `__import__`)
- Forbidden attribute access patterns
- Forbidden file I/O operations

### Layer 4: Policy Evaluation (Post-Code-Gen)

`PolicyEvaluator.evaluate(code=generated_code)` fans out to all registered policies:
- `CodePolicy` — forbidden modules, eval/exec
- `DataPolicy` — SQL table/column access, DDL blocking
- `ResourcePolicy` — CPU/memory/time limits
- `RuntimePolicy` — AST complexity (cyclomatic, nesting)
- `BudgetPolicy` — cost ceiling enforcement
- `PromptInjectionPolicy` — scans generated code for injection patterns
- `PIIPolicy` — scans generated code for PII

### Layer 5: Approval Workflow

Two flavors:
- **Out-of-band:** `ApprovalRequired` exception → HTTP 202 → operator resolves via separate endpoint
- **In-request (F5):** `stream.request_approval()` → pauses a running stream → auto-registers `/agent/{name}/resume/{stream_id}` → delivers decision back to the stream

### Layer 6: Process Sandbox

`ProcessSandbox` executes code in an isolated subprocess:
- Code is base64-encoded for transport (prevents shell injection)
- `asyncio.wait_for` enforces timeout
- Output is serialized through a strict wire format
- Resource monitors (CPU, memory) run during execution
- Post-execution validators check output safety

**Forward-looking:** `VISION.md` Track 2 plans `GVisorSandbox` (kernel-level isolation), `WasmSandbox` (cross-platform), and `SecretBroker` (secrets never enter the LLM prompt).

### Layer 7: Audit Trail

Every request produces a bounded `ExecutionTrace`:
- `InMemoryAuditRecorder` (dev) or `SqliteAuditRecorder` (production)
- Records: intent, parsed payload, generated code, policy outcomes, tool calls, stream events, cost, final response
- `iter_since()` for the `agenticapi replay` CLI
- `ExecutionTrace.stream_events` for streaming lifecycle audit (F8)

---

## Policy Hook Matrix

| Hook | When it fires | Who overrides it | Default |
|---|---|---|---|
| `evaluate_intent_text(intent_text=...)` | Before LLM (step 6) | `PromptInjectionPolicy`, `PIIPolicy` | Allow |
| `evaluate(code=...)` | After code generation (step 7b) | All policies | Allow (base) |
| `evaluate_tool_call(tool_name=..., arguments=...)` | E4 tool-first path (step 7c) | `DataPolicy`, `PIIPolicy` | Allow |

---

## Contributor Checklist

When implementing a new feature, verify:

1. **User input is never passed unsanitized to `eval()`, `exec()`, `subprocess`, or `os.system()`.**
2. **Secrets (API keys, passwords) are never logged, stored in audit traces, or embedded in LLM prompts.** Use env vars; the framework reads them at backend construction time only.
3. **New policy hooks default to allow.** A policy that doesn't override a hook must not silently deny requests.
4. **New string inputs are covered by pre-LLM scanning.** If you add a new field to the request body that reaches the LLM, ensure `evaluate_intent_text()` covers it.
5. **Tests include adversarial inputs.** Every handler test should include at least one injection attempt and one PII-containing input.
