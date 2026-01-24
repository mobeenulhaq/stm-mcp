import httpx

from stm_mcp.data.config import GTFSRTConfig
from stm_mcp.models.alerts import I3Response


class I3Client:
    """Async HTTP client for fetching service status from the i3 API.

    Usage:
        async with I3Client(config) as client:
            response = await client.fetch_service_status()
    """

    def __init__(self, config: GTFSRTConfig):
        """Initialize the client.

        Args:
            config: Configuration with API key and i3 URL.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "I3Client":
        """Enter async context - create HTTP client."""
        headers = {}
        if self._config.api_key:
            headers["apikey"] = self._config.api_key
        self._client = httpx.AsyncClient(headers=headers, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context - close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_service_status(self) -> I3Response:
        """Fetch and parse the service status from the i3 API.

        Returns:
            I3Response with parsed alerts.

        Raises:
            RuntimeError: If client not initialized.
            httpx.HTTPError: If the HTTP request fails.
        """
        if not self._client:
            raise RuntimeError("Client not initialized - use 'async with'")

        response = await self._client.get(self._config.i3_etatservice_url)
        response.raise_for_status()

        # parse JSON directly into Pydantic model
        return I3Response.model_validate(response.json())
