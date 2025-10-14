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
    sid: str
    data: list[AuthPermission] = Field(default_factory=list)


class AuthClient(BaseModel):
    """Auth permission verification client"""

    app_id: str
    span: Span
    type: Optional[str] = Field(default="agent")
    ability_id: Optional[str] = Field(default=None)

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
                        "AUTH_API_URL not configured, skipping permission check"
                    )
                    return True

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
                    response.raise_for_status()

                    auth_response = AuthResponse(**response.json())

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
                        "AUTH_API_URL not configured, returning empty permissions"
                    )
                    return []

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
                    response.raise_for_status()

                    auth_response = AuthResponse(**response.json())

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
