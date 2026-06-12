"""Command-line interface for local LoveCA tools."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from loveca import __version__
from loveca.cards.images import ImageCacheError, cache_card_images
from loveca.cards.importer import CardImportError, import_normalized_cards
from loveca.db.bootstrap import (
    DatabaseSchemaError,
    get_schema_version,
    initialize_database,
)
from loveca.decks.analyzer import (
    DeckAnalyzerError,
    analyze_deck_file,
    render_analysis_json,
    render_analysis_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loveca",
        description="Local card database, deck analysis, and simulation tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    cards_parser = subparsers.add_parser("cards", help="Card database commands.")
    cards_subparsers = cards_parser.add_subparsers(dest="cards_command")
    cards_init_parser = cards_subparsers.add_parser(
        "init",
        help="Initialize the local SQLite card database.",
    )
    cards_init_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="SQLite database path.",
    )
    cards_import_parser = cards_subparsers.add_parser(
        "import",
        help="Import normalized local card JSON into SQLite.",
    )
    cards_import_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="SQLite database path.",
    )
    cards_import_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Normalized card JSON path.",
    )
    cards_import_parser.add_argument(
        "--normalization",
        type=Path,
        required=True,
        help="Reviewed Work and Unit normalization JSON path.",
    )
    cards_subparsers.add_parser("export", help="Export card data from the local database.")
    cards_subparsers.add_parser("search", help="Search cards in the local database.")
    cards_cache_parser = cards_subparsers.add_parser(
        "cache-images",
        help="Cache official card images for local UI use.",
    )
    cards_cache_parser.add_argument("--database", type=Path, required=True)
    cards_cache_parser.add_argument("--cache-dir", type=Path, required=True)
    cards_cache_parser.add_argument("--delay", type=float, default=1.0)
    cards_cache_parser.add_argument("--limit", type=int)

    decks_parser = subparsers.add_parser("decks", help="Deck analysis commands.")
    decks_subparsers = decks_parser.add_subparsers(dest="decks_command")
    decks_analyze_parser = decks_subparsers.add_parser(
        "analyze",
        help="Analyze deck legality and consistency.",
    )
    decks_analyze_parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="SQLite database path.",
    )
    decks_analyze_parser.add_argument(
        "--deck",
        type=Path,
        required=True,
        help="Decklist JSON path.",
    )
    decks_analyze_parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    sim_parser = subparsers.add_parser("sim", help="Simulation commands.")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command")
    sim_subparsers.add_parser("draw", help="Run draw and opening hand simulations.")

    web_parser = subparsers.add_parser("web", help="Visual rules debugger.")
    web_subparsers = web_parser.add_subparsers(dest="web_command")
    web_serve_parser = web_subparsers.add_parser(
        "serve",
        help="Serve the local FastAPI and SPA application.",
    )
    web_serve_parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/loveca.sqlite3"),
    )
    web_serve_parser.add_argument(
        "--matches",
        type=Path,
        default=Path("data/matches.sqlite3"),
    )
    web_serve_parser.add_argument(
        "--image-cache",
        type=Path,
        default=Path("data/card_images"),
    )
    web_serve_parser.add_argument("--host", default="127.0.0.1")
    web_serve_parser.add_argument("--port", type=int, default=8765)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "cards" and args.cards_command == "init":
        try:
            initialize_database(args.database)
            version = get_schema_version(args.database)
        except (DatabaseSchemaError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Initialized SQLite schema v{version} at {args.database}.")
        return 0

    if args.command == "cards" and args.cards_command == "import":
        try:
            summary = import_normalized_cards(
                args.database,
                args.input,
                args.normalization,
            )
        except (CardImportError, DatabaseSchemaError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Imported {summary.records_imported}/{summary.records_seen} records "
            f"into {args.database} (batch {summary.batch_id}, {summary.status})."
        )
        if summary.status == "completed_with_review":
            print(
                f"warning: {summary.review_candidates} normalization candidate(s) "
                "require review.",
                file=sys.stderr,
            )
        return 0

    if args.command == "cards" and args.cards_command == "cache-images":
        try:
            summary = cache_card_images(
                args.database,
                args.cache_dir,
                delay=args.delay,
                limit=args.limit,
            )
        except (ImageCacheError, DatabaseSchemaError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Image cache updated: {summary['fetched']} fetched, "
            f"{summary['skipped']} skipped, {summary['failed']} failed."
        )
        return 0 if summary["failed"] == 0 else 1

    if args.command == "decks" and args.decks_command == "analyze":
        try:
            analysis = analyze_deck_file(args.database, args.deck)
        except (DeckAnalyzerError, DatabaseSchemaError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.output == "json":
            print(render_analysis_json(analysis))
        else:
            print(render_analysis_text(analysis))
        return 0 if analysis.is_legal else 1

    if args.command == "web" and args.web_command == "serve":
        import uvicorn

        from loveca.webapp import ApiSettings, create_app

        application = create_app(
            ApiSettings(
                card_database_path=args.database,
                runtime_database_path=args.matches,
                image_cache_dir=args.image_cache,
                web_dist_dir=Path("web/dist"),
            )
        )
        uvicorn.run(application, host=args.host, port=args.port)
        return 0

    parser.error("command is planned but not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
