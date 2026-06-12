"""Respectful local cache for official card images referenced by the catalog."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import connect_database, get_schema_version
from loveca.db.schema import SCHEMA_VERSION


class ImageCacheError(RuntimeError):
    """Raised when the local official-image cache cannot be updated."""


def cache_card_images(
    database_path: Path,
    cache_dir: Path,
    *,
    delay: float = 1.0,
    limit: int | None = None,
) -> dict[str, Any]:
    if delay < 1:
        raise ImageCacheError("image cache delay must be at least 1 second")
    if get_schema_version(database_path) != SCHEMA_VERSION:
        raise ImageCacheError(f"image cache requires card schema v{SCHEMA_VERSION}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    existing = _load_manifest(manifest_path)
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT card_id, image_url
            FROM card_printings
            WHERE image_url IS NOT NULL
            ORDER BY card_id
            """
        ).fetchall()
    if limit is not None:
        rows = rows[:limit]

    entries = dict(existing.get("entries", {}))
    fetched = 0
    failed = 0
    skipped = 0
    for index, row in enumerate(rows):
        card_id = str(row["card_id"])
        image_url = str(row["image_url"])
        _validate_official_image_url(image_url)
        current = entries.get(card_id)
        if current and current.get("source_url") == image_url:
            local_path = cache_dir / str(current.get("local_path", ""))
            if current.get("status") == "cached" and local_path.is_file():
                skipped += 1
                continue
        if index > 0:
            time.sleep(delay)
        try:
            request = urllib.request.Request(
                image_url,
                headers={
                    "User-Agent": (
                        "loveca-simulation-image-cache/0.1 "
                        "(local rules-review tool)"
                    )
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                content_type = response.headers.get_content_type()
            extension = _extension_for(image_url, content_type)
            filename = f"{hashlib.sha256(card_id.encode()).hexdigest()[:20]}{extension}"
            (cache_dir / filename).write_bytes(data)
            entries[card_id] = {
                "card_id": card_id,
                "source_url": image_url,
                "local_path": filename,
                "sha256": hashlib.sha256(data).hexdigest(),
                "fetched_at": _utc_now(),
                "status": "cached",
            }
            fetched += 1
        except (OSError, urllib.error.URLError) as exc:
            entries[card_id] = {
                "card_id": card_id,
                "source_url": image_url,
                "local_path": None,
                "sha256": None,
                "fetched_at": _utc_now(),
                "status": "failed",
                "error": str(exc),
            }
            failed += 1
    manifest = {
        "version": 1,
        "updated_at": _utc_now(),
        "entries": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
        "manifest_path": str(manifest_path),
    }


def resolve_cached_image(cache_dir: Path, card_id: str) -> Path | None:
    manifest = _load_manifest(cache_dir / "manifest.json")
    entry = manifest.get("entries", {}).get(card_id)
    if not isinstance(entry, dict) or entry.get("status") != "cached":
        return None
    local_path = entry.get("local_path")
    if not isinstance(local_path, str):
        return None
    resolved = (cache_dir / local_path).resolve()
    if cache_dir.resolve() not in resolved.parents or not resolved.is_file():
        return None
    return resolved


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImageCacheError(f"invalid image cache manifest: {path}") from exc
    if payload.get("version") != 1 or not isinstance(payload.get("entries"), dict):
        raise ImageCacheError("unsupported image cache manifest")
    return payload


def _validate_official_image_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "llofficial-cardgame.com"
    ):
        raise ImageCacheError(f"unofficial image URL is not allowed: {url!r}")


def _extension_for(url: str, content_type: str) -> str:
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return suffix
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(content_type, ".img")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
