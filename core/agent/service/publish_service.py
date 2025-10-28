"""Bot configuration publish service for managing publication lifecycle."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.utils.snowfake import get_snowflake_id
from cache.redis_client import BaseRedisClient, create_redis_client
from common_imports import Span
from consts.publish_status import (
    PLATFORM_NAMES,
    Platform,
    add_platform,
    is_published,
    remove_platform,
)
from domain.models.bot_config_table import TbBotConfig
from exceptions.agent_exc import AgentExc
from infra import agent_config
from repository.mysql_client import MysqlClient


class PublishService(BaseModel):
    """Service for managing bot configuration publication."""

    app_id: str
    bot_id: str
    span: Span
    redis_client: BaseRedisClient | None = Field(default=None)
    mysql_client: MysqlClient | None = Field(default=None)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, __context: Any) -> None:
        """Initialize Redis and MySQL clients after instance creation."""
        if self.redis_client is None:
            self.redis_client = create_redis_client(
                cluster_addr=agent_config.REDIS_CLUSTER_ADDR,
                standalone_addr=agent_config.REDIS_ADDR,
                password=agent_config.REDIS_PASSWORD,
            )
        if self.mysql_client is None:
            self.mysql_client = MysqlClient(
                database_url=(
                    f"mysql+pymysql://{agent_config.MYSQL_USER}:"
                    f"{agent_config.MYSQL_PASSWORD}@"
                    f"{agent_config.MYSQL_HOST}:"
                    f"{agent_config.MYSQL_PORT}/"
                    f"{agent_config.MYSQL_DB}?charset=utf8mb4"
                )
            )

    def _get_redis_key(self) -> str:
        """Get Redis cache key for bot configuration."""
        return f"spark_bot:bot_config:{self.bot_id}"

    async def _clear_cache(self) -> None:
        """Clear bot configuration cache."""
        with self.span.start("ClearBotConfigCache") as sp:
            sp.add_info_events({"bot_id": self.bot_id})
            assert self.redis_client is not None
            await self.redis_client.delete(self._get_redis_key())

    async def publish(
        self,
        platform: Platform,
        publish_data: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> None:
        """
        Publish bot configuration to specified platform.

        Args:
            platform: Target platform to publish to
            publish_data: Optional publish data, if None uses current config
            version: Optional version identifier for creating version snapshots

        Raises:
            AgentExc: When bot config not found or operation fails
        """
        with self.span.start("PublishBotConfig") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": self.bot_id,
                    "platform": platform.name,
                }
            )

            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                # Get bot config
                bot_config = (
                    session.query(TbBotConfig)
                    .filter_by(app_id=self.app_id, bot_id=self.bot_id, is_deleted=False)
                    .first()
                )

                if not bot_config:
                    sp.add_error_event(
                        f"Bot config not found: "
                        f"app_id={self.app_id}, bot_id={self.bot_id}"
                    )
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Update publish status using bitmask
                old_status = bot_config.publish_status or 0
                new_status = add_platform(old_status, platform)
                bot_config.publish_status = new_status

                sp.add_info_events(
                    {
                        "old_publish_status": old_status,
                        "new_publish_status": new_status,
                    }
                )

                # Update publish data
                if publish_data:
                    bot_config.publish_data = json.dumps(
                        publish_data, ensure_ascii=False
                    )
                else:
                    # Use current configuration as publish data
                    current_config = {
                        "app_id": bot_config.app_id,
                        "bot_id": bot_config.bot_id,
                        "knowledge_config": json.loads(
                            str(bot_config.knowledge_config)
                        ),
                        "model_config": json.loads(
                            str(bot_config.model_config)
                        ),
                        "regular_config": json.loads(
                            str(bot_config.regular_config)
                        ),
                        "tool_ids": json.loads(str(bot_config.tool_ids)),
                        "mcp_server_ids": json.loads(
                            str(bot_config.mcp_server_ids)
                        ),
                        "mcp_server_urls": json.loads(
                            str(bot_config.mcp_server_urls)
                        ),
                        "flow_ids": json.loads(str(bot_config.flow_ids)),
                    }
                    bot_config.publish_data = json.dumps(
                        current_config, ensure_ascii=False
                    )

                session.add(bot_config)

                # Handle version snapshot creation if version is specified
                if version:
                    self._handle_version(session, bot_config, version, sp)

                session.commit()

                sp.add_info_events(
                    {
                        "message": (
                            f"Successfully published to "
                            f"{PLATFORM_NAMES[platform]}"
                        ),
                        "version": version if version else "-1",
                    }
                )

            # Clear cache after successful publish
            await self._clear_cache()

    async def unpublish(self, platform: Platform) -> None:
        """
        Unpublish bot configuration from specified platform.

        Args:
            platform: Target platform to unpublish from

        Raises:
            AgentExc: When bot config not found or not published to platform
        """
        with self.span.start("UnpublishBotConfig") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": self.bot_id,
                    "platform": platform.name,
                }
            )

            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                # Get bot config
                bot_config = (
                    session.query(TbBotConfig)
                    .filter_by(app_id=self.app_id, bot_id=self.bot_id, is_deleted=False)
                    .first()
                )

                if not bot_config:
                    sp.add_error_event(
                        f"Bot config not found: "
                        f"app_id={self.app_id}, bot_id={self.bot_id}"
                    )
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Check if published to platform
                old_status = bot_config.publish_status or 0
                if not is_published(old_status, platform):
                    sp.add_info_events(
                        {
                            "message": (
                                f"Not published to "
                                f"{PLATFORM_NAMES[platform]}"
                            )
                        }
                    )
                    raise AgentExc(
                        40063,
                        (
                            f"Bot config not published to "
                            f"{PLATFORM_NAMES[platform]}"
                        ),
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Remove platform from publish status
                new_status = remove_platform(old_status, platform)
                bot_config.publish_status = new_status

                sp.add_info_events(
                    {
                        "old_publish_status": old_status,
                        "new_publish_status": new_status,
                    }
                )

                # If unpublished from all platforms, clear publish data
                if new_status == 0:
                    bot_config.publish_data = None
                    sp.add_info_events(
                        {"message": "Cleared publish data (all platforms)"}
                    )

                session.add(bot_config)
                session.commit()

                sp.add_info_events(
                    {
                        "message": (
                            f"Successfully unpublished from "
                            f"{PLATFORM_NAMES[platform]}"
                        )
                    }
                )

            # Clear cache after successful unpublish
            await self._clear_cache()

    async def check_published(self, platform: Platform | None = None) -> bool:
        """
        Check if bot configuration is published.

        Args:
            platform: Specific platform to check, if None checks if published to any platform

        Returns:
            bool: True if published, False otherwise

        Raises:
            AgentExc: When bot config not found
        """
        with self.span.start("CheckBotPublished") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": self.bot_id,
                    "platform": platform.name if platform else "any",
                }
            )

            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                bot_config = (
                    session.query(TbBotConfig)
                    .filter_by(app_id=self.app_id, bot_id=self.bot_id, is_deleted=False)
                    .first()
                )

                if not bot_config:
                    sp.add_error_event(
                        f"Bot config not found: "
                        f"app_id={self.app_id}, bot_id={self.bot_id}"
                    )
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                publish_status = bot_config.publish_status or 0

                if platform:
                    result = is_published(publish_status, platform)
                    sp.add_info_events(
                        {
                            "publish_status": publish_status,
                            "platform": platform.name,
                            "is_published": result,
                        }
                    )
                else:
                    result = publish_status > 0
                    sp.add_info_events(
                        {
                            "publish_status": publish_status,
                            "is_published_any": result,
                        }
                    )

                return result

    def _handle_version(
        self, session: Any, bot_config: TbBotConfig, version: str, span: Span
    ) -> None:
        """
        Handle version snapshot creation for bot configuration.

        Creates a new versioned bot config record with the same bot_id,
        or updates existing version if it already exists.

        Args:
            session: Database session
            bot_config: The bot configuration being published
            version: Version identifier (e.g., v1.0, v2.0)
            span: Tracing span for logging

        Behavior:
            - bot_id remains constant across versions (like workflow.group_id)
            - If version doesn't exist: Creates new record with same bot_id
            - If version exists: Updates existing version record
            - Marks original record as version="-1" (main development version)
        """
        span.add_info_events(
            {
                "operation": "handle_version",
                "version": version,
                "bot_id": bot_config.bot_id,
            }
        )

        # Check if version already exists for this app_id and bot_id
        # If multiple records exist, returns first one (constraint handled by upstream)
        existing_version = (
            session.query(TbBotConfig)
            .filter_by(
                app_id=bot_config.app_id,
                bot_id=bot_config.bot_id,
                version=version,
                is_deleted=False,
            )
            .first()
        )

        if not existing_version:
            # Create new version snapshot with same bot_id
            # bot_id stays constant (external identifier)
            # id is explicitly generated with snowflake algorithm
            version_snapshot = TbBotConfig(
                id=get_snowflake_id(),  # Generate unique ID for version snapshot
                app_id=bot_config.app_id,
                bot_id=bot_config.bot_id,  # Keep same bot_id
                version=version,
                # Copy configuration data
                knowledge_config=bot_config.knowledge_config,
                model_config=bot_config.model_config,
                regular_config=bot_config.regular_config,
                tool_ids=bot_config.tool_ids,
                mcp_server_ids=bot_config.mcp_server_ids,
                mcp_server_urls=bot_config.mcp_server_urls,
                flow_ids=bot_config.flow_ids,
                # Copy publish information
                publish_status=bot_config.publish_status,
                publish_data=bot_config.publish_data,
            )
            session.add(version_snapshot)

            span.add_info_events(
                {
                    "action": "created_version_snapshot",
                    "bot_id": version_snapshot.bot_id,
                    "version": version_snapshot.version,
                }
            )
        else:
            # Update existing version
            existing_version.knowledge_config = bot_config.knowledge_config
            existing_version.model_config = bot_config.model_config
            existing_version.regular_config = bot_config.regular_config
            existing_version.tool_ids = bot_config.tool_ids
            existing_version.mcp_server_ids = bot_config.mcp_server_ids
            existing_version.mcp_server_urls = bot_config.mcp_server_urls
            existing_version.flow_ids = bot_config.flow_ids
            existing_version.publish_status = bot_config.publish_status
            existing_version.publish_data = bot_config.publish_data

            span.add_info_events(
                {
                    "action": "updated_existing_version",
                    "bot_id": existing_version.bot_id,
                }
            )

        # Mark original record as main development version
        bot_config.version = "-1"
