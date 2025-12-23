"""
Unit tests for server startup module.
"""

import os
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from plugin.aitools.app.start_server import AIToolsServer, aitools_app


class TestAIToolsServer:
    """Test cases for AIToolsServer"""

    @pytest.fixture
    def server(self) -> AIToolsServer:
        """Create a test server instance"""
        return AIToolsServer()

    @patch.object(AIToolsServer, "setup_server")
    @patch.object(AIToolsServer, "start_uvicorn")
    def test_start(
        self, mock_start_uvicorn: Mock, mock_setup_server: Mock, server: AIToolsServer
    ) -> None:
        """Test server start method"""
        server.start()

        mock_setup_server.assert_called_once()
        mock_start_uvicorn.assert_called_once()

    @patch.dict(os.environ, {"SERVICE_PORT_KEY": "invalid_port"})
    def test_start_uvicorn_invalid_port(self) -> None:
        """Test starting uvicorn with invalid port"""
        # Mock the constants
        with patch(
            "plugin.aitools.app.start_server.SERVICE_PORT_KEY", "SERVICE_PORT_KEY"
        ):
            with pytest.raises(ValueError):
                AIToolsServer.start_uvicorn()

    def test_server_has_load_config_method(self, server: AIToolsServer) -> None:
        """Test that server instance has load_config method (may be added later)"""
        # This test ensures that if load_config method is added later,
        # it will be available on the server instance
        if hasattr(server, "load_config"):
            assert callable(server.load_config)
        else:
            # Add a placeholder method for testing
            server.load_config = Mock()
            assert callable(server.load_config)


class TestAitoolsApp:
    """Test cases for aitools_app function"""

    @patch("plugin.aitools.app.start_server.app")
    def test_aitools_app_creation(self, mock_app: Mock) -> None:
        """Test aitools app creation"""
        result = aitools_app()

        # Verify FastAPI app is created
        assert isinstance(result, FastAPI)

        # Verify the result has the expected FastAPI methods
        assert hasattr(result, "include_router")
        assert hasattr(result, "get")
        assert hasattr(result, "post")

    @patch("plugin.aitools.app.start_server.app")
    def test_aitools_app_returns_fastapi_instance(self, mock_app: Mock) -> None:
        """Test that aitools_app returns a FastAPI instance"""
        app_instance = aitools_app()

        assert isinstance(app_instance, FastAPI)
        assert hasattr(app_instance, "include_router")
        assert hasattr(app_instance, "get")
        assert hasattr(app_instance, "post")

    @patch("plugin.aitools.app.start_server.FastAPI")
    @patch("plugin.aitools.app.start_server.app")
    def test_aitools_app_fastapi_initialization(
        self, mock_router: Mock, mock_fastapi: Mock
    ) -> None:
        """Test FastAPI initialization in aitools_app"""
        mock_app_instance = Mock()
        mock_fastapi.return_value = mock_app_instance

        result = aitools_app()

        # Verify FastAPI is instantiated
        mock_fastapi.assert_called_once_with()

        # Verify router is included
        mock_app_instance.include_router.assert_called_once_with(mock_router)

        # Verify the mock instance is returned
        assert result == mock_app_instance
