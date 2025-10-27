"""
Authentication middleware for Agent service
Handles x-consumer-username extraction from api_key when header is missing
"""
import json
from collections import OrderedDict
from typing import Any, Optional

import aiohttp
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from common_imports import Span, logger
from infra.config.middleware import MiddlewareConfig


class LRUCache:
    """LRU (Least Recently Used) cache"""

    def __init__(self, max_size: int = 3000):
        """
        Initialize LRU cache

        :param max_size: Maximum number of items in cache
        """
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[str]:
        """
        Get value from cache and move to end (most recently used)

        :param key: Cache key
        :return: Cached value or None if not found
        """
        if key not in self._cache:
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value: str) -> None:
        """
        Set value in cache
        If key exists, move to end
        If cache is full, remove least recently used item

        :param key: Cache key
        :param value: Value to cache
        """
        if key in self._cache:
            # Update existing key and move to end
            self._cache[key] = value
            self._cache.move_to_end(key)
        else:
            # Add new key
            self._cache[key] = value

            # Check if cache is full
            if len(self._cache) > self._max_size:
                # Remove least recently used (first item)
                self._cache.popitem(last=False)

    def __len__(self) -> int:
        """Return current cache size"""
        return len(self._cache)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for Agent service

    This middleware checks if x-consumer-username header exists:
    - If present: skip authentication and continue
    - If missing: extract api_key from authorization header and query app_auth service
                  to get appid, then inject as x-consumer-username
    """

    def __init__(self, app: ASGIApp, config: MiddlewareConfig):
        """
        Initialize the authentication middleware

        :param app: The ASGI application
        :param config: Middleware configuration
        """
        super().__init__(app)
        self.config = config
        # Paths that require authentication
        self.need_auth_paths = [
            "/agent/v1/chat/completions",
        ]
        # Initialize LRU cache with max 3000 items
        self._cache = LRUCache(max_size=3000)

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """
        Dispatch the request with authentication logic

        :param request: The request object
        :param call_next: The next function to call
        :return: The response object
        """
        # Check if the path requires authentication
        if request.url.path not in self.need_auth_paths:
            return await call_next(request)

        # Check if x-consumer-username header already exists
        x_consumer_username = request.headers.get("x-consumer-username")
        if x_consumer_username:
            return await call_next(request)

        # Start tracing span
        span = Span()
        with span.start("AuthMiddleware") as span_ctx:
            # Get authorization header
            authorization = request.headers.get("authorization")
            if not authorization:
                logger.warning(
                    f"Missing authorization header for path: {request.url.path}"
                )
                return self._generate_error_response(
                    "authorization header is required", span_ctx.sid, 40001
                )

            try:
                # Extract api_key and query app_auth service (with cache)
                x_consumer_username = await self._get_app_id_from_api_key(
                    authorization, span_ctx
                )
            except Exception as e:
                logger.error(
                    f"Failed to get app_id from api_key: {str(e)}", exc_info=True
                )
                span_ctx.record_exception(e)
                return self._generate_error_response(
                    "Failed to authenticate with api_key", span_ctx.sid, 40003
                )

            # Inject x-consumer-username into request headers
            headers = list(request.scope["headers"])
            headers.append((b"x-consumer-username", x_consumer_username.encode()))
            request.scope["headers"] = headers

            span_ctx.add_info_event(
                f"Injected x-consumer-username: {x_consumer_username}"
            )

        return await call_next(request)

    def _extract_api_key(self, authorization: str) -> str:
        """
        Extract api_key from authorization header

        :param authorization: The authorization header value (format: "Bearer api_key:secret")
        :return: The api_key
        :raises ValueError: If authorization header format is invalid
        """
        try:
            auth_parts = authorization.split(" ")
            if len(auth_parts) != 2 or auth_parts[0].lower() != "bearer":
                raise ValueError("Invalid authorization header format")

            # Extract api_key (before colon if present)
            api_key = auth_parts[1].split(":")[0]
            if not api_key:
                raise ValueError("Empty api_key in authorization header")

            return api_key
        except (IndexError, ValueError) as e:
            logger.error(f"Failed to parse authorization header: {str(e)}")
            raise ValueError(f"Invalid authorization header format: {str(e)}")

    async def _query_app_auth_service(
        self, api_key: str, span: Span
    ) -> str:
        """
        Query app_auth service to get app_id

        :param api_key: The API key to query
        :param span: The span object for tracing
        :return: The app_id
        :raises Exception: If auth service call fails
        """
        # Build app_auth service URL
        app_auth_url = self._build_app_auth_url(api_key)
        if not app_auth_url:
            raise ValueError("APP_AUTH configuration is incomplete")

        span.add_info_event(f"Querying app_auth service: {app_auth_url}")

        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.get(
                app_auth_url,
                headers=self._build_auth_headers(),
                timeout=timeout,
            ) as response:
                response_text = await response.text()
                span.add_info_event(
                    f"App auth service response: status={response.status}, body={response_text}"
                )

                if response.status != 200:
                    raise Exception(
                        f"App auth service returned status {response.status}: {response_text}"
                    )

                return self._parse_auth_response(response_text)

    def _parse_auth_response(self, response_text: str) -> str:
        """
        Parse app_auth service response and extract app_id

        :param response_text: The response text from auth service
        :return: The app_id
        :raises Exception: If response parsing fails or app_id not found
        """
        result = json.loads(response_text)
        code = result.get("code")
        if code != 0:
            error_msg = result.get("message", "Unknown error")
            raise Exception(
                f"App auth service returned error code {code}: {error_msg}"
            )

        # Extract appid
        data = result.get("data", {})
        app_id = data.get("appid")
        if not app_id:
            raise Exception(
                f"appid not found in response: {response_text}"
            )

        return str(app_id)

    async def _get_app_id_from_api_key(
        self, authorization: str, span: Span
    ) -> str:
        """
        Get app_id by querying app_auth service with api_key

        Reference: core/workflow/extensions/fastapi/middleware/auth.py:70
        Endpoint: /v2/app/key/api_key/{api_key}

        :param authorization: The authorization header value (format: "Bearer api_key:secret")
        :param span: The span object for tracing
        :return: The app_id (used as x-consumer-username)
        """
        # Extract api_key from authorization header
        api_key = self._extract_api_key(authorization)

        # Check cache first
        cache_key = f"agent:app:api_key:{api_key}"
        cached_app_id = self._cache.get(cache_key)
        if cached_app_id:
            span.add_info_event(f"Retrieved app_id from cache: {cached_app_id}")
            return cached_app_id

        # Query app_auth service
        try:
            app_id = await self._query_app_auth_service(api_key, span)

            # Cache the result
            self._cache.set(cache_key, app_id)
            span.add_info_event(f"Successfully retrieved app_id: {app_id}")
            return app_id

        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect to app_auth service: {str(e)}")
            raise Exception(f"Failed to connect to app_auth service: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse app_auth response: {str(e)}")
            raise Exception("Invalid JSON response from app_auth service")

    def _build_app_auth_url(self, api_key: str) -> str:
        """
        Build app_auth service URL for api_key lookup

        Expected endpoint: {protocol}://{host}{api_key_path}/{api_key}

        :param api_key: The API key to query
        :return: Full URL for the app_auth service
        """
        host = self.config.APP_AUTH_HOST
        protocol = self.config.APP_AUTH_PROT or "http"
        api_key_path = self.config.APP_AUTH_API_KEY_PATH or "/v2/app/key/api_key"

        if not host:
            logger.error("APP_AUTH_HOST not configured")
            return ""

        # Build URL using configured path
        return f"{protocol}://{host}{api_key_path}/{api_key}"

    def _build_auth_headers(self) -> dict[str, str]:
        """
        Build authentication headers for app_auth service requests

        :return: Dictionary of headers
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Add API key/secret if configured
        api_key = self.config.APP_AUTH_API_KEY
        secret = self.config.APP_AUTH_SECRET

        if api_key and secret:
            # Use simple Bearer token format or custom auth format as needed
            # Adjust based on actual app_auth service requirements
            headers["X-API-Key"] = api_key
            headers["X-API-Secret"] = secret

        return headers

    def _generate_error_response(
        self, message: str, request_id: str, code: int = 40000
    ) -> JSONResponse:
        """
        Generate standardized error response

        :param message: Error message
        :param request_id: Request ID for tracing
        :param code: Error code
        :return: JSONResponse with error details
        """
        return JSONResponse(
            status_code=401,
            content={
                "code": code,
                "message": message,
                "id": request_id,
                "object": "error",
            },
        )
