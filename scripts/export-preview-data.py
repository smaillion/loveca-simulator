"""Export static preview data for the browser-only GitHub Pages build.

The exporter is intentionally conservative. It writes parsed card metadata,
official image URL references, effect registry data, and source/audit metadata
that are useful for a static preview shell, but it never copies downloaded card
image files into the output package. By default it also omits bulk official
effect text revisions. Publishing full official Japanese card text remains an
explicit release decision.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loveca.cards.catalog import get_catalog_card, list_catalog_cards, list_catalog_facets
from loveca.simulation.effects import load_effect_registry

PREVIEW_DATA_VERSION = "browser-preview-data.v0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--effect-registry",
        type=Path,
        default=Path("data_sources/effect-registry.v0.json"),
    )
    parser.add_argument(
        "--include-official-text",
        action="store_true",
        help="Include full card text revisions. Use only after public-release review.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cards = _load_all_cards(args.database, include_official_text=args.include_official_text)
    facets = list_catalog_facets(args.database)
    registry = load_effect_registry(args.effect_registry)
    registry_payload = json.loads(args.effect_registry.read_text(encoding="utf-8"))
    support_counts: dict[str, int] = {}
    for effect in registry.effects:
        support_counts[effect.simulation_support] = (
            support_counts.get(effect.simulation_support, 0) + 1
        )

    manifest = {
        "data_version": PREVIEW_DATA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "card_count": len(cards),
        "effect_count": len(registry.effects),
        "effect_support_counts": support_counts,
        "include_official_text": args.include_official_text,
        "image_strategy": "official_url_only",
        "bundles_card_images": False,
        "files": {
            "cards": "cards.json",
            "facets": "facets.json",
            "effect_registry": "effect-registry.v0.json",
        },
        "public_release_note": (
            "This static data package is intended for browser preview builds. "
            "It contains parsed card/effect data and official image URL "
            "references, but no bundled official card image files. Bulk "
            "official text redistribution requires explicit review."
        ),
    }

    _write_json(args.output_dir / "manifest.json", manifest)
    _write_json(args.output_dir / "cards.json", {"items": cards})
    _write_json(args.output_dir / "facets.json", facets)
    _write_json(args.output_dir / "effect-registry.v0.json", registry_payload)
    return 0


def _load_all_cards(database: Path, *, include_official_text: bool) -> list[dict[str, Any]]:
    summaries = list_catalog_cards(database, limit=100_000, offset=0)
    cards: list[dict[str, Any]] = []
    for item in summaries["items"]:
        detail = get_catalog_card(database, str(item["card_code"]))
        if not include_official_text:
            detail = _strip_public_sensitive_text(detail)
        cards.append(detail)
    return cards


def _strip_public_sensitive_text(detail: dict[str, Any]) -> dict[str, Any]:
    next_detail = json.loads(json.dumps(detail, ensure_ascii=False))
    next_detail["text_revisions"] = [
        {
            key: value
            for key, value in revision.items()
            if key not in {"raw_effect_text_ja"}
        }
        for revision in next_detail.get("text_revisions", [])
    ]
    for effect in next_detail.get("card", {}).get("effects", []):
        effect.pop("label_ja", None)
    return next_detail


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
