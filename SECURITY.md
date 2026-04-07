# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in AgenticAPI, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email security concerns to the maintainers directly
3. Include a description of the vulnerability and steps to reproduce
4. Allow reasonable time for a fix before public disclosure

## Security Architecture

AgenticAPI implements a multi-layered defense strategy for safe agent code execution:

### Layer 1: Prompt Design
- User input is XML-escaped before inclusion in LLM prompts
- System prompts explicitly instruct the LLM to avoid dangerous operations
- User content is separated from system instructions using XML tags

### Layer 2: Static Analysis
- AST-based analysis of generated code before execution
- Detects: forbidden imports, eval/exec, dynamic imports, file I/O, dangerous builtins
- Checks both direct calls (`eval()`) and attribute-based calls (`builtins.eval()`)

### Layer 3: Policy Evaluation
- **CodePolicy**: Module allowlist/denylist, dynamic import prevention
- **DataPolicy**: Table/column access controls, DDL prevention, SQL comment stripping
- **ResourcePolicy**: Loop depth limits, memory/CPU bounds
- **RuntimePolicy**: Code complexity limits

### Layer 4: Sandbox Execution
- Code runs in an isolated subprocess (Phase 1: ProcessSandbox)
- User code is base64-encoded for safe transport to the subprocess
- Timeout enforcement prevents infinite loops
- stdout/stderr captured separately

### Layer 5: Post-Execution Validation
- Execution monitors check resource usage against limits
- Result validators ensure output correctness
- Audit recorder captures full execution traces

### Layer 6: Approval Workflow
- Write operations can require human approval before execution
- Configurable approval rules per action type and domain
- Timeout and expiration handling for pending approvals

## Known Limitations (Phase 1)

- **ProcessSandbox** provides process-level isolation, not kernel-level. For multi-tenant production use, upgrade to ContainerSandbox (Phase 2)
- **Static analysis** detects known patterns via AST. Sophisticated obfuscation may bypass detection. The sandbox provides defense-in-depth
- **In-memory storage** for sessions, audit traces, and approval requests. Production deployments should use persistent backends
- **API keys** should be provided via environment variables, never hardcoded

## Secrets Management

- API keys (Anthropic, OpenAI, Google) are read from environment variables
- Never commit `.env` files to version control
- Test files use mock backends that require no API keys
