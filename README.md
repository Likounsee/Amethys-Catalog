# Amethys Catalog

Public, read-only master catalogue for Amethys Launcher.

This repository is deliberately separate from the launcher source code. Its GitHub Pages site distributes static catalogue files; it is not a dynamic API and requires no VPS.

## Published format

- `manifest.json`: version, counts, checksums and shard layout.
- `index/games-index.json.zst`: compact offline search index containing only Amethys ID, name and slug.
- `shards/{bucket}.json.zst`: detailed game records, generic source identities and supported store identities, grouped by Amethys ID range.
- `metadata/genres.json`: shared genre list.

The launcher should fetch the manifest, download the search index once, and fetch a detail shard only when a game fiche is opened. Shards and the index are cacheable and independently verifiable with SHA-256. The full transient SQLite build database is not published or downloaded by users.

The global Store catalogue is separate from each PC's local installed-game library. Presence in this catalogue does not imply ownership or installation.

## Publishing

1. Enable **Settings → Pages → Build and deployment → GitHub Actions**.
2. Add repository Actions secrets:
   - `IGDB_CLIENT_ID`
   - `IGDB_CLIENT_SECRET`
3. Run **Actions → Build and publish Amethys game catalogue → Run workflow**.

The stable Amethys ID registry lives in this repository and is required for every build. The workflow refuses to generate a fresh registry if this file is missing: published Amethys IDs must remain stable and must never be reused.

The workflow also runs every Monday at 04:17 UTC. The current ingestion adapter imports Windows PC metadata from IGDB, validates the SQLite source, compact index, detail shards and checksums, then publishes the static site. IGDB is an ingestion source, not the owner of Amethys game identities or the permanent catalogue format. Future official publisher/store feeds can be added as separate ingestion adapters without changing Amethys IDs or the public distribution contract.

## Data scope

The current data import covers Windows PC main games from IGDB. Amethys IDs are the canonical primary keys in the catalogue database; IGDB and store identifiers are recorded separately in the generic source-identity table and registry. The current importer writes IGDB and supported store identities into that mapping. Supported store identities (Steam, GOG, Epic, EA, Ubisoft, Battle.net, Amazon Games and Humble) are optional metadata: a game remains in the master catalogue even when no supported offer is currently known. Unknown store identities are omitted, not used to discard the game. The catalogue does not contain user accounts, entitlements, local paths, installations, download state, or commercial game files.

Respect IGDB's applicable attribution and partnership requirements before commercial distribution.


## Official store promotions

The public feed accepts manually curated promotion records in
`catalogs/store-promotions-v1.json`. A record is published only when it matches
an existing Amethys game and its exact supported store product identity, uses
the store's HTTPS product URL, provides integer prices in minor currency units,
and includes a UTC validity window and verification timestamp. The launcher
can derive the displayed discount from the two prices; no percentage is
accepted as an independent source of truth.

The promotion feed is intentionally empty until verified source data is
available. IGDB supplies game metadata and store identities, not live prices or
discounts. No price is inferred from metadata, scraped from an unapproved
source, or fabricated by the catalogue builder.
