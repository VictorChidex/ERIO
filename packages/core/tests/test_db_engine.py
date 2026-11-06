import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from erio_core.db.engine import make_engine
from erio_core.settings import Settings


def test_a_session_stuck_in_a_transaction_is_ended_by_postgres(database_url: str) -> None:
    engine = make_engine(Settings(database_url=database_url, db_idle_in_transaction_s=1))

    with engine.connect() as connection:
        connection.execute(text("select 1"))  # a transaction is open, and then nothing happens
        time.sleep(2.5)
        with pytest.raises(DBAPIError):
            connection.execute(text("select 1"))


def test_a_wait_for_a_lock_gives_up(database_url: str) -> None:
    holder = make_engine(Settings(database_url=database_url))
    waiter = make_engine(Settings(database_url=database_url, db_lock_timeout_s=1))
    with holder.begin() as setup:
        setup.execute(text("create table lock_probe (id int)"))

    with holder.connect() as first:
        first.execute(text("lock table lock_probe in access exclusive mode"))
        started = time.monotonic()
        with waiter.connect() as second, pytest.raises(DBAPIError, match="lock timeout"):
            second.execute(text("select * from lock_probe"))
        assert time.monotonic() - started < 10  # it gave up after about a second


def test_an_ordinary_session_is_not_affected(database_url: str) -> None:
    engine = make_engine(Settings(database_url=database_url))

    with engine.begin() as connection:
        assert connection.execute(text("select 1")).scalar_one() == 1
        shown = connection.execute(text("show idle_in_transaction_session_timeout")).scalar_one()
    assert shown == "5min"
