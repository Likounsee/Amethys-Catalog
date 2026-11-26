"""Focused regression tests for URLs emitted by the public catalogue builder."""
from __future__ import annotations

import unittest

from scripts.build_igdb_catalog_db import (
    is_valid_cover_url,
    is_valid_store_url,
    store_record,
)


class StoreUrlValidationTests(unittest.TestCase):
    def test_accepts_https_store_urls(self) -> None:
        for value in (
            "https://store.steampowered.com/app/570/",
            "https://www.gog.com/game/example",
            "https://store.epicgames.com/p/example",
            "https://www.ea.com/games/example",
            "https://store.ubisoft.com/game/example",
            "https://us.shop.battle.net/en-us/product/example",
            "https://gaming.amazon.com/",
            "https://www.humblebundle.com/store/example",
            "https://example.com:443/product?id=42",
        ):
            with self.subTest(value=value):
                self.assertTrue(is_valid_store_url(value))

    def test_store_urls_must_match_the_declared_provider(self) -> None:
        valid = {
            "steam": "https://store.steampowered.com/app/570/",
            "gog": "https://www.gog.com/game/example",
            "epic": "https://store.epicgames.com/p/example",
            "ea": "https://www.ea.com/games/example",
            "ubisoft": "https://store.ubisoft.com/game/example",
            "battle-net": "https://us.shop.battle.net/en-us/product/example",
            "amazon-games": "https://gaming.amazon.com/",
            "humble": "https://www.humblebundle.com/store/example",
        }
        for store, url in valid.items():
            with self.subTest(store=store):
                self.assertTrue(is_valid_store_url(url, store))
                self.assertFalse(is_valid_store_url("https://attacker.example/game", store))

    def test_rejects_unsafe_or_malformed_store_urls(self) -> None:
        for value in (
            "http://store.steampowered.com/app/570/",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "//store.steampowered.com/app/570/",
            "https://user:password@example.com/game",
            "https://@example.com/game",
            "https://example.com:8443/game",
            "https://example.com/line\nbreak",
            "https://example.com\\@evil.example/game",
            "https://[invalid-ipv6/game",
            "https://example.com/" + "a" * 2048,
        ):
            with self.subTest(value=value):
                self.assertFalse(is_valid_store_url(value))

    def test_accepts_only_the_igdb_cover_host(self) -> None:
        self.assertTrue(
            is_valid_cover_url(
                "https://images.igdb.com/igdb/image/upload/t_cover_big/abc.jpg"
            )
        )
        for value in (
            "https://example.com/abc.jpg",
            "https://images.igdb.com.evil.example/abc.jpg",
            "http://images.igdb.com/abc.jpg",
            "https://user@images.igdb.com/abc.jpg",
            "https://images.igdb.com:8443/abc.jpg",
            "https://images.igdb.com/line\nbreak",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_valid_cover_url(value))


class StoreRecordTests(unittest.TestCase):
    def test_keeps_supported_store_with_valid_official_url(self) -> None:
        result = store_record(
            {"name": "Example Game"},
            {
                "external_game_source": {"name": "Steam"},
                "uid": "570",
                "name": "Dota 2",
                "url": "https://store.steampowered.com/app/570/",
            },
        )
        self.assertEqual(
            result,
            ("steam", "570", "Dota 2", "https://store.steampowered.com/app/570/"),
        )

    def test_builds_steam_url_when_provider_url_is_missing(self) -> None:
        result = store_record(
            {"name": "Dota 2"},
            {"external_game_source": {"name": "Steam"}, "uid": "570"},
        )
        self.assertEqual(
            result,
            ("steam", "570", "Dota 2", "https://store.steampowered.com/app/570/"),
        )

    def test_rejects_invalid_store_urls_without_fallback(self) -> None:
        for url in (
            "http://store.steampowered.com/app/570/",
            "https://attacker.example/game",
            "https://user@store.steampowered.com/app/570/",
            "https://store.steampowered.com:8443/app/570/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(
                    store_record(
                        {"name": "Dota 2"},
                        {
                            "external_game_source": {"name": "Steam"},
                            "uid": "123",
                            "url": url,
                        },
                    )
                )

    def test_store_record_rejects_cross_provider_domain(self) -> None:
        result = store_record(
            {"name": "Example Game"},
            {
                "external_game_source": {"name": "GOG"},
                "uid": "123",
                "name": "Example Game",
                "url": "https://store.steampowered.com/app/123/",
            },
        )
        self.assertIsNone(result)

    def test_only_numeric_steam_ids_get_generated_urls(self) -> None:
        self.assertIsNone(
            store_record(
                {"name": "Game"},
                {"external_game_source": {"name": "Steam"}, "uid": "not-a-number"},
            )
        )

    def test_unsupported_stores_are_not_published(self) -> None:
        for name in ("itch.io", "Unknown Store"):
            with self.subTest(name=name):
                self.assertIsNone(
                    store_record(
                        {"name": "Game"},
                        {
                            "external_game_source": {"name": name},
                            "uid": "123",
                            "url": "https://example.com/game",
                        },
                    )
                )


if __name__ == "__main__":
    unittest.main()
