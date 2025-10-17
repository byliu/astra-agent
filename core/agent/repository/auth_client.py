"""Auth permission verification client"""
import json
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from common_imports import Span
from exceptions.agent_exc import AgentExc
from infra import agent_config


class AuthPermission(BaseModel):
    """Auth permission model"""

    app_id: str = Field(description="Application ID")
    type: str = Field(
        description="Authorization type: workflow, agent, tool"
    )
    ability_id: str = Field(
        description="Ability ID (workflow/agent/tool ID)"
    )
    status: int = Field(description="Authorization status: 0=disabled, 1=enabled")
    create_at: str
    update_at: str


class AuthResponse(BaseModel):
    """Auth API response model"""

    code: int
    message: str
    sid: str | None = Field(default=None)  # Make sid optional for error responses
    data: list[AuthPermission] = Field(default_factory=list)


class AuthClient(BaseModel):
    """Auth permission verification client"""

    app_id: str
    span: Span
    type: Optional[str] = Field(default="agent")
    ability_id: Optional[str] = Field(default=None)
    x_consumer_username: Optional[str] = Field(default=None, description="Tenant app ID for header")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def verify_permission(self, bot_id: str) -> bool:
        """
        Verify if app_id has permission to access bot_id

        Args:
            bot_id: Bot configuration ID to verify

        Returns:
            bool: True if has permission, False otherwise

        Raises:
            AgentExc: When auth service call fails
        """
        with self.span.start("VerifyAuthPermission") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": bot_id,
                    "type": self.type,
                }
            )

            try:
                auth_url = agent_config.AUTH_API_URL
                if not auth_url:
                    sp.add_info_event(
                        "AUTH_API_URL not configured"
                    )
                    raise AgentExc(
                        50004,
                        "Auth service not configured",
                        on=f"app_id:{self.app_id} bot_id:{bot_id}",
                    )

                # Build query parameters
                params: dict[str, Any] = {"app_id": self.app_id}
                if self.type:
                    params["type"] = self.type
                if self.ability_id or bot_id:
                    params["ability_id"] = self.ability_id or bot_id

                sp.add_info_events(
                    {
                        "auth-url": auth_url,
                        "query-params": json.dumps(params, ensure_ascii=False),
                    }
                )

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        auth_url,
                        params=params,
                    )
                    
                    # Parse response before checking status
                    response_data = response.json()
                    
                    # Check HTTP status code
                    if response.status_code != 200:
                        sp.add_info_event(
                            f"Auth service HTTP error: status={response.status_code}, "
                            f"response={response_data}"
                        )
                        raise AgentExc(
                            50001,
                            f"Auth service returned error: {response_data.get('message', response.text)}",
                            on=f"app_id:{self.app_id} bot_id:{bot_id}",
                        )
                    
                    auth_response = AuthResponse(**response_data)

                    sp.add_info_events(
                        {
                            "auth-response": auth_response.model_dump_json(),
                        }
                    )

                    # Check response code
                    if auth_response.code != 0:
                        sp.add_info_event(
                            f"Auth service returned error: "
                            f"code={auth_response.code}, "
                            f"message={auth_response.message}"
                        )
                        return False

                    # Check permissions in data
                    for perm in auth_response.data:
                        if (
                            perm.app_id == self.app_id
                            and perm.ability_id == bot_id
                            and perm.type == self.type
                            and perm.status == 1
                        ):
                            sp.add_info_event(
                                f"Permission verified: app_id={self.app_id}, "
                                f"bot_id={bot_id}, status=enabled"
                            )
                            return True

                    sp.add_info_event(
                        f"Permission denied: app_id={self.app_id}, "
                        f"bot_id={bot_id}, no matching enabled permission found"
                    )
                    return False

            except AgentExc:  # pylint: disable=try-except-raise
                # Re-raise AgentExc without wrapping
                raise
            except httpx.HTTPStatusError as e:
                sp.add_info_event(
                    f"Auth service HTTP error: status={e.response.status_code}, "
                    f"detail={e.response.text}"
                )
                raise AgentExc(
                    50001,
                    f"Auth service returned error: {e.response.status_code}",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e
            except httpx.RequestError as e:
                sp.add_info_event(f"Auth service connection error: {str(e)}")
                raise AgentExc(
                    50002,
                    "Failed to connect to auth service",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e
            except Exception as e:
                sp.add_info_event(f"Unexpected error during auth check: {str(e)}")
                raise AgentExc(
                    50003,
                    f"Auth verification failed: {str(e)}",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e

    async def get_permissions(
        self,
    ) -> list[AuthPermission]:
        """
        Get all permissions for app_id

        Returns:
            list[AuthPermission]: List of permissions

        Raises:
            AgentExc: When auth service call fails
        """
        with self.span.start("GetAuthPermissions") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "type": self.type,
                    "ability_id": self.ability_id,
                }
            )

            try:
                auth_url = agent_config.AUTH_API_URL
                if not auth_url:
                    sp.add_info_event(
                        "AUTH_API_URL not configured"
                    )
                    raise AgentExc(
                        50004,
                        "Auth service not configured",
                        on=f"app_id:{self.app_id}",
                    )

                params: dict[str, Any] = {"app_id": self.app_id}
                if self.type:
                    params["type"] = self.type
                if self.ability_id:
                    params["ability_id"] = self.ability_id

                sp.add_info_events(
                    {
                        "auth-url": auth_url,
                        "query-params": json.dumps(params, ensure_ascii=False),
                    }
                )

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        auth_url,
                        params=params,
                    )
                    
                    # Parse response before checking status
                    response_data = response.json()
                    
                    # Check HTTP status code
                    if response.status_code != 200:
                        sp.add_info_event(
                            f"Auth service HTTP error: status={response.status_code}, "
                            f"response={response_data}"
                        )
                        raise AgentExc(
                            50001,
                            f"Auth service returned error: {response_data.get('message', response.text)}",
                            on=f"app_id:{self.app_id} bot_id:{bot_id}",
                        )
                    
                    auth_response = AuthResponse(**response_data)

                    sp.add_info_events(
                        {
                            "auth-response": auth_response.model_dump_json(),
                            "permissions-count": len(auth_response.data),
                        }
                    )

                    if auth_response.code != 0:
                        sp.add_info_event(
                            f"Auth service returned error: "
                            f"code={auth_response.code}, "
                            f"message={auth_response.message}"
                        )
                        return []

                    return auth_response.data

            except AgentExc:  # pylint: disable=try-except-raise
                # Re-raise AgentExc without wrapping
                raise
            except httpx.HTTPStatusError as e:
                sp.add_info_event(
                    f"Auth service HTTP error: status={e.response.status_code}"
                )
                raise AgentExc(
                    50001,
                    f"Auth service returned error: {e.response.status_code}",
                    on=f"app_id:{self.app_id}",
                ) from e
            except httpx.RequestError as e:
                sp.add_info_event(f"Auth service connection error: {str(e)}")
                raise AgentExc(
                    50002,
                    "Failed to connect to auth service",
                    on=f"app_id:{self.app_id}",
                ) from e
            except Exception as e:
                sp.add_info_event(f"Unexpected error: {str(e)}")
                raise AgentExc(
                    50003,
                    f"Failed to get permissions: {str(e)}",
                    on=f"app_id:{self.app_id}",
                ) from e

    async def bind_permission(self, bot_id: str) -> None:
        """
        Create authorization binding between app_id and bot_id.

        Calls the /auth/v1/add endpoint to register the permission relationship.

        Args:
            bot_id: Bot configuration ID to bind

        Raises:
            AgentExc: When auth service call fails or binding fails
        """
        with self.span.start("BindAuthPermission") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": bot_id,
                    "type": self.type,
                }
            )

            try:
                auth_url = agent_config.AUTH_API_URL
                if not auth_url:
                    sp.add_info_event("AUTH_API_URL not configured")
                    raise AgentExc(
                        50004,
                        "Auth service not configured",
                        on=f"app_id:{self.app_id} bot_id:{bot_id}",
                    )

                # Build URL for /auth/v1/add endpoint
                # Replace /get with /add in the URL
                if auth_url.endswith("/auth/v1/get"):
                    bind_url = auth_url.replace("/auth/v1/get", "/auth/v1/add")
                elif auth_url.endswith("/get"):
                    bind_url = auth_url.replace("/get", "/add")
                else:
                    # Assume base URL, append /add
                    bind_url = f"{auth_url.rstrip('/')}/add"

                # Build request body according to OpenAPI spec
                payload = {
                    "app_id": self.app_id,
                    "type": self.type or "agent",
                    "ability_id": bot_id,
                }

                sp.add_info_events(
                    {
                        "bind-url": bind_url,
                        "request-payload": json.dumps(payload, ensure_ascii=False),
                    }
                )

                # Build headers
                headers = {}
                if self.x_consumer_username:
                    headers["x-consumer-username"] = self.x_consumer_username
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        bind_url,
                        json=payload,
                        headers=headers,
                    )
                    
                    # Parse response before checking status
                    response_data = response.json()
                    
                    # Check HTTP status code
                    if response.status_code != 200:
                        sp.add_error_event(
                            f"Auth service HTTP error: status={response.status_code}, "
                            f"response={response_data}"
                        )
                        raise AgentExc(
                            50001,
                            f"Auth service returned error: {response_data.get('message', response.text)}",
                            on=f"app_id:{self.app_id} bot_id:{bot_id}",
                        )
                    
                    auth_response = AuthResponse(**response_data)

                    sp.add_info_events(
                        {
                            "bind-response": auth_response.model_dump_json(),
                        }
                    )

                    # Check response code
                    if auth_response.code != 0:
                        sp.add_error_event(
                            f"Auth service bind failed: "
                            f"code={auth_response.code}, "
                            f"message={auth_response.message}"
                        )
                        raise AgentExc(
                            40062,
                            f"Authorization bind failed: {auth_response.message}",
                            on=f"app_id:{self.app_id} bot_id:{bot_id}",
                        )

                    sp.add_info_event(
                        f"Successfully bound permission: app_id={self.app_id}, "
                        f"bot_id={bot_id}"
                    )

            except AgentExc:  # pylint: disable=try-except-raise
                # Re-raise AgentExc without wrapping
                raise
            except httpx.HTTPStatusError as e:
                sp.add_error_event(
                    f"Auth service HTTP error: status={e.response.status_code}, "
                    f"detail={e.response.text}"
                )
                raise AgentExc(
                    50001,
                    f"Auth service returned error: {e.response.status_code}",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e
            except httpx.RequestError as e:
                sp.add_error_event(f"Auth service connection error: {str(e)}")
                raise AgentExc(
                    50002,
                    "Failed to connect to auth service",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e
            except Exception as e:
                sp.add_error_event(f"Unexpected error during bind: {str(e)}")
                raise AgentExc(
                    50003,
                    f"Authorization bind failed: {str(e)}",
                    on=f"app_id:{self.app_id} bot_id:{bot_id}",
                ) from e
