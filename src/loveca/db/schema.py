"""Versioned SQLite schema for the local card catalog."""

SCHEMA_VERSION = 2

REQUIRED_TABLES = (
    "schema_metadata",
    "import_batches",
    "card_sets",
    "gameplay_cards",
    "card_printings",
    "member_card_attributes",
    "live_card_attributes",
    "card_heart_values",
    "special_blade_hearts",
    "source_observations",
    "card_text_revisions",
    "card_text_revision_observations",
    "works",
    "units",
    "gameplay_card_works",
    "gameplay_card_units",
    "printing_references",
    "normalization_candidates",
)

SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_metadata (key, value)
VALUES ('schema_version', '{SCHEMA_VERSION}');

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    input_path TEXT NOT NULL,
    normalization_path TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    normalization_hash TEXT NOT NULL,
    parser_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_imported INTEGER NOT NULL DEFAULT 0,
    review_candidates INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    CHECK (
        status IN (
            'running',
            'completed',
            'completed_with_review',
            'failed'
        )
    ),
    CHECK (records_seen >= 0),
    CHECK (records_imported >= 0),
    CHECK (review_candidates >= 0)
);

CREATE TABLE IF NOT EXISTS card_sets (
    id INTEGER PRIMARY KEY,
    card_set_code TEXT NOT NULL UNIQUE,
    source_url TEXT,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed'
);

CREATE TABLE IF NOT EXISTS gameplay_cards (
    id INTEGER PRIMARY KEY,
    card_code TEXT NOT NULL UNIQUE,
    canonical_name_ja TEXT NOT NULL,
    card_type TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed',
    CHECK (card_type IN ('member', 'live', 'energy'))
);

CREATE TABLE IF NOT EXISTS card_printings (
    id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL UNIQUE,
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE RESTRICT,
    card_set_id INTEGER NOT NULL
        REFERENCES card_sets(id) ON DELETE RESTRICT,
    rarity_ja TEXT,
    image_url TEXT,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed'
);

CREATE TABLE IF NOT EXISTS member_card_attributes (
    gameplay_card_id INTEGER PRIMARY KEY
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    cost INTEGER,
    blade INTEGER,
    blade_heart_color_slot TEXT,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed',
    CHECK (cost IS NULL OR cost >= 0),
    CHECK (blade IS NULL OR blade >= 0),
    CHECK (
        blade_heart_color_slot IS NULL
        OR blade_heart_color_slot IN (
            'heart0',
            'heart01',
            'heart02',
            'heart03',
            'heart04',
            'heart05',
            'heart06'
        )
    )
);

CREATE TABLE IF NOT EXISTS live_card_attributes (
    gameplay_card_id INTEGER PRIMARY KEY
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    score INTEGER,
    blade_heart_color_slot TEXT,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed',
    CHECK (score IS NULL OR score >= 0),
    CHECK (
        blade_heart_color_slot IS NULL
        OR blade_heart_color_slot IN (
            'heart0',
            'heart01',
            'heart02',
            'heart03',
            'heart04',
            'heart05',
            'heart06'
        )
    )
);

CREATE TABLE IF NOT EXISTS card_heart_values (
    id INTEGER PRIMARY KEY,
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    heart_role TEXT NOT NULL,
    color_slot TEXT NOT NULL,
    value INTEGER NOT NULL,
    source_label TEXT,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed',
    CHECK (heart_role IN ('basic', 'required')),
    CHECK (
        color_slot IN (
            'heart0',
            'heart01',
            'heart02',
            'heart03',
            'heart04',
            'heart05',
            'heart06'
        )
    ),
    CHECK (value > 0),
    CHECK (heart_role != 'basic' OR color_slot != 'heart0'),
    UNIQUE (gameplay_card_id, heart_role, color_slot)
);

CREATE TABLE IF NOT EXISTS special_blade_hearts (
    id INTEGER PRIMARY KEY,
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    effect_type TEXT NOT NULL,
    value INTEGER,
    resolution_timing TEXT,
    source_alt TEXT NOT NULL,
    source_field TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed',
    CHECK (ordinal >= 0),
    CHECK (effect_type IN ('all_color', 'draw', 'score', 'unknown')),
    CHECK (value IS NULL OR value > 0),
    CHECK (effect_type = 'unknown' OR value IS NOT NULL),
    UNIQUE (gameplay_card_id, ordinal)
);

CREATE TABLE IF NOT EXISTS source_observations (
    id INTEGER PRIMARY KEY,
    card_printing_id INTEGER NOT NULL
        REFERENCES card_printings(id) ON DELETE CASCADE,
    import_batch_id INTEGER NOT NULL
        REFERENCES import_batches(id) ON DELETE RESTRICT,
    source_url TEXT NOT NULL,
    source_version TEXT,
    fetched_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ja',
    raw_product_label_ja TEXT,
    raw_fields_json TEXT NOT NULL,
    parse_notes_json TEXT NOT NULL,
    UNIQUE (card_printing_id, source_url, fetched_at, parser_version)
);

CREATE TABLE IF NOT EXISTS card_text_revisions (
    id INTEGER PRIMARY KEY,
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    raw_effect_text_ja TEXT NOT NULL,
    raw_text_hash TEXT NOT NULL,
    revision_status TEXT NOT NULL DEFAULT 'provisional',
    created_from_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE RESTRICT,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    CHECK (
        revision_status IN (
            'provisional',
            'current',
            'superseded',
            'deprecated'
        )
    ),
    CHECK (revision_number > 0),
    UNIQUE (gameplay_card_id, revision_number),
    UNIQUE (gameplay_card_id, raw_text_hash)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_card_text_one_current
    ON card_text_revisions(gameplay_card_id)
    WHERE revision_status = 'current';

CREATE TABLE IF NOT EXISTS card_text_revision_observations (
    text_revision_id INTEGER NOT NULL
        REFERENCES card_text_revisions(id) ON DELETE CASCADE,
    source_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE CASCADE,
    PRIMARY KEY (text_revision_id, source_observation_id)
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    work_key TEXT NOT NULL UNIQUE,
    canonical_name_ja TEXT NOT NULL UNIQUE,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed'
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    unit_key TEXT NOT NULL UNIQUE,
    canonical_name_ja TEXT NOT NULL UNIQUE,
    validation_status TEXT NOT NULL DEFAULT 'source_confirmed'
);

CREATE TABLE IF NOT EXISTS gameplay_card_works (
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    work_id INTEGER NOT NULL
        REFERENCES works(id) ON DELETE RESTRICT,
    source_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE CASCADE,
    raw_label_ja TEXT NOT NULL,
    PRIMARY KEY (gameplay_card_id, work_id, source_observation_id)
);

CREATE TABLE IF NOT EXISTS gameplay_card_units (
    gameplay_card_id INTEGER NOT NULL
        REFERENCES gameplay_cards(id) ON DELETE CASCADE,
    unit_id INTEGER NOT NULL
        REFERENCES units(id) ON DELETE RESTRICT,
    source_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE CASCADE,
    raw_label_ja TEXT NOT NULL,
    PRIMARY KEY (gameplay_card_id, unit_id, source_observation_id)
);

CREATE TABLE IF NOT EXISTS printing_references (
    id INTEGER PRIMARY KEY,
    source_printing_id INTEGER NOT NULL
        REFERENCES card_printings(id) ON DELETE CASCADE,
    related_card_id TEXT NOT NULL,
    related_card_code TEXT NOT NULL,
    source_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE CASCADE,
    review_status TEXT NOT NULL DEFAULT 'unfetched',
    CHECK (review_status IN ('unfetched', 'confirmed', 'rejected')),
    UNIQUE (source_printing_id, related_card_id, source_observation_id)
);

CREATE TABLE IF NOT EXISTS normalization_candidates (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    raw_value_ja TEXT NOT NULL,
    first_source_observation_id INTEGER NOT NULL
        REFERENCES source_observations(id) ON DELETE RESTRICT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    CHECK (entity_type IN ('work', 'unit')),
    CHECK (review_status IN ('pending', 'resolved', 'rejected')),
    UNIQUE (entity_type, raw_value_ja)
);

CREATE INDEX IF NOT EXISTS idx_gameplay_cards_name
    ON gameplay_cards(canonical_name_ja);
CREATE INDEX IF NOT EXISTS idx_gameplay_cards_type
    ON gameplay_cards(card_type);
CREATE INDEX IF NOT EXISTS idx_card_printings_gameplay
    ON card_printings(gameplay_card_id);
CREATE INDEX IF NOT EXISTS idx_card_printings_set
    ON card_printings(card_set_id);
CREATE INDEX IF NOT EXISTS idx_heart_values_lookup
    ON card_heart_values(heart_role, color_slot, value);
CREATE INDEX IF NOT EXISTS idx_source_observations_printing
    ON source_observations(card_printing_id);
CREATE INDEX IF NOT EXISTS idx_text_revisions_gameplay
    ON card_text_revisions(gameplay_card_id);
CREATE INDEX IF NOT EXISTS idx_printing_references_related
    ON printing_references(related_card_id);

CREATE TRIGGER IF NOT EXISTS trg_member_attributes_card_type
BEFORE INSERT ON member_card_attributes
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'member'
        THEN RAISE(ABORT, 'member attributes require member card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_member_attributes_card_type_update
BEFORE UPDATE OF gameplay_card_id ON member_card_attributes
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'member'
        THEN RAISE(ABORT, 'member attributes require member card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_live_attributes_card_type
BEFORE INSERT ON live_card_attributes
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'live attributes require live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_live_attributes_card_type_update
BEFORE UPDATE OF gameplay_card_id ON live_card_attributes
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'live attributes require live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_heart_value_card_type
BEFORE INSERT ON card_heart_values
BEGIN
    SELECT CASE
        WHEN NEW.heart_role = 'basic' AND (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'member'
        THEN RAISE(ABORT, 'basic Heart requires member card type')
        WHEN NEW.heart_role = 'required' AND (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'required Heart requires live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_heart_value_card_type_update
BEFORE UPDATE OF gameplay_card_id, heart_role ON card_heart_values
BEGIN
    SELECT CASE
        WHEN NEW.heart_role = 'basic' AND (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'member'
        THEN RAISE(ABORT, 'basic Heart requires member card type')
        WHEN NEW.heart_role = 'required' AND (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'required Heart requires live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_special_blade_heart_card_type
BEFORE INSERT ON special_blade_hearts
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'special Blade Heart requires live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_special_blade_heart_card_type_update
BEFORE UPDATE OF gameplay_card_id ON special_blade_hearts
BEGIN
    SELECT CASE
        WHEN (
            SELECT card_type
            FROM gameplay_cards
            WHERE id = NEW.gameplay_card_id
        ) != 'live'
        THEN RAISE(ABORT, 'special Blade Heart requires live card type')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_gameplay_card_type_immutable
BEFORE UPDATE OF card_type ON gameplay_cards
WHEN NEW.card_type != OLD.card_type
BEGIN
    SELECT RAISE(ABORT, 'Gameplay Card card_type is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_text_revision_identity_immutable
BEFORE UPDATE OF
    gameplay_card_id,
    revision_number,
    raw_effect_text_ja,
    raw_text_hash
ON card_text_revisions
WHEN NEW.gameplay_card_id != OLD.gameplay_card_id
  OR NEW.revision_number != OLD.revision_number
  OR NEW.raw_effect_text_ja != OLD.raw_effect_text_ja
  OR NEW.raw_text_hash != OLD.raw_text_hash
BEGIN
    SELECT RAISE(ABORT, 'Card Text Revision identity and raw text are immutable');
END;

PRAGMA user_version = {SCHEMA_VERSION};
"""
