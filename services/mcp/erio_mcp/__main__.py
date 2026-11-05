"""Run the MCP server: streamable HTTP by default, or ``--stdio``."""

import sys

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from erio_core.settings import get_settings
from erio_mcp.server import server

PORT = 8100


def main() -> None:
    if "--stdio" in sys.argv[1:]:
        server.run("stdio")
        return
    app = server.streamable_http_app(
        stateless_http=True,
        # Answer only to known Host headers (DNS-rebinding protection).
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=get_settings().mcp_allowed_hosts,
        ),
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)  # noqa: S104 (inside the container)


if __name__ == "__main__":
    main()
