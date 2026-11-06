"""The shared OpenSearch client keeps a connection per API request thread."""

from erio_core.search.index import client


def test_pool_holds_a_connection_for_each_api_request_thread() -> None:
    # With urllib3's default of one, every concurrent request opened a new
    # connection and dropped it (the 200 requests per second load test).
    connection = client().transport.connection_pool.connections[0]
    assert connection.pool.pool.maxsize == 40
