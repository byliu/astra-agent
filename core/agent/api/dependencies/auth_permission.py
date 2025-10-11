"""FastAPI dependencies for auth permission verification"""
from typing import Annotated, Optional

from fastapi import Depends, Query

from common_imports import Span
from exceptions.agent_exc import AgentExc
from repository.auth_client import AuthClient


async def verify_bot_permission(
    app_id: Annotated[str, Query(min_length=1, max_length=64)],
    bot_id: Annotated[str, Query(min_length=1, max_length=64)],
) -> tuple[str, str]:
    """
    Dependency to verify bot permission before processing request

    Args:
        app_id: Application ID from query parameter
        bot_id: Bot ID from query parameter

    Returns:
        tuple[str, str]: Verified (app_id, bot_id)

    Raises:
        AgentExc: When permission verification fails
    """
    span = Span(app_id=app_id)
    with span.start("VerifyBotPermission") as sp:
        auth_client = AuthClient(
            app_id=app_id,
            span=sp,
            type="agent",
        )

        has_permission = await auth_client.verify_permission(bot_id)

        if not has_permission:
            raise AgentExc(
                40300,
                "Permission denied: app does not have access to this bot",
                on=f"app_id:{app_id} bot_id:{bot_id}",
            )

        return app_id, bot_id


async def verify_bot_permission_from_body(
    app_id: str,
    bot_id: str,
) -> tuple[str, str]:
    """
    Dependency to verify bot permission from request body

    Args:
        app_id: Application ID from request body
        bot_id: Bot ID from request body

    Returns:
        tuple[str, str]: Verified (app_id, bot_id)

    Raises:
        AgentExc: When permission verification fails
    """
    span = Span(app_id=app_id)
    with span.start("VerifyBotPermission") as sp:
        auth_client = AuthClient(
            app_id=app_id,
            span=sp,
            type="agent",
        )

        has_permission = await auth_client.verify_permission(bot_id)

        if not has_permission:
            raise AgentExc(
                40300,
                "Permission denied: app does not have access to this bot",
                on=f"app_id:{app_id} bot_id:{bot_id}",
            )

        return app_id, bot_id
