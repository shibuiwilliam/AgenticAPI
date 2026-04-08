"""Authentication and authorization for AgenticAPI.

Provides security scheme classes following FastAPI's patterns:
callable objects that extract credentials from HTTP requests,
composable via the ``Authenticator`` class.

Security schemes:
    - ``APIKeyHeader`` — API key in a request header
    - ``APIKeyQuery`` — API key in a query parameter
    - ``HTTPBearer`` — Bearer token in the Authorization header
    - ``HTTPBasic`` — Basic credentials in the Authorization header

Usage:
    from agenticapi.security import APIKeyHeader, Authenticator, AuthUser

    api_key_scheme = APIKeyHeader(name="X-API-Key")

    async def verify_api_key(credentials):
        if credentials.credentials == "secret":
            return AuthUser(user_id="user-1", username="alice")
        return None

    auth = Authenticator(scheme=api_key_scheme, verify=verify_api_key)

    @app.agent_endpoint(name="orders", auth=auth)
    async def order_agent(intent, context):
        ...
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agenticapi.exceptions import AuthenticationError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class AuthCredentials:
    """Extracted credentials from an HTTP request.

    Attributes:
        scheme: The authentication scheme (e.g. "bearer", "basic", "apikey").
        credentials: The raw credential value (token, key, or password).
        scopes: Optional OAuth2 scopes associated with the credentials.
    """

    scheme: str
    credentials: str
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthUser:
    """An authenticated user.

    Carried through the request lifecycle via ``AgentContext.metadata``.
    The ``user_id`` field is also set on ``AgentContext.user_id``.

    Attributes:
        user_id: Unique identifier for the user.
        username: Optional human-readable username.
        roles: Roles assigned to the user (e.g. "admin", "operator").
        scopes: OAuth2 scopes granted to this user/token.
        metadata: Arbitrary additional user metadata.
    """

    user_id: str
    username: str | None = None
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SecurityScheme(Protocol):
    """Protocol for authentication scheme implementations.

    Each scheme is a callable that extracts credentials from
    a Starlette ``Request``. If ``auto_error`` is True and
    credentials are missing, the scheme raises ``AuthenticationError``.

    Implementations must provide ``scheme_name`` and ``auto_error``
    attributes, and be callable with a ``Request`` argument.
    """

    scheme_name: str
    auto_error: bool

    async def __call__(self, request: Request) -> AuthCredentials | None:
        """Extract credentials from the request.

        Args:
            request: The incoming Starlette request.

        Returns:
            Extracted credentials, or None if not found and auto_error is False.

        Raises:
            AuthenticationError: If credentials are missing and auto_error is True.
        """
        ...


class APIKeyHeader:
    """Extract an API key from a request header.

    Example:
        scheme = APIKeyHeader(name="X-API-Key")
        credentials = await scheme(request)
        # credentials.credentials == "the-key-value"

    Args:
        name: Header name to read the API key from.
        auto_error: If True, raise AuthenticationError when the header is missing.
    """

    def __init__(self, name: str = "X-API-Key", *, auto_error: bool = True) -> None:
        self.name = name
        self.scheme_name = "apiKeyHeader"
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> AuthCredentials | None:
        """Extract API key from the configured header.

        Args:
            request: The incoming Starlette request.

        Returns:
            AuthCredentials with the API key, or None.

        Raises:
            AuthenticationError: If the header is missing and auto_error is True.
        """
        api_key = request.headers.get(self.name)
        if api_key:
            return AuthCredentials(scheme="apikey", credentials=api_key)
        if self.auto_error:
            raise AuthenticationError(f"Missing {self.name} header")
        return None


class APIKeyQuery:
    """Extract an API key from a query parameter.

    Example:
        scheme = APIKeyQuery(name="api_key")
        credentials = await scheme(request)  # from ?api_key=value

    Args:
        name: Query parameter name to read the API key from.
        auto_error: If True, raise AuthenticationError when the parameter is missing.
    """

    def __init__(self, name: str = "api_key", *, auto_error: bool = True) -> None:
        self.name = name
        self.scheme_name = "apiKeyQuery"
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> AuthCredentials | None:
        """Extract API key from the configured query parameter.

        Args:
            request: The incoming Starlette request.

        Returns:
            AuthCredentials with the API key, or None.

        Raises:
            AuthenticationError: If the parameter is missing and auto_error is True.
        """
        api_key = request.query_params.get(self.name)
        if api_key:
            return AuthCredentials(scheme="apikey", credentials=api_key)
        if self.auto_error:
            raise AuthenticationError(f"Missing {self.name} query parameter")
        return None


class HTTPBearer:
    """Extract a Bearer token from the Authorization header.

    Expects the format: ``Authorization: Bearer <token>``

    Example:
        scheme = HTTPBearer()
        credentials = await scheme(request)
        # credentials.credentials == "the-jwt-token"

    Args:
        auto_error: If True, raise AuthenticationError when the header is missing or malformed.
    """

    def __init__(self, *, auto_error: bool = True) -> None:
        self.scheme_name = "bearer"
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> AuthCredentials | None:
        """Extract Bearer token from the Authorization header.

        Args:
            request: The incoming Starlette request.

        Returns:
            AuthCredentials with the token, or None.

        Raises:
            AuthenticationError: If the header is missing/malformed and auto_error is True.
        """
        authorization = request.headers.get("Authorization")
        if not authorization:
            if self.auto_error:
                raise AuthenticationError("Missing Authorization header")
            return None

        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            if self.auto_error:
                raise AuthenticationError("Invalid Authorization header: expected 'Bearer <token>'")
            return None

        return AuthCredentials(scheme="bearer", credentials=parts[1])


class HTTPBasic:
    """Extract Basic credentials from the Authorization header.

    Expects the format: ``Authorization: Basic <base64(username:password)>``

    The extracted ``credentials`` string contains the raw password.
    The ``username`` is stored in ``AuthCredentials.scopes[0]`` for
    convenience, but the primary use case is passing both to a
    verify function.

    Example:
        scheme = HTTPBasic()
        credentials = await scheme(request)
        # credentials.credentials == "username:password"

    Args:
        auto_error: If True, raise AuthenticationError when the header is missing or malformed.
    """

    def __init__(self, *, auto_error: bool = True) -> None:
        self.scheme_name = "basic"
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> AuthCredentials | None:
        """Extract Basic credentials from the Authorization header.

        Args:
            request: The incoming Starlette request.

        Returns:
            AuthCredentials with 'username:password' as credentials, or None.

        Raises:
            AuthenticationError: If the header is missing/malformed and auto_error is True.
        """
        authorization = request.headers.get("Authorization")
        if not authorization:
            if self.auto_error:
                raise AuthenticationError("Missing Authorization header")
            return None

        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "basic":
            if self.auto_error:
                raise AuthenticationError("Invalid Authorization header: expected 'Basic <credentials>'")
            return None

        try:
            decoded = base64.b64decode(parts[1]).decode("utf-8")
        except Exception:
            if self.auto_error:
                raise AuthenticationError("Invalid Basic credentials encoding") from None
            return None

        return AuthCredentials(scheme="basic", credentials=decoded)


@dataclass(frozen=True, slots=True)
class Authenticator:
    """Combines a security scheme with a verification function.

    The scheme extracts raw credentials from the request.
    The verify function validates those credentials and returns
    an ``AuthUser`` (or None if invalid).

    Used as the ``auth=`` parameter on endpoint decorators
    and the ``AgenticApp`` constructor.

    Example:
        api_key = APIKeyHeader(name="X-API-Key")

        async def verify(creds: AuthCredentials) -> AuthUser | None:
            if creds.credentials == "secret-key":
                return AuthUser(user_id="u1", username="alice")
            return None

        auth = Authenticator(scheme=api_key, verify=verify)

        @app.agent_endpoint(name="orders", auth=auth)
        async def orders_agent(intent, context):
            print(context.user_id)  # "u1"

    Attributes:
        scheme: The security scheme that extracts credentials.
        verify: Async function that validates credentials and returns an AuthUser.
    """

    scheme: SecurityScheme
    verify: Callable[[AuthCredentials], Awaitable[AuthUser | None]]
