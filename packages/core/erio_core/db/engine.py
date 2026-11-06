"""The database engine every long-running service uses.

Besides a pre-ping, it sets two limits on each session, enforced by Postgres:
a session may not sit in an open transaction (``idle_in_transaction_session_timeout``)
or wait for a lock (``lock_timeout``) longer than the settings allow. A worker that
stalls on a slow dependency then loses its own transaction and locks instead of
freezing every writer queued behind it.
"""

from sqlalchemy import Engine, create_engine

from erio_core.settings import Settings


def make_engine(settings: Settings) -> Engine:
    options = (
        f"-c idle_in_transaction_session_timeout={settings.db_idle_in_transaction_s * 1000} "
        f"-c lock_timeout={settings.db_lock_timeout_s * 1000}"
    )
    return create_engine(
        settings.sqlalchemy_url, pool_pre_ping=True, connect_args={"options": options}
    )
