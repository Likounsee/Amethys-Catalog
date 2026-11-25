#!/usr/bin/env python3
"""Build the public, compressed Amethys PC master catalogue from IGDB.

Secrets are read only from the process environment and are never written to the
database, logs, generated files, or GitHub Release assets.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "scripts" / "catalog_schema.sql"
MASTER_JSON = ROOT / "catalogs" / "master-games-v1.json"
REGISTRY_PATH = ROOT / "catalogs" / "amethys-id-registry.json"
DB_PATH = ROOT / "catalog.db"
COMPRESSED_PATH = ROOT / "catalog.db.zst"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_ROOT = "https://api.igdb.com/v4"
PAGE_SIZE = 500
MAX_RETRIES = 6
WINDOWS_PC_PLATFORM_ID = 6

# Only stores that Amethys currently exposes as supported platform identities.
# itch.io is intentionally excluded. Unrecognized IGDB sources are ignored.
STORE_NAMES = {
    "steam": "steam",
    "gog": "gog",
    "epic games store": "epic",
    "epic game store": "epic",
    "epic games": "epic",
    "ea app": "ea",
    "origin": "ea",
    "ubisoft connect": "ubisoft",
    "ubisoft store": "ubisoft",
    "battle.net": "battle-net",
    "blizzard shop": "battle-net",
    "amazon games": "amazon-games",
    "humble store": "humble",
}


def http_request(url: str, *, data: bytes | None = None,
                 headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"IGDB/Twitch HTTP {error.code}; response body suppressed to protect credentials") from None
            retry_after = error.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else min(2 ** attempt, 30))
        except (urllib.error.URLError, TimeoutError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("IGDB request retry limit reached")


def get_token(client_id: str, client_secret: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    })
    payload = json.loads(http_request(
        f"{TOKEN_URL}?{query}", data=b"",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ))
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Twitch OAuth response has no access_token")
    return token


def igdb_query(body: str, client_id: str, token: str) -> list[dict]:
    payload = http_request(f"{API_ROOT}/games", data=body.encode("utf-8"), headers={
        "Client-ID": client_id,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "text/plain",
    })
    decoded = json.loads(payload)
    if not isinstance(decoded, list):
        raise RuntimeError("Unexpected IGDB response (expected an array)")
    return decoded


def split_source_identity_key(value: str) -> tuple[str, str] | None:
    """Split a persisted source key at its final separator.

    Source namespaces may contain a colon (for example store:steam), so
    splitting at the first colon would silently lose the complete namespace.
    """
    source, separator, external_id = str(value).rpartition(":")
    if not separator or not source or not external_id:
        return None
    return source, external_id


def load_identity_state() -> tuple[
    dict[int, int], set[int], dict[tuple[str, str], int], dict[tuple[str, str], int]
]:
    registry = {
        "igdb_to_amethys_id": {},
        "source_to_amethys_id": {},
        "retired_or_known_ids": [],
    }
    if REGISTRY_PATH.exists():
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    igdb_to_amethys = {
        int(key): int(value)
        for key, value in registry.get("igdb_to_amethys_id", {}).items()
    }
    source_ids: dict[tuple[str, str], int] = {}
    for key, value in registry.get("source_to_amethys_id", {}).items():
        identity = split_source_identity_key(str(key))
        if identity is not None:
            source_ids[identity] = int(value)
    for igdb_id, amethys_id in igdb_to_amethys.items():
        source_ids.setdefault(("igdb", str(igdb_id)), amethys_id)

    known_ids = {int(value) for value in registry.get("retired_or_known_ids", [])}
    previous_external: dict[tuple[str, str], int] = {}

    # Preserve the IDs already shipped in the small seed catalogue on first run.
    if MASTER_JSON.exists():
        previous = json.loads(MASTER_JSON.read_text(encoding="utf-8"))
        for game in previous.get("games", []):
            amethys_id = int(game["amethys_id"])
            known_ids.add(amethys_id)
            raw_igdb_id = game.get("igdb_id")
            if raw_igdb_id is None and str(game.get("id", "")).startswith("igdb-"):
                try:
                    raw_igdb_id = int(game["id"][5:])
                except ValueError:
                    raw_igdb_id = None
            if raw_igdb_id is not None:
                igdb_to_amethys.setdefault(int(raw_igdb_id), amethys_id)
                source_ids.setdefault(("igdb", str(raw_igdb_id)), amethys_id)
            for offer in game.get("offers", []):
                provider = str(offer.get("provider_id", "")).lower()
                external_id = str(offer.get("external_id", "")).strip()
                if provider in ("steam", "gog", "epic", "epic-games") and external_id:
                    store = "epic" if provider == "epic-games" else provider
                    previous_external[(store, external_id)] = amethys_id
                    source_ids.setdefault((f"store:{store}", external_id), amethys_id)

    known_ids.update(igdb_to_amethys.values())
    known_ids.update(source_ids.values())
    return igdb_to_amethys, known_ids, previous_external, source_ids


def store_record(game: dict, external: dict) -> tuple[str, str, str, str] | None:
    source = external.get("external_game_source") or {}
    source_name = str(source.get("name", "")).strip().lower()
    store = STORE_NAMES.get(source_name)
    if not store:  # includes itch.io and sources we do not support
        return None
    external_id = str(external.get("uid") or "").strip()
    if not external_id:
        return None
    url = external.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        if store == "steam" and external_id.isdigit():
            url = f"https://store.steampowered.com/app/{external_id}/"
        else:
            return None
    name = str(external.get("name") or game.get("name") or "").strip()
    return store, external_id, name, url


def main() -> None:
    client_id = os.environ.get("IGDB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("IGDB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("Missing IGDB_CLIENT_ID / IGDB_CLIENT_SECRET environment secrets")

    igdb_to_amethys, known_ids, previous_external, source_ids = load_identity_state()
    next_amethys_id = max(known_ids | {1_000_000}) + 1
    token = get_token(client_id, client_secret)
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    DB_PATH.unlink(missing_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    inserted_games = 0
    inserted_stores = 0
    skipped_duplicate_store_ids = 0
    last_igdb_id = 0
    fields = (
        "id,name,category,version_parent,slug,summary,first_release_date,cover.image_id,genres.name,"
        "external_games.uid,external_games.name,external_games.url,"
        "external_games.external_game_source.name"
    )

    try:
        while True:
            # Keyset pagination avoids IGDB offset ceilings and remains stable
            # when the catalogue is larger than 10,000 records.
            query = (
                f"fields {fields}; "
                # Keep the array-valued platform predicate at the API boundary,
                # then filter the enum-valued category locally. This avoids an
                # empty catalogue if IGDB's combined predicate yields no rows.
                f"where platforms = ({WINDOWS_PC_PLATFORM_ID}) "
                f"& id > {last_igdb_id}; "
                f"sort id asc; limit {PAGE_SIZE};"
            )
            page = igdb_query(query, client_id, token)
            if not page:
                break

            fetched_count = len(page)
            with connection:
                for game in page:
                    igdb_id = int(game["id"])
                    last_igdb_id = max(last_igdb_id, igdb_id)
                    # IGDB category 0 is a main game. Null is accepted as the
                    # default category; DLC and other secondary entries are skipped.
                    category = game.get("category")
                    if category not in (None, 0) or game.get("version_parent") is not None:
                        continue
                    name = str(game.get("name") or "").strip()
                    if not name:
                        continue

                    # Store identities enrich a game record but are optional:
                    # the master catalogue also indexes games with no known offer.
                    store_rows = []
                    seen_store_keys: set[tuple[str, str]] = set()
                    for external in game.get("external_games") or []:
                        record = store_record(game, external)
                        if not record:
                            continue
                        store, external_id, _store_name, _url = record
                        store_key = (store, external_id)
                        if store_key in seen_store_keys or connection.execute(
                            "SELECT 1 FROM game_stores WHERE store = ? AND external_id = ?",
                            store_key,
                        ).fetchone():
                            skipped_duplicate_store_ids += 1
                            continue
                        seen_store_keys.add(store_key)
                        store_rows.append(record)

                    amethys_id = igdb_to_amethys.get(igdb_id)
                    if amethys_id is None:
                        amethys_id = source_ids.get(("igdb", str(igdb_id)))
                    if amethys_id is None:
                        for store, external_id, _store_name, _url in store_rows:
                            amethys_id = source_ids.get((f"store:{store}", external_id))
                            if amethys_id is None:
                                amethys_id = previous_external.get((store, external_id))
                            if amethys_id is not None:
                                break
                    if amethys_id is None:
                        while next_amethys_id in known_ids:
                            next_amethys_id += 1
                        amethys_id = next_amethys_id
                        next_amethys_id += 1
                    if amethys_id in known_ids and igdb_id not in igdb_to_amethys:
                        # A legacy ID can be reused only when matched by an
                        # existing store identity; otherwise allocate a fresh ID.
                        matched = any(
                            source_ids.get((f"store:{store}", external_id), previous_external.get((store, external_id))) == amethys_id
                            for store, external_id, _n, _u in store_rows
                        ) or source_ids.get(("igdb", str(igdb_id))) == amethys_id
                        if not matched:
                            while next_amethys_id in known_ids:
                                next_amethys_id += 1
                            amethys_id = next_amethys_id
                            next_amethys_id += 1

                    accepted_store_rows = []
                    for store_row in store_rows:
                        store, external_id, _store_name, _url = store_row
                        previous_id = source_ids.get(
                            (f"store:{store}", external_id),
                            previous_external.get((store, external_id)),
                        )
                        if previous_id is not None and previous_id != amethys_id:
                            skipped_duplicate_store_ids += 1
                            continue
                        accepted_store_rows.append(store_row)
                    store_rows = accepted_store_rows

                    igdb_to_amethys[igdb_id] = amethys_id
                    source_ids[("igdb", str(igdb_id))] = amethys_id
                    for store, external_id, _store_name, _url in store_rows:
                        source_ids[(f"store:{store}", external_id)] = amethys_id
                    known_ids.add(amethys_id)
                    release_timestamp = game.get("first_release_date")
                    release_date = (
                        dt.datetime.fromtimestamp(release_timestamp, tz=dt.timezone.utc)
                        .date().isoformat()
                        if isinstance(release_timestamp, (int, float)) else None
                    )
                    cover_id = (game.get("cover") or {}).get("image_id")
                    cover_url = (
                        f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover_id}.jpg"
                        if cover_id else None
                    )
                    genres = sorted({
                        str(item.get("name", "")).strip()
                        for item in game.get("genres", []) if item.get("name")
                    })
                    connection.execute(
                        """INSERT INTO games
                           (amethys_id, igdb_id, name, slug, summary, release_date,
                            cover_url, genres_json, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (amethys_id, igdb_id, name, game.get("slug"), game.get("summary"),
                         release_date, cover_url, json.dumps(genres, ensure_ascii=False),
                         generated_at),
                    )
                    connection.execute(
                        "INSERT INTO game_source_ids(source, external_id, amethys_id) VALUES (?, ?, ?)",
                        ("igdb", str(igdb_id), amethys_id),
                    )
                    inserted_games += 1

                    for store, external_id, store_name, store_url in store_rows:
                        try:
                            connection.execute(
                                "INSERT INTO game_source_ids(source, external_id, amethys_id) VALUES (?, ?, ?)",
                                (f"store:{store}", external_id, amethys_id),
                            )
                            connection.execute(
                                """INSERT INTO game_stores
                                   (amethys_id, store, external_id, store_name, store_url)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (amethys_id, store, external_id, store_name, store_url),
                            )
                            inserted_stores += 1
                        except sqlite3.IntegrityError:
                            # IGDB can expose one external product against more
                            # than one record; never create an ambiguous mapping.
                            skipped_duplicate_store_ids += 1

            print(
                f"IGDB cursor={last_igdb_id}; games={inserted_games}; "
                f"store IDs={inserted_stores}",
                file=sys.stderr,
            )
            if fetched_count < PAGE_SIZE:
                break
            time.sleep(0.30)  # IGDB limit: 4 requests/second.

        if inserted_games == 0:
            raise RuntimeError(
                "IGDB returned no main games for Windows platform "
                f"{WINDOWS_PC_PLATFORM_ID}; the platform query completed but matched "
                "zero records. Refusing to publish an empty catalogue."
            )

        connection.executemany(
            "INSERT INTO catalog_meta(key, value) VALUES (?, ?)",
            [
                ("schema_version", "2"),
                ("source", "IGDB"),
                ("platform_filter", "Windows PC (IGDB platform 6)"),
                ("category_filter", "0"),
                ("generated_at", generated_at),
                ("game_count", str(inserted_games)),
                ("store_identity_count", str(inserted_stores)),
            ],
        )
        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
    finally:
        connection.close()

    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps({
        "schema_version": 2,
        "igdb_to_amethys_id": {
            str(key): value for key, value in sorted(igdb_to_amethys.items())
        },
        "source_to_amethys_id": {
            f"{source}:{external_id}": amethys_id
            for (source, external_id), amethys_id in sorted(source_ids.items())
        },
        "retired_or_known_ids": sorted(known_ids),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Export a compact offline search index and lazily downloaded detail shards.
    public_dir = ROOT / "public"
    index_dir = public_dir / "index"
    shards_dir = public_dir / "shards"
    metadata_dir = public_dir / "metadata"
    for directory in (index_dir, shards_dir, metadata_dir):
        directory.mkdir(parents=True, exist_ok=True)

    def write_zstd_json(path: Path, value: object) -> dict:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = zstandard.ZstdCompressor(level=19, threads=0).compress(raw)
        path.write_bytes(compressed)
        return {
            "file": path.relative_to(public_dir).as_posix(),
            "records": len(value) if isinstance(value, list) else None,
            "compressed_size": len(compressed),
            "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        }

    def write_json(path: Path, value: object) -> dict:
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        path.write_bytes(raw)
        return {
            "file": path.relative_to(public_dir).as_posix(),
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    index_rows = connection.execute(
        "SELECT amethys_id, name, slug, genres_json, cover_url FROM games ORDER BY amethys_id"
    )
    search_index = [
        [
            int(row["amethys_id"]),
            row["name"],
            row["slug"],
            json.loads(row["genres_json"] or "[]"),
            row["cover_url"],
        ]
        for row in index_rows
    ]
    index_info = write_zstd_json(index_dir / "games-index.json.zst", search_index)

    shard_size = 1000
    shard_manifest = []
    shard_records = []
    current_bucket = None
    current_count = 0
    genres_seen: set[str] = set()

    def flush_shard(bucket: int, records: list[dict]) -> None:
        if not records:
            return
        filename = f"{bucket:06d}.json.zst"
        info = write_zstd_json(shards_dir / filename, records)
        info["bucket"] = bucket
        info["game_count"] = len(records)
        shard_manifest.append(info)

    cursor = connection.execute(
        """SELECT g.igdb_id, g.amethys_id, g.name, g.slug, g.summary,
                  g.release_date, g.cover_url, g.genres_json,
                  s.store, s.external_id, s.store_name, s.store_url
           FROM games AS g
           LEFT JOIN game_stores AS s ON s.amethys_id = g.amethys_id
           ORDER BY g.amethys_id, s.store, s.external_id"""
    )
    current_game = None
    current_record = None
    for row in cursor:
        game_id = int(row["igdb_id"])
        if game_id != current_game:
            if current_record is not None:
                bucket = int(current_record["amethys_id"]) // shard_size
                if current_bucket is not None and bucket != current_bucket:
                    flush_shard(current_bucket, shard_records)
                    shard_records = []
                current_bucket = bucket
                shard_records.append(current_record)
            current_game = game_id
            current_record = {
                "amethys_id": int(row["amethys_id"]),
                "igdb_id": game_id,
                "name": row["name"],
                "slug": row["slug"],
                "summary": row["summary"],
                "release_date": row["release_date"],
                "cover_url": row["cover_url"],
                "genres": json.loads(row["genres_json"] or "[]"),
                "source_ids": [
                    {"source": source, "external_id": external_id}
                    for source, external_id in connection.execute(
                        "SELECT source, external_id FROM game_source_ids "
                        "WHERE amethys_id = ? ORDER BY source, external_id",
                        (int(row["amethys_id"]),),
                    )
                ],
                "stores": [],
            }
            genres_seen.update(current_record["genres"])
        if row["store"] is not None:
            current_record["stores"].append({
                "store": row["store"],
                "external_id": row["external_id"],
                "name": row["store_name"],
                "url": row["store_url"],
            })
    if current_record is not None:
        bucket = int(current_record["amethys_id"]) // shard_size
        if current_bucket is not None and bucket != current_bucket:
            flush_shard(current_bucket, shard_records)
            shard_records = []
        current_bucket = bucket
        shard_records.append(current_record)
    if current_bucket is not None:
        flush_shard(current_bucket, shard_records)

    source_identity_count = connection.execute(
        "SELECT COUNT(*) FROM game_source_ids"
    ).fetchone()[0]
    connection.close()
    genres_info = write_json(
        metadata_dir / "genres.json",
        {"schema_version": 1, "genres": sorted(genres_seen, key=str.casefold)},
    )

    manifest = {
        "manifest_schema_version": 2,
        "catalog_schema_version": 2,
        "catalog_version": generated_at,
        "generated_at": generated_at,
        "source": "IGDB",
        "platform": "windows-pc",
        "game_count": inserted_games,
        "store_identity_count": inserted_stores,
        "source_identity_count": source_identity_count,
        "search_index": {
            **index_info,
            "format": "json-array-zstd",
            "record_fields": ["amethys_id", "name", "slug", "genres", "cover_url"],
        },
        "shards": {
            "scheme": "amethys-id-range-v1",
            "bucket_size": shard_size,
            "path_template": "shards/{bucket:06d}.json.zst",
            "game_count": inserted_games,
            "files": shard_manifest,
        },
        "metadata": {"genres": genres_info},
    }
    write_json(public_dir / "manifest.json", manifest)

    print(
        f"Built {inserted_games} Windows PC games with {inserted_stores} supported store identities; "
        f"and skipped {skipped_duplicate_store_ids} duplicate store identities; "
        f"published {len(shard_manifest)} detail shards. "
        f"Search index={index_info['compressed_size']:,} bytes."
    )


if __name__ == "__main__":
    main()
