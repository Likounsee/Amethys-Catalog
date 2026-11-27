-- Amethys-owned distributed master catalogue.
-- Canonical identity is amethys_id. Provider IDs are optional source identities.
-- Never add per-user installations, local paths, ownership or download state here.
PRAGMA foreign_keys = ON;

CREATE TABLE games (
    amethys_id       INTEGER PRIMARY KEY CHECK (amethys_id > 0),
    igdb_id          INTEGER UNIQUE,
    name             TEXT NOT NULL,
    slug             TEXT,
    summary          TEXT,
    release_date     TEXT,
    cover_url        TEXT,
    genres_json      TEXT NOT NULL DEFAULT '[]',
    updated_at       TEXT NOT NULL
);

CREATE TABLE game_source_ids (
    source           TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    amethys_id       INTEGER NOT NULL REFERENCES games(amethys_id) ON DELETE CASCADE,
    PRIMARY KEY (source, external_id),
    CHECK (length(source) > 0),
    CHECK (length(external_id) > 0)
);

CREATE TABLE game_stores (
    id               INTEGER PRIMARY KEY,
    amethys_id       INTEGER NOT NULL REFERENCES games(amethys_id) ON DELETE CASCADE,
    store            TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    store_name       TEXT,
    store_url        TEXT NOT NULL,
    UNIQUE (store, external_id),
    CHECK (length(store) > 0),
    CHECK (length(external_id) > 0)
);

CREATE TABLE catalog_meta (
    key              TEXT PRIMARY KEY,
    value            TEXT NOT NULL
);

CREATE INDEX idx_games_name ON games(name COLLATE NOCASE);
CREATE INDEX idx_games_slug ON games(slug);
CREATE INDEX idx_game_source_ids_amethys_id ON game_source_ids(amethys_id);
CREATE INDEX idx_game_stores_game ON game_stores(amethys_id);
CREATE INDEX idx_game_stores_store_id ON game_stores(store, external_id);


-- Curated official store promotions. Prices are integer minor units and are
-- published only with an official product URL and a recent verification time.
CREATE TABLE store_promotions (
    promotion_id       TEXT PRIMARY KEY NOT NULL,
    amethys_id         INTEGER NOT NULL REFERENCES games(amethys_id) ON DELETE CASCADE,
    store              TEXT NOT NULL,
    external_id        TEXT NOT NULL,
    current_price_minor INTEGER NOT NULL CHECK (current_price_minor > 0),
    regular_price_minor INTEGER NOT NULL CHECK (regular_price_minor > current_price_minor),
    currency           TEXT NOT NULL CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    valid_from         TEXT NOT NULL,
    valid_until        TEXT NOT NULL,
    checked_at         TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    CHECK (valid_until > valid_from),
    UNIQUE (store, external_id)
);
CREATE INDEX idx_store_promotions_game ON store_promotions(amethys_id);
CREATE INDEX idx_store_promotions_validity ON store_promotions(valid_from, valid_until);
