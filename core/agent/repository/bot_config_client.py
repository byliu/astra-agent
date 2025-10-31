import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.bot_config import (
    BotConfig,
    BotKnowledgeConfig,
    BotModelConfig,
    BotRegularConfig,
)
from api.utils.snowfake import get_snowflake_id
from cache.redis_client import BaseRedisClient, create_redis_client

# pylint: disable=no-member
from common_imports import Span
from domain.models.bot_config_table import TbBotConfig
from exceptions.agent_exc import AgentExc
from exceptions.bot_config_exc import BotConfigMgrExc
from infra import agent_config
from repository.mysql_client import MysqlClient


class BotConfigClient(BaseModel):
    app_id: str
    bot_id: str
    span: Span
    redis_client: Optional[BaseRedisClient] = Field(default=None)
    mysql_client: Optional[MysqlClient] = Field(default=None)
    allow_cross_app_access: bool = Field(
        default=False,
        description="Allow accessing bot config across different app_ids (for authorized access)"
    )

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
                    f"{agent_config.MYSQL_PASSWORD}"
                    f"@{agent_config.MYSQL_HOST}:"
                    f"{agent_config.MYSQL_PORT}/{agent_config.MYSQL_DB}"
                    "?charset=utf8mb4"
                )
            )

    def redis_key(self) -> str:
        # Use only bot_id as key to enable cache sharing across authorized apps
        # Since bot_id is unique, no conflicts will occur
        return f"spark_bot:bot_config:{self.bot_id}"

    async def pull_from_redis(self, span: Span) -> Optional[BotConfig]:
        with span.start("PullFromRedis") as sp:
            assert self.redis_client is not None
            redis_value = await self.redis_client.get(self.redis_key())
            if not redis_value:
                sp.add_info_events({"redis-value": ""})
                return None

            # For keys with expiration time, reset to configured expiration
            ex_seconds = agent_config.REDIS_EXPIRE
            await self.refresh_redis_ttl(
                ex_seconds,
                (
                    redis_value.decode("utf-8")
                    if isinstance(redis_value, bytes)
                    else redis_value
                ),
            )

            try:
                config = json.loads(
                    redis_value.decode("utf-8")
                    if isinstance(redis_value, bytes)
                    else redis_value
                )
            except json.decoder.JSONDecodeError as exc:
                raise AgentExc(
                    40003,
                    "invalid bot config",
                    on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                ) from exc

            result = await self.build_bot_config(value=config)
            sp.add_info_events(
                {"redis-value": result.model_dump_json(by_alias=True)}
            )

            return result

    async def set_to_redis(self, value: str, ex: int | None = None) -> None:
        if ex is None:
            ex = agent_config.REDIS_EXPIRE
        assert self.redis_client is not None
        redis_set_value = await self.redis_client.set(
            self.redis_key(), value, ex=ex
        )
        if not redis_set_value:
            raise AgentExc(
                40001,
                "failed to retrieve bot config",
                on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
            )

    async def refresh_redis_ttl(self, ex: int, value: str) -> None:
        assert self.redis_client is not None
        ttl_key = await self.redis_client.get_ttl(self.redis_key())
        if ttl_key is not None and ttl_key > 0:
            await self.set_to_redis(value, ex)

    @staticmethod
    async def build_bot_config(
        value: dict[str, Any] | TbBotConfig,
    ) -> BotConfig:
        if isinstance(value, dict):
            return BotConfig(**value)

        # Handle TbBotConfig database record with proper type conversion
        bot_config = BotConfig(
            app_id=str(value.app_id),
            bot_id=str(value.bot_id),
            knowledge_config=BotKnowledgeConfig(
                **json.loads(str(value.knowledge_config))
            ),
            model_config=BotModelConfig(**json.loads(str(value.model_config))),
            regular_config=BotRegularConfig(
                **json.loads(str(value.regular_config))
            ),
            tool_ids=json.loads(str(value.tool_ids)),
            mcp_server_ids=json.loads(str(value.mcp_server_ids)),
            mcp_server_urls=json.loads(str(value.mcp_server_urls)),
            flow_ids=json.loads(str(value.flow_ids)),
        )

        return bot_config

    async def pull_from_mysql(
        self, span: Span, version: str = "-1"
    ) -> Optional[BotConfig]:
        with span.start("PullFromMySQL") as sp:
            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                # Build query filters based on cross-app access mode
                if self.allow_cross_app_access:
                    # When cross-app access is allowed, only filter by bot_id
                    # This allows authorized apps to access bots owned by other apps
                    record = (
                        session.query(TbBotConfig)
                        .filter_by(
                            bot_id=self.bot_id,
                            version=version,
                            is_deleted=False,
                        )
                        .first()
                    )
                else:
                    # Normal mode: filter by both app_id and bot_id
                    record = (
                        session.query(TbBotConfig)
                        .filter_by(
                            app_id=self.app_id,
                            bot_id=self.bot_id,
                            version=version,
                            is_deleted=False,
                        )
                        .first()
                    )
                if not record:
                    sp.add_info_events({"mysql-value": ""})
                    return None
                bot_config = await self.build_bot_config(value=record)
                sp.add_info_events(
                    {"mysql-value": bot_config.model_dump_json(by_alias=True)}
                )
                # Only cache main version (version="-1")
                # Version snapshots are not cached
                # (historical data, low access frequency)
                if version == "-1":
                    ex_seconds = agent_config.REDIS_EXPIRE
                    await self.set_to_redis(
                        bot_config.model_dump_json(by_alias=True), ex_seconds
                    )

                return bot_config

    async def pull(
        self, raw: bool = False, version: str = "-1"
    ) -> BotConfig | dict[Any, Any]:
        """
        Pull bot config from cache or database.

        Args:
            raw: If True, return dict instead of BotConfig object
            version: Version to retrieve, defaults to "-1" (main version)

        Returns:
            BotConfig object or dict

        Note:
            - Only main version (version="-1") is cached in Redis
            - Version snapshots are always fetched from MySQL
        """
        with self.span.start("Pull") as sp:
            sp.add_info_events({"requested_version": version})

            # Only check Redis cache for main version
            if version == "-1":
                bot_config = await self.pull_from_redis(
                    sp
                ) or await self.pull_from_mysql(sp, version)
            else:
                # Version snapshots: directly query MySQL, no cache
                bot_config = await self.pull_from_mysql(sp, version)

            if not bot_config:
                raise AgentExc(
                    40001,
                    "failed to retrieve bot config",
                    on=(
                        f"app_id:{self.app_id} "
                        f"bot_id:{self.bot_id} version:{version}"
                    ),
                )

            # Only check app_id match if cross-app access is not allowed
            if not self.allow_cross_app_access and bot_config.app_id != self.app_id:
                raise AgentExc(
                    40001,
                    "failed to retrieve bot config",
                    on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                )

            if raw:
                return dict(bot_config.model_dump(by_alias=True))

            return bot_config

    async def add(self, bot_config: BotConfig) -> BotConfig:
        """
        Create new bot config - only check if main version exists.

        Version snapshots are created by publish operations,
        not by this method.
        """
        with self.span.start("Add") as sp:
            # Only check if main version exists
            value = await self.pull_from_redis(
                sp
            ) or await self.pull_from_mysql(sp, version="-1")
            if value:
                raise BotConfigMgrExc(
                    40053,
                    "bot config main version already exists, cannot create",
                    on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                )

            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:

                record = TbBotConfig(
                    id=get_snowflake_id(),
                    app_id=bot_config.app_id,
                    bot_id=bot_config.bot_id,
                    knowledge_config=(
                        bot_config.knowledge_config.model_dump_json()
                    ),
                    model_config=(
                        bot_config.model_config_.model_dump_json()
                    ),
                    regular_config=(
                        bot_config.regular_config.model_dump_json()
                    ),
                    tool_ids=json.dumps(
                        bot_config.tool_ids, ensure_ascii=False
                    ),
                    mcp_server_ids=json.dumps(
                        bot_config.mcp_server_ids, ensure_ascii=False
                    ),
                    mcp_server_urls=json.dumps(
                        bot_config.mcp_server_urls, ensure_ascii=False
                    ),
                    flow_ids=json.dumps(
                        bot_config.flow_ids, ensure_ascii=False
                    ),
                    is_deleted=False,
                )
                session.add(record)

            return bot_config

    async def delete(self) -> None:
        """
        Delete bot config - cascade delete all versions.

        This will delete:
        - Main version (version="-1")
        - All version snapshots (v1.0, v2.0, etc.)
        """
        with self.span.start("Delete") as sp:
            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                # Check main version exists
                value = await self.pull_from_redis(
                    sp
                ) or await self.pull_from_mysql(sp, version="-1")
                if not value:
                    raise AgentExc(
                        40001,
                        "Main version not found, cannot delete",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )
                if value.app_id != self.app_id:
                    raise AgentExc(
                        40001,
                        "failed to retrieve bot config",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Check if bot is published - published bots cannot be deleted
                # Must unpublish first before deletion
                record = (
                    session.query(TbBotConfig)
                    .filter_by(
                        app_id=self.app_id,
                        bot_id=self.bot_id,
                        version="-1",
                        is_deleted=False,
                    )
                    .first()
                )

                if record and record.publish_status and record.publish_status > 0:
                    sp.add_error_event(
                        f"Cannot delete published bot: bot_id={self.bot_id}, "
                        f"publish_status={record.publish_status}"
                    )
                    raise AgentExc(
                        40063,
                        "Cannot delete published bot. Please unpublish first.",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id} publish_status:{record.publish_status}",
                    )

                # Cascade delete: remove all versions of this bot_id
                deleted_count = (
                    session.query(TbBotConfig)
                    .filter_by(
                        app_id=self.app_id,
                        bot_id=self.bot_id,
                        is_deleted=False,
                    )
                    .delete()
                )
                sp.add_info_events({"deleted_versions_count": deleted_count})

                # Check if exists in Redis
                redis_value = await self.pull_from_redis(sp)

                if redis_value:
                    try:
                        assert self.redis_client is not None
                        await self.redis_client.delete(self.redis_key())
                    except Exception as e:
                        raise BotConfigMgrExc(
                            40051, "failed to delete bot config", on=str(e)
                        ) from e

    async def update(self, bot_config: BotConfig) -> BotConfig:
        """
        Update bot config - only main version (version="-1") can be updated.

        Version snapshots are immutable and cannot be updated.
        """
        with self.span.start("Update") as sp:
            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                # Only allow updating main version
                value = await self.pull_from_redis(
                    sp
                ) or await self.pull_from_mysql(sp, version="-1")
                if not value:
                    raise AgentExc(
                        40001,
                        "Main version not found, cannot update",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )
                if value.app_id != self.app_id:
                    raise AgentExc(
                        40001,
                        "failed to retrieve bot config",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                # Query main version only
                record = (
                    session.query(TbBotConfig)
                    .filter_by(
                        app_id=self.app_id,
                        bot_id=self.bot_id,
                        version="-1",
                        is_deleted=False,
                    )
                    .first()
                )
                if record:
                    # Update record attributes
                    record.knowledge_config = (
                        bot_config.knowledge_config.model_dump_json()
                    )
                    record.model_config = (
                        bot_config.model_config_.model_dump_json()
                    )
                    record.regular_config = (
                        bot_config.regular_config.model_dump_json()
                    )
                    record.tool_ids = json.dumps(
                        bot_config.tool_ids, ensure_ascii=False
                    )
                    record.mcp_server_ids = json.dumps(
                        bot_config.mcp_server_ids, ensure_ascii=False
                    )
                    record.mcp_server_urls = json.dumps(
                        bot_config.mcp_server_urls, ensure_ascii=False
                    )
                    record.flow_ids = json.dumps(
                        bot_config.flow_ids, ensure_ascii=False
                    )

                    session.add(record)

                redis_value = await self.pull_from_redis(sp)
                if redis_value:
                    assert self.redis_client is not None
                    ttl_key = await self.redis_client.get_ttl(self.redis_key())
                    bot_config_value = bot_config.model_dump_json(
                        by_alias=True
                    )
                    if ttl_key == -1:
                        await self.set_to_redis(bot_config_value, ex=None)
                    elif ttl_key is not None and ttl_key > 0:
                        await self.set_to_redis(bot_config_value)

            return bot_config
