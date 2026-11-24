# Amethys Catalog

Public, read-only master catalogue for Amethys Launcher.

This repository is deliberately separate from the launcher source code. Its GitHub Pages site distributes static catalogue files; it is not a dynamic API and requires no VPS.

## Published format

- `manifest.json`: version, counts, checksums and shard layout.
- `index/games-index.json.zst`: compact offline search index containing only Amethys ID, name and slug.
- `shards/{bucket}.json.zst`: detailed game records and supported store identities, grouped by Amethys ID range.
- `metadata/genres.json`: shared genre list.

The launcher should fetch the manifest, download the search index once, and fetch a detail shard only when a game fiche is opened. Shards and the index are cacheable and independently verifiable with SHA-256. The full transient SQLite build database is not published or downloaded by users.

The global Store catalogue is separate from each PC's local installed-game library. Presence in this catalogue does not imply ownership or installation.

## Publishing

1. Enable **Settings → Pages → Build and deployment → GitHub Actions**.
2. Add repository Actions secrets:
   - `IGDB_CLIENT_ID`
   - `IGDB_CLIENT_SECRET`
3. Run **Actions → Build and publish Amethys game catalogue → Run workflow**.

The first run imports the stable Amethys ID registry from the public Amethys-Launcher repository, then keeps the registry in this repository for subsequent runs. Do not delete or regenerate it: published Amethys IDs must remain stable and must never be reused.

The workflow also runs every Monday at 04:17 UTC. It builds from IGDB, validates the SQLite source, compact index, detail shards and checksums, then publishes the static site.

## Data scope

Windows PC main games from IGDB, with supported external identities for Steam, GOG, Epic, EA, Ubisoft, Battle.net, Amazon Games and Humble. itch.io and unknown sources are excluded. The catalogue does not contain user accounts, entitlements, local paths, installations, download state, or commercial game files.

Respect IGDB's applicable attribution and partnership requirements before commercial distribution.
