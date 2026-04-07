"""Tests for A2A capability registry."""

from __future__ import annotations

from agenticapi.interface.a2a.capability import Capability, CapabilityRegistry


class TestCapability:
    def test_create(self) -> None:
        cap = Capability(
            name="inventory",
            description="Inventory management",
            sla_max_latency_ms=500,
        )
        assert cap.name == "inventory"
        assert cap.description == "Inventory management"
        assert cap.sla_max_latency_ms == 500
        assert cap.sla_availability == 0.99

    def test_defaults(self) -> None:
        cap = Capability(name="test")
        assert cap.input_schema == {}
        assert cap.output_schema == {}
        assert cap.sla_max_latency_ms == 5000


class TestCapabilityRegistry:
    def test_register_and_get(self) -> None:
        registry = CapabilityRegistry()
        cap = Capability(name="search", description="Search products")
        registry.register(cap)
        assert registry.get("search") is cap

    def test_get_nonexistent(self) -> None:
        registry = CapabilityRegistry()
        assert registry.get("missing") is None

    def test_has(self) -> None:
        registry = CapabilityRegistry()
        registry.register(Capability(name="a"))
        assert registry.has("a") is True
        assert registry.has("b") is False

    def test_list_capabilities(self) -> None:
        registry = CapabilityRegistry()
        registry.register(Capability(name="a"))
        registry.register(Capability(name="b"))
        caps = registry.list_capabilities()
        assert len(caps) == 2
        names = {c.name for c in caps}
        assert names == {"a", "b"}

    def test_register_overwrites(self) -> None:
        registry = CapabilityRegistry()
        registry.register(Capability(name="a", description="v1"))
        registry.register(Capability(name="a", description="v2"))
        assert registry.get("a").description == "v2"  # type: ignore[union-attr]
        assert len(registry.list_capabilities()) == 1
