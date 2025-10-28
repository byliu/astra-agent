"""Bot configuration publish and authorization management API endpoints."""

import traceback
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from api.schemas.publish_inputs import AuthBindInput, PublishInput, PublishResponse
from common_imports import Span
from consts.publish_status import PLATFORM_NAMES, PublishOperation
from exceptions.agent_exc import AgentExc, AgentInternalExc
from service.auth_service import AuthService
from service.publish_service import PublishService

publish_router = APIRouter(prefix="/agent/v1", tags=["Bot Publish & Auth"])


@publish_router.post("/publish", response_model=PublishResponse)  # type: ignore[misc]
async def publish_bot_config(
    x_consumer_username: Annotated[str, Header()],
    publish_input: PublishInput,
) -> JSONResponse:
    """
    Publish or unpublish bot configuration to/from specified platform.

    This endpoint allows tenant applications to:
    - Publish bot configurations to make them available on specific platforms
    - Unpublish bot configurations to remove them from platforms

    Args:
        x_consumer_username: Tenant app ID from header
        publish_input: Publish operation details

    Returns:
        JSONResponse: Success or error response with span ID for tracing

    Raises:
        Various AgentExc: When validation fails or operation errors occur
    """
    tenant_app_id = x_consumer_username
    span = Span(app_id=tenant_app_id)

    with span.start("PublishBotConfig") as sp:
        sp.set_attributes(
            {
                "app_id": publish_input.app_id,
                "bot_id": publish_input.bot_id,
                "operation": publish_input.operation.name,
                "platform": publish_input.platform.name,
            }
        )

        sp.add_info_events(
            {
                "user-input": publish_input.model_dump_json(by_alias=True),
            }
        )

        try:
            # Create publish service
            publish_service = PublishService(
                app_id=publish_input.app_id,
                bot_id=publish_input.bot_id,
                span=sp,
            )

            # Execute publish or unpublish operation
            if publish_input.operation == PublishOperation.PUBLISH:
                await publish_service.publish(
                    platform=publish_input.platform,
                    publish_data=None,  # Use current config
                    version=publish_input.version,  # Optional version for snapshots
                )
                version_msg = (
                    f" (version: {publish_input.version})"
                    if publish_input.version
                    else ""
                )
                message = (
                    f"Successfully published to {PLATFORM_NAMES[publish_input.platform]}"
                    f"{version_msg}"
                )
            else:  # UNPUBLISH
                await publish_service.unpublish(platform=publish_input.platform)
                message = (
                    f"Successfully unpublished from {PLATFORM_NAMES[publish_input.platform]}"
                )

            response = PublishResponse(
                code=0,
                message=message,
                sid=sp.sid,
            )

            sp.add_info_events(
                {
                    "publish-outputs": response.model_dump_json(by_alias=True),
                }
            )

            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )

        except AgentExc as e:
            sp.record_exception(e)
            response = PublishResponse(
                code=e.c,
                message=e.m,
                sid=sp.sid,
            )
            sp.add_info_events(
                {
                    "publish-outputs": response.model_dump_json(by_alias=True),
                }
            )
            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )

        except Exception as e:
            traceback.print_exc()
            sp.record_exception(e)
            agent_internal_exc = AgentInternalExc()
            response = PublishResponse(
                code=agent_internal_exc.c,
                message=f"{agent_internal_exc.m}: {str(e)}",
                sid=sp.sid,
            )
            sp.add_info_events(
                {
                    "publish-outputs": response.model_dump_json(by_alias=True),
                }
            )
            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )


@publish_router.post("/auth", response_model=PublishResponse)  # type: ignore[misc]
async def bind_bot_authorization(
    x_consumer_username: Annotated[str, Header()],
    auth_input: AuthBindInput,
) -> JSONResponse:
    """
    Create authorization binding between app and bot configuration.

    This endpoint:
    1. Validates bot is published
    2. Calls remote auth service to create binding
    3. Caches authorization status

    Args:
        x_consumer_username: Tenant app ID from header
        auth_input: Authorization binding details

    Returns:
        JSONResponse: Success or error response with span ID for tracing

    Raises:
        Various AgentExc: When validation fails or binding errors occur
    """
    tenant_app_id = x_consumer_username
    span = Span(app_id=tenant_app_id)

    with span.start("BindBotAuthorization") as sp:
        sp.set_attributes(
            {
                "tenant_app_id": tenant_app_id,
                "target_app_id": auth_input.app_id,
                "bot_id": auth_input.bot_id,
            }
        )

        sp.add_info_events(
            {
                "user-input": auth_input.model_dump_json(by_alias=True),
            }
        )

        try:
            # Create auth service
            auth_service = AuthService(
                app_id=auth_input.app_id,
                bot_id=auth_input.bot_id,
                span=sp,
                x_consumer_username=x_consumer_username,
            )

            # Bind authorization
            await auth_service.bind()

            response = PublishResponse(
                code=0,
                message="Successfully created authorization binding",
                sid=sp.sid,
            )

            sp.add_info_events(
                {
                    "auth-outputs": response.model_dump_json(by_alias=True),
                }
            )

            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )

        except AgentExc as e:
            sp.record_exception(e)
            response = PublishResponse(
                code=e.c,
                message=e.m,
                sid=sp.sid,
            )
            sp.add_info_events(
                {
                    "auth-outputs": response.model_dump_json(by_alias=True),
                }
            )
            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )

        except Exception as e:
            traceback.print_exc()
            sp.record_exception(e)
            agent_internal_exc = AgentInternalExc()
            response = PublishResponse(
                code=agent_internal_exc.c,
                message=f"{agent_internal_exc.m}: {str(e)}",
                sid=sp.sid,
            )
            sp.add_info_events(
                {
                    "auth-outputs": response.model_dump_json(by_alias=True),
                }
            )
            return JSONResponse(
                status_code=200,
                content=response.model_dump(by_alias=True),
            )
