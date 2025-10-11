"""Middleware package for Agent service"""

from .auth_middleware import AuthMiddleware

__all__ = ["AuthMiddleware"]
