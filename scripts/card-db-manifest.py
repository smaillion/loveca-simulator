"""Generate and verify the locked card database manifest."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import get_schema_version
from loveca.simulation.online import card_database_fingerprint, effect_registry_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data/loveca.sqlite3"
DEFAULT_MANIFEST = PROJECT_ROOT / "data/loveca-db-manifest.json"
DEFAULT_EFFECT_REGISTRY = PROJECT_ROOT / "data_sources/effect-registry.v0.json"


def build_manifest(
    *,
    database: Path,
    effect_registry: Path,
    source_scope: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "manifest_version": "loveca-card-db-manifest.v0",
        "database_path": display_path(database),
        "schema_version": get_schema_version(database),
        "card_database_fingerprint": card_database_fingerprint(database),
        "effect_registry_path": display_path(effect_registry),
        "effect_registry_hash": effect_registry_hash(effect_registry),
        "source_scope": source_scope,
        "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(path: Path, expected: dict[str, Any]) -> None:
    current = load_manifest(path)
    ignored = {"generated_at"}
    mismatches = [
        key
        for key, value in expected.items()
        if key not in ignored and current.get(key) != value
    ]
    if mismatches:
        details = ", ".join(mismatches)
        raise SystemExit(f"card database manifest is stale: {details}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "verify"])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--effect-registry", type=Path, default=DEFAULT_EFFECT_REGISTRY)
    parser.add_argument(
        "--source-scope",
        default="official-card-list.locked",
        help="Human-readable official data scope represented by this DB.",
    )
    args = parser.parse_args()

    expected = build_manifest(
        database=args.database,
        effect_registry=args.effect_registry,
        source_scope=args.source_scope,
    )
    if args.command == "generate":
        write_manifest(args.manifest, expected)
        return
    verify_manifest(args.manifest, expected)


if __name__ == "__main__":
    main()
