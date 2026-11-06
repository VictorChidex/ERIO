"""Raw payload storage in S3 (S3Mock locally), kept so any crawl can be replayed.

A posting's payload is stored once per distinct content: the key ends in the
content hash, so an unchanged posting re-crawled every 15 minutes costs no
new object.
"""

import gzip
import json
from typing import Any, Protocol

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from erio_core.schemas import RawPosting
from erio_core.settings import Settings


class RawStore(Protocol):
    def put_posting(self, posting: RawPosting) -> str: ...

    def get_posting(self, key: str) -> dict[str, Any]: ...


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
