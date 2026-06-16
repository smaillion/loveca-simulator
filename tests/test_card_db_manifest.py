from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from loveca.cards.importer import import_normalized_cards

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"


def test_card_db_manifest_generate_and_verify(tmp_path):
    database = tmp_path / "cards.sqlite3"
    manifest = tmp_path / "manifest.json"
    import_normalized_cards(database, SAMPLE_CARDS, NORMALIZATION)

    subprocess.run(
        [
            sys.executable,
            "scripts/card-db-manifest.py",
            "generate",
            "--database",
            str(database),
            "--manifest",
            str(manifest),
            "--effect-registry",
            str(REGISTRY),
            "--source-scope",
            "test-sample",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == "loveca-card-db-manifest.v0"
    assert payload["schema_version"] == 2
    assert payload["card_database_fingerprint"]
    assert payload["effect_registry_hash"]

    subprocess.run(
        [
            sys.executable,
            "scripts/card-db-manifest.py",
            "verify",
            "--database",
            str(database),
            "--manifest",
            str(manifest),
            "--effect-registry",
            str(REGISTRY),
            "--source-scope",
            "test-sample",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def test_card_db_manifest_verify_fails_when_manifest_is_stale(tmp_path):
    database = tmp_path / "cards.sqlite3"
    manifest = tmp_path / "manifest.json"
    import_normalized_cards(database, SAMPLE_CARDS, NORMALIZATION)
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": "loveca-card-db-manifest.v0",
                "database_path": str(database),
                "schema_version": 2,
                "card_database_fingerprint": "stale",
                "effect_registry_path": str(REGISTRY),
                "effect_registry_hash": "stale",
                "source_scope": "test-sample",
                "generated_at": "2026-06-16T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/card-db-manifest.py",
            "verify",
            "--database",
            str(database),
            "--manifest",
            str(manifest),
            "--effect-registry",
            str(REGISTRY),
            "--source-scope",
            "test-sample",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "manifest is stale" in result.stderr
