"""Shared by the public job services (kind "service" in the platform registry).

A public job service lists jobs of many employers from one fixed host, so its
board token is just ``https://{host}`` for a host the connector declares. Any
other token is refused, which keeps a hostile token from aiming a connector at
another host.
"""

import html
import re
from urllib.parse import urlsplit

SPACE = re.compile(r"\s+")


def service_host(board_token: str, hosts: frozenset[str], name: str) -> str:
    """The host of a service token (``https://{host}``, nothing after it)."""
    parts = urlsplit(board_token)
    if (
        parts.scheme != "https"
        or parts.hostname not in hosts
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.username
        or parts.port
    ):
        allowed = " or ".join(f"https://{h}" for h in sorted(hosts))
        raise ValueError(f"not a {name} token ({allowed}): {board_token!r}")
    return str(parts.hostname)


def plain(value: object) -> str | None:
    """A source's text field as one clean line: entities decoded, spaces collapsed."""
    if value is None:
        return None
    text = SPACE.sub(" ", html.unescape(str(value))).strip()
    return text or None
