"""Formal official card-list importer.

This module turns the official card-list source into a full normalized local
catalog artifact. It reuses the existing spike parser logic, but the public
entrypoint is a production-oriented command that can fetch all discoverable
cards, write local review artifacts, and optionally import the normalized
result into the versioned SQLite catalog.
"""

from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loveca.cards.importer import (
    ImportSummary,
    derive_card_code,
    import_normalized_cards,
    normalize_card_identifier,
)

try:
    from tools.importer_spike import cardlist_sample as spike
except ImportError as exc:  # pragma: no cover - source checkout dependency
    project_root = Path(__file__).parents[3]
    if (project_root / "tools" / "importer_spike" / "cardlist_sample.py").is_file():
        sys.path.insert(0, str(project_root))
        try:
            from tools.importer_spike import cardlist_sample as spike
        except ImportError as retry_exc:
            raise ImportError(
                "The formal importer depends on tools.importer_spike.cardlist_sample "
                "in the source checkout."
            ) from retry_exc
    else:
        raise ImportError(
            "The formal importer depends on tools.importer_spike.cardlist_sample in "
            "the source checkout."
        ) from exc


OFFICIAL_IMPORTER_VERSION = "official_import_v2"
OFFICIAL_API_PARSER_VERSION = "cardlist_api_v0.1"
DEFAULT_OUTPUT_ROOT = Path("data/imports/official")
DEFAULT_NORMALIZED_FILENAME = "cards-official.json"
DEFAULT_RAW_DIRNAME = "raw"
DEFAULT_REPORT_DIRNAME = "reports"
DEFAULT_FIELD_REPORT_FILENAME = "field-coverage-report.md"
DEFAULT_IMPORT_REPORT_FILENAME = "importer-report.md"
DEFAULT_PRODUCT_KIND_QUOTA = (("M", "member"), ("L", "live"), ("E", "energy"))
API_PAGE_SIZE = 100
API_CARD_TYPE_MAP = {
    "M": "メンバー",
    "L": "ライブ",
    "E": "エネルギー",
}
API_BLADE_HEART_COLOR_MAP = {
    "桃": "heart01",
    "赤": "heart02",
    "黄": "heart03",
    "緑": "heart04",
    "青": "heart05",
    "紫": "heart06",
}


class OfficialCardSourceError(RuntimeError):
    """Raised when the official source returns unusable catalog data."""


@dataclass(frozen=True)
class OfficialApiConfig:
    list_endpoint: str
    detail_endpoint: str
    image_base_url: str


@dataclass(frozen=True)
class OfficialImportResult:
    cards: list[dict[str, Any]]
    card_list_url: str
    discovered_product_codes: tuple[str, ...]
    inspected_pages: tuple[dict[str, Any], ...]
    raw_files: tuple[str, ...]
    normalized_path: Path
    importer_report_path: Path
    field_coverage_path: Path
    db_import_summary: ImportSummary | None = None


def run_official_card_import(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    manifest_path: Path = spike.MANIFEST_PATH,
    delay: float = 1.0,
    database_path: Path | None = None,
    normalization_path: Path | None = None,
    card_set_codes: tuple[str, ...] | None = None,
    import_mode: str = "full-refresh",
) -> OfficialImportResult:
    """Fetch the official card list and write a full normalized local artifact."""

    card_list_url = spike.read_card_list_url(manifest_path)
    base_domain = urllib.parse.urlparse(card_list_url).netloc
    session = spike.OfficialSiteSession(base_domain, delay)

    return crawl_official_card_catalog(
        session=session,
        card_list_url=card_list_url,
        output_root=output_root,
        database_path=database_path,
        normalization_path=normalization_path,
        card_set_codes=card_set_codes,
        import_mode=import_mode,
    )


def crawl_official_card_catalog(
    *,
    session: Any,
    card_list_url: str,
    output_root: Path,
    database_path: Path | None = None,
    normalization_path: Path | None = None,
    card_set_codes: tuple[str, ...] | None = None,
    import_mode: str = "full-refresh",
) -> OfficialImportResult:
    """Run the catalog crawl with an injected session for testing."""

    output_dirs = _prepare_output_dirs(output_root)
    base_domain = urllib.parse.urlparse(card_list_url).netloc
    requested_product_codes = _normalize_product_codes(card_set_codes)

    card_list_result = session.fetch(card_list_url)
    inspected_pages: list[dict[str, Any]] = [spike.page_record(card_list_result, "card_list")]
    raw_files: list[str] = []
    cards: list[dict[str, Any]] = []

    if card_list_result.error is not None:
        _write_reports(
            output_dirs=output_dirs,
            card_list_url=card_list_url,
            cards=cards,
            inspected_pages=inspected_pages,
            raw_files=raw_files,
            discovered_product_codes=(),
            access_limited=True,
            db_import_summary=None,
            import_mode=import_mode,
            requested_product_codes=requested_product_codes,
        )
        return OfficialImportResult(
            cards=cards,
            card_list_url=card_list_url,
            discovered_product_codes=(),
            inspected_pages=tuple(inspected_pages),
            raw_files=tuple(raw_files),
            normalized_path=output_dirs["normalized"] / DEFAULT_NORMALIZED_FILENAME,
            importer_report_path=output_dirs["reports"] / DEFAULT_IMPORT_REPORT_FILENAME,
            field_coverage_path=output_dirs["reports"] / DEFAULT_FIELD_REPORT_FILENAME,
        )

    card_list_html = _ensure_text(card_list_result.body)
    card_list_sample = output_dirs["raw"] / "cardlist.html"
    card_list_sample.write_text(card_list_html, encoding="utf-8")
    raw_files.append(str(card_list_sample))

    discovery = spike.inspect_html(card_list_url, card_list_html, base_domain)
    api_config = _discover_api_config(card_list_url, card_list_html)
    product_codes = (
        list(requested_product_codes)
        if requested_product_codes
        else _discover_product_codes(card_list_url, card_list_html, discovery)
    )

    seen_printing_ids: set[str] = set()
    seen_gameplay_codes: dict[str, tuple[str, str]] = {}
    for product_code in product_codes:
        for card_kind, kind_name in DEFAULT_PRODUCT_KIND_QUOTA:
            if api_config is not None:
                cards.extend(
                    _crawl_api_bucket(
                        session=session,
                        card_list_url=card_list_url,
                        api_config=api_config,
                        card_kind=card_kind,
                        kind_name=kind_name,
                        product_code=product_code,
                        inspected_pages=inspected_pages,
                        output_raw_dir=output_dirs["raw"],
                        raw_files=raw_files,
                        seen_printing_ids=seen_printing_ids,
                        seen_gameplay_codes=seen_gameplay_codes,
                    )
                )
                continue

            search_url = spike.make_product_card_kind_search_url(
                card_list_url,
                product_code,
                card_kind,
            )
            search_result = session.fetch(search_url, referer=card_list_url)
            inspected_pages.append(
                spike.page_record(search_result, f"search_{product_code.lower()}_{kind_name}")
            )
            if search_result.error is not None:
                continue

            search_html = _ensure_text(search_result.body)
            search_sample = (
                output_dirs["raw"] / f"{product_code.lower()}-{kind_name}-search.html"
            )
            search_sample.write_text(search_html, encoding="utf-8")
            raw_files.append(str(search_sample))

            bucket_cards = _crawl_bucket(
                session=session,
                card_list_url=card_list_url,
                search_result_url=search_url,
                search_html=search_html,
                card_kind=card_kind,
                product_code=product_code,
                inspected_pages=inspected_pages,
                output_raw_dir=output_dirs["raw"],
                seen_printing_ids=seen_printing_ids,
                seen_gameplay_codes=seen_gameplay_codes,
                detail_endpoint=urllib.parse.urljoin(card_list_url, "/cardlist/detail/"),
            )
            cards.extend(bucket_cards)

    if product_codes and not cards:
        failure_reason = (
            "The official source exposed product codes but returned zero card records. "
            "The website contract may have changed; the existing catalog was not imported."
        )
        _write_reports(
            output_dirs=output_dirs,
            card_list_url=card_list_url,
            cards=cards,
            inspected_pages=inspected_pages,
            raw_files=raw_files,
            discovered_product_codes=product_codes,
            access_limited=False,
            db_import_summary=None,
            import_mode=import_mode,
            requested_product_codes=requested_product_codes,
            failure_reason=failure_reason,
        )
        raise OfficialCardSourceError(failure_reason)

    cards = _backfill_missing_names(cards)
    normalized_path = output_dirs["normalized"] / DEFAULT_NORMALIZED_FILENAME
    spike.write_json(normalized_path, cards)
    field_coverage_path = output_dirs["reports"] / DEFAULT_FIELD_REPORT_FILENAME
    spike.write_field_coverage(field_coverage_path, cards)

    db_import_summary: ImportSummary | None = None
    if database_path is not None:
        if normalization_path is None:
            raise ValueError("normalization_path is required when database_path is set")
        db_import_summary = import_normalized_cards(
            database_path,
            normalized_path,
            normalization_path,
            card_set_codes=tuple(product_codes),
        )

    importer_report_path = output_dirs["reports"] / DEFAULT_IMPORT_REPORT_FILENAME
    _write_reports(
        output_dirs=output_dirs,
        card_list_url=card_list_url,
        cards=cards,
        inspected_pages=inspected_pages,
        raw_files=raw_files,
        discovered_product_codes=product_codes,
        access_limited=False,
        db_import_summary=db_import_summary,
        import_mode=import_mode,
        requested_product_codes=requested_product_codes,
        failure_reason=None,
    )

    return OfficialImportResult(
        cards=cards,
        card_list_url=card_list_url,
        discovered_product_codes=tuple(product_codes),
        inspected_pages=tuple(inspected_pages),
        raw_files=tuple(raw_files),
        normalized_path=normalized_path,
        importer_report_path=importer_report_path,
        field_coverage_path=field_coverage_path,
        db_import_summary=db_import_summary,
    )


def _discover_api_config(
    card_list_url: str,
    card_list_html: str,
) -> OfficialApiConfig | None:
    api_base = _html_data_attribute(card_list_html, "data-api-base")
    image_base = _html_data_attribute(card_list_html, "data-image-base")
    if api_base and image_base:
        normalized_api_base = urllib.parse.urljoin(card_list_url, api_base).rstrip("/")
        return OfficialApiConfig(
            list_endpoint=f"{normalized_api_base}/list",
            detail_endpoint=f"{normalized_api_base}/detail",
            image_base_url=urllib.parse.urljoin(card_list_url, image_base),
        )

    config_match = re.search(
        r"\bPWOCG_CFG\s*=\s*(?P<payload>\{.*?\})\s*;",
        card_list_html,
        flags=re.DOTALL,
    )
    if config_match is None:
        return None
    try:
        config = json.loads(config_match.group("payload"))
    except json.JSONDecodeError:
        return None
    api_base = config.get("apiBase")
    image_base = config.get("cardImageBase")
    endpoints = config.get("endpoints")
    if not isinstance(api_base, str) or not isinstance(image_base, str):
        return None
    if not isinstance(endpoints, dict):
        return None
    list_path = endpoints.get("list")
    detail_path = endpoints.get("detail")
    if not isinstance(list_path, str) or not isinstance(detail_path, str):
        return None
    normalized_api_base = urllib.parse.urljoin(card_list_url, api_base).rstrip("/")
    return OfficialApiConfig(
        list_endpoint=f"{normalized_api_base}/{list_path.lstrip('/')}",
        detail_endpoint=f"{normalized_api_base}/{detail_path.lstrip('/')}",
        image_base_url=urllib.parse.urljoin(card_list_url, image_base),
    )


def _html_data_attribute(content: str, attribute: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(attribute)}\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html.unescape(match.group("value")).strip() if match is not None else None


def _crawl_api_bucket(
    *,
    session: Any,
    card_list_url: str,
    api_config: OfficialApiConfig,
    card_kind: str,
    kind_name: str,
    product_code: str,
    inspected_pages: list[dict[str, Any]],
    output_raw_dir: Path,
    raw_files: list[str],
    seen_printing_ids: set[str],
    seen_gameplay_codes: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    page_number = 1
    records_seen = 0
    expected_total: int | None = None
    search_result_url = spike.make_product_card_kind_search_url(
        card_list_url,
        product_code,
        card_kind,
    )

    while expected_total is None or records_seen < expected_total:
        list_url = _url_with_query(
            api_config.list_endpoint,
            title=product_code,
            card_kind=card_kind,
            page=page_number,
            per_page=API_PAGE_SIZE,
            sort="new",
        )
        list_result = session.fetch(list_url, referer=search_result_url)
        inspected_pages.append(
            spike.page_record(
                list_result,
                f"api_{product_code.lower()}_{kind_name}_page_{page_number}",
            )
        )
        if list_result.error is not None:
            break
        payload = _parse_api_payload(
            list_result.body,
            context=f"{product_code}/{card_kind} list page {page_number}",
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise OfficialCardSourceError(
                f"official API list response has no items array: {product_code}/{card_kind}"
            )
        expected_total = _non_negative_int(payload.get("total"), "official API total")

        raw_path = (
            output_raw_dir
            / f"{product_code.lower()}-{kind_name}-api-page-{page_number}.json"
        )
        spike.write_json(raw_path, payload)
        raw_files.append(str(raw_path))

        if not items:
            break
        records_seen += len(items)
        for item in items:
            if not isinstance(item, dict):
                raise OfficialCardSourceError(
                    f"official API returned a non-object card: {product_code}/{card_kind}"
                )
            card_id = item.get("card_number")
            api_card_id = item.get("id")
            if not isinstance(card_id, str) or not card_id.strip():
                raise OfficialCardSourceError(
                    f"official API card is missing card_number: {product_code}/{card_kind}"
                )
            normalized_card_id = normalize_card_identifier(card_id)
            if normalized_card_id in seen_printing_ids:
                continue
            if not isinstance(api_card_id, int):
                raise OfficialCardSourceError(
                    f"official API card is missing numeric id: {normalized_card_id}"
                )

            detail_url = _url_with_query(api_config.detail_endpoint, id=api_card_id)
            detail_cache_path = (
                output_raw_dir / f"{_sanitize_filename(normalized_card_id)}.api.json"
            )
            cached_detail = _read_matching_api_detail_cache(detail_cache_path, item)
            if cached_detail is not None:
                detail_payload = cached_detail
                detail_fetched_at = list_result.fetched_at
                inspected_pages.append(
                    {
                        "page_type": f"api_card_detail_{normalized_card_id}",
                        "url": detail_url,
                        "status": "cache",
                        "content_type": "application/json",
                        "fetched_at": detail_fetched_at,
                        "error": None,
                    }
                )
            else:
                detail_result = session.fetch(detail_url, referer=search_result_url)
                inspected_pages.append(
                    spike.page_record(
                        detail_result,
                        f"api_card_detail_{normalized_card_id}",
                    )
                )
                if detail_result.error is not None:
                    continue
                detail_payload = _parse_api_payload(
                    detail_result.body,
                    context=f"card detail {normalized_card_id}",
                )
                detail_fetched_at = detail_result.fetched_at
                spike.write_json(detail_cache_path, detail_payload)
            detail_card = detail_payload.get("card")
            if not isinstance(detail_card, dict):
                raise OfficialCardSourceError(
                    f"official API detail response has no card object: {normalized_card_id}"
                )
            merged = {**item, **detail_card}
            record = _normalize_api_card(
                merged,
                detail_payload=detail_payload,
                card_kind=card_kind,
                product_code=product_code,
                search_result_url=search_result_url,
                image_base_url=api_config.image_base_url,
                fetched_at=detail_fetched_at,
                seen_gameplay_codes=seen_gameplay_codes,
            )
            seen_printing_ids.add(normalized_card_id)
            cards.append(record)

        page_number += 1

    return cards


def _read_matching_api_detail_cache(
    path: Path,
    list_item: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("card"), dict):
        return None
    cached_card = payload["card"]
    identity_fields = (
        "id",
        "picture",
        "card_number",
        "card_name",
        "card_kind",
        "rare",
        "expansion",
        "cost",
        "heart0",
        "heart01",
        "heart02",
        "heart03",
        "heart04",
        "heart05",
        "heart06",
        "attack",
        "text",
        "text_html",
    )
    if any(cached_card.get(field) != list_item.get(field) for field in identity_fields):
        return None
    return payload


def _parse_api_payload(body: bytes | str, *, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(_ensure_text(body))
    except json.JSONDecodeError as exc:
        raise OfficialCardSourceError(
            f"official API returned invalid JSON for {context}"
        ) from exc
    if not isinstance(payload, dict):
        raise OfficialCardSourceError(
            f"official API returned a non-object payload for {context}"
        )
    return payload


def _normalize_api_card(
    card: dict[str, Any],
    *,
    detail_payload: dict[str, Any],
    card_kind: str,
    product_code: str,
    search_result_url: str,
    image_base_url: str,
    fetched_at: str,
    seen_gameplay_codes: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    card_id = normalize_card_identifier(_required_api_string(card, "card_number"))
    card_type = _required_api_string(card, "card_kind")
    expected_card_type = API_CARD_TYPE_MAP[card_kind]
    if card_type != expected_card_type:
        raise OfficialCardSourceError(
            f"official API card kind mismatch for {card_id}: "
            f"expected {expected_card_type}, got {card_type}"
        )
    name = _required_api_string(card, "card_name")
    derived_card_code = derive_card_code(card_id)
    gameplay_card_code = _choose_gameplay_card_code(
        card_id=card_id,
        derived_card_code=derived_card_code,
        name=name,
        card_type=card_type,
        seen_gameplay_codes=seen_gameplay_codes,
    )
    raw_effect_text = _api_effect_text(card)
    picture = _optional_api_string(card.get("picture"))
    relation_cards = detail_payload.get("relationCards")
    related_printing_ids = (
        [
            normalize_card_identifier(related["card_number"])
            for related in relation_cards or []
            if isinstance(related, dict)
            and isinstance(related.get("card_number"), str)
            and related["card_number"].strip()
        ]
        if card_type != "エネルギー"
        else []
    )
    source_url = spike.make_card_source_url(search_result_url, card_id)
    unmapped_fields = []
    for label, field_name in (("作品名", "work_title"), ("参加ユニット", "unit_name")):
        value = _optional_api_string(card.get(field_name))
        if value and value != "-":
            unmapped_fields.append({"label": label, "raw_text": value})

    member_attributes = None
    live_attributes = None
    unmapped_icons: list[dict[str, str]] = []
    normalized_icon_aliases: list[dict[str, str]] = []
    if card_type == "メンバー":
        member_blade_heart = _api_regular_blade_heart_color(card.get("blade_heart"))
        raw_blade_heart = _optional_api_string(card.get("blade_heart"))
        if raw_blade_heart not in (None, "-") and member_blade_heart is None:
            unmapped_icons.append(
                {"source_field": "ブレードハート", "source_alt": raw_blade_heart}
            )
        member_attributes = {
            "cost": _optional_api_integer(card.get("cost")),
            "heart_by_color": _api_heart_map(card, include_neutral=False),
            "blade": _optional_api_integer(card.get("attack")),
            "blade_heart_color": member_blade_heart,
        }
    elif card_type == "ライブ":
        raw_live_blade_heart = _optional_api_string(card.get("attack"))
        blade_heart_color, special_blade_hearts = _api_live_blade_hearts(
            raw_live_blade_heart
        )
        if raw_live_blade_heart in {"[全ブレード]", "[ALLブレード]"}:
            normalized_icon_aliases.append(
                {
                    "source_field": "ブレードハート",
                    "source_alt": raw_live_blade_heart,
                    "canonical_alt": "ALL1",
                }
            )
        if any(item["effect_type"] == "unknown" for item in special_blade_hearts):
            unmapped_icons.extend(
                {
                    "source_field": item["source_field"],
                    "source_alt": item["source_alt"],
                }
                for item in special_blade_hearts
                if item["effect_type"] == "unknown"
            )
        live_attributes = {
            "required_heart_by_color": _api_heart_map(card, include_neutral=True),
            "score": _optional_api_integer(card.get("blade_heart")),
            "blade_heart_color": blade_heart_color,
            "special_blade_hearts": special_blade_hearts or None,
        }

    return {
        "card_id": card_id,
        "card_code": gameplay_card_code,
        "name": name,
        "card_type": card_type,
        "product": _api_product_name(card, detail_payload, product_code),
        "product_code": product_code,
        "rarity": _optional_api_string(card.get("rare")),
        "member_attributes": member_attributes,
        "live_attributes": live_attributes,
        "raw_effect_text": raw_effect_text,
        "image_url": urllib.parse.urljoin(image_base_url, picture) if picture else None,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "parser_version": OFFICIAL_API_PARSER_VERSION,
        "related_printing_ids": related_printing_ids,
        "parse_notes": {
            "source": "card_list_json_api",
            "import_source": "official_full_import",
            "list_method": "GET",
            "detail_method": "GET",
            "candidate_effect_blocks": spike.split_candidate_effect_blocks(
                raw_effect_text
            ),
            "unmapped_fields": unmapped_fields,
            "unmapped_icons": unmapped_icons,
            "normalized_icon_aliases": normalized_icon_aliases,
            "card_kind": card_kind,
            "product_code": product_code,
            "api_card_id": card.get("id"),
            "gameplay_card_code_strategy": (
                "full_card_id_conflict_fallback"
                if gameplay_card_code != derived_card_code
                else "derived_from_printing_id"
            ),
            "derived_card_code": derived_card_code,
        },
    }


def _api_effect_text(card: dict[str, Any]) -> str | None:
    text_html = _optional_api_string(card.get("text_html"))
    if text_html:
        return spike.text_with_image_alts(text_html) or None
    return _optional_api_string(card.get("text"))


def _api_heart_map(
    card: dict[str, Any],
    *,
    include_neutral: bool,
) -> dict[str, int | None]:
    slots = (("heart0",) if include_neutral else ()) + tuple(
        f"heart0{index}" for index in range(1, 7)
    )
    return {
        slot: (value if (value := _optional_api_integer(card.get(slot))) else None)
        for slot in slots
    }


def _api_live_blade_hearts(
    raw_value: Any,
) -> tuple[str | None, list[dict[str, Any]]]:
    source_alt = _optional_api_string(raw_value)
    if source_alt in (None, "-"):
        return None, []
    if source_alt in {"[全ブレード]", "[ALLブレード]"}:
        return "heart0", [
            {
                "effect_type": "all_color",
                "value": 1,
                "resolution_timing": "live_success_judgment",
                "source_alt": "ALL1",
                "source_field": "ブレードハート",
            }
        ]
    all_match = re.fullmatch(r"ALL(?P<value>\d+)", source_alt, re.IGNORECASE)
    if all_match is not None:
        value = int(all_match.group("value"))
        return "heart0", [
            {
                "effect_type": "all_color",
                "value": value,
                "resolution_timing": "live_success_judgment",
                "source_alt": source_alt,
                "source_field": "ブレードハート",
            }
        ]
    color_match = re.fullmatch(r"(?P<color>[桃赤黄緑青紫])(?P<value>\d+)", source_alt)
    if color_match is not None and int(color_match.group("value")) == 1:
        return API_BLADE_HEART_COLOR_MAP[color_match.group("color")], []
    numeric_suffix = re.search(r"(?P<value>\d+)$", source_alt)
    return None, [
        {
            "effect_type": "unknown",
            "value": int(numeric_suffix.group("value")) if numeric_suffix else None,
            "resolution_timing": None,
            "source_alt": source_alt,
            "source_field": "ブレードハート",
        }
    ]


def _api_regular_blade_heart_color(raw_value: Any) -> str | None:
    source_alt = _optional_api_string(raw_value)
    if source_alt is None:
        return None
    match = re.fullmatch(r"(?P<color>[桃赤黄緑青紫])(?:1)?", source_alt)
    return API_BLADE_HEART_COLOR_MAP.get(match.group("color")) if match else None


def _api_product_name(
    card: dict[str, Any],
    detail_payload: dict[str, Any],
    product_code: str,
) -> str:
    direct = _optional_api_string(card.get("expansion_name"))
    if direct:
        return direct
    expansion = detail_payload.get("expansion")
    if isinstance(expansion, dict):
        name = _optional_api_string(expansion.get("name"))
        if name:
            return name
    return product_code


def _required_api_string(card: dict[str, Any], field: str) -> str:
    value = _optional_api_string(card.get(field))
    if value is None:
        raise OfficialCardSourceError(f"official API card field is missing: {field}")
    return value


def _optional_api_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_api_integer(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*", value)
    return int(match.group(1)) if match is not None else None


def _non_negative_int(value: Any, field: str) -> int:
    parsed = value if isinstance(value, int) else _optional_api_integer(value)
    if parsed is None or parsed < 0:
        raise OfficialCardSourceError(f"{field} must be a non-negative integer")
    return parsed


def _url_with_query(url: str, **params: Any) -> str:
    return f"{url}?{urllib.parse.urlencode(params)}"


def _crawl_bucket(
    *,
    session: Any,
    card_list_url: str,
    search_result_url: str,
    search_html: str,
    card_kind: str,
    product_code: str,
    inspected_pages: list[dict[str, Any]],
    output_raw_dir: Path,
    seen_printing_ids: set[str],
    seen_gameplay_codes: dict[str, str],
    detail_endpoint: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    queue = spike.normalize_cards_from_search_results(
        search_result_url=search_result_url,
        search_result_html=search_html,
        fetched_at=_utc_now(),
        limit=10_000,
    )
    queue = _dedupe_printing_ids(queue, seen_printing_ids)

    page_number = 2
    while True:
        incremental_url = spike.make_incremental_search_url(
            card_list_url,
            product_code,
            card_kind,
            page=page_number,
        )
        incremental_result = session.fetch(incremental_url, referer=search_result_url, ajax=True)
        inspected_pages.append(
            spike.page_record(
                incremental_result,
                f"search_{product_code.lower()}_{card_kind.lower()}_page_{page_number}",
            )
        )
        if incremental_result.error is not None:
            break
        incremental_html = _ensure_text(incremental_result.body)
        if not incremental_html.strip():
            break
        incremental_path = (
            output_raw_dir
            / f"{product_code.lower()}-{card_kind.lower()}-search-page-{page_number}.html"
        )
        incremental_path.write_text(incremental_html, encoding="utf-8")
        if incremental_html not in {"NG", "ng"}:
            search_cards = spike.normalize_cards_from_search_results(
                search_result_url=search_result_url,
                search_result_html=incremental_html,
                fetched_at=_utc_now(),
                limit=10_000,
            )
            new_cards = _dedupe_printing_ids(search_cards, seen_printing_ids)
            if not new_cards:
                break
            queue.extend(new_cards)
        page_number += 1

    for candidate in queue:
        card_id = candidate.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            continue
        detail_request_url = spike.make_detail_request_url(detail_endpoint)
        detail_result = session.fetch(
            detail_request_url,
            form_data={"cardno": card_id},
            referer=search_result_url,
            ajax=True,
        )
        inspected_pages.append(
            spike.page_record(
                detail_result,
                f"card_detail_{product_code.lower()}_{card_kind.lower()}_{card_id}",
            )
        )
        if detail_result.error is not None:
            continue
        detail_html = _ensure_text(detail_result.body)
        if not detail_html.strip() or detail_html.strip() == "NG":
            continue

        detail_sample = output_raw_dir / f"{_sanitize_filename(card_id)}.html"
        detail_sample.write_text(detail_html, encoding="utf-8")

        detail_card = spike.normalize_card(
            candidate["source_url"],
            detail_html,
            detail_result.fetched_at,
            detail_endpoint="/cardlist/detail/",
        )
        enriched = _normalize_card_record_identifiers(
            spike.merge_card_candidate(candidate, detail_card)
        )
        enriched_card_id = enriched.get("card_id")
        derived_card_code = (
            derive_card_code(enriched_card_id) if isinstance(enriched_card_id, str) else ""
        )
        gameplay_card_code = _choose_gameplay_card_code(
            card_id=enriched_card_id,
            derived_card_code=derived_card_code,
            name=enriched.get("name"),
            card_type=enriched.get("card_type"),
            seen_gameplay_codes=seen_gameplay_codes,
        )
        enriched["card_code"] = gameplay_card_code
        enriched["product_code"] = product_code
        enriched["parse_notes"] = {
            **(enriched.get("parse_notes") or {}),
            "import_source": "official_full_import",
            "card_kind": card_kind,
            "product_code": product_code,
            "detail_request_url": detail_request_url,
            "gameplay_card_code_strategy": (
                "full_card_id_conflict_fallback"
                if gameplay_card_code != derived_card_code
                else "derived_from_printing_id"
            ),
            "derived_card_code": derived_card_code,
        }
        cards.append(enriched)

    return cards


def _choose_gameplay_card_code(
    *,
    card_id: str | None,
    derived_card_code: str | None,
    name: str | None,
    card_type: str | None,
    seen_gameplay_codes: dict[str, tuple[str, str]],
) -> str:
    card_id = normalize_card_identifier(card_id) if card_id else card_id
    derived_card_code = (
        normalize_card_identifier(derived_card_code)
        if derived_card_code
        else derived_card_code
    )
    if not card_id:
        return derived_card_code or ""
    if not derived_card_code:
        return card_id
    if card_type in {"エネルギー", "energy"} and card_id != derived_card_code:
        seen_gameplay_codes[card_id] = (
            str(card_type or ""),
            _normalize_name_identity(name or ""),
        )
        return card_id
    current_identity = (str(card_type or ""), _normalize_name_identity(name or ""))
    existing_identity = seen_gameplay_codes.get(derived_card_code)
    if existing_identity is None or existing_identity == current_identity:
        seen_gameplay_codes[derived_card_code] = current_identity
        return derived_card_code
    seen_gameplay_codes[card_id] = current_identity
    return card_id


def _normalize_name_identity(value: str) -> str:
    ignored_separators = {
        "・",
        "･",
        "/",
        "\\",
        "-",
        "‐",
        "‑",
        "–",
        "—",
        "〜",
        "~",
        "＿",
        "_",
    }
    return "".join(
        part
        for part in unicodedata.normalize("NFKC", value)
        if not part.isspace() and part not in ignored_separators
    )


def _dedupe_printing_ids(
    cards: list[dict[str, Any]],
    seen_printing_ids: set[str],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for card in cards:
        card_id = card.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            continue
        normalized_card_id = normalize_card_identifier(card_id)
        if normalized_card_id in seen_printing_ids:
            continue
        seen_printing_ids.add(normalized_card_id)
        deduped.append(card)
    return deduped


def _normalize_card_record_identifiers(card: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(card)
    for field in ("card_id", "card_code"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = normalize_card_identifier(value)
    related_ids = normalized.get("related_printing_ids")
    if isinstance(related_ids, list):
        normalized["related_printing_ids"] = [
            normalize_card_identifier(item) if isinstance(item, str) else item
            for item in related_ids
        ]
    return normalized


def _discover_product_codes(
    card_list_url: str,
    card_list_html: str,
    discovery: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    for match in re.finditer(
        r"""href=(?P<quote>["'])(?P<value>/cardlist/searchresults/\?expansion=[^"']+)(?P=quote)""",
        card_list_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        parsed = urllib.parse.urlparse(
            urllib.parse.urljoin(card_list_url, match.group("value"))
        )
        query = urllib.parse.parse_qs(parsed.query)
        for expansion in query.get("expansion", []):
            if expansion:
                add(expansion)

    for url in discovery.get("search_result_urls", []):
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        for value in query.get("expansion", []):
            if value:
                add(value)
        for value in query.get("title", []):
            if value and _looks_like_product_code(value):
                add(value)

    if candidates:
        return candidates

    for match in re.finditer(
        r"""<option\b[^>]*value=(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
        card_list_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        value = match.group("value").strip()
        if _looks_like_product_code(value):
            add(value)

    if candidates:
        return candidates

    # Fallback to the root page itself when no product filter is discoverable.
    return [urllib.parse.urlparse(card_list_url).path.rstrip("/").split("/")[-1] or "cardlist"]


def _looks_like_product_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9!+\-]{2,12}", value))


def _normalize_product_codes(card_set_codes: tuple[str, ...] | None) -> tuple[str, ...]:
    if not card_set_codes:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in card_set_codes:
        item = value.strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _backfill_missing_names(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names_by_code: dict[str, str] = {}
    ambiguous_codes: set[str] = set()
    for card in cards:
        card_code = card.get("card_code")
        name = card.get("name")
        if not isinstance(card_code, str) or not card_code:
            continue
        if not isinstance(name, str) or not name:
            continue
        existing = names_by_code.get(card_code)
        if existing is None:
            names_by_code[card_code] = name
        elif existing != name:
            ambiguous_codes.add(card_code)

    enriched_cards: list[dict[str, Any]] = []
    for card in cards:
        card_code = card.get("card_code")
        if (
            isinstance(card_code, str)
            and card_code not in ambiguous_codes
            and card.get("name") in (None, "")
            and card_code in names_by_code
        ):
            card = dict(card)
            parse_notes = dict(card.get("parse_notes") or {})
            parse_notes["name_backfilled_from_card_code"] = card_code
            card["parse_notes"] = parse_notes
            card["name"] = names_by_code[card_code]
        enriched_cards.append(card)
    return enriched_cards


def _prepare_output_dirs(root: Path) -> dict[str, Path]:
    raw_dir = root / DEFAULT_RAW_DIRNAME
    normalized_dir = root / "normalized"
    reports_dir = root / DEFAULT_REPORT_DIRNAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return {"raw": raw_dir, "normalized": normalized_dir, "reports": reports_dir}


def _write_reports(
    *,
    output_dirs: dict[str, Path],
    card_list_url: str,
    cards: list[dict[str, Any]],
    inspected_pages: list[dict[str, Any]],
    raw_files: list[str],
    discovered_product_codes: tuple[str, ...] | list[str],
    access_limited: bool,
    db_import_summary: ImportSummary | None,
    import_mode: str,
    requested_product_codes: tuple[str, ...],
    failure_reason: str | None = None,
) -> None:
    importer_report = output_dirs["reports"] / DEFAULT_IMPORT_REPORT_FILENAME
    coverage_path = output_dirs["reports"] / DEFAULT_FIELD_REPORT_FILENAME

    total_cards = len(cards)
    type_counts = Counter(card.get("card_type") for card in cards)
    special_counts: dict[str, int] = defaultdict(int)
    card_set_counts = Counter(
        str(card.get("product_code") or "")
        for card in cards
        if isinstance(card.get("product_code"), str) and card.get("product_code")
    )
    missing_name_count = sum(1 for card in cards if not card.get("name"))
    for card in cards:
        for item in (card.get("live_attributes") or {}).get("special_blade_hearts") or []:
            effect_type = item.get("effect_type") or "unknown"
            special_counts[str(effect_type)] += 1

    lines = [
        "# Official Import Report",
        "",
        "## Summary",
        "",
        f"* Importer version: `{OFFICIAL_IMPORTER_VERSION}`",
        f"* Source: `{card_list_url}`",
        f"* Mode: `{import_mode}`",
        f"* Status: `{'failed' if failure_reason else ('access_limited' if access_limited else 'completed')}`",
        f"* Requested card sets: `{', '.join(requested_product_codes) or 'all discovered sets'}`",
        f"* Products discovered: `{len(discovered_product_codes)}`",
        f"* Records written: `{total_cards}`",
        f"* Member cards: `{type_counts.get('メンバー', 0)}`",
        f"* Live cards: `{type_counts.get('ライブ', 0)}`",
        f"* Energy cards: `{type_counts.get('エネルギー', 0)}`",
        f"* Records still missing name: `{missing_name_count}`",
    ]
    if failure_reason:
        lines.extend([f"* Failure reason: `{failure_reason}`"])
    if db_import_summary is not None:
        lines.extend(
            [
                "",
                "## Database Import",
                "",
                f"* Batch id: `{db_import_summary.batch_id}`",
                f"* Status: `{db_import_summary.status}`",
                f"* Records seen: `{db_import_summary.records_seen}`",
                f"* Records imported: `{db_import_summary.records_imported}`",
                "* Targeted card sets: "
                f"`{', '.join(db_import_summary.targeted_card_sets) or 'all'}`",
                f"* New Gameplay Cards: `{db_import_summary.new_gameplay_cards}`",
                f"* New Card Printings: `{db_import_summary.new_card_printings}`",
                f"* New Text Revisions: `{db_import_summary.new_text_revisions}`",
                f"* Reused Text Revisions: `{db_import_summary.reused_text_revisions}`",
                f"* Review candidates: `{db_import_summary.review_candidates}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Card Set Coverage",
            "",
            "| card_set_code | records |",
            "| --- | ---: |",
        ]
    )
    if card_set_counts:
        for card_set_code, count in sorted(card_set_counts.items()):
            lines.append(f"| `{card_set_code}` | {count} |")
    else:
        lines.append("| - | 0 |")

    lines.extend(
        [
            "",
            "## Special Blade Heart Coverage",
            "",
            "| effect_type | observed |",
            "| --- | ---: |",
        ]
    )
    for effect_type in ("all_color", "draw", "score", "unknown"):
        lines.append(f"| `{effect_type}` | {special_counts.get(effect_type, 0)} |")

    lines.extend(
        [
            "",
            "## Discovered Product Codes",
            "",
            ", ".join(f"`{code}`" for code in discovered_product_codes) or "-",
            "",
            "## Pages Inspected",
            "",
        ]
    )
    for page in inspected_pages:
        lines.append(
            f"* `{page['page_type']}` `{page['status']}` {page['url']}"
            + (f" - {page['error']}" if page["error"] else "")
        )

    lines.extend(
        [
            "",
            "## Raw Files",
            "",
            *([f"* `{value}`" for value in raw_files] or ["* None written."]),
            "",
            "## Notes",
            "",
            "* This importer preserves raw Japanese detail text and official source URLs.",
            "* It does not interpret Effect DSL; it only emits normalized source data.",
            "* Missing or unresolved fields remain null and are reported separately.",
            "",
        ]
    )
    importer_report.write_text("\n".join(lines), encoding="utf-8")

    if not coverage_path.exists():
        spike.write_field_coverage(coverage_path, cards)


def _ensure_text(body: str | bytes) -> str:
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return body


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE)
    return cleaned.strip("._") or "card"
