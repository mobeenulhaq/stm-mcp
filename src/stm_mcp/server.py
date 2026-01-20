from datetime import UTC, datetime
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

# Initialize the MCP server
mcp = FastMCP(
    "STM Transit",
    instructions="Montreal STM transit information - schedules, real-time arrivals, and trip planning",
)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: str


@mcp.tool()
def health() -> HealthResponse:
    """Check if the STM MCP server is running and healthy.

    Returns the server status, version, and current timestamp.
    """
    from stm_mcp import __version__

    return HealthResponse(
        status="ok",
        version=__version__,
        timestamp=datetime.now(UTC).isoformat(),
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
