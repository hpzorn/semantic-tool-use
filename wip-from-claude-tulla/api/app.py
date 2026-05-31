"""HTTP application factory for the ontology-server-side phase routes.

Provides :func:`create_app` — the entry point the deployment process
calls at start-up.  The factory:

* Builds an HTTP app object (FastAPI by default, or a duck-typed test
  shim when *app_factory* is supplied).
* Installs the bearer-token guard so every mounted route requires
  ``Authorization: Bearer <token>``.
* Calls :func:`api.routes.phases.register` to mount the phase route
  handlers from :mod:`api.routes.phases`.

The token is read from the ``TULLA_API_TOKEN`` environment variable when
not passed explicitly.  An app constructed without a token cannot be
deployed — the factory raises immediately so a misconfigured restart
does not silently expose the routes.

Quality focus: isaqb:Operability — the bearer-token wrapper is applied
*before* the route handler is registered with the app, so framework
restarts cannot mount an unauthenticated route by accident.  The
verification criterion (new routes return 200 with bearer auth) is
checked end-to-end via :class:`_BearerTokenApp` in the unit tests.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from api.routes.phases import (
    _LIST_PIPELINE_PATH,
    _NEXT_PHASE_PATH,
    _RENDER_GATES_PATH,
    _RENDER_INPUT_CONTRACT_PATH,
    _RENDER_METHODOLOGY_PATH,
    _RENDER_OUTPUT_CONTRACT_PATH,
    _RENDER_PHASE_PROMPT_PATH,
    _RENDER_TOOLS_PATH,
    _ROUTE_PATH,
    register,
)
from mcp.phase_tools import SparqlClient


# All routes mounted by :func:`api.routes.phases.register` — kept in one
# place so the bearer-token guard and the verification tests share a
# single source of truth.
PHASE_ROUTES: tuple[str, ...] = (
    _ROUTE_PATH,
    _RENDER_METHODOLOGY_PATH,
    _RENDER_TOOLS_PATH,
    _RENDER_GATES_PATH,
    _RENDER_INPUT_CONTRACT_PATH,
    _RENDER_OUTPUT_CONTRACT_PATH,
    _RENDER_PHASE_PROMPT_PATH,
    _LIST_PIPELINE_PATH,
    _NEXT_PHASE_PATH,
)


_BEARER_PREFIX = "Bearer "


def _extract_bearer_token(header_value: str | None) -> str:
    """Return the token portion of an ``Authorization`` header value.

    Returns the empty string when *header_value* is missing or does not
    use the ``Bearer`` scheme — the caller maps that onto a 401.
    """
    if not header_value or not header_value.startswith(_BEARER_PREFIX):
        return ""
    return header_value[len(_BEARER_PREFIX):]


def check_bearer_token(
    expected_token: str,
    header_value: str | None,
) -> tuple[bool, dict[str, Any] | None]:
    """Validate an ``Authorization`` header against *expected_token*.

    Returns ``(True, None)`` on success and ``(False, error_body)`` when
    the header is missing or the token does not match.  The error body
    is the JSON payload the route should return alongside a 401 status.
    """
    presented = _extract_bearer_token(header_value)
    if not presented:
        return False, {"error": "missing or malformed Authorization header"}
    if presented != expected_token:
        return False, {"error": "invalid bearer token"}
    return True, None


def create_app(
    sparql: SparqlClient,
    *,
    token: str | None = None,
    app_factory: Callable[[], Any] | None = None,
) -> Any:
    """Create an HTTP app, install bearer auth, and mount the phase routes.

    *token* defaults to the ``TULLA_API_TOKEN`` environment variable.
    A missing token is a fatal configuration error — the factory raises
    :class:`RuntimeError` rather than mounting unauthenticated routes.

    *app_factory* is the framework-specific constructor (e.g.
    ``lambda: FastAPI()``).  When omitted, the in-process
    :class:`_BearerTokenApp` is used — this keeps the wiring testable
    without pulling in a web framework as a hard dependency.  The
    bearer guard is applied identically in both modes: by wrapping the
    handler before it is passed to :func:`api.routes.phases.register`.
    """
    resolved_token = token if token is not None else os.environ.get("TULLA_API_TOKEN", "")
    if not resolved_token:
        raise RuntimeError(
            "create_app requires a bearer token "
            "(set TULLA_API_TOKEN or pass token=...)",
        )

    app = app_factory() if app_factory is not None else _BearerTokenApp(resolved_token)
    if isinstance(app, _BearerTokenApp):
        # The in-process app applies the guard itself — it knows the token.
        register(app, sparql)
        return app

    # External frameworks (FastAPI / Flask): wrap the handlers before
    # registration so the guard is unconditionally in front of every
    # route.  We attach a shim app whose .get/.post forward through the
    # guard onto the real app's .get/.post.
    guarded = _BearerTokenShim(app, resolved_token)
    register(guarded, sparql)
    return app


class _BearerTokenApp:
    """In-process FastAPI-shaped app that guards every route with bearer auth.

    Implements the ``.get`` / ``.post`` decorator surface that
    :func:`api.routes.phases.register` calls.  Each registered handler
    is wrapped so it consults :func:`check_bearer_token` before invoking
    the user code — this is the load-bearing invariant for the
    verification criterion ("new routes return 200 with bearer auth").
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._routes: dict[tuple[str, str], Callable[..., Any]] = {}

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._make_decorator("GET", path)

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._make_decorator("POST", path)

    def _make_decorator(
        self, method: str, path: str,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._routes[(method, path)] = self._wrap_with_auth(fn)
            return fn
        return decorator

    def _wrap_with_auth(
        self, fn: Callable[..., Any],
    ) -> Callable[..., Any]:
        token = self._token

        def guarded(
            *args: Any,
            authorization: str | None = None,
            **kwargs: Any,
        ) -> Any:
            ok, error = check_bearer_token(token, authorization)
            if not ok:
                return 401, error
            result = fn(*args, **kwargs)
            if isinstance(result, tuple):
                return result
            return 200, result

        return guarded

    def call(
        self,
        method: str,
        path: str,
        *,
        authorization: str | None = None,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """Test entry point — dispatch a request through the guard."""
        handler = self._routes.get((method, path))
        if handler is None:
            return 404, {"error": "no such route"}
        return handler(authorization=authorization, **kwargs)

    def list_routes(self) -> list[tuple[str, str]]:
        return list(self._routes.keys())


class _BearerTokenShim:
    """Decorator forwarder that wraps every handler with the bearer guard.

    Used when a real framework app (e.g. FastAPI) is supplied via
    *app_factory*.  We forward ``.get`` / ``.post`` calls to the real
    app but interpose the guard around the user's handler so the route
    cannot be reached without a valid bearer token.  The user's handler
    signature is preserved by accepting ``authorization`` as a
    framework-provided keyword (e.g. a FastAPI ``Header()`` dependency).
    """

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._token = token

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._wrap(self._app.get, path)

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._wrap(self._app.post, path)

    def _wrap(
        self,
        method: Callable[..., Any],
        path: str,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        token = self._token

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            def guarded(
                *args: Any,
                authorization: str | None = None,
                **kwargs: Any,
            ) -> Any:
                ok, error = check_bearer_token(token, authorization)
                if not ok:
                    return 401, error
                return fn(*args, **kwargs)

            method(path)(guarded)
            return guarded

        return decorator
