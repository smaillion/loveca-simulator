"""Local deck library persistence for decklist.v0 files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loveca.decks.analyzer import DeckFileError, DeckList, load_deck, parse_deck


class DeckLibraryError(RuntimeError):
    """Raised when a local deck library operation fails."""


@dataclass(frozen=True)
class SavedDeck:
    name: str | None
    path: Path
    version: str
    main_card_count: int
    energy_card_count: int


def save_deck_file(
    deck_path: Path,
    library_root: Path,
    *,
    name: str | None = None,
    overwrite: bool = False,
) -> Path:
    deck = load_deck(deck_path)
    return save_deck_payload(
        deck,
        library_root,
        name=name or deck.name,
        overwrite=overwrite,
    )


def save_deck_payload(
    deck: DeckList | dict[str, Any],
    library_root: Path,
    *,
    name: str | None = None,
    overwrite: bool = False,
    destination: Path | None = None,
) -> Path:
    parsed = deck if isinstance(deck, DeckList) else parse_deck(deck)
    library_root.mkdir(parents=True, exist_ok=True)
    deck_name = name if name is not None else parsed.name
    payload = _serialize_deck(parsed, deck_name)
    if destination is None:
        slug = _slugify(deck_name or "untitled")
        destination = _unique_path(library_root / f"{slug}.json", overwrite=overwrite)
    else:
        destination = _resolve_destination(library_root, destination, overwrite=overwrite)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def update_saved_deck(
    library_root: Path,
    identifier: str,
    deck: DeckList | dict[str, Any],
    *,
    name: str | None = None,
    overwrite: bool = True,
) -> Path:
    source = resolve_saved_deck_path(library_root, identifier)
    parsed = deck if isinstance(deck, DeckList) else parse_deck(deck)
    destination = source if overwrite else _unique_path(
        library_root / f"{_slugify(name or parsed.name or 'untitled')}.json",
        overwrite=False,
    )
    payload = _serialize_deck(parsed, name if name is not None else parsed.name)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if destination != source and source.exists():
        source.unlink()
    return destination


def list_saved_decks(library_root: Path) -> list[SavedDeck]:
    if not library_root.exists():
        return []
    results: list[SavedDeck] = []
    for path in sorted(library_root.glob("*.json")):
        try:
            deck = load_deck(path)
        except DeckFileError:
            continue
        results.append(
            SavedDeck(
                name=deck.name,
                path=path,
                version=deck.version,
                main_card_count=sum(entry.quantity for entry in deck.main_deck),
                energy_card_count=sum(entry.quantity for entry in deck.energy_deck),
            )
        )
    return results


def load_saved_deck(library_root: Path, identifier: str) -> DeckList:
    path = resolve_saved_deck_path(library_root, identifier)
    return load_deck(path)


def rename_saved_deck(
    library_root: Path,
    identifier: str,
    new_name: str,
) -> Path:
    path = resolve_saved_deck_path(library_root, identifier)
    deck = load_deck(path)
    destination = _unique_path(library_root / f"{_slugify(new_name)}.json", overwrite=False)
    payload = _serialize_deck(deck, new_name)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if destination != path:
        path.unlink()
    return destination


def delete_saved_deck(library_root: Path, identifier: str) -> None:
    path = resolve_saved_deck_path(library_root, identifier)
    path.unlink()


def resolve_saved_deck_path(library_root: Path, identifier: str) -> Path:
    root = library_root.resolve()
    candidate = Path(identifier)
    if candidate.is_absolute() or candidate.suffix == ".json":
        resolved = candidate if candidate.is_absolute() else root / candidate
        if resolved.exists():
            return resolved.resolve()
    if not root.exists():
        raise DeckLibraryError(f"deck library does not exist: {library_root}")
    slug = _slugify(identifier)
    direct = root / f"{slug}.json"
    if direct.exists():
        return direct.resolve()
    matches = [path for path in root.glob("*.json") if _slugify(path.stem) == slug]
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise DeckLibraryError(f"saved deck not found: {identifier}")
    raise DeckLibraryError(f"saved deck identifier is ambiguous: {identifier}")


def _slugify(value: str | None) -> str:
    if not value:
        return "untitled"
    slug = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return slug.lower() or "untitled"


def _unique_path(path: Path, *, overwrite: bool) -> Path:
    if overwrite or not path.exists():
        return path
    raise DeckLibraryError(f"saved deck already exists: {path.name}")


def _serialize_deck(deck: DeckList, deck_name: str | None) -> dict[str, Any]:
    return {
        "version": deck.version,
        "name": deck_name,
        "main_deck": [
            {
                "card_code": entry.card_code,
                "quantity": entry.quantity,
                "preferred_printing_id": entry.preferred_printing_id,
            }
            for entry in deck.main_deck
        ],
        "energy_deck": [
            {
                "card_code": entry.card_code,
                "quantity": entry.quantity,
                "preferred_printing_id": entry.preferred_printing_id,
            }
            for entry in deck.energy_deck
        ],
    }


def _resolve_destination(library_root: Path, destination: Path, *, overwrite: bool) -> Path:
    resolved = destination if destination.is_absolute() else library_root / destination
    resolved = resolved.resolve()
    root = library_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise DeckLibraryError("saved deck destination must stay within the library root")
    if resolved.exists() and not overwrite:
        raise DeckLibraryError(f"saved deck already exists: {resolved.name}")
    return resolved
