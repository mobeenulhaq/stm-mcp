"""Tests for the MCP server and health tool."""

from stm_mcp import __version__
from stm_mcp.server import health


def test_health_returns_ok_status():
    """Health check should return status ok."""
    response = health()
    assert response.status == "ok"


def test_health_returns_version():
    """Health check should return the current version."""
    response = health()
    assert response.version == __version__


def test_health_returns_timestamp():
    """Health check should return a valid ISO timestamp."""
    response = health()
    assert response.timestamp is not None
    # Should be parseable as ISO format
    assert "T" in response.timestamp
