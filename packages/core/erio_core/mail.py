"""Sending email through Resend, or to a log line when no key is set (local development).

The provider key is read from a file whose path is in ``ERIO_MAIL_KEY_FILE`` (a mounted
file), never from a setting or the image (decision D-08). With no file the message is
written to the log instead, so the whole alert flow can be run and read without sending.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from erio_core.settings import get_settings

log = logging.getLogger("erio.mail")
RESEND_URL = "https://api.resend.com/emails"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str
    # Lets mail clients show their own "unsubscribe" button (a page that stops the alerts).
    unsubscribe_url: str | None = None


class MailError(RuntimeError):
    """The provider refused or could not be reached; the caller decides whether to retry."""


def _key() -> str | None:
    path = get_settings().mail_key_file
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def send(message: Message, *, transport: httpx.BaseTransport | None = None) -> bool:
    """True when sent; False when only logged (no key). Raises MailError on a real failure."""
    key = _key()
    if key is None:
        log.info(
            "mail not sent (no key): to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.text,
        )
        return False
    headers: dict[str, str] = {}
    if message.unsubscribe_url:
        headers = {"List-Unsubscribe": f"<{message.unsubscribe_url}>"}
    body = {
        "from": get_settings().mail_from,
        "to": [message.to],
        "subject": message.subject,
        "text": message.text,
        "html": message.html,
        "headers": headers,
    }
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            response = client.post(
                RESEND_URL, json=body, headers={"Authorization": f"Bearer {key}"}
            )
    except httpx.HTTPError as error:
        raise MailError(f"mail provider unreachable: {error.__class__.__name__}") from error
    if response.status_code >= 400:
        raise MailError(f"mail provider answered {response.status_code}")
    return True
