"""HTMX support for agent endpoints.

Provides helpers for building HTMX-powered web applications with
AgenticAPI. Endpoints can detect HTMX requests via headers and return
HTML fragments for partial page updates.

Usage:
    from agenticapi.interface.htmx import HtmxHeaders, HtmxResponse

    @app.agent_endpoint(name="items")
    async def items(intent, context, htmx: HtmxHeaders):
        if htmx.is_htmx:
            # Return HTML fragment for partial swap
            return HTMLResult(content="<li>Item 1</li><li>Item 2</li>")
        # Full page for non-HTMX requests
        return HTMLResult(content="<html><body>...</body></html>")

See https://htmx.org for the HTMX library documentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HtmxHeaders:
    """Parsed HTMX request headers.

    Injected into handlers that declare an ``HtmxHeaders`` parameter.
    Provides typed access to all standard HTMX request headers.

    Attributes:
        is_htmx: True if the request was made by HTMX (HX-Request header present).
        boosted: True if the request came from an hx-boost element.
        target: The id of the target element (HX-Target header).
        trigger: The id of the element that triggered the request (HX-Trigger header).
        trigger_name: The name of the trigger element (HX-Trigger-Name header).
        current_url: The current browser URL (HX-Current-URL header).
        prompt: The user response to an hx-prompt (HX-Prompt header).
    """

    is_htmx: bool = False
    boosted: bool = False
    target: str | None = None
    trigger: str | None = None
    trigger_name: str | None = None
    current_url: str | None = None
    prompt: str | None = None

    @classmethod
    def from_scope(cls, scope: dict[str, Any]) -> HtmxHeaders:
        """Extract HTMX headers from an ASGI scope.

        Args:
            scope: The ASGI scope dict containing request headers.

        Returns:
            Parsed HtmxHeaders instance.
        """
        headers: dict[str, str] = {}
        for key, value in scope.get("headers", []):
            headers[key.decode("latin-1").lower()] = value.decode("latin-1")

        return cls(
            is_htmx=headers.get("hx-request", "").lower() == "true",
            boosted=headers.get("hx-boosted", "").lower() == "true",
            target=headers.get("hx-target"),
            trigger=headers.get("hx-trigger"),
            trigger_name=headers.get("hx-trigger-name"),
            current_url=headers.get("hx-current-url"),
            prompt=headers.get("hx-prompt"),
        )


def htmx_response_headers(
    *,
    trigger: str | None = None,
    trigger_after_settle: str | None = None,
    trigger_after_swap: str | None = None,
    redirect: str | None = None,
    refresh: bool = False,
    retarget: str | None = None,
    reswap: str | None = None,
    push_url: str | bool | None = None,
    replace_url: str | bool | None = None,
) -> dict[str, str]:
    """Build HTMX response headers.

    Use with any response type to control HTMX client-side behavior.

    Args:
        trigger: Trigger client-side events after response is received.
        trigger_after_settle: Trigger events after the settling step.
        trigger_after_swap: Trigger events after the swap step.
        redirect: Redirect the browser to a new URL.
        refresh: If True, trigger a full page refresh.
        retarget: Override the swap target CSS selector.
        reswap: Override the swap strategy (innerHTML, outerHTML, etc.).
        push_url: Push a URL into the browser history.
        replace_url: Replace the current URL in the browser.

    Returns:
        Dict of HTMX response headers.

    Example:
        headers = htmx_response_headers(trigger="itemAdded", reswap="outerHTML")
        return HTMLResult(content="<li>New item</li>", headers=headers)
    """
    headers: dict[str, str] = {}
    if trigger is not None:
        headers["HX-Trigger"] = trigger
    if trigger_after_settle is not None:
        headers["HX-Trigger-After-Settle"] = trigger_after_settle
    if trigger_after_swap is not None:
        headers["HX-Trigger-After-Swap"] = trigger_after_swap
    if redirect is not None:
        headers["HX-Redirect"] = redirect
    if refresh:
        headers["HX-Refresh"] = "true"
    if retarget is not None:
        headers["HX-Retarget"] = retarget
    if reswap is not None:
        headers["HX-Reswap"] = reswap
    if push_url is not None:
        headers["HX-Push-Url"] = str(push_url).lower() if isinstance(push_url, bool) else push_url
    if replace_url is not None:
        headers["HX-Replace-Url"] = str(replace_url).lower() if isinstance(replace_url, bool) else replace_url
    return headers
