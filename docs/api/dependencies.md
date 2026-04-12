# Dependency Injection

FastAPI-style `Depends()` handler injection, scanner, and solver. See the [Dependency Injection guide](../guides/dependency-injection.md) for usage patterns.

## Depends

::: agenticapi.dependencies.depends.Depends

::: agenticapi.dependencies.depends.Dependency

## Scanner

The scanner inspects a handler's signature at registration time and produces an `InjectionPlan` describing how each parameter should be resolved.

::: agenticapi.dependencies.scanner.scan_handler

::: agenticapi.dependencies.scanner.InjectionKind

::: agenticapi.dependencies.scanner.InjectionPlan

::: agenticapi.dependencies.scanner.ParamPlan

## Solver

The solver applies an `InjectionPlan` to a live request, resolving all dependencies and producing a `ResolvedHandlerCall` that can be invoked through an `AsyncExitStack`.

::: agenticapi.dependencies.solver.solve

::: agenticapi.dependencies.solver.invoke_handler

::: agenticapi.dependencies.solver.ResolvedHandlerCall

::: agenticapi.dependencies.solver.DependencyResolutionError
