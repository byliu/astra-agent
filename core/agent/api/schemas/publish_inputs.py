"""Input and output schemas for bot publish and authorization APIs."""

from pydantic import BaseModel, Field

from consts.publish_status import Platform, PublishOperation


class PublishInput(BaseModel):
    """Input model for bot publish/unpublish operations."""

    app_id: str = Field(..., min_length=1, max_length=64, description="Application ID")
    bot_id: str = Field(..., min_length=1, max_length=64, description="Bot configuration ID")
    operation: PublishOperation = Field(..., description="Publish operation: 1=publish, 0=unpublish")
    platform: Platform = Field(..., description="Target platform: 1=XINGCHEN, 4=KAIFANG, 16=AIUI")


class AuthBindInput(BaseModel):
    """Input model for authorization binding."""

    app_id: str = Field(..., min_length=1, max_length=64, description="Application ID to bind")
    bot_id: str = Field(..., min_length=1, max_length=64, description="Bot configuration ID to bind")


class PublishResponse(BaseModel):
    """Standard response model for publish and auth operations."""

    code: int = Field(default=0, description="Response code: 0=success, others=error")
    message: str = Field(default="success", description="Response message")
    sid: str = Field(default="", description="Span/trace ID for debugging")
    data: dict | None = Field(default=None, description="Optional response data")
