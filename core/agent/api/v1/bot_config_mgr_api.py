import json
import traceback
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.routing import APIRoute

from api.dependencies.auth_permission import (
    verify_bot_permission,
    verify_bot_permission_from_body,
)
from api.schemas.bot_config import BotConfig
from api.schemas.bot_config_mgr_response import GeneralResponse

# Use unified common package import module
from common_imports import Span
from exceptions.agent_exc import AgentExc, AgentInternalExc
from exceptions.bot_config_exc import BotConfigMgrExc
from repository.bot_config_client import BotConfigClient

bot_config_mgr_router = APIRouter(prefix="/agent/v1")


@asynccontextmanager
async def tracing_context(
    app_id: str, operation_name: str, input_data: Optional[Dict[str, Any]] = None
) -> AsyncIterator[Span]:
    """Unified tracing context manager"""
    span = Span(app_id=app_id)
    with span.start(operation_name) as sp:
        try:
            sp.set_attribute("app_id", app_id)
            if input_data:
                sp.add_info_events(
                    {f"{operation_name.lower()}-inputs": json.dumps(input_data)}
                )
            yield sp
        except (BotConfigMgrExc, AgentExc) as e:
            response = GeneralResponse(code=e.c, message=e.m)
            sp.add_info_events(
                {
                    f"{operation_name.lower()}-outputs": response.model_dump_json(
                        by_alias=True
                    )
                }
            )
            raise
        except (ValueError, TypeError, KeyError) as e:
            # Handle data validation and processing related exceptions
            agent_internal_exc = AgentInternalExc()
            response = GeneralResponse(
                code=agent_internal_exc.c,
                message=f"{agent_internal_exc.m}: Data processing error - {str(e)}",
            )
            sp.add_info_events(
                {
                    f"{operation_name.lower()}-outputs": response.model_dump_json(
                        by_alias=True
                    )
                }
            )
            raise BotConfigMgrExc(c=response.code, m=response.message) from e
        except Exception as e:
            # Final exception capture, log detailed information for debugging
            traceback.print_exc()
            agent_internal_exc = AgentInternalExc()
            response = GeneralResponse(
                code=agent_internal_exc.c,
                message=f"{agent_internal_exc.m}: Unexpected error - {str(e)}",
            )
            sp.add_info_events(
                {
                    f"{operation_name.lower()}-outputs": response.model_dump_json(
                        by_alias=True
                    )
                }
            )
            raise BotConfigMgrExc(c=response.code, m=response.message) from e


async def handle_bot_config_operation(
    operation_func: Callable,
    app_id: str,
    bot_id: Optional[str],
    operation_name: str,
    input_data: Optional[Dict[str, Any]] = None,
) -> GeneralResponse:
    """Unified bot config operation handler function"""
    try:
        input_dict = {"app_id": app_id}
        if bot_id:
            input_dict["bot_id"] = bot_id
        if input_data:
            input_dict.update(input_data)

        async with tracing_context(app_id, operation_name, input_dict) as sp:
            if bot_id:
                sp.set_attribute("bot_id", bot_id)

            result = await operation_func(sp)

            if isinstance(result, dict):
                response = GeneralResponse(data=result)
            else:
                response = (
                    result
                    if isinstance(result, GeneralResponse)
                    else GeneralResponse(data=result)
                )

            sp.add_info_events(
                {
                    f"{operation_name.lower()}-outputs": response.model_dump_json(
                        by_alias=True
                    )
                }
            )
            return response

    except (BotConfigMgrExc, AgentExc) as e:
        return GeneralResponse(code=e.c, message=e.m)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Keep broad exception catching here to ensure API won't crash due to
        # unknown errors
        # This is the last line of defense for Web API, ensuring always return
        # valid HTTP responses
        # Complies with microservice architecture best practices, ensuring
        # high service availability
        traceback.print_exc()
        agent_internal_exc = AgentInternalExc()
        return GeneralResponse(
            code=agent_internal_exc.c,
            message=f"{agent_internal_exc.m}: Service error - {str(e)}",
        )


@bot_config_mgr_router.post("/bot-config")  # type: ignore[misc]
async def create_bot_config(
    x_consumer_username: Annotated[str, Header()],
    bot_config: BotConfig,
) -> GeneralResponse:
    """Create new bot config"""

    # Tenant isolation: verify header matches body app_id
    # This ensures each tenant can only create bots under their own app_id
    # No external Auth Service verification needed for creation
    if x_consumer_username != bot_config.app_id:
        raise AgentExc(
            40300,
            "Permission denied: tenant app ID mismatch",
            on=f"header:{x_consumer_username} body:{bot_config.app_id}",
        )

    async def _create_operation(sp: Span) -> dict[str, Any]:
        result = await BotConfigClient(
            app_id=bot_config.app_id, bot_id=bot_config.bot_id, span=sp
        ).add(bot_config)
        # Convert BotConfig to dict for GeneralResponse
        return result.model_dump(by_alias=True)

    return await handle_bot_config_operation(
        operation_func=_create_operation,
        app_id=bot_config.app_id,
        bot_id=bot_config.bot_id,
        operation_name="CreateBotConfig",
        input_data=bot_config.model_dump(by_alias=True),
    )


@bot_config_mgr_router.delete("/bot-config")  # type: ignore[misc]
async def delete_bot_config(
    verified_params: tuple[str, str] = Depends(verify_bot_permission),
) -> GeneralResponse:
    """Delete bot config and clear associated cache"""
    app_id, bot_id = verified_params

    async def _delete_operation(sp: Span) -> GeneralResponse:
        bot_config_client = BotConfigClient(app_id=app_id, bot_id=bot_id, span=sp)

        # Delete bot config from database
        await bot_config_client.delete()

        # Clear authorization cache for this bot
        # Cache key pattern: agent:auth:{any_app_id}:{bot_id}
        # Note: Redis doesn't support pattern delete in cluster mode,
        # so we rely on TTL expiration (3600s)
        # Individual auth cache will be invalidated when apps try to access
        sp.add_info_events(
            {
                "message": "Bot config deleted, auth cache will expire naturally",
                "cache_ttl": "3600s",
            }
        )

        return GeneralResponse()

    return await handle_bot_config_operation(
        operation_func=_delete_operation,
        app_id=app_id,
        bot_id=bot_id,
        operation_name="DeleteBotConfig",
    )


@bot_config_mgr_router.put("/bot-config")  # type: ignore[misc]
async def update_bot_config(
    bot_config: BotConfig,
    x_consumer_username: Annotated[str, Header()],
) -> GeneralResponse:
    """Update bot config"""

    # Verify permission
    await verify_bot_permission_from_body(
        bot_config.app_id, bot_config.bot_id, x_consumer_username
    )

    async def _update_operation(sp: Span) -> dict[str, Any]:
        result = await BotConfigClient(
            app_id=bot_config.app_id, bot_id=bot_config.bot_id, span=sp
        ).update(bot_config)
        # Convert BotConfig to dict for GeneralResponse
        return result.model_dump(by_alias=True)

    return await handle_bot_config_operation(
        operation_func=_update_operation,
        app_id=bot_config.app_id,
        bot_id=bot_config.bot_id,
        operation_name="UpdateBotConfig",
        input_data=bot_config.model_dump(by_alias=True),
    )


@bot_config_mgr_router.get("/bot-config")  # type: ignore[misc]
async def get_bot_config(
    verified_params: tuple[str, str] = Depends(verify_bot_permission),
    include_publish_info: bool = Query(
        default=False, description="Include publish status information"
    ),
    version: str = Query(
        default="-1",
        description="Version to query (default: -1 for main version)",
    ),
) -> GeneralResponse:
    """
    Query bot config with optional version and publish status information.

    Args:
        version: Version identifier
            - "-1" (default): main development version
            - "v1.0", "v2.0", etc.: version snapshots
        include_publish_info: Include publish status details
    """
    app_id, bot_id = verified_params

    async def _get_operation(sp: Span) -> dict[str, Any]:
        bot_config_result = await BotConfigClient(
            app_id=app_id, bot_id=bot_id, span=sp
        ).pull(raw=True, version=version)

        # Ensure returning dict type
        if isinstance(bot_config_result, dict):
            result = bot_config_result
        else:
            result = bot_config_result.model_dump()

        # Optionally add publish status information
        if include_publish_info:
            from consts.publish_status import PLATFORM_NAMES, Platform, get_published_platforms

            publish_status = result.get("publish_status", 0)
            published_platforms = get_published_platforms(publish_status)

            result["publish_info"] = {
                "publish_status": publish_status,
                "is_published": publish_status > 0,
                "published_platforms": [
                    {"value": p.value, "name": PLATFORM_NAMES[p]}
                    for p in published_platforms
                ],
                "has_publish_data": result.get("publish_data") is not None,
            }

            sp.add_info_events(
                {
                    "include_publish_info": True,
                    "publish_status": publish_status,
                    "platforms_count": len(published_platforms),
                }
            )

        return result  # type: ignore[no-any-return]

    return await handle_bot_config_operation(
        operation_func=_get_operation,
        app_id=app_id,
        bot_id=bot_id,
        operation_name="GetBotConfig",
    )
