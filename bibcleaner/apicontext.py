import httpx2


class ApiContext:
    def __init__(self):
        options = {
            "timeout": 20.0,
            "limits": httpx2.Limits(
                max_connections=50, max_keepalive_connections=20
            ),
        }
        try:
            self.client = httpx2.AsyncClient(http2=True, **options)
        except ImportError:
            # Keep the service usable in minimal installations. The declared
            # dependency enables HTTP/2 in normal deployments.
            self.client = httpx2.AsyncClient(http2=False, **options)

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def close(self):
        await self.client.aclose()
