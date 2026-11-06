import json
from pathlib import Path

import pytest

from erio_core.schemas import RawPosting
from erio_core.settings import Settings
from erio_ingest.storage import (
    FileRawStore,
    S3RawStore,
    _encode,
    import_s3mock_tree,
    make_store,
    posting_key,
)


def posting(external_id: str = "123", **payload: object) -> RawPosting:
    return RawPosting(
        source_slug="greenhouse",
        board_token="acme",
        external_id=external_id,
        payload=payload or {"title": "Engineer"},
    )


def test_the_s3_client_gives_up_on_a_stalled_store_and_retries() -> None:
    store = S3RawStore(Settings(s3_connect_timeout_s=3.0, s3_read_timeout_s=11.0))

    config = store.client.meta.config
    assert (config.connect_timeout, config.read_timeout) == (3.0, 11.0)
    assert config.retries == {"mode": "standard", "total_max_attempts": 4}  # three retries


def test_a_payload_survives_a_round_trip_through_files(tmp_path: Path) -> None:
    store = FileRawStore(tmp_path)

    key = store.put_posting(posting(title="Nurse", pay="fair"))

    assert key == posting_key(posting(title="Nurse", pay="fair"))
    assert store.get_posting(key) == {"title": "Nurse", "pay": "fair"}


def test_a_stored_payload_is_replaced_whole_and_leaves_no_temp_files(tmp_path: Path) -> None:
    store = FileRawStore(tmp_path)
    key = store.put_posting(posting(title="A"))

    store.put_bytes(key, _encode({"title": "B"}))

    assert store.get_posting(key) == {"title": "B"}
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize(
    "external_id", ["../../outside", "a/../../b", "..", ".hidden", "with space/and:colon", "x" * 20]
)
def test_no_external_id_can_write_outside_the_store(tmp_path: Path, external_id: str) -> None:
    root = tmp_path / "raw"
    store = FileRawStore(root)

    key = store.put_posting(posting(external_id))

    assert store.get_posting(key) == {"title": "Engineer"}
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written and all(p.resolve().is_relative_to(root.resolve()) for p in written)


def test_different_keys_never_share_a_file(tmp_path: Path) -> None:
    store = FileRawStore(tmp_path)

    first = store.put_posting(posting("a/b", title="one"))
    second = store.put_posting(posting("a%2Fb", title="two"))

    assert store.get_posting(first) == {"title": "one"}
    assert store.get_posting(second) == {"title": "two"}


def test_a_missing_payload_is_an_error_not_an_empty_result(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FileRawStore(tmp_path).get_posting("postings/greenhouse/none/0.json.gz")


def test_the_store_is_files_when_a_directory_is_set_and_s3_otherwise(tmp_path: Path) -> None:
    assert isinstance(make_store(Settings(raw_store_dir=str(tmp_path))), FileRawStore)
    assert isinstance(make_store(Settings(raw_store_dir=None)), S3RawStore)


def s3mock_tree(root: Path, objects: dict[str, dict[str, object]]) -> None:
    """The layout S3Mock keeps on disk: <bucket>/<id>/binaryData and objectMetadata.json."""
    for n, (key, payload) in enumerate(objects.items()):
        folder = root / "erio-raw" / f"00000000-0000-0000-0000-{n:012d}"
        folder.mkdir(parents=True)
        (folder / "binaryData").write_bytes(_encode(payload))
        (folder / "objectMetadata.json").write_text(json.dumps({"id": folder.name, "key": key}))


def test_objects_of_an_s3mock_directory_are_imported_under_their_keys(tmp_path: Path) -> None:
    objects = {
        "postings/lever/1/aa.json.gz": {"title": "One"},
        "postings/workday/a/b/2/bb.json.gz": {"title": "Two"},
    }
    s3mock_tree(tmp_path / "s3", objects)
    store = FileRawStore(tmp_path / "raw")

    assert import_s3mock_tree(tmp_path / "s3", store) == 2

    assert store.get_posting("postings/lever/1/aa.json.gz") == {"title": "One"}
    assert store.get_posting("postings/workday/a/b/2/bb.json.gz") == {"title": "Two"}
    assert import_s3mock_tree(tmp_path / "s3", store) == 0  # a second run copies nothing
