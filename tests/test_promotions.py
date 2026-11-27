#!/usr/bin/env python3
"""Regression tests for the manually curated official promotion feed."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_igdb_catalog_db as builder


class PromotionFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.feed_path = Path(self.directory.name) / "promotions.json"
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(Path(builder.SCHEMA_PATH).read_text(encoding="utf-8"))
        self.connection.execute(
            "INSERT INTO games(amethys_id, igdb_id, name, updated_at) VALUES (1001, 1, 'Example', '2026-11-27T00:00:00Z')"
        )
        self.connection.execute(
            """INSERT INTO game_stores(amethys_id, store, external_id, store_name, store_url)
               VALUES (1001, 'steam', '570', 'Dota 2', 'https://store.steampowered.com/app/570/')"""
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.directory.cleanup()

    def offer(self) -> dict:
        return {
            "promotion_id": "steam-570-autumn-2026",
            "amethys_id": 1001,
            "store": "steam",
            "external_id": "570",
            "current_price_minor": 1250,
            "regular_price_minor": 2500,
            "currency": "EUR",
            "valid_from": "2026-11-26T00:00:00Z",
            "valid_until": "2026-12-01T00:00:00Z",
            "checked_at": "2026-11-27T00:00:00Z",
            "source_url": "https://store.steampowered.com/app/570/",
        }

    def write_feed(self, offers: list[dict]) -> None:
        self.feed_path.write_text(
            json.dumps({"schema_version": 1, "offers": offers}),
            encoding="utf-8",
        )

    def test_imports_only_promotion_matching_official_catalogue_identity(self) -> None:
        self.write_feed([self.offer()])
        with patch.object(builder, "PROMOTIONS_PATH", self.feed_path):
            count = builder.import_store_promotions(
                self.connection, "2026-11-27T12:00:00+00:00"
            )
        self.assertEqual(count, 1)
        row = self.connection.execute(
            "SELECT current_price_minor, regular_price_minor, currency FROM store_promotions"
        ).fetchone()
        self.assertEqual(row, (1250, 2500, "EUR"))

    def test_rejects_price_that_is_not_a_discount(self) -> None:
        offer = self.offer()
        offer["regular_price_minor"] = offer["current_price_minor"]
        self.write_feed([offer])
        with patch.object(builder, "PROMOTIONS_PATH", self.feed_path):
            with self.assertRaisesRegex(ValueError, "regular price must exceed"):
                builder.import_store_promotions(
                    self.connection, "2026-11-27T12:00:00+00:00"
                )

    def test_rejects_store_product_not_linked_to_game(self) -> None:
        offer = self.offer()
        offer["external_id"] = "999999"
        self.write_feed([offer])
        with patch.object(builder, "PROMOTIONS_PATH", self.feed_path):
            with self.assertRaisesRegex(ValueError, "does not match a known"):
                builder.import_store_promotions(
                    self.connection, "2026-11-27T12:00:00+00:00"
                )

    def test_rejects_non_official_source_url(self) -> None:
        offer = self.offer()
        offer["source_url"] = "https://example.com/fake-sale"
        self.write_feed([offer])
        with patch.object(builder, "PROMOTIONS_PATH", self.feed_path):
            with self.assertRaisesRegex(ValueError, "valid official"):
                builder.import_store_promotions(
                    self.connection, "2026-11-27T12:00:00+00:00"
                )

    def test_rejects_duplicate_products(self) -> None:
        self.write_feed([self.offer(), self.offer() | {"promotion_id": "duplicate"}])
        with patch.object(builder, "PROMOTIONS_PATH", self.feed_path):
            with self.assertRaisesRegex(ValueError, "Multiple current promotion"):
                builder.import_store_promotions(
                    self.connection, "2026-11-27T12:00:00+00:00"
                )


if __name__ == "__main__":
    unittest.main()
