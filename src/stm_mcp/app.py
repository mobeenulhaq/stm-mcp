"""MCP application instance.

This module exists to avoid circular import issues when running with `python -m`.
All tool modules should import `mcp` from here, not from server.py.
"""

from mcp.server.fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP(
    "STM Transit",
    instructions="Montreal STM transit information - schedules, real-time arrivals, and trip planning",
)
