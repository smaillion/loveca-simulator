"""Small official card-list importer spike.

This is intentionally not the production importer. It samples a small number of
official card-list pages and writes local review artifacts under data_samples/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PARSER_VERSION = "cardlist_spike_v0.3"
MANIFEST_PATH = Path("data_sources/source-manifest.yaml")
OUTPUT_ROOT = Path("data_samples")
CARD_KIND_SAMPLES = (("M", "member", 5), ("L", "live", 5), ("E", "energy", 2))
CROSS_PRODUCT_CODES = ("BP01", "BP03", "BP06", "PLSD01", "HSSD01", "PR")
CROSS_PRODUCT_KIND_QUOTAS = (("M", "member", 2), ("L", "live", 2), ("E", "energy", 1))
CROSS_PRODUCT_SAMPLE_SIZE = sum(
    quota for _product in CROSS_PRODUCT_CODES for _kind, _name, quota in CROSS_PRODUCT_KIND_QUOTAS
)
HEART_COLOR_IDS = ("heart01", "heart02", "heart03", "heart04", "heart05", "heart06")
REQUIRED_HEART_COLOR_IDS = ("heart0", *HEART_COLOR_IDS)
HEART_COLOR_DEFINITIONS = {
    "heart0": {"display_ja": "任意色", "display_en": "any", "display_zh": "任意颜色"},
    "heart01": {"display_ja": "桃", "display_en": "pink", "display_zh": "粉色"},
    "heart02": {"display_ja": "赤", "display_en": "red", "display_zh": "红色"},
    "heart03": {"display_ja": "黄", "display_en": "yellow", "display_zh": "黄色"},
    "heart04": {"display_ja": "緑", "display_en": "green", "display_zh": "绿色"},
    "heart05": {"display_ja": "青", "display_en": "blue", "display_zh": "蓝色"},
    "heart06": {"display_ja": "紫", "display_en": "purple", "display_zh": "紫色"},
}
CARD_FIELDS = [
    "card_id",
    "name",
    "card_type",
    "product",
    "rarity",
    "member_attributes",
    "live_attributes",
    "raw_effect_text",
    "image_url",
    "source_url",
    "fetched_at",
    "parser_version",
    "parse_notes",
]
COVERAGE_FIELD_SPECS = [
    ("card_id", None, "high", "Direct official card-number field."),
    ("name", None, "high", "Direct official detail heading."),
    ("card_type", None, "high", "Direct official card-type field."),
    ("product", None, "high", "Direct official product field."),
    ("rarity", None, "high", "Direct official rarity field."),
    (
        "member_attributes.cost",
        {"メンバー"},
        "high",
        "Applicable only to Member cards.",
    ),
    (
        "member_attributes.heart_by_color",
        {"メンバー"},
        "high",
        "Applicable only to Member cards; requires at least one observed Heart value.",
    ),
    (
        "member_attributes.blade",
        {"メンバー"},
        "high",
        "Applicable only to Member cards.",
    ),
    (
        "member_attributes.blade_heart_color",
        {"メンバー"},
        "high",
        "Applicable only when the Member exposes a Blade Heart icon.",
    ),
    (
        "live_attributes.score",
        {"ライブ"},
        "high",
        "Applicable only to Live cards.",
    ),
    (
        "live_attributes.required_heart_by_color",
        {"ライブ"},
        "high",
        "Applicable only to Live cards; requires at least one observed requirement.",
    ),
    (
        "live_attributes.blade_heart_color",
        {"ライブ"},
        "high",
        "Applicable only when the Live card exposes a Blade Heart icon.",
    ),
    (
        "live_attributes.special_blade_hearts",
        {"ライブ"},
        "high",
        "Applicable only when the Live card exposes official special Blade Heart icons.",
    ),
    (
        "raw_effect_text",
        {"メンバー", "ライブ"},
        "medium",
        "Preserves visible Japanese text and inline official icon alt text.",
    ),
    ("image_url", None, "high", "Direct official card image URL."),
    ("source_url", None, "high", "Stable card-number search URL."),
    ("fetched_at", None, "high", "UTC fetch timestamp."),
    ("parser_version", None, "high", "Importer spike parser version."),
    ("parse_notes", None, "high", "Structured parser audit notes."),
]
GENERATED_SAMPLE_FILES = [
    Path("raw/cardlist-sample.html"),
    Path("raw/card-searchresults-sample.html"),
    Path("raw/card-detail-sample-001.html"),
    Path("raw/card-searchresults-member.html"),
    Path("raw/card-searchresults-live.html"),
    Path("raw/card-searchresults-energy.html"),
    Path("raw/card-detail-member-sample.html"),
    Path("raw/card-detail-live-sample.html"),
    Path("raw/card-detail-energy-sample.html"),
    Path("raw/cardlist-api-sample.json"),
    Path("normalized/cards-sample.json"),
    Path("reports/importer-spike-report.md"),
    Path("reports/field-coverage-report.md"),
]
ATTRIBUTE_PATTERN = re.compile(
    r"""(?P<name>href|src|action)\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)
URL_PATTERN = re.compile(r"""https?://[^\s"'<>\\]+""", re.IGNORECASE)
QUOTED_CARDLIST_PATH_PATTERN = re.compile(r"""["'](?P<value>/cardlist/[^"']+)["']""")
CARD_RESULT_PATTERN = re.compile(
    r"""<div\b(?P<tag>[^>]*\bcard=(?P<quote>["'])(?P<card>.*?)(?P=quote)[^>]*)>\s*"""
    r"""<img\b(?P<imgtag>[^>]*)>""",
    re.IGNORECASE | re.DOTALL,
)
SCRIPT_DATA_PATTERN = re.compile(
    r"<script[^>]*>(?P<body>.*?)</script>", re.IGNORECASE | re.DOTALL
)
TAG_PATTERN = re.compile(r"<[^>]+>")
DETAIL_FIELD_PATTERN = re.compile(
    r"""<dt\b[^>]*>(?P<label>.*?)</dt>\s*<dd\b[^>]*>(?P<value>.*?)</dd>""",
    re.IGNORECASE | re.DOTALL,
)
INFO_TEXT_PATTERN = re.compile(
    r"""<p\b[^>]*class=(?P<quote>["'])[^"']*\binfo-Text\b[^"']*(?P=quote)[^>]*>"""
    r"""(?P<value>.*?)</p>""",
    re.IGNORECASE | re.DOTALL,
)
INFO_HEADING_PATTERN = re.compile(
    r"""<p\b[^>]*class=(?P<quote>["'])[^"']*\binfo-Heading\b[^"']*(?P=quote)[^>]*>"""
    r"""(?P<value>.*?)</p>""",
    re.IGNORECASE | re.DOTALL,
)
RELATED_CARD_PATTERN = re.compile(
    r"""relatedCard\(\s*(?P<quote>["'])(?P<card_id>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None
    body: str | bytes
    content_type: str
    fetched_at: str
    error: str | None = None


class OfficialSiteSession:
    def __init__(self, base_domain: str, delay: float) -> None:
        self.base_domain = base_domain
        self.delay = delay
        self.last_request_at: float | None = None
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )

    def fetch(
        self,
        url: str,
        *,
        form_data: dict[str, str] | None = None,
        referer: str | None = None,
        ajax: bool = False,
    ) -> FetchResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != self.base_domain:
            return FetchResult(
                url,
                None,
                "",
                "",
                utc_now(),
                error="refused non-official or non-HTTPS URL",
            )

        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)

        headers = {
            "User-Agent": "loveca-simulation-importer-spike/0.2 (+local research)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"
        data = None
        if form_data is not None:
            data = urllib.parse.urlencode(form_data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"

        result = fetch_text(url, opener=self.opener, data=data, headers=headers)
        self.last_request_at = time.monotonic()
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample the official LoveCA card list.")
    parser.add_argument(
        "--profile",
        choices=("baseline", "cross-product"),
        default="baseline",
        help="Sampling profile. Cross-product writes separate coverage artifacts.",
    )
    parser.add_argument("--limit", type=int, default=12, help="Number of cards to sample, 10-30.")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between sequential requests.",
    )
    args = parser.parse_args(argv)

    if not 10 <= args.limit <= 30:
        parser.error("--limit must be between 10 and 30")
    if args.delay < 1.0:
        parser.error("--delay must be at least 1.0 second")
    if args.profile == "cross-product":
        if args.limit != CROSS_PRODUCT_SAMPLE_SIZE:
            parser.error(
                f"--profile cross-product requires --limit {CROSS_PRODUCT_SAMPLE_SIZE}"
            )
        return run_cross_product_profile(limit=args.limit, delay=args.delay)

    output_dirs = prepare_output_dirs(OUTPUT_ROOT)
    card_list_url = read_card_list_url(MANIFEST_PATH)
    base_domain = urllib.parse.urlparse(card_list_url).netloc
    session = OfficialSiteSession(base_domain, args.delay)

    inspected_pages: list[dict[str, Any]] = []
    raw_files: list[str] = []
    normalized_cards: list[dict[str, Any]] = []

    card_list_result = session.fetch(card_list_url)
    inspected_pages.append(page_record(card_list_result, "card_list"))

    if card_list_result.error is not None:
        write_json(output_dirs["normalized"] / "cards-sample.json", normalized_cards)
        write_spike_report(
            output_dirs["reports"] / "importer-spike-report.md",
            card_list_url=card_list_url,
            inspected_pages=inspected_pages,
            raw_files=raw_files,
            discovered=empty_discovery(),
            normalized_cards=normalized_cards,
            access_limited=True,
            requested_count=args.limit,
        )
        write_field_coverage(output_dirs["reports"] / "field-coverage-report.md", normalized_cards)
        print("Card list access failed; wrote access-limited spike reports.")
        return 0

    card_list_html = ensure_text(card_list_result.body)
    card_list_sample = output_dirs["raw"] / "cardlist-sample.html"
    card_list_sample.write_text(card_list_html, encoding="utf-8")
    raw_files.append(str(card_list_sample))

    discovered = inspect_html(card_list_url, card_list_html, base_domain)
    sample_counts = allocate_sample_counts(args.limit)
    detail_endpoint = urllib.parse.urljoin(card_list_url, "/cardlist/detail/")

    for card_kind, kind_name, _weight in CARD_KIND_SAMPLES:
        kind_limit = sample_counts[card_kind]
        search_result_url = make_card_kind_search_url(card_list_url, card_kind)
        search_result = session.fetch(search_result_url, referer=card_list_url)
        inspected_pages.append(page_record(search_result, f"card_search_results_{kind_name}"))
        if search_result.error is not None:
            continue

        search_result_html = ensure_text(search_result.body)
        search_result_sample = output_dirs["raw"] / f"card-searchresults-{kind_name}.html"
        search_result_sample.write_text(search_result_html, encoding="utf-8")
        raw_files.append(str(search_result_sample))
        discovered = merge_discovery(
            discovered,
            inspect_html(search_result_url, search_result_html, base_domain),
        )

        candidates = normalize_cards_from_search_results(
            search_result_url=search_result_url,
            search_result_html=search_result_html,
            fetched_at=search_result.fetched_at,
            limit=kind_limit,
        )
        representative_written = False
        for index, candidate in enumerate(candidates, start=1):
            card_id = candidate["card_id"]
            detail_request_url = make_detail_request_url(detail_endpoint)
            detail_result = session.fetch(
                detail_request_url,
                form_data={"cardno": card_id},
                referer=search_result_url,
                ajax=True,
            )
            inspected_pages.append(
                page_record(detail_result, f"card_detail_{kind_name}_{index:03d}")
            )
            detail_html = ensure_text(detail_result.body)
            detail_rejected = not detail_html.strip() or detail_html.strip() == "NG"
            if detail_result.error is not None or detail_rejected:
                candidate["parse_notes"]["detail_error"] = (
                    detail_result.error or "empty or rejected detail response"
                )
                normalized_cards.append(candidate)
                continue

            if not representative_written:
                detail_sample_path = (
                    output_dirs["raw"] / f"card-detail-{kind_name}-sample.html"
                )
                detail_sample_path.write_text(detail_html, encoding="utf-8")
                raw_files.append(str(detail_sample_path))
                representative_written = True

            detail_card = normalize_card(
                candidate["source_url"],
                detail_html,
                detail_result.fetched_at,
                detail_endpoint=detail_endpoint,
            )
            normalized_cards.append(merge_card_candidate(candidate, detail_card))

    normalized_cards = normalized_cards[: args.limit]
    write_json(output_dirs["normalized"] / "cards-sample.json", normalized_cards)
    write_spike_report(
        output_dirs["reports"] / "importer-spike-report.md",
        card_list_url=card_list_url,
        inspected_pages=inspected_pages,
        raw_files=raw_files,
        discovered=discovered,
        normalized_cards=normalized_cards,
        access_limited=not normalized_cards,
        requested_count=args.limit,
    )
    write_field_coverage(output_dirs["reports"] / "field-coverage-report.md", normalized_cards)

    print(f"Wrote {len(normalized_cards)} sampled card records to data_samples/normalized.")
    return 0


def run_cross_product_profile(*, limit: int, delay: float) -> int:
    output_dirs = prepare_cross_product_output_dirs(OUTPUT_ROOT)
    card_list_url = read_card_list_url(MANIFEST_PATH)
    base_domain = urllib.parse.urlparse(card_list_url).netloc
    session = OfficialSiteSession(base_domain, delay)
    detail_endpoint = urllib.parse.urljoin(card_list_url, "/cardlist/detail/")

    inspected_pages: list[dict[str, Any]] = []
    raw_files: list[str] = []
    normalized_cards: list[dict[str, Any]] = []
    bucket_results: list[dict[str, Any]] = []

    card_list_result = session.fetch(card_list_url)
    inspected_pages.append(page_record(card_list_result, "card_list"))
    if card_list_result.error is not None:
        write_cross_product_artifacts(
            output_dirs=output_dirs,
            card_list_url=card_list_url,
            inspected_pages=inspected_pages,
            raw_files=raw_files,
            cards=normalized_cards,
            bucket_results=bucket_results,
            requested_count=limit,
            access_limited=True,
        )
        print("Card list access failed; wrote access-limited cross-product reports.")
        return 0

    card_list_html = ensure_text(card_list_result.body)
    card_list_sample = output_dirs["raw"] / "cardlist.html"
    card_list_sample.write_text(card_list_html, encoding="utf-8")
    raw_files.append(str(card_list_sample))

    for product_code in CROSS_PRODUCT_CODES:
        for card_kind, kind_name, quota in CROSS_PRODUCT_KIND_QUOTAS:
            search_result_url = make_product_card_kind_search_url(
                card_list_url,
                product_code,
                card_kind,
            )
            search_result = session.fetch(search_result_url, referer=card_list_url)
            inspected_pages.append(
                page_record(
                    search_result,
                    f"search_{product_code.lower()}_{kind_name}",
                )
            )
            search_html = ensure_text(search_result.body)
            raw_search_path = (
                output_dirs["raw"]
                / f"{product_code.lower()}-{kind_name}-search.html"
            )
            if search_result.error is None:
                raw_search_path.write_text(search_html, encoding="utf-8")
                raw_files.append(str(raw_search_path))

            candidates = []
            if search_result.error is None:
                candidates = normalize_cards_from_search_results(
                    search_result_url=search_result_url,
                    search_result_html=search_html,
                    fetched_at=search_result.fetched_at,
                    limit=100,
                )
            candidate_queue = select_distinct_card_codes(candidates, len(candidates))
            representative_written = False
            successful = 0
            attempted = 0
            detail_errors = 0
            type_mismatches = 0
            pagination_used = False
            page_two_loaded = False
            queue_index = 0

            while successful < quota:
                if queue_index >= len(candidate_queue):
                    if page_two_loaded or search_result.error is not None:
                        break
                    page_two_loaded = True
                    pagination_used = True
                    incremental_url = make_incremental_search_url(
                        card_list_url,
                        product_code,
                        card_kind,
                        page=2,
                    )
                    incremental_result = session.fetch(
                        incremental_url,
                        referer=search_result_url,
                        ajax=True,
                    )
                    inspected_pages.append(
                        page_record(
                            incremental_result,
                            f"search_{product_code.lower()}_{kind_name}_page_2",
                        )
                    )
                    if incremental_result.error is not None:
                        break

                    incremental_html = ensure_text(incremental_result.body)
                    incremental_path = (
                        output_dirs["raw"]
                        / f"{product_code.lower()}-{kind_name}-search-page-2.html"
                    )
                    incremental_path.write_text(incremental_html, encoding="utf-8")
                    raw_files.append(str(incremental_path))
                    more_candidates = normalize_cards_from_search_results(
                        search_result_url=search_result_url,
                        search_result_html=incremental_html,
                        fetched_at=incremental_result.fetched_at,
                        limit=100,
                    )
                    known_codes = {
                        candidate["card_code"] for candidate in candidate_queue
                    }
                    for candidate in select_distinct_card_codes(
                        more_candidates,
                        len(more_candidates),
                    ):
                        if candidate["card_code"] not in known_codes:
                            candidate_queue.append(candidate)
                            known_codes.add(candidate["card_code"])
                    if queue_index >= len(candidate_queue):
                        break
                    continue

                candidate = candidate_queue[queue_index]
                queue_index += 1
                attempted += 1
                detail_result = session.fetch(
                    make_detail_request_url(detail_endpoint),
                    form_data={"cardno": candidate["card_id"]},
                    referer=search_result_url,
                    ajax=True,
                )
                inspected_pages.append(
                    page_record(
                        detail_result,
                        f"detail_{product_code.lower()}_{kind_name}_{attempted:02d}",
                    )
                )
                detail_html = ensure_text(detail_result.body)
                detail_rejected = not detail_html.strip() or detail_html.strip() == "NG"
                if detail_result.error is not None or detail_rejected:
                    detail_errors += 1
                    continue

                detail_card = normalize_card(
                    candidate["source_url"],
                    detail_html,
                    detail_result.fetched_at,
                    detail_endpoint=detail_endpoint,
                )
                merged = merge_card_candidate(candidate, detail_card)
                if card_type_to_kind(merged.get("card_type")) != card_kind:
                    type_mismatches += 1
                    continue

                if not representative_written:
                    detail_path = (
                        output_dirs["raw"]
                        / f"{product_code.lower()}-{kind_name}-detail.html"
                    )
                    detail_path.write_text(detail_html, encoding="utf-8")
                    raw_files.append(str(detail_path))
                    representative_written = True

                normalized_cards.append(
                    enrich_cross_product_card(
                        merged,
                        product_code=product_code,
                        detail_html=detail_html,
                    )
                )
                successful += 1

            bucket_results.append(
                {
                    "product_code": product_code,
                    "card_kind": card_kind,
                    "kind_name": kind_name,
                    "requested": quota,
                    "selected": attempted,
                    "successful": successful,
                    "detail_errors": detail_errors,
                    "type_mismatches": type_mismatches,
                    "pagination_used": pagination_used,
                    "search_error": search_result.error,
                }
            )

    write_cross_product_artifacts(
        output_dirs=output_dirs,
        card_list_url=card_list_url,
        inspected_pages=inspected_pages,
        raw_files=raw_files,
        cards=normalized_cards,
        bucket_results=bucket_results,
        requested_count=limit,
        access_limited=not normalized_cards,
    )
    print(
        f"Wrote {len(normalized_cards)} cross-product card records "
        "to data_samples/normalized."
    )
    return 0


def prepare_output_dirs(root: Path) -> dict[str, Path]:
    dirs = {
        "raw": root / "raw",
        "normalized": root / "normalized",
        "reports": root / "reports",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    for relative_path in GENERATED_SAMPLE_FILES:
        path = root / relative_path
        if path.exists():
            path.unlink()
    return dirs


def prepare_cross_product_output_dirs(root: Path) -> dict[str, Path]:
    dirs = {
        "raw": root / "raw" / "cross-product",
        "normalized": root / "normalized",
        "reports": root / "reports",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    raw_root = dirs["raw"]
    for path in sorted(raw_root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()

    for path in (
        dirs["normalized"] / "cards-cross-product-sample.json",
        dirs["reports"] / "cross-product-coverage-report.md",
        dirs["reports"] / "cross-product-field-coverage.md",
    ):
        if path.exists():
            path.unlink()
    return dirs


def allocate_sample_counts(limit: int) -> dict[str, int]:
    total_weight = sum(weight for _kind, _name, weight in CARD_KIND_SAMPLES)
    raw_counts = {
        kind: limit * weight / total_weight
        for kind, _name, weight in CARD_KIND_SAMPLES
    }
    counts = {kind: int(raw_counts[kind]) for kind, _name, _weight in CARD_KIND_SAMPLES}
    remaining = limit - sum(counts.values())
    ranking = sorted(
        CARD_KIND_SAMPLES,
        key=lambda item: (raw_counts[item[0]] - counts[item[0]], item[2]),
        reverse=True,
    )
    for index in range(remaining):
        counts[ranking[index][0]] += 1
    return counts


def make_card_kind_search_url(card_list_url: str, card_kind: str) -> str:
    search_url = urllib.parse.urljoin(card_list_url, "/cardlist/searchresults/")
    return f"{search_url}?{urllib.parse.urlencode({'card_kind': card_kind})}"


def make_product_card_kind_search_url(
    card_list_url: str,
    product_code: str,
    card_kind: str,
) -> str:
    search_url = urllib.parse.urljoin(card_list_url, "/cardlist/searchresults/")
    query = urllib.parse.urlencode(
        {"title": product_code, "card_kind": card_kind}
    )
    return f"{search_url}?{query}"


def make_incremental_search_url(
    card_list_url: str,
    product_code: str,
    card_kind: str,
    *,
    page: int,
) -> str:
    incremental_url = urllib.parse.urljoin(card_list_url, "/cardlist/cardsearch_ex")
    query = urllib.parse.urlencode(
        {
            "title": product_code,
            "card_kind": card_kind,
            "view": "image",
            "page": page,
        }
    )
    return f"{incremental_url}?{query}"


def make_detail_request_url(detail_endpoint: str) -> str:
    cache_buster = int(time.time() * 1000)
    return f"{detail_endpoint}?{urllib.parse.urlencode({'t': cache_buster})}"


def derive_card_code(card_id: str | None) -> str | None:
    if not card_id:
        return None
    match = re.match(
        r"^(?P<card_code>.+?-(?:E)?\d{2,4})(?:-.+)?$",
        card_id,
        re.IGNORECASE,
    )
    return match.group("card_code") if match else card_id


def select_distinct_card_codes(
    candidates: list[dict[str, Any]],
    quota: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for candidate in candidates:
        card_code = derive_card_code(candidate.get("card_id"))
        if card_code is None or card_code in seen_codes:
            continue
        selected.append(candidate | {"card_code": card_code})
        seen_codes.add(card_code)
        if len(selected) >= quota:
            break
    return selected


def extract_related_printing_ids(detail_html: str) -> list[str]:
    return unique_list(
        [
            html.unescape(match.group("card_id")).strip()
            for match in RELATED_CARD_PATTERN.finditer(detail_html)
        ]
    )


def enrich_cross_product_card(
    card: dict[str, Any],
    *,
    product_code: str,
    detail_html: str | None,
) -> dict[str, Any]:
    enriched = dict(card)
    card_id = enriched.get("card_id")
    related_printing_ids = (
        extract_related_printing_ids(detail_html) if detail_html else []
    )
    enriched["card_code"] = derive_card_code(card_id)
    enriched["product_code"] = product_code
    enriched["related_printing_ids"] = related_printing_ids
    enriched["printing_group_ids"] = unique_list(
        ([card_id] if card_id else []) + related_printing_ids
    )
    parse_notes = dict(enriched.get("parse_notes") or {})
    parse_notes.update(
        {
            "sample_profile": "cross-product",
            "requested_product_code": product_code,
            "source_field_labels": (
                sorted(extract_detail_fields(detail_html)) if detail_html else []
            ),
        }
    )
    enriched["parse_notes"] = parse_notes
    return enriched


def merge_card_candidate(
    candidate: dict[str, Any],
    detail_card: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(detail_card)
    for field in ("card_id", "name", "image_url"):
        if merged.get(field) in (None, ""):
            merged[field] = candidate.get(field)
    merged["source_url"] = candidate["source_url"]
    merged["parse_notes"]["search_result_url"] = candidate["parse_notes"].get(
        "search_result_url"
    )
    return merged


def read_card_list_url(manifest_path: Path) -> str:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    in_card_list = False
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("  card_list:"):
            in_card_list = True
            continue
        if in_card_list and line.startswith("  ") and not line.startswith("    "):
            in_card_list = False
        if in_card_list and line.strip().startswith("url:"):
            _, value = line.split(":", 1)
            return value.strip().strip('"').strip("'")

    raise ValueError("Manifest does not define sources.card_list.url")


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def fetch_text(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> FetchResult:
    fetched_at = utc_now()
    request_headers = headers or {
        "User-Agent": "loveca-simulation-importer-spike/0.2 (+local research)",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
    )
    url_opener = opener or urllib.request.build_opener()
    try:
        with url_opener.open(request, timeout=20) as response:
            content_type = response.headers.get("content-type", "")
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            if content_type.lower().startswith("text/") or "json" in content_type.lower():
                body: str | bytes = data.decode(charset, errors="replace")
            else:
                body = data
            return FetchResult(url, response.status, body, content_type, fetched_at)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return FetchResult(
            url,
            exc.code,
            body,
            exc.headers.get("content-type", ""),
            fetched_at,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except urllib.error.URLError as exc:
        return FetchResult(url, None, "", "", fetched_at, error=f"URL error: {exc.reason}")
    except TimeoutError:
        return FetchResult(url, None, "", "", fetched_at, error="timeout")


def ensure_text(body: str | bytes) -> str:
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return body


def page_record(result: FetchResult, page_type: str) -> dict[str, Any]:
    return {
        "page_type": page_type,
        "url": result.url,
        "status": result.status,
        "content_type": result.content_type,
        "fetched_at": result.fetched_at,
        "error": result.error,
    }


def empty_discovery() -> dict[str, Any]:
    return {
        "detail_page_urls": [],
        "search_result_urls": [],
        "pagination_urls": [],
        "same_domain_api_candidates": [],
        "forms": [],
        "script_sources": [],
        "image_urls": [],
        "embedded_json_blocks": 0,
    }


def inspect_html(base_url: str, content: str, base_domain: str) -> dict[str, Any]:
    discovered = empty_discovery()
    links = collect_attribute_urls(base_url, content)
    path_prefix = urllib.parse.urlparse(base_url).path.rstrip("/") + "/"

    for url in links:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != base_domain:
            continue
        path = parsed.path
        lower_url = url.lower()
        if is_search_result_url(path):
            discovered["search_result_urls"].append(url)
        if is_detail_url(parsed):
            discovered["detail_page_urls"].append(url)
        elif path.startswith(path_prefix) and path.rstrip("/") != path_prefix.rstrip("/"):
            if not is_static_asset(path) and not is_search_result_url(path):
                discovered["detail_page_urls"].append(url)
        if looks_like_pagination(url):
            discovered["pagination_urls"].append(url)
        if looks_like_api(url):
            discovered["same_domain_api_candidates"].append(url)
        if is_image(path):
            discovered["image_urls"].append(url)

    for match in re.finditer(r"<form\b(?P<tag>[^>]*)>", content, flags=re.IGNORECASE | re.DOTALL):
        tag = match.group("tag")
        action = extract_attribute(tag, "action")
        method = extract_attribute(tag, "method") or "GET"
        discovered["forms"].append(
            {
                "method": method.upper(),
                "action": normalize_url(base_url, action) if action else base_url,
            }
        )

    for match in re.finditer(
        r"<script\b(?P<tag>[^>]*)>", content, flags=re.IGNORECASE | re.DOTALL
    ):
        src = extract_attribute(match.group("tag"), "src")
        if src:
            url = normalize_url(base_url, src)
            if urllib.parse.urlparse(url).netloc == base_domain:
                discovered["script_sources"].append(url)
                if looks_like_api(url):
                    discovered["same_domain_api_candidates"].append(url)

    for match in SCRIPT_DATA_PATTERN.finditer(content):
        if looks_like_embedded_json(match.group("body")):
            discovered["embedded_json_blocks"] += 1

    return {
        key: unique_list(value) if isinstance(value, list) else value
        for key, value in discovered.items()
    }


def collect_attribute_urls(base_url: str, content: str) -> list[str]:
    urls: list[str] = []
    for match in ATTRIBUTE_PATTERN.finditer(content):
        value = html.unescape(match.group("value")).strip()
        if value and not value.startswith(("#", "mailto:", "tel:", "javascript:")):
            urls.append(normalize_url(base_url, value))
    for match in URL_PATTERN.finditer(content):
        urls.append(match.group(0))
    for match in QUOTED_CARDLIST_PATH_PATTERN.finditer(content):
        urls.append(
            normalize_url(
                base_url,
                html.unescape(match.group("value")).strip(),
            )
        )
    return unique_list(urls)


def normalize_url(base_url: str, value: str) -> str:
    return urllib.parse.urljoin(base_url, value)


def extract_attribute(tag: str, attr_name: str) -> str | None:
    pattern = re.compile(
        rf"""{re.escape(attr_name)}\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(tag)
    if match is None:
        return None
    return html.unescape(match.group("value")).strip()


def unique_list(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = (
            json.dumps(value, sort_keys=True, ensure_ascii=False)
            if isinstance(value, dict)
            else str(value)
        )
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def is_static_asset(path: str) -> bool:
    return path.lower().endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"))


def is_image(path: str) -> bool:
    return path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def is_search_result_url(path: str) -> bool:
    return "/cardlist/searchresults" in path.lower()


def is_detail_url(parsed: urllib.parse.ParseResult) -> bool:
    query = urllib.parse.parse_qs(parsed.query)
    return "/cardlist/detail" in parsed.path.lower() or "cardno" in query


def looks_like_pagination(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    path = parsed.path.lower()
    return any(key in query for key in ("page", "paged", "p")) or "/page/" in path


def looks_like_api(url: str) -> bool:
    lower_url = url.lower()
    return any(
        token in lower_url
        for token in ("api", "ajax", "json", "wp-json", "cardsearch_ex", "/cardlist/detail/")
    )


def looks_like_embedded_json(body: str) -> bool:
    stripped = body.strip()
    return (
        stripped.startswith("{")
        or stripped.startswith("[")
        or "__NEXT_DATA__" in body
        or "application/json" in body
    )


def fetch_api_sample_if_available(
    discovered: dict[str, Any],
    base_domain: str,
    output_dirs: dict[str, Path],
    inspected_pages: list[dict[str, Any]],
) -> Path | None:
    for candidate in discovered["same_domain_api_candidates"]:
        if urllib.parse.urlparse(candidate).netloc != base_domain:
            continue
        result = fetch_text(candidate)
        inspected_pages.append(page_record(result, "api_candidate"))
        if result.error is None and "json" in result.content_type.lower():
            output_path = output_dirs["raw"] / "cardlist-api-sample.json"
            output_path.write_text(ensure_text(result.body), encoding="utf-8")
            return output_path
        return None
    return None


def merge_discovery(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, list):
            merged[key] = unique_list(list(merged.get(key, [])) + value)
        elif isinstance(value, int):
            merged[key] = int(merged.get(key, 0)) + value
        else:
            merged[key] = value
    return merged


def normalize_cards_from_search_results(
    search_result_url: str, search_result_html: str, fetched_at: str, limit: int
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for match in CARD_RESULT_PATTERN.finditer(search_result_html):
        if len(cards) >= limit:
            break
        card_id = html.unescape(match.group("card")).strip()
        image_src = extract_attribute(match.group("imgtag"), "src")
        name = extract_attribute(match.group("imgtag"), "alt")
        source_url = make_card_source_url(search_result_url, card_id)
        cards.append(
            empty_card(
                source_url=source_url,
                fetched_at=fetched_at,
                parse_notes={
                    "source": "card_search_result_page",
                    "search_result_url": search_result_url,
                    "detail_endpoint": "/cardlist/detail/",
                    "detail_method": "POST",
                    "warning": (
                        "Detail fields require the official same-domain AJAX endpoint."
                    ),
                },
            )
            | {
                "card_id": card_id or None,
                "name": name or None,
                "image_url": normalize_url(search_result_url, image_src) if image_src else None,
            }
        )
    return cards


def make_card_source_url(search_result_url: str, card_id: str) -> str:
    parsed = urllib.parse.urlparse(search_result_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["cardno"] = [card_id]
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
    )


def normalize_cards_from_listing(
    card_list_url: str, card_list_html: str, fetched_at: str, limit: int
) -> list[dict[str, Any]]:
    text = html_to_lines(card_list_html)
    card_ids = unique_list(find_card_ids("\n".join(text)))[:limit]
    if not card_ids:
        return []

    cards: list[dict[str, Any]] = []
    for card_id in card_ids:
        cards.append(
            empty_card(
                source_url=card_list_url,
                fetched_at=fetched_at,
                parse_notes={
                    "source": "card_list_page",
                    "candidate_card_id": card_id,
                    "warning": "No detail page was discovered; fields are not inferred.",
                },
            )
            | {"card_id": card_id}
        )
    return cards


def normalize_card(
    source_url: str,
    detail_html: str,
    fetched_at: str,
    *,
    detail_endpoint: str = "/cardlist/detail/",
) -> dict[str, Any]:
    fields = extract_detail_fields(detail_html)
    field_text = {label: value["text"] for label, value in fields.items()}
    field_html = {label: value["html"] for label, value in fields.items()}
    image_url = first_image_url(source_url, detail_html)
    raw_effect_text = extract_official_effect_text(detail_html)
    candidate_effect_blocks = split_candidate_effect_blocks(raw_effect_text)
    card_type = field_text.get("カードタイプ")
    known_labels = {
        "収録商品",
        "カードタイプ",
        "コスト",
        "基本ハート",
        "ブレードハート",
        "ブレード",
        "スコア",
        "必要ハート",
        "特殊ハート",
        "レアリティ",
        "カード番号",
    }

    parse_notes: dict[str, Any] = {
        "source": "card_detail_ajax",
        "detail_endpoint": detail_endpoint,
        "detail_method": "POST",
        "candidate_effect_blocks": candidate_effect_blocks,
        "unmapped_fields": [
            {"label": label, "raw_text": value["text"] or None}
            for label, value in fields.items()
            if label not in known_labels
        ],
        "unmapped_icons": collect_unmapped_card_icons(field_html),
    }

    return {
        "card_id": field_text.get("カード番号"),
        "name": extract_detail_name(detail_html),
        "card_type": card_type,
        "product": field_text.get("収録商品"),
        "rarity": field_text.get("レアリティ"),
        "member_attributes": member_attributes_for(card_type, field_text, field_html),
        "live_attributes": live_attributes_for(card_type, field_text, field_html),
        "raw_effect_text": raw_effect_text,
        "image_url": image_url,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "parse_notes": parse_notes,
    }


def extract_detail_fields(detail_html: str) -> dict[str, dict[str, str]]:
    fields: dict[str, dict[str, str]] = {}
    for match in DETAIL_FIELD_PATTERN.finditer(detail_html):
        label = clean_text(match.group("label"))
        value_html = match.group("value")
        if label:
            fields[label] = {
                "html": value_html,
                "text": text_with_image_alts(value_html),
            }
    return fields


def extract_detail_name(detail_html: str) -> str | None:
    match = INFO_HEADING_PATTERN.search(detail_html)
    if match is not None:
        return clean_text(match.group("value")) or None
    lines = html_to_lines(detail_html)
    return extract_name(detail_html, lines)


def extract_official_effect_text(detail_html: str) -> str | None:
    match = INFO_TEXT_PATTERN.search(detail_html)
    if match is None:
        return None
    return text_with_image_alts(match.group("value")) or None


def text_with_image_alts(fragment: str) -> str:
    def replace_image(match: re.Match[str]) -> str:
        alt = extract_attribute(match.group("tag"), "alt")
        return f"【{alt}】" if alt else " "

    with_alts = re.sub(
        r"<img\b(?P<tag>[^>]*)>",
        replace_image,
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return clean_text(with_alts)


def collect_unmapped_card_icons(
    field_html: dict[str, str],
) -> list[dict[str, str]]:
    unmapped: list[dict[str, str]] = []
    relevant_fields = ("基本ハート", "必要ハート", "ブレードハート", "特殊ハート")
    known_heart_classes = {
        "heart0",
        *HEART_COLOR_IDS,
        *(f"b_{color_id}" for color_id in HEART_COLOR_IDS),
    }
    known_alt_patterns = (r"ALL\d+", r"ドロー\d+", r"スコア\d+")

    for source_field in relevant_fields:
        fragment = field_html.get(source_field, "")
        class_tokens = re.findall(
            r"""\b(?:b_)?heart[A-Za-z0-9_-]*\b""",
            fragment,
            flags=re.IGNORECASE,
        )
        for source_value in class_tokens:
            if source_value.lower() not in {item.lower() for item in known_heart_classes}:
                unmapped.append(
                    {
                        "source_field": source_field,
                        "source_kind": "class",
                        "source_value": source_value,
                        "review_status": "review_required",
                    }
                )

        for image_match in re.finditer(
            r"<img\b(?P<tag>[^>]*)>",
            fragment,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            source_alt = extract_attribute(image_match.group("tag"), "alt")
            if not source_alt:
                continue
            if not any(
                re.fullmatch(pattern, source_alt, re.IGNORECASE)
                for pattern in known_alt_patterns
            ):
                unmapped.append(
                    {
                        "source_field": source_field,
                        "source_kind": "alt",
                        "source_value": source_alt,
                        "review_status": "review_required",
                    }
                )
    return unique_list(unmapped)


def empty_card(source_url: str, fetched_at: str, parse_notes: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": None,
        "name": None,
        "card_type": None,
        "product": None,
        "rarity": None,
        "member_attributes": None,
        "live_attributes": None,
        "raw_effect_text": None,
        "image_url": None,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "parse_notes": parse_notes,
    }


def html_to_lines(content: str) -> list[str]:
    content = re.sub(r"<script\b.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    text = TAG_PATTERN.sub("\n", content)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def empty_heart_color_map(color_ids: tuple[str, ...] = HEART_COLOR_IDS) -> dict[str, int | None]:
    return {color_id: None for color_id in color_ids}


def member_attributes_for(
    card_type: str | None,
    field_text: dict[str, str],
    field_html: dict[str, str],
) -> dict[str, Any] | None:
    if card_type != "メンバー":
        return None
    return {
        "cost": parse_integer(field_text.get("コスト")),
        "heart_by_color": extract_heart_values(
            field_html.get("基本ハート", ""),
            HEART_COLOR_IDS,
        ),
        "blade": parse_integer(field_text.get("ブレード")),
        "blade_heart_color": extract_blade_heart_color(
            field_html.get("ブレードハート", "")
        ),
    }


def live_attributes_for(
    card_type: str | None,
    field_text: dict[str, str],
    field_html: dict[str, str],
) -> dict[str, Any] | None:
    if card_type != "ライブ":
        return None
    blade_heart_html = field_html.get("ブレードハート", "")
    special_blade_hearts = extract_special_blade_hearts(
        blade_heart_html,
        source_field="ブレードハート",
        allowed_effect_types={"all_color"},
    )
    special_blade_hearts.extend(
        extract_special_blade_hearts(
            field_html.get("特殊ハート", ""),
            source_field="特殊ハート",
        )
    )
    return {
        "required_heart_by_color": extract_heart_values(
            field_html.get("必要ハート", ""),
            REQUIRED_HEART_COLOR_IDS,
        ),
        "score": parse_integer(field_text.get("スコア")),
        "blade_heart_color": extract_blade_heart_color(blade_heart_html),
        "special_blade_hearts": special_blade_hearts or None,
    }


def extract_heart_values(
    field_html: str,
    color_ids: tuple[str, ...],
) -> dict[str, int | None]:
    values = empty_heart_color_map(color_ids)
    for match in re.finditer(
        r"""\bheart(?P<index>0|0[1-6])\b[^>]*>\s*(?P<value>\d+)\s*<""",
        field_html,
        re.IGNORECASE,
    ):
        color_id = f"heart{match.group('index')}"
        if color_id in values:
            values[color_id] = int(match.group("value"))
    return values


def parse_integer(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*", value)
    return int(match.group(1)) if match else None


def extract_blade_heart_color(field_html: str) -> str | None:
    if re.search(r"""\balt\s*=\s*(?P<quote>["'])ALL1(?P=quote)""", field_html, re.IGNORECASE):
        return "heart0"
    match = re.search(r"\bb_heart(?P<index>0[1-6])\b", field_html)
    if match is None:
        return None
    return f"heart{match.group('index')}"


def extract_special_blade_hearts(
    field_html: str,
    *,
    source_field: str = "特殊ハート",
    allowed_effect_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for match in re.finditer(
        r"<img\b(?P<tag>[^>]*)>",
        field_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        source_alt = extract_attribute(match.group("tag"), "alt")
        if not source_alt:
            continue

        entry: dict[str, Any] = {
            "effect_type": "unknown",
            "value": None,
            "resolution_timing": None,
            "source_alt": source_alt,
            "source_field": source_field,
        }
        known_patterns = (
            (r"スコア(?P<value>\d+)", "score", "live_judgment"),
            (r"ドロー(?P<value>\d+)", "draw", "after_yell"),
            (r"ALL(?P<value>\d+)", "all_color", "live_success_judgment"),
        )
        for pattern, effect_type, timing in known_patterns:
            value_match = re.fullmatch(pattern, source_alt, re.IGNORECASE)
            if value_match is not None:
                entry.update(
                    {
                        "effect_type": effect_type,
                        "value": int(value_match.group("value")),
                        "resolution_timing": timing,
                    }
                )
                break
        if allowed_effect_types is None or entry["effect_type"] in allowed_effect_types:
            entries.append(entry)
    return entries


def find_card_ids(text: str) -> list[str]:
    patterns = [
        r"\b[A-Z]{1,4}![A-Z0-9-]+-[A-Z0-9]{2,5}\b",
        r"\b[A-Z]{1,4}-[A-Z0-9]{1,6}-\d{3,4}[A-Z]?\b",
        r"\b[A-Z]{1,4}/\d{3}[A-Z]?\b",
    ]
    ids: list[str] = []
    for pattern in patterns:
        ids.extend(re.findall(pattern, text))
    return ids


def first_or_none(values: list[str]) -> str | None:
    return values[0] if values else None


def extract_name(detail_html: str, lines: list[str]) -> str | None:
    for pattern in (
        r"<h1[^>]*>(?P<name>.*?)</h1>",
        r"<h2[^>]*>(?P<name>.*?)</h2>",
        r"<title[^>]*>(?P<name>.*?)</title>",
    ):
        match = re.search(pattern, detail_html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = clean_text(match.group("name"))
            if value:
                return value.split("|")[0].strip()
    for line in lines[:20]:
        if not find_card_ids(line) and len(line) <= 80:
            return line
    return None


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_PATTERN.sub(" ", value))).strip()


def extract_labeled_value(lines: list[str], labels: list[str]) -> str | None:
    for index, line in enumerate(lines):
        normalized = line.strip()
        for label in labels:
            if normalized == label and index + 1 < len(lines):
                return lines[index + 1]
            if normalized.startswith(label):
                value = normalized[len(label) :].strip(" :：")
                if value:
                    return value
    return None


def extract_effect_text(lines: list[str]) -> str | None:
    labels = ["効果", "テキスト", "能力", "カードテキスト"]
    stop_labels = {
        "カードタイプ",
        "種類",
        "タイプ",
        "収録商品",
        "商品",
        "レアリティ",
        "コスト",
        "ハート",
        "ブレード",
        "ペンライト",
        "スコア",
    }
    for index, line in enumerate(lines):
        if line in labels or any(line.startswith(label + "：") for label in labels):
            first = line
            collected: list[str] = []
            for label in labels:
                if first.startswith(label):
                    inline = first[len(label) :].strip(" :：")
                    if inline:
                        collected.append(inline)
                    break
            for candidate in lines[index + 1 :]:
                if candidate in stop_labels:
                    break
                if collected and find_card_ids(candidate):
                    break
                collected.append(candidate)
                if len(collected) >= 8:
                    break
            return "\n".join(collected).strip() or None
    return None


def split_candidate_effect_blocks(raw_effect_text: str | None) -> list[str]:
    if not raw_effect_text:
        return []
    blocks = [
        block.strip()
        for block in re.split(r"(?:\n{2,}|(?=【[^】]+】)|(?=\[[^\]]+\]))", raw_effect_text)
        if block.strip()
    ]
    return blocks if len(blocks) > 1 else []


def first_image_url(source_url: str, detail_html: str) -> str | None:
    for match in ATTRIBUTE_PATTERN.finditer(detail_html):
        if match.group("name").lower() != "src":
            continue
        value = html.unescape(match.group("value")).strip()
        url = normalize_url(source_url, value)
        if is_image(urllib.parse.urlparse(url).path):
            return url
    return None


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_spike_report(
    path: Path,
    *,
    card_list_url: str,
    inspected_pages: list[dict[str, Any]],
    raw_files: list[str],
    discovered: dict[str, Any],
    normalized_cards: list[dict[str, Any]],
    access_limited: bool,
    requested_count: int,
) -> None:
    coverage_rows = field_coverage(normalized_cards)
    if access_limited:
        status = "access_limited"
    elif len(normalized_cards) < requested_count:
        status = "partial_sample"
    else:
        status = "sample_completed"
    card_type_counts = {
        card_type: sum(1 for card in normalized_cards if card.get("card_type") == card_type)
        for card_type in ("メンバー", "ライブ", "エネルギー")
    }
    unmapped_labels = sorted(
        {
            item["label"]
            for card in normalized_cards
            for item in card.get("parse_notes", {}).get("unmapped_fields", [])
            if item.get("label")
        }
    )
    lines = [
        "# Importer Spike Report",
        "",
        "## Summary",
        "",
        f"* Status: `{status}`",
        f"* Source: `{card_list_url}`",
        f"* Parser version: `{PARSER_VERSION}`",
        f"* Requested cards: `{requested_count}`",
        f"* Sampled cards: `{len(normalized_cards)}`",
        (
            "* Card types: "
            f"`{card_type_counts['メンバー']}` Member, "
            f"`{card_type_counts['ライブ']}` Live, "
            f"`{card_type_counts['エネルギー']}` Energy"
        ),
        "",
        "## Pages Inspected",
        "",
    ]
    if inspected_pages:
        for page in inspected_pages:
            lines.append(
                f"* `{page['page_type']}` `{page['status']}` {page['url']}"
                + (f" - {page['error']}" if page["error"] else "")
            )
    else:
        lines.append("* None.")

    lines.extend(
        [
            "",
            "## Data Extraction Method",
            "",
            "* Loaded `sources.card_list.url` from `data_sources/source-manifest.yaml`.",
            "* Used one cookie-aware official-site session for all requests.",
            "* Fetched pages sequentially with a minimum one-second request interval.",
            (
                "* Requested separate official search result pages with `card_kind=M`, "
                "`card_kind=L`, and `card_kind=E`."
            ),
            (
                "* Loaded card details through the official same-domain AJAX endpoint using "
                "`POST /cardlist/detail/` with form field `cardno`."
            ),
            (
                "* Parsed official detail headings and `<dl>` fields. Preserved Japanese "
                "effect text and inline official image `alt` labels without Effect DSL parsing."
            ),
            "",
            "## Fields Successfully Extracted",
            "",
        ]
    )
    for row in coverage_rows:
        if row["extracted_count"] > 0:
            lines.append(
                f"* `{row['field']}`: `{row['extracted_count']}` extracted "
                f"(`{row['confidence']}` confidence)"
            )
    if not any(row["extracted_count"] > 0 for row in coverage_rows):
        lines.append("* No card-level fields were confidently extracted.")

    lines.extend(["", "## Fields Missing or Unreliable", ""])
    missing_rows = [row for row in coverage_rows if row["missing_count"] > 0]
    if missing_rows:
        for row in missing_rows:
            lines.append(
                f"* `{row['field']}`: `{row['missing_count']}` missing - {row['notes']}"
            )
    else:
        lines.append("* No required field was missing for its applicable sampled card type.")
    if unmapped_labels:
        lines.append(
            "* Unmapped official fields preserved in `parse_notes.unmapped_fields`: "
            + ", ".join(f"`{label}`" for label in unmapped_labels)
        )

    lines.extend(
        [
            "",
            "## Pagination Behavior",
            "",
            (
                "* Initial search results expose an incremental same-domain endpoint: "
                "`/cardlist/cardsearch_ex?view=image&page=...`."
            ),
            "* This spike reads only the first result page for each card type.",
            "",
            "## Search Result Page Behavior",
            "",
            list_or_none(discovered["search_result_urls"][:30]),
            "",
            "## Detail Page Behavior",
            "",
            (
                "* Details are not independent stable pages. The official UI sends a "
                "cookie-aware AJAX POST to `/cardlist/detail/` with `cardno`."
            ),
            (
                "* A direct POST without the search-page session may return HTTP 200 with "
                "an empty body, so the spike establishes the official session first."
            ),
            "",
            "## Hidden JSON or API Candidates",
            "",
            f"* Embedded JSON-like script blocks: `{discovered['embedded_json_blocks']}`",
            list_or_none(discovered["same_domain_api_candidates"]),
            "",
            "## Image URL Behavior",
            "",
            list_or_none(discovered["image_urls"][:30]),
            "",
            "## Raw Files Written",
            "",
            list_or_none(raw_files),
            "",
            "## Risks for Full Import",
            "",
            "* Detail extraction depends on an undocumented AJAX HTML contract.",
            "* Session or anti-automation behavior may change without notice.",
            (
                "* Some semantics are represented by image classes or `alt` text rather "
                "than text fields."
            ),
            "* Effect text does not expose guaranteed machine-readable separators.",
            (
                "* Special Blade Heart parsing currently recognizes only exact official "
                "`ALLn`, `ドローn`, and `スコアn` icon labels."
            ),
            (
                "* Energy cards have no special attributes in this model; they should remain "
                "plain card identities used as one Energy card for payment."
            ),
            (
                "* Detail-page and search pagination behavior must be confirmed across multiple "
                "products before schema decisions."
            ),
            "* Public exports must avoid redistributing bulk official text.",
            "",
            "## Recommended Changes to specs/000-card-database.spec.md",
            "",
            (
                "* Keep the final schema deferred until the same fields are reviewed across "
                "multiple releases and rarities."
            ),
            (
                "* Preserve `source_url`, `fetched_at`, `parser_version`, and raw Japanese "
                "effect text per card source record."
            ),
            (
                "* Require type-specific Heart color fields: Member basic Heart and Live "
                "required Heart must not be collapsed into one scalar. Live required Heart "
                "must support the any-color slot `heart0`."
            ),
            (
                "* Keep `blade` as a Member attribute. Allow Blade Heart color on Member "
                "and Live cards when the official card data exposes it. Energy cards remain "
                "attribute-less."
            ),
            (
                "* Model repeatable Live-card special Blade Hearts separately from normal "
                "Blade Heart color and raw card effect text."
            ),
            (
                "* Support Loveca point-system restriction data as separate deck legality "
                "metadata with a total deck point limit of 9."
            ),
            "",
            "## Recommended Changes to specs/014-data-importer.spec.md",
            "",
            "* Document cookie-aware AJAX detail fetching as an observed source behavior.",
            "* Require same-domain enforcement, conservative fetch limits, and partial reports.",
            (
                "* Preserve official Heart color source identifiers such as `heart01` through "
                "`heart06`, plus `heart0` for any-color requirements, until terminology "
                "normalization confirms canonical color names."
            ),
            (
                "* Normalize Blade/Penlight to one project concept, `blade`, and emit it "
                "only for Member card attributes. Blade Heart color remains a separate "
                "card attribute when visible in official data."
            ),
            (
                "* Parse exact `特殊ハート` image labels into Live-only "
                "`special_blade_hearts` while preserving the original `alt` value."
            ),
            (
                "* Import point-system records separately from card list records; point values "
                "must not be confused with Live score."
            ),
            "",
            "## Recommended Next Implementation Step",
            "",
            (
                "* Review additional products for new special Blade Heart icon types before "
                "expanding source coverage or finalizing any database schema."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_cross_product_artifacts(
    *,
    output_dirs: dict[str, Path],
    card_list_url: str,
    inspected_pages: list[dict[str, Any]],
    raw_files: list[str],
    cards: list[dict[str, Any]],
    bucket_results: list[dict[str, Any]],
    requested_count: int,
    access_limited: bool,
) -> None:
    write_json(
        output_dirs["normalized"] / "cards-cross-product-sample.json",
        cards,
    )
    write_cross_product_report(
        output_dirs["reports"] / "cross-product-coverage-report.md",
        card_list_url=card_list_url,
        inspected_pages=inspected_pages,
        raw_files=raw_files,
        cards=cards,
        bucket_results=bucket_results,
        requested_count=requested_count,
        access_limited=access_limited,
    )
    write_cross_product_field_coverage(
        output_dirs["reports"] / "cross-product-field-coverage.md",
        cards,
    )


def write_cross_product_report(
    path: Path,
    *,
    card_list_url: str,
    inspected_pages: list[dict[str, Any]],
    raw_files: list[str],
    cards: list[dict[str, Any]],
    bucket_results: list[dict[str, Any]],
    requested_count: int,
    access_limited: bool,
) -> None:
    expected_buckets = {
        (product_code, card_kind): quota
        for product_code in CROSS_PRODUCT_CODES
        for card_kind, _kind_name, quota in CROSS_PRODUCT_KIND_QUOTAS
    }
    actual_buckets = {
        (product_code, card_kind): sum(
            1
            for card in cards
            if card.get("product_code") == product_code
            and card_type_to_kind(card.get("card_type")) == card_kind
        )
        for product_code in CROSS_PRODUCT_CODES
        for card_kind, _kind_name, _quota in CROSS_PRODUCT_KIND_QUOTAS
    }
    complete = len(cards) == requested_count and all(
        actual_buckets[key] == quota for key, quota in expected_buckets.items()
    )
    if access_limited:
        status = "access_limited"
    elif complete:
        status = "sample_completed"
    else:
        status = "partial_sample"

    special_counts: dict[str, int] = {}
    special_alts: dict[str, set[str]] = {}
    for card in cards:
        for item in (card.get("live_attributes") or {}).get(
            "special_blade_hearts"
        ) or []:
            effect_type = item["effect_type"]
            special_counts[effect_type] = special_counts.get(effect_type, 0) + 1
            special_alts.setdefault(effect_type, set()).add(item["source_alt"])

    printing_groups: dict[str, set[str]] = {}
    for card in cards:
        for printing_id in card.get("printing_group_ids") or []:
            card_code = derive_card_code(printing_id)
            if card_code:
                printing_groups.setdefault(card_code, set()).add(printing_id)
    repeated_printing_groups = {
        code: sorted(ids) for code, ids in printing_groups.items() if len(ids) > 1
    }

    unmapped_fields = sorted(
        {
            item["label"]
            for card in cards
            for item in card.get("parse_notes", {}).get("unmapped_fields", [])
            if item.get("label")
        }
    )
    unmapped_icons = unique_list(
        [
            item
            for card in cards
            for item in card.get("parse_notes", {}).get("unmapped_icons", [])
        ]
    )

    lines = [
        "# Cross-Product Coverage Report",
        "",
        "## Summary",
        "",
        f"* Status: `{status}`",
        f"* Source: `{card_list_url}`",
        f"* Parser version: `{PARSER_VERSION}`",
        f"* Requested cards: `{requested_count}`",
        f"* Sampled cards: `{len(cards)}`",
        "* Products: " + ", ".join(f"`{code}`" for code in CROSS_PRODUCT_CODES),
        "",
        "## Product and Card-Type Matrix",
        "",
        "| product | sampled | Member | Live | Energy | core complete |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for product_code in CROSS_PRODUCT_CODES:
        product_cards = [
            card for card in cards if card.get("product_code") == product_code
        ]
        type_counts = {
            card_type: sum(
                1 for card in product_cards if card.get("card_type") == card_type
            )
            for card_type in ("メンバー", "ライブ", "エネルギー")
        }
        core_complete = sum(
            1
            for card in product_cards
            if all(
                card.get(field) not in (None, "")
                for field in (
                    "card_id",
                    "card_code",
                    "name",
                    "card_type",
                    "product",
                    "product_code",
                    "rarity",
                )
            )
        )
        lines.append(
            f"| `{product_code}` | {len(product_cards)} | "
            f"{type_counts['メンバー']} | {type_counts['ライブ']} | "
            f"{type_counts['エネルギー']} | {core_complete} |"
        )

    lines.extend(
        [
            "",
            "## Bucket Results",
            "",
            "| product | kind | requested | attempted | successful | detail errors | type mismatches | page 2 used | error |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for result in bucket_results:
        lines.append(
            f"| `{result['product_code']}` | `{result['kind_name']}` | "
            f"{result['requested']} | {result['selected']} | {result['successful']} | "
            f"{result.get('detail_errors', 0)} | "
            f"{result.get('type_mismatches', 0)} | "
            f"`{str(result['pagination_used']).lower()}` | "
            f"{result['search_error'] or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Card-Type Field Boundaries",
            "",
            "| field group | Member | Live | Energy |",
            "| --- | --- | --- | --- |",
            "| Cost, basic Heart, Blade | observed | not emitted | not emitted |",
            "| Score, required Heart | not emitted | observed | not emitted |",
            "| Special Blade Hearts | not emitted | observed when present | not emitted |",
            "| Type-specific attributes | Member attributes | Live attributes | none |",
            "",
            "## Special Blade Heart Coverage",
            "",
        ]
    )
    lines.extend(
        [
            "| normalized type | official label family | observed | labels | review status |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    special_families = (
        ("all_color", "ALLn"),
        ("draw", "ドローn"),
        ("score", "スコアn"),
        ("unknown", "other"),
    )
    for effect_type, label_family in special_families:
        count = special_counts.get(effect_type, 0)
        labels = ", ".join(
            f"`{alt}`" for alt in sorted(special_alts.get(effect_type, set()))
        )
        if effect_type == "unknown":
            review_status = "requires_review" if count else "none_observed"
        else:
            review_status = "source_confirmed" if count else "not_observed"
        lines.append(
            f"| `{effect_type}` | `{label_family}` | {count} | "
            f"{labels or '-'} | `{review_status}` |"
        )

    lines.extend(["", "## Printing Relationships", ""])
    if repeated_printing_groups:
        for card_code, printing_ids in sorted(repeated_printing_groups.items()):
            lines.append(
                f"* `{card_code}`: "
                + ", ".join(f"`{printing_id}`" for printing_id in printing_ids)
            )
    else:
        lines.append("* No related printing group with multiple IDs was observed.")

    lines.extend(
        [
            "",
            "## HTML Structure by Product",
            "",
            "| product | observed official detail labels |",
            "| --- | --- |",
        ]
    )
    for product_code in CROSS_PRODUCT_CODES:
        labels = sorted(
            {
                label
                for card in cards
                if card.get("product_code") == product_code
                for label in card.get("parse_notes", {}).get(
                    "source_field_labels", []
                )
            }
        )
        lines.append(
            f"| `{product_code}` | "
            + (", ".join(f"`{label}`" for label in labels) if labels else "-")
            + " |"
        )

    lines.extend(["", "## Unmapped Source Data", ""])
    if unmapped_fields:
        lines.append(
            "* Detail labels: "
            + ", ".join(f"`{label}`" for label in unmapped_fields)
        )
    else:
        lines.append("* No unmapped detail labels.")
    if unmapped_icons:
        for item in unmapped_icons:
            lines.append(
                f"* `{item['source_field']}` {item['source_kind']} "
                f"`{item['source_value']}`: `{item['review_status']}`"
            )
    else:
        lines.append("* No unmapped Heart or Blade Heart icon was observed.")

    lines.extend(
        [
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
            "## Raw Files Written",
            "",
            list_or_none(raw_files),
            "",
            "## Data-Model Recommendations",
            "",
            "* Add a stable gameplay `card_code` separate from full printing `card_id`.",
            (
                "* Preserve product code, rarity, image, and related printing IDs as "
                "printing-level metadata."
            ),
            (
                "* Keep Member, Live, and Energy type-specific boundaries already documented."
            ),
            (
                "* Keep repeatable special Blade Hearts separate from free-form effect text."
            ),
            (
                "* Defer fields that remain unmapped or appear in only one source generation "
                "until their official semantics are reviewed."
            ),
            "",
            "## Recommended Next Step",
            "",
            (
                "* Use this coverage set to freeze the Phase 1 conceptual schema and "
                "production importer contract; do not start a full import yet."
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def card_type_to_kind(card_type: str | None) -> str | None:
    return {"メンバー": "M", "ライブ": "L", "エネルギー": "E"}.get(card_type)


def write_cross_product_field_coverage(
    path: Path,
    cards: list[dict[str, Any]],
) -> None:
    extended_specs = [
        ("card_code", None, "high", "Derived gameplay identity."),
        ("product_code", None, "high", "Requested official expansion code."),
        (
            "related_printing_ids",
            None,
            "high",
            "Optional official related-printing links.",
        ),
        *COVERAGE_FIELD_SPECS,
    ]
    lines = [
        "# Cross-Product Field Coverage",
        "",
        f"* Parser version: `{PARSER_VERSION}`",
        f"* Sampled cards: `{len(cards)}`",
        "",
        "## Global Coverage",
        "",
        "| field | extracted_count | missing_count | confidence | notes |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for field, applicable_types, confidence, notes in extended_specs:
        applicable_cards = [
            card
            for card in cards
            if applicable_types is None or card.get("card_type") in applicable_types
        ]
        extracted = sum(
            1
            for card in applicable_cards
            if has_extracted_value(nested_value(card, field))
        )
        lines.append(
            f"| `{field}` | {extracted} | {len(applicable_cards) - extracted} | "
            f"`{confidence if extracted else 'not_observed'}` | {notes} |"
        )

    lines.extend(
        [
            "",
            "## Core Coverage by Product",
            "",
            "| product | records | card identity | card type | product | rarity | attributes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for product_code in CROSS_PRODUCT_CODES:
        product_cards = [
            card for card in cards if card.get("product_code") == product_code
        ]
        identity = sum(
            1
            for card in product_cards
            if card.get("card_id") and card.get("card_code")
        )
        attributes = sum(
            1
            for card in product_cards
            if (
                card.get("card_type") == "エネルギー"
                and card.get("member_attributes") is None
                and card.get("live_attributes") is None
            )
            or has_extracted_value(card.get("member_attributes"))
            or has_extracted_value(card.get("live_attributes"))
        )
        lines.append(
            f"| `{product_code}` | {len(product_cards)} | {identity} | "
            f"{sum(bool(card.get('card_type')) for card in product_cards)} | "
            f"{sum(bool(card.get('product')) for card in product_cards)} | "
            f"{sum(bool(card.get('rarity')) for card in product_cards)} | "
            f"{attributes} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def list_or_none(values: list[Any]) -> str:
    if not values:
        return "* None discovered."
    return "\n".join(f"* `{value}`" for value in values)


def nested_value(card: dict[str, Any], path: str) -> Any:
    value: Any = card
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def has_extracted_value(value: Any) -> bool:
    if value in (None, "", []):
        return False
    if isinstance(value, dict):
        return any(item not in (None, "", []) for item in value.values())
    return True


def field_coverage(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, applicable_types, confidence, notes in COVERAGE_FIELD_SPECS:
        applicable_cards = [
            card
            for card in cards
            if applicable_types is None or card.get("card_type") in applicable_types
        ]
        extracted = sum(
            1 for card in applicable_cards if has_extracted_value(nested_value(card, field))
        )
        rows.append(
            {
                "field": field,
                "extracted_count": extracted,
                "missing_count": len(applicable_cards) - extracted,
                "confidence": confidence if extracted else "not_observed",
                "notes": notes,
            }
        )
    return rows


def write_field_coverage(path: Path, cards: list[dict[str, Any]]) -> None:
    coverage_rows = field_coverage(cards)
    lines = [
        "# Field Coverage Report",
        "",
        f"* Parser version: `{PARSER_VERSION}`",
        f"* Sampled cards: `{len(cards)}`",
        "",
        "| field | extracted_count | missing_count | confidence | notes |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in coverage_rows:
        lines.append(
            f"| `{row['field']}` | {row['extracted_count']} | {row['missing_count']} | "
            f"`{row['confidence']}` | {row['notes']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
