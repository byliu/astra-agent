"""Unit tests for AuthClient"""

import pytest
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from common_imports import Span
from exceptions.agent_exc import AgentExc
from repository.auth_client import AuthClient, AuthPermission, AuthResponse


@pytest.fixture
def mock_span() -> MagicMock:
    """Create mock Span"""
    span = MagicMock(spec=Span)

    mock_sub_span = MagicMock()
    mock_sub_span.set_attributes = MagicMock()
    mock_sub_span.add_info_events = MagicMock()
    mock_sub_span.add_info_event = MagicMock()

    # Create context manager that doesn't swallow exceptions
    mock_context = MagicMock()
    mock_context.__enter__ = MagicMock(return_value=mock_sub_span)
    mock_context.__exit__ = MagicMock(
        return_value=False
    )  # Don't suppress exceptions

    span.start = MagicMock(return_value=mock_context)

    return span


@pytest.fixture
def auth_client(mock_span: MagicMock) -> AuthClient:
    """Create AuthClient instance"""
    return AuthClient(
        app_id="test_app",
        span=mock_span,
        type="agent",
        x_consumer_username="2hhikfuh",
    )


class TestAuthClient:
    """Test cases for AuthClient"""

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_success(self, mock_config: MagicMock, auth_client: AuthClient) -> None:
        """Test successful permission verification"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        mock_response_data = {
            "code": 0,
            "message": "success",
            "sid": "test_sid",
            "data": [
                {
                    "app_id": "test_app",
                    "type": "agent",
                    "ability_id": "test_bot",
                    "status": 1,
                    "create_at": "2024-01-01",
                    "update_at": "2024-01-01",
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=mock_response_data)
            mock_response.raise_for_status = MagicMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_http_client

            result = await auth_client.verify_permission("test_bot")

            assert result is True
            mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_denied(self, mock_config: MagicMock, auth_client: AuthClient) -> None:
        """Test permission denied"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        mock_response_data = {
            "code": 0,
            "message": "success",
            "sid": "test_sid",
            "data": [
                {
                    "app_id": "test_app",
                    "type": "agent",
                    "ability_id": "test_bot",
                    "status": 0,  # Disabled
                    "create_at": "2024-01-01",
                    "update_at": "2024-01-01",
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=mock_response_data)
            mock_response.raise_for_status = MagicMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_http_client

            result = await auth_client.verify_permission("test_bot")

            assert result is False

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_no_matching_permission(
        self, mock_config: MagicMock, auth_client: AuthClient
    ) -> None:
        """Test no matching permission found"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        mock_response_data = {
            "code": 0,
            "message": "success",
            "sid": "test_sid",
            "data": [],  # No permissions
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=mock_response_data)
            mock_response.raise_for_status = MagicMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_http_client

            result = await auth_client.verify_permission("test_bot")

            assert result is False

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_url_not_configured(
        self, mock_config: MagicMock, auth_client: AuthClient
    ) -> None:
        """Test permission check fails when URL not configured"""
        mock_config.AUTH_API_URL = ""

        with pytest.raises(AgentExc) as exc_info:
            await auth_client.verify_permission("test_bot")

        assert exc_info.value.c == 50004
        assert "Auth service not configured" in exc_info.value.m

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_http_error(
        self, mock_config: MagicMock, auth_client: AuthClient
    ) -> None:
        """Test HTTP error during permission check"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_http_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Error", request=MagicMock(), response=mock_response
                )
            )
            mock_client.return_value.__aenter__.return_value = mock_http_client

            with pytest.raises(AgentExc) as exc_info:
                await auth_client.verify_permission("test_bot")

            assert exc_info.value.c == 50001

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_verify_permission_connection_error(
        self, mock_config: MagicMock, auth_client: AuthClient
    ) -> None:
        """Test connection error during permission check"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(
                side_effect=httpx.RequestError(
                    "Connection failed", request=MagicMock()
                )
            )
            mock_client.return_value.__aenter__.return_value = mock_http_client

            with pytest.raises(AgentExc) as exc_info:
                await auth_client.verify_permission("test_bot")

            assert exc_info.value.c == 50002

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_get_permissions_success(self, mock_config: MagicMock, auth_client: AuthClient) -> None:
        """Test successful get permissions"""
        mock_config.AUTH_API_URL = "http://auth-service/auth/v1/get"

        mock_response_data = {
            "code": 0,
            "message": "success",
            "sid": "test_sid",
            "data": [
                {
                    "app_id": "test_app",
                    "type": "agent",
                    "ability_id": "bot1",
                    "status": 1,
                    "create_at": "2024-01-01",
                    "update_at": "2024-01-01",
                },
                {
                    "app_id": "test_app",
                    "type": "agent",
                    "ability_id": "bot2",
                    "status": 1,
                    "create_at": "2024-01-01",
                    "update_at": "2024-01-01",
                },
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value=mock_response_data)
            mock_response.raise_for_status = MagicMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_http_client

            permissions = await auth_client.get_permissions()

            assert len(permissions) == 2
            assert permissions[0].ability_id == "bot1"
            assert permissions[1].ability_id == "bot2"

    @pytest.mark.asyncio
    @patch("repository.auth_client.agent_config")
    async def test_get_permissions_url_not_configured(
        self, mock_config: MagicMock, auth_client: AuthClient
    ) -> None:
        """Test get permissions fails when URL not configured"""
        mock_config.AUTH_API_URL = ""

        with pytest.raises(AgentExc) as exc_info:
            await auth_client.get_permissions()

        assert exc_info.value.c == 50004
        assert "Auth service not configured" in exc_info.value.m


class TestAuthPermission:
    """Test cases for AuthPermission model"""

    def test_auth_permission_creation(self) -> None:
        """Test AuthPermission model creation"""
        permission = AuthPermission(
            app_id="test_app",
            type="agent",
            ability_id="test_bot",
            status=1,
            create_at="2024-01-01",
            update_at="2024-01-01",
        )

        assert permission.app_id == "test_app"
        assert permission.type == "agent"
        assert permission.ability_id == "test_bot"
        assert permission.status == 1


class TestAuthResponse:
    """Test cases for AuthResponse model"""

    def test_auth_response_creation(self) -> None:
        """Test AuthResponse model creation"""
        response = AuthResponse(
            code=0,
            message="success",
            sid="test_sid",
            data=[
                AuthPermission(
                    app_id="test_app",
                    type="agent",
                    ability_id="test_bot",
                    status=1,
                    create_at="2024-01-01",
                    update_at="2024-01-01",
                )
            ],
        )

        assert response.code == 0
        assert response.message == "success"
        assert len(response.data) == 1
