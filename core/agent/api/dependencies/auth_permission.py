"""FastAPI dependencies for auth permission verification"""
from typing import Annotated, Optional

from fastapi import Depends, Header, Query

from common_imports import Span
from exceptions.agent_exc import AgentExc
from repository.auth_client import AuthClient
from repository.bot_config_client import BotConfigClient


async def verify_bot_permission(
    app_id: Annotated[str, Query(min_length=1, max_length=64)],
    bot_id: Annotated[str, Query(min_length=1, max_length=64)],
    x_consumer_username: Annotated[Optional[str], Header()] = None,
) -> tuple[str, str]:
    """
    Dependency to verify bot permission before processing request.
    
    Permission logic:
    1. If app_id is the bot owner (creator) → allow access
    2. If app_id is authorized via auth service → allow access  
    3. Otherwise → deny access

    Args:
        app_id: Application ID from query parameter
        bot_id: Bot ID from query parameter
        x_consumer_username: Tenant app ID from header (for test logic)

    Returns:
        tuple[str, str]: Verified (app_id, bot_id)

    Raises:
        AgentExc: When permission verification fails
    """
    span = Span(app_id=app_id)
    with span.start("VerifyBotPermission") as sp:
        # Step 1: Check if bot exists and get its owner
        try:
            bot_config_client = BotConfigClient(
                app_id=app_id,
                bot_id=bot_id,
                span=sp,
                allow_cross_app_access=True,  # Allow querying across apps
            )
            bot_config = await bot_config_client.pull()
            
            sp.add_info_events({
                "bot_owner": bot_config.app_id,
                "requester_app_id": app_id,
            })
            
            # Step 2: Check if requester is the bot owner (creator)
            if bot_config.app_id == app_id:
                sp.add_info_event(
                    f"Permission granted: app_id={app_id} is the bot owner"
                )
                return app_id, bot_id
            
            # Step 3: Not the owner, check authorization via auth service
            sp.add_info_event(
                "Requester is not owner, checking auth service authorization"
            )
            
        except AgentExc as e:
            # Bot not found or other errors
            sp.add_error_event(f"Failed to retrieve bot config: {e.m}")
            raise AgentExc(
                40001,
                f"Bot not found or access denied: {e.m}",
                on=f"app_id:{app_id} bot_id:{bot_id}",
            ) from e
        
        # Check authorization via auth service
        auth_client = AuthClient(
            app_id=app_id,
            span=sp,
            type="agent",
            x_consumer_username=x_consumer_username,
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
    x_consumer_username: Optional[str] = None,
) -> tuple[str, str]:
    """
    Dependency to verify bot permission from request body.
    
    Permission logic:
    1. If app_id is the bot owner (creator) → allow access
    2. If app_id is authorized via auth service → allow access
    3. Otherwise → deny access

    Args:
        app_id: Application ID from request body
        bot_id: Bot ID from request body
        x_consumer_username: Tenant app ID from header (for test logic)

    Returns:
        tuple[str, str]: Verified (app_id, bot_id)

    Raises:
        AgentExc: When permission verification fails
    """
    span = Span(app_id=app_id)
    with span.start("VerifyBotPermission") as sp:
        # Step 1: Check if bot exists and get its owner
        try:
            bot_config_client = BotConfigClient(
                app_id=app_id,
                bot_id=bot_id,
                span=sp,
                allow_cross_app_access=True,  # Allow querying across apps
            )
            bot_config = await bot_config_client.pull()
            
            sp.add_info_events({
                "bot_owner": bot_config.app_id,
                "requester_app_id": app_id,
            })
            
            # Step 2: Check if requester is the bot owner (creator)
            if bot_config.app_id == app_id:
                sp.add_info_event(
                    f"Permission granted: app_id={app_id} is the bot owner"
                )
                return app_id, bot_id
            
            # Step 3: Not the owner, check authorization via auth service
            sp.add_info_event(
                "Requester is not owner, checking auth service authorization"
            )
            
        except AgentExc as e:
            # Bot not found or other errors
            sp.add_error_event(f"Failed to retrieve bot config: {e.m}")
            raise AgentExc(
                40001,
                f"Bot not found or access denied: {e.m}",
                on=f"app_id:{app_id} bot_id:{bot_id}",
            ) from e
        
        # Check authorization via auth service
        auth_client = AuthClient(
            app_id=app_id,
            span=sp,
            type="agent",
            x_consumer_username=x_consumer_username,
        )
        
        has_permission = await auth_client.verify_permission(bot_id)
        
        if not has_permission:
            raise AgentExc(
                40300,
                "Permission denied: app does not have access to this bot",
                on=f"app_id:{app_id} bot_id:{bot_id}",
            )
        
        return app_id, bot_id
