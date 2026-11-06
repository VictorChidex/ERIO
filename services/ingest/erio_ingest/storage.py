"""Raw payload storage, kept so any crawl can be replayed.

In the cloud payloads live in S3. On the local stack they are plain files on a volume
(``ERIO_RAW_STORE_DIR``): a fake S3 server slowed to seconds per request at tens of
thousands of objects, and files need no extra service and no credentials. Both are
addressed by the same keys, so a database row points at either.

A posting's payload is stored once per distinct content: the key ends in the
content hash, so an unchanged posting re-crawled every 15 minutes costs no
new object.
"""

import gzip
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from erio_core.schemas import RawPosting
from erio_core.settings import Settings


class RawStore(Protocol):
    def put_posting(self, posting: RawPosting) -> str: ...

    def get_posting(self, key: str) -> dict[str, Any]: ...


# How many payloads are read or written at a time; object storage answers slowly one by one.
STORE_WORKERS = 8


def posting_key(posting: RawPosting) -> str:
    return f"postings/{posting.source_slug}/{posting.external_id}/{posting.content_hash}.json.gz"


def _encode(payload: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _decode(blob: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(gzip.decompress(blob))
    return payload


class S3RawStore:
    def __init__(self, settings: Settings):
        config = Config(
            signature_version=UNSIGNED if settings.s3_unsigned else None,
            connect_timeout=settings.s3_connect_timeout_s,
            read_timeout=settings.s3_read_timeout_s,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self.bucket = settings.raw_bucket
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint_url, config=config, region_name="us-east-1"
        )

    def put_posting(self, posting: RawPosting) -> str:
        key = posting_key(posting)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=_encode(posting.payload),
            ContentType="application/json",
            ContentEncoding="gzip",
        )
        return key

    def get_posting(self, key: str) -> dict[str, Any]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return _decode(response["Body"].read())


class MemoryRawStore:
    """In-memory store for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_posting(self, posting: RawPosting) -> str:
        key = posting_key(posting)
        self.objects[key] = _encode(posting.payload)
        return key

    def get_posting(self, key: str) -> dict[str, Any]:
        return _decode(self.objects[key])


class FileRawStore:
    """Payloads as files under one directory, for the local stack."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        # Each key segment is percent-encoded and may not start with a dot, so no key, however
        # odd its external id, can name a place outside ``root`` or collide with another key.
        parts = [quote(part, safe="") for part in key.split("/")]
        parts = [("%2E" + part[1:]) if part.startswith(".") else part for part in parts]
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError(f"not a storable key: {key!r}")
        return path

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the target and renamed into place, so a reader never sees half a file.
        temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        temp.write_bytes(data)
        os.replace(temp, path)

    def put_posting(self, posting: RawPosting) -> str:
        key = posting_key(posting)
        self.put_bytes(key, _encode(posting.payload))
        return key

    def get_posting(self, key: str) -> dict[str, Any]:
        return _decode(self._path(key).read_bytes())

    def has(self, key: str) -> bool:
        return self._path(key).exists()


def make_store(settings: Settings) -> RawStore:
    """Files when ``raw_store_dir`` is set (the local stack), S3 otherwise."""
    if settings.raw_store_dir:
        return FileRawStore(settings.raw_store_dir)
    return S3RawStore(settings)


def import_s3mock_tree(source: Path, store: FileRawStore, bucket: str = "erio-raw") -> int:
    """Copy the objects of an S3Mock data directory into ``store``, keeping every key.

    S3Mock keeps each object as ``<bucket>/<id>/binaryData`` beside an ``objectMetadata.json``
    that names its key. Objects already in ``store`` are left alone, so it can run twice.
    Returns how many objects were copied.
    """
    copied = 0
    for metadata in sorted((source / bucket).glob("*/objectMetadata.json")):
        key = json.loads(metadata.read_text(encoding="utf-8"))["key"]
        if store.has(key):
            continue
        store.put_bytes(key, (metadata.parent / "binaryData").read_bytes())
        copied += 1
    return copied


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "import-s3mock":
        copied = import_s3mock_tree(Path(argv[2]), FileRawStore(argv[3]))
        print(f"copied {copied} objects")
        return 0
    print("usage: python -m erio_ingest.storage import-s3mock <s3mock data dir> <target dir>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
