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
    PublishOperation,
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
                    f"{agent_config.MYSQL_PASSWORD}@{agent_config.MYSQL_HOST}:"
                    f"{agent_config.MYSQL_PORT}/{agent_config.MYSQL_DB}?charset=utf8mb4"
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
        self, platform: Platform, publish_data: dict[str, Any] | None = None
    ) -> None:
        """
        Publish bot configuration to specified platform.

        Args:
            platform: Target platform to publish to
            publish_data: Optional publish data, if None uses current config

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
                        f"Bot config not found: app_id={self.app_id}, bot_id={self.bot_id}"
                    )
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Initialize group_id if not set
                if not bot_config.group_id:
                    bot_config.group_id = str(get_snowflake_id())
                    sp.add_info_events({"group_id": bot_config.group_id})

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
                        "knowledge_config": json.loads(str(bot_config.knowledge_config)),
                        "model_config": json.loads(str(bot_config.model_config)),
                        "regular_config": json.loads(str(bot_config.regular_config)),
                        "tool_ids": json.loads(str(bot_config.tool_ids)),
                        "mcp_server_ids": json.loads(str(bot_config.mcp_server_ids)),
                        "mcp_server_urls": json.loads(str(bot_config.mcp_server_urls)),
                        "flow_ids": json.loads(str(bot_config.flow_ids)),
                    }
                    bot_config.publish_data = json.dumps(
                        current_config, ensure_ascii=False
                    )

                session.add(bot_config)
                session.commit()

                sp.add_info_events(
                    {
                        "message": f"Successfully published to {PLATFORM_NAMES[platform]}"
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
                        f"Bot config not found: app_id={self.app_id}, bot_id={self.bot_id}"
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
                        {"message": f"Not published to {PLATFORM_NAMES[platform]}"}
                    )
                    raise AgentExc(
                        40063,
                        f"Bot config not published to {PLATFORM_NAMES[platform]}",
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
                    sp.add_info_events({"message": "Cleared publish data (all platforms)"})

                session.add(bot_config)
                session.commit()

                sp.add_info_events(
                    {
                        "message": f"Successfully unpublished from {PLATFORM_NAMES[platform]}"
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
                        f"Bot config not found: app_id={self.app_id}, bot_id={self.bot_id}"
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
