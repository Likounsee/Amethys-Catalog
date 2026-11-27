#!/usr/bin/env python3
"""Validate the public compact catalogue before publishing it."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import zstandard

try:
    # Works when invoked as a module from the repository root.
    from scripts.build_igdb_catalog_db import STORE_URL_HOSTS, is_valid_cover_url, is_valid_store_url
except ModuleNotFoundError:
    # Direct script execution puts scripts/, not the repository root, on sys.path.
    from build_igdb_catalog_db import STORE_URL_HOSTS, is_valid_cover_url, is_valid_store_url

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_schema_version"] == 2
    assert manifest["game_count"] > 0
    assert manifest["shards"]["game_count"] == manifest["game_count"]
    assert manifest.get("promotion_count", 0) >= 0

    index_meta = manifest["search_index"]
    index_path = PUBLIC / index_meta["file"]
    index_bytes = index_path.read_bytes()
    assert len(index_bytes) == index_meta["compressed_size"]
    assert sha256(index_bytes) == index_meta["compressed_sha256"]
    index = json.loads(zstandard.ZstdDecompressor().decompress(index_bytes))
    assert len(index) == manifest["game_count"]
    ids = [int(item[0]) for item in index]
    search_promotions: dict[int, list[dict]] = {}
    assert len(ids) == len(set(ids)), "duplicate Amethys IDs in search index"
    for row in index:
        assert isinstance(row, list) and 4 <= len(row) <= 6, (
            "search index rows must contain identity, title, slug, genres, optional cover and promotions"
        )
        assert isinstance(row[1], str) and row[1].strip(), (
            f"search index row {row[0]} has an empty title"
        )
        assert isinstance(row[3], list), (
            f"search index row {row[0]} has invalid genres"
        )
        if len(row) >= 5 and row[4] is not None:
            assert isinstance(row[4], str) and is_valid_cover_url(row[4]), (
                f"search index row {row[0]} has an invalid cover URL"
            )
        promotions = row[5] if len(row) == 6 else []
        assert isinstance(promotions, list), f"search index row {row[0]} has invalid promotions"
        search_promotions[int(row[0])] = promotions

    shard_total = 0
    shard_ids = set()
    verified_store_identities = 0
    verified_source_identities = 0
    verified_promotions = 0
    shard_promotions: dict[int, list[dict]] = {}
    for item in manifest["shards"]["files"]:
        path = PUBLIC / item["file"]
        compressed = path.read_bytes()
        assert len(compressed) == item["compressed_size"], item["file"]
        assert sha256(compressed) == item["compressed_sha256"], item["file"]
        records = json.loads(zstandard.ZstdDecompressor().decompress(compressed))
        assert len(records) == item["game_count"], item["file"]
        for record in records:
            game_id = int(record["amethys_id"])
            cover_url = record.get("cover_url")
            assert cover_url is None or (
                isinstance(cover_url, str) and is_valid_cover_url(cover_url)
            ), f"game {game_id} has an invalid cover URL"
            stores = record.get("stores", [])
            assert isinstance(stores, list), (
                f"game {game_id} has an invalid store identity list"
            )
            for store in stores:
                assert isinstance(store, dict), (
                    f"game {game_id} has an invalid store identity record"
                )
                store_name = store.get("store")
                assert isinstance(store_name, str) and store_name in STORE_URL_HOSTS, (
                    f"game {game_id} has an unsupported store identity"
                )
                store_url = store.get("url")
                assert store_url is None or (
                    isinstance(store_url, str)
                    and is_valid_store_url(store_url, store_name)
                ), f"game {game_id} has an invalid store URL for {store_name}"
            verified_store_identities += len(stores)
            promotions = record.get("promotions", [])
            assert isinstance(promotions, list), f"game {game_id} has invalid promotions"
            known_store_products = {
                (store.get("store"), store.get("external_id")): store.get("url")
                for store in stores
            }
            for promotion in promotions:
                assert isinstance(promotion, dict), f"game {game_id} has an invalid promotion"
                assert promotion.get("store") in STORE_URL_HOSTS, f"game {game_id} has an unsupported promotion store"
                assert isinstance(promotion.get("external_id"), str) and promotion["external_id"], f"game {game_id} has an invalid promotion product ID"
                assert known_store_products.get((promotion["store"], promotion["external_id"])) == promotion.get("source_url"), f"game {game_id} promotion is not tied to its official store identity"
                current_price = promotion.get("current_price_minor")
                regular_price = promotion.get("regular_price_minor")
                assert isinstance(current_price, int) and not isinstance(current_price, bool) and current_price >= 0, f"game {game_id} has an invalid current price"
                assert isinstance(regular_price, int) and not isinstance(regular_price, bool) and regular_price > current_price, f"game {game_id} has an invalid regular price"
                currency = promotion.get("currency")
                assert isinstance(currency, str) and len(currency) == 3 and currency.isascii() and currency.isalpha() and currency == currency.upper(), f"game {game_id} has an invalid currency"
                assert is_valid_store_url(promotion.get("source_url", ""), promotion["store"]), f"game {game_id} has an invalid promotion source URL"
                for timestamp in ("valid_from", "valid_until", "checked_at"):
                    value = promotion.get(timestamp)
                    assert isinstance(value, str) and value.endswith("Z"), f"game {game_id} promotion has invalid {timestamp}"
                    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                    assert parsed.utcoffset() == dt.timedelta(0), f"game {game_id} promotion {timestamp} must be UTC"
                assert promotion["valid_until"] > promotion["valid_from"], f"game {game_id} has an invalid promotion window"
                verified_promotions += 1
            shard_promotions[game_id] = promotions
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
    assert verified_promotions == manifest.get("promotion_count", 0), (
        "manifest promotion count does not match detail shards"
    )
    assert search_promotions == shard_promotions, "search index and detail shards disagree on promotions"
    genres_meta = manifest["metadata"]["genres"]
    genres_path = PUBLIC / genres_meta["file"]
    genres_bytes = genres_path.read_bytes()
    assert sha256(genres_bytes) == genres_meta["sha256"]
    print(
        f"Validated {len(ids)} games, {len(manifest['shards']['files'])} shards "
        f"and {manifest['store_identity_count']} store identities "
        f"plus {manifest['source_identity_count']} source identities and "
        f"{verified_promotions} verified promotions."
    )


if __name__ == "__main__":
    main()
