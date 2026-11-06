from erio_core.settings import Settings
from erio_ingest.storage import S3RawStore


def test_the_s3_client_gives_up_on_a_stalled_store_and_retries() -> None:
    store = S3RawStore(Settings(s3_connect_timeout_s=3.0, s3_read_timeout_s=11.0))

    config = store.client.meta.config
    assert (config.connect_timeout, config.read_timeout) == (3.0, 11.0)
    assert config.retries == {"mode": "standard", "total_max_attempts": 4}  # three retries
