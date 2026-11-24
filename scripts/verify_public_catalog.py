#!/usr/bin/env python3
"""Validate the public compact catalogue before publishing it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_schema_version"] == 2
    assert manifest["game_count"] > 0
    assert manifest["shards"]["game_count"] == manifest["game_count"]

    index_meta = manifest["search_index"]
    index_path = PUBLIC / index_meta["file"]
    index_bytes = index_path.read_bytes()
    assert len(index_bytes) == index_meta["compressed_size"]
    assert sha256(index_bytes) == index_meta["compressed_sha256"]
    index = json.loads(zstandard.ZstdDecompressor().decompress(index_bytes))
    assert len(index) == manifest["game_count"]
    ids = [int(item[0]) for item in index]
    assert len(ids) == len(set(ids)), "duplicate Amethys IDs in search index"

    shard_total = 0
    shard_ids = set()
    verified_store_identities = 0
    verified_source_identities = 0
    for item in manifest["shards"]["files"]:
        path = PUBLIC / item["file"]
        compressed = path.read_bytes()
        assert len(compressed) == item["compressed_size"], item["file"]
        assert sha256(compressed) == item["compressed_sha256"], item["file"]
        records = json.loads(zstandard.ZstdDecompressor().decompress(compressed))
        assert len(records) == item["game_count"], item["file"]
        for record in records:
            game_id = int(record["amethys_id"])
            stores = record.get("stores", [])
            assert isinstance(stores, list), (
                f"game {game_id} has an invalid store identity list"
            )
            verified_store_identities += len(stores)
            source_ids = record.get("source_ids", [])
            assert isinstance(source_ids, list), (
                f"game {game_id} has an invalid source identity list"
            )
            seen_source_ids = set()
            for source_id in source_ids:
                assert isinstance(source_id, dict), (
                    f"game {game_id} has an invalid source identity record"
                )
                source = source_id.get("source")
                external_id = source_id.get("external_id")
                assert isinstance(source, str) and source, (
                    f"game {game_id} has an empty source namespace"
                )
                assert isinstance(external_id, str) and external_id, (
                    f"game {game_id} has an empty external identity"
                )
                identity = (source, external_id)
                assert identity not in seen_source_ids, (
                    f"game {game_id} repeats source identity {identity}"
                )
                seen_source_ids.add(identity)
            verified_source_identities += len(source_ids)
            assert game_id // manifest["shards"]["bucket_size"] == item["bucket"]
            assert game_id not in shard_ids, f"duplicate game ID {game_id}"
            shard_ids.add(game_id)
        shard_total += len(records)

    assert shard_total == manifest["game_count"]
    assert shard_ids == set(ids), "search index and detail shards disagree"
    assert verified_store_identities == manifest["store_identity_count"], (
        "manifest store identity count does not match detail shards"
    )
    assert verified_source_identities == manifest["source_identity_count"], (
        "manifest source identity count does not match detail shards"
    )
    genres_meta = manifest["metadata"]["genres"]
    genres_path = PUBLIC / genres_meta["file"]
    genres_bytes = genres_path.read_bytes()
    assert sha256(genres_bytes) == genres_meta["sha256"]
    print(
        f"Validated {len(ids)} games, {len(manifest['shards']['files'])} shards "
        f"and {manifest['store_identity_count']} store identities "
        f"plus {manifest['source_identity_count']} source identities."
    )


if __name__ == "__main__":
    main()
