"""Publish status constants and platform definitions for bot configuration management."""

from enum import IntEnum


class PublishOperation(IntEnum):
    """Publish operation types."""

    PUBLISH = 1  # Publish bot configuration
    UNPUBLISH = 0  # Unpublish/take offline bot configuration


class Platform(IntEnum):
    """Platform identifiers using bitmask values."""

    XINGCHEN = 1  # 星辰平台 (0b00001)
    KAIFANG = 4  # 开放平台 (0b00100)
    AIUI = 16  # AIUI平台 (0b10000)


# Platform name mapping for user-friendly messages
PLATFORM_NAMES = {
    Platform.XINGCHEN: "星辰平台",
    Platform.KAIFANG: "开放平台",
    Platform.AIUI: "AIUI平台",
}


def is_published(publish_status: int, platform: Platform) -> bool:
    """
    Check if bot is published to specified platform.

    Args:
        publish_status: Current publish status bitmask
        platform: Platform to check

    Returns:
        bool: True if published to platform, False otherwise
    """
    return (publish_status & platform) > 0


def add_platform(publish_status: int, platform: Platform) -> int:
    """
    Add platform to publish status.

    Args:
        publish_status: Current publish status bitmask
        platform: Platform to add

    Returns:
        int: Updated publish status
    """
    return publish_status | platform


def remove_platform(publish_status: int, platform: Platform) -> int:
    """
    Remove platform from publish status.

    Args:
        publish_status: Current publish status bitmask
        platform: Platform to remove

    Returns:
        int: Updated publish status
    """
    return publish_status & ~platform


def get_published_platforms(publish_status: int) -> list[Platform]:
    """
    Get list of platforms where bot is published.

    Args:
        publish_status: Current publish status bitmask

    Returns:
        list[Platform]: List of platforms
    """
    platforms = []
    for platform in Platform:
        if is_published(publish_status, platform):
            platforms.append(platform)
    return platforms
