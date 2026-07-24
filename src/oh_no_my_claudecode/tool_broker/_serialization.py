"""Canonical serialization shared by signed and hash-chained records."""

from __future__ import annotations

import json


def canonical_json_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
