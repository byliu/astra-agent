"""Authorization service for managing app and bot permission bindings."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cache.redis_client import BaseRedisClient, create_redis_client
from common_imports import Span
from domain.models.bot_config_table import TbBotConfig
from exceptions.agent_exc import AgentExc
from infra import agent_config
from repository.auth_client import AuthClient
from repository.mysql_client import MysqlClient


class AuthService(BaseModel):
    """Service for managing authorization between apps and bots."""

    app_id: str
    bot_id: str
    span: Span
    x_consumer_username: str | None = Field(default=None, description="Tenant app ID for header")
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

    def _get_auth_cache_key(self) -> str:
        """Get Redis cache key for authorization status."""
        return f"agent:auth:{self.app_id}:{self.bot_id}"

    async def bind(self) -> None:
        """
        Bind app_id to bot_id by creating authorization relationship.

        This method:
        1. Validates bot configuration exists and is published
        2. Calls remote auth service to create binding
        3. Caches authorization status in Redis

        Raises:
            AgentExc: When bot not found, not published, or auth service fails
        """
        with self.span.start("BindAuthorization") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": self.bot_id,
                }
            )

            # Step 1: Validate bot exists and is published
            # Note: Only check bot_id, not app_id, because we're authorizing
            # a different app to access this bot
            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                bot_config = (
                    session.query(TbBotConfig)
                    .filter_by(
                        bot_id=self.bot_id,
                        version="-1",  # Only check main version
                        is_deleted=False
                    )
                    .first()
                )

                if not bot_config:
                    sp.add_error_event(f"Bot config not found: bot_id={self.bot_id}")
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"bot_id:{self.bot_id}",
                    )

                # Check if bot is published
                publish_status = bot_config.publish_status or 0
                if publish_status == 0:
                    sp.add_error_event(
                        f"Bot not published: bot_id={self.bot_id}, "
                        f"publish_status={publish_status}"
                    )
                    raise AgentExc(
                        40060,
                        "Bot configuration not published, cannot bind authorization",
                        on=f"bot_id:{self.bot_id}",
                    )

                sp.add_info_events(
                    {
                        "bot_app_id": bot_config.app_id,
                        "bot_id": bot_config.bot_id,
                        "publish_status": publish_status,
                    }
                )

            # Step 2: Call remote auth service to create binding
            # Read x_consumer_username from config instead of parameter
            from infra.config.middleware import MiddlewareConfig
            config = MiddlewareConfig()
            
            auth_client = AuthClient(
                app_id=self.app_id,
                span=sp,
                type="agent",
                ability_id=self.bot_id,
                x_consumer_username=config.AUTH_REQUIRED_USERNAME,
            )

            try:
                # Call auth service /auth/v1/add endpoint
                await auth_client.bind_permission(self.bot_id)
                sp.add_info_events(
                    {"message": "Successfully called auth service to create binding"}
                )
            except AgentExc as e:
                sp.add_error_event(f"Auth service binding failed: {e.m}")
                raise AgentExc(
                    40061,
                    f"Authorization binding failed: {e.m}",
                    on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                ) from e

            # Step 3: Cache authorization status
            assert self.redis_client is not None
            cache_key = self._get_auth_cache_key()
            await self.redis_client.set(
                cache_key,
                "NORMAL",
                ex=agent_config.REDIS_EXPIRE,
            )
            sp.add_info_events(
                {
                    "cache_key": cache_key,
                    "cache_value": "NORMAL",
                    "cache_ttl": agent_config.REDIS_EXPIRE,
                }
            )

    async def check_permission(self) -> bool:
        """
        Check if app_id has permission to access bot_id.

        This method uses a two-tier caching strategy:
        1. Check Redis cache first for fast response
        2. Fall back to remote auth service if cache miss
        3. Write result back to cache

        Returns:
            bool: True if has permission, False otherwise

        Raises:
            AgentExc: When auth service fails or permission denied
        """
        with self.span.start("CheckBotPermission") as sp:
            sp.set_attributes(
                {
                    "app_id": self.app_id,
                    "bot_id": self.bot_id,
                }
            )

            # Step 1: Check Redis cache
            assert self.redis_client is not None
            cache_key = self._get_auth_cache_key()
            cached_status = await self.redis_client.get(cache_key)

            if cached_status:
                status_str = (
                    cached_status.decode("utf-8")
                    if isinstance(cached_status, bytes)
                    else cached_status
                )
                sp.add_info_events(
                    {
                        "cache_hit": True,
                        "cache_status": status_str,
                    }
                )

                if status_str == "NORMAL":
                    return True
                elif status_str == "DENIED":
                    raise AgentExc(
                        40300,
                        "Permission denied: app does not have access to this bot",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

            # Step 2: Cache miss, query auth service
            sp.add_info_events({"cache_hit": False})

            auth_client = AuthClient(
                app_id=self.app_id,
                span=sp,
                type="agent",
                ability_id=self.bot_id,
            )

            try:
                has_permission = await auth_client.verify_permission(self.bot_id)

                # Step 3: Write result back to cache
                cache_value = "NORMAL" if has_permission else "DENIED"
                await self.redis_client.set(
                    cache_key,
                    cache_value,
                    ex=agent_config.REDIS_EXPIRE,
                )

                sp.add_info_events(
                    {
                        "auth_service_result": has_permission,
                        "cached_value": cache_value,
                    }
                )

                if not has_permission:
                    raise AgentExc(
                        40300,
                        "Permission denied: app does not have access to this bot",
                        on=f"app_id:{self.app_id} bot_id:{self.bot_id}",
                    )

                return True

            except AgentExc as e:
                # Re-raise AgentExc without wrapping
                raise

    async def check_bot_published(self) -> bool:
        """
        Check if bot configuration is published.

        Returns:
            bool: True if published to any platform, False otherwise

        Raises:
            AgentExc: When bot config not found or not published
        """
        with self.span.start("CheckBotPublished") as sp:
            sp.set_attributes({"bot_id": self.bot_id})

            assert self.mysql_client is not None
            with self.mysql_client.session_getter() as session:
                bot_config = (
                    session.query(TbBotConfig)
                    .filter_by(
                        bot_id=self.bot_id,
                        version="-1",  # Only check main version
                        is_deleted=False
                    )
                    .first()
                )

                if not bot_config:
                    sp.add_error_event(f"Bot config not found: bot_id={self.bot_id}")
                    raise AgentExc(
                        40001,
                        "Failed to get bot configuration",
                        on=f"bot_id:{self.bot_id}",
                    )

                publish_status = bot_config.publish_status or 0
                is_published = publish_status > 0

                sp.add_info_events(
                    {
                        "publish_status": publish_status,
                        "is_published": is_published,
                    }
                )

                if not is_published:
                    raise AgentExc(
                        40060,
                        "Bot configuration not published",
                        on=f"bot_id:{self.bot_id}",
                    )

                return True
