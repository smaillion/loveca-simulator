"""Command-line interface for local LoveCA tools."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from loveca import __version__
from loveca.cards.images import ImageCacheError, cache_card_images
from loveca.cards.importer import (
    CardImportError,
    import_normalized_cards,
    validate_normalized_cards,
    write_import_report,
    write_validation_report,
)
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
from loveca.decks.library import (
    DeckLibraryError,
    delete_saved_deck,
    import_deck_directory,
    list_saved_decks,
    load_saved_deck,
    rename_saved_deck,
    save_deck_file,
)
from loveca.simulation.effect_candidates import (
    DEFAULT_EFFECT_REGISTRY,
    discover_effect_candidates,
    render_candidates_json,
)


def run_official_card_import(**kwargs):
    """Load the official importer only for the command that needs it."""

    from loveca.cards.official_importer import run_official_card_import as run_import

    return run_import(**kwargs)


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
    cards_import_parser.add_argument(
        "--card-set",
        action="append",
        dest="card_sets",
        help="Optional card_set_code filter for incremental imports. Repeatable.",
    )
    cards_import_parser.add_argument(
        "--report",
        type=Path,
        help="Optional Markdown report path for import results.",
    )
    cards_validate_parser = cards_subparsers.add_parser(
        "validate",
        help="Validate normalized local card JSON without writing SQLite data.",
    )
    cards_validate_parser.add_argument("--input", type=Path, required=True)
    cards_validate_parser.add_argument("--normalization", type=Path, required=True)
    cards_validate_parser.add_argument(
        "--card-set",
        action="append",
        dest="card_sets",
        help="Optional card_set_code filter for incremental validation. Repeatable.",
    )
    cards_validate_parser.add_argument(
        "--report",
        type=Path,
        help="Optional Markdown report path for validation results.",
    )
    cards_official_import_parser = cards_subparsers.add_parser(
        "import-official",
        help="Fetch the official card list and write a full normalized artifact.",
    )
    cards_official_import_parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/imports/official"),
        help="Directory for raw, normalized, and report artifacts.",
    )
    cards_official_import_parser.add_argument(
        "--database",
        type=Path,
        help="Optional SQLite card database path to populate after fetching.",
    )
    cards_official_import_parser.add_argument(
        "--normalization",
        type=Path,
        help="Reviewed Work and Unit normalization JSON path required with --database.",
    )
    cards_official_import_parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between sequential official requests.",
    )
    cards_official_import_parser.add_argument(
        "--mode",
        choices=("full-refresh", "incremental-set"),
        default="full-refresh",
        help="Official importer mode.",
    )
    cards_official_import_parser.add_argument(
        "--card-set",
        action="append",
        dest="card_sets",
        help="Target card_set_code values for incremental official imports. Repeatable.",
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
    decks_save_parser = decks_subparsers.add_parser(
        "save",
        help="Save a decklist.v0 file into the local deck library.",
    )
    decks_save_parser.add_argument("--deck", type=Path, required=True)
    decks_save_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )
    decks_save_parser.add_argument("--name")
    decks_save_parser.add_argument("--overwrite", action="store_true")

    decks_import_directory_parser = decks_subparsers.add_parser(
        "import-directory",
        help="Import every decklist.v0 JSON file from a directory into the local deck library.",
    )
    decks_import_directory_parser.add_argument("--source", type=Path, required=True)
    decks_import_directory_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )
    decks_import_directory_parser.add_argument(
        "--prefix",
        help="Optional prefix added to each imported deck name.",
    )
    decks_import_directory_parser.add_argument("--overwrite", action="store_true")

    decks_list_parser = decks_subparsers.add_parser(
        "list",
        help="List saved decks in the local deck library.",
    )
    decks_list_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )

    decks_load_parser = decks_subparsers.add_parser(
        "load",
        help="Print a saved deck to stdout.",
    )
    decks_load_parser.add_argument("--deck", required=True)
    decks_load_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )

    decks_rename_parser = decks_subparsers.add_parser(
        "rename",
        help="Rename a saved deck file and deck name.",
    )
    decks_rename_parser.add_argument("--deck", required=True)
    decks_rename_parser.add_argument("--name", required=True)
    decks_rename_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )

    decks_delete_parser = decks_subparsers.add_parser(
        "delete",
        help="Delete a saved deck from the local deck library.",
    )
    decks_delete_parser.add_argument("--deck", required=True)
    decks_delete_parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("data/decks"),
    )

    sim_parser = subparsers.add_parser("sim", help="Simulation commands.")
    sim_subparsers = sim_parser.add_subparsers(dest="sim_command")
    sim_subparsers.add_parser("draw", help="Run draw and opening hand simulations.")

    effects_parser = subparsers.add_parser("effects", help="Effect registry helpers.")
    effects_subparsers = effects_parser.add_subparsers(dest="effects_command")
    effects_candidates_parser = effects_subparsers.add_parser(
        "candidates",
        help="Discover exact-text effect registry candidates.",
    )
    effects_candidates_parser.add_argument("--database", type=Path, required=True)
    effects_candidates_parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_EFFECT_REGISTRY,
    )
    effects_candidates_parser.add_argument(
        "--include-registered",
        action="store_true",
    )
    effects_candidates_parser.add_argument("--output", type=Path)

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
                card_set_codes=tuple(args.card_sets or ()),
            )
            if args.report:
                write_import_report(
                    args.report,
                    input_path=args.input,
                    normalization_path=args.normalization,
                    summary=summary,
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

    if args.command == "cards" and args.cards_command == "validate":
        try:
            summary = validate_normalized_cards(
                args.input,
                args.normalization,
                card_set_codes=tuple(args.card_sets or ()),
            )
            if args.report:
                write_validation_report(
                    args.report,
                    input_path=args.input,
                    normalization_path=args.normalization,
                    summary=summary,
                )
        except (CardImportError, DatabaseSchemaError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Validated {summary.records_selected}/{summary.records_seen} records "
            f"(errors={summary.error_count}, warnings={summary.warning_count}, "
            f"review={summary.review_candidates})."
        )
        if summary.error_count:
            for issue in summary.issues[:10]:
                if issue.severity != "error":
                    continue
                print(
                    f"error: record {issue.record_index} [{issue.field}] {issue.message}",
                    file=sys.stderr,
                )
            return 1
        if summary.review_candidates:
            print(
                f"warning: {summary.review_candidates} normalization candidate(s) "
                "require review.",
                file=sys.stderr,
            )
        if summary.warning_count > summary.review_candidates:
            print(
                f"warning: {summary.warning_count - summary.review_candidates} "
                "non-blocking validation warning(s) reported.",
                file=sys.stderr,
            )
        return 0

    if args.command == "cards" and args.cards_command == "import-official":
        try:
            if args.mode == "incremental-set" and not args.card_sets:
                raise ValueError("--mode incremental-set requires at least one --card-set")
            official_result = run_official_card_import(
                output_root=args.output_root,
                database_path=args.database,
                normalization_path=args.normalization,
                delay=args.delay,
                card_set_codes=tuple(args.card_sets or ()),
                import_mode=args.mode,
            )
        except (CardImportError, DatabaseSchemaError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"Fetched {len(official_result.cards)} official card records into "
            f"{official_result.normalized_path}."
        )
        if official_result.db_import_summary is not None:
            db_summary = official_result.db_import_summary
            print(
                f"Imported {db_summary.records_imported}/{db_summary.records_seen} "
                f"records into {args.database} (batch {db_summary.batch_id}, "
                f"{db_summary.status})."
            )
            if db_summary.status == "completed_with_review":
                print(
                    f"warning: {db_summary.review_candidates} normalization candidate(s) "
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

    if args.command == "effects" and args.effects_command == "candidates":
        try:
            candidates = discover_effect_candidates(
                args.database,
                registry_path=args.registry,
                include_registered=args.include_registered,
            )
            payload = render_candidates_json(candidates)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.output:
            print(f"Wrote {len(candidates)} effect candidate(s) to {args.output}.")
        else:
            print(payload)
        return 0

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

    if args.command == "decks" and args.decks_command == "save":
        try:
            destination = save_deck_file(
                args.deck,
                args.library_root,
                name=args.name,
                overwrite=args.overwrite,
            )
        except (DeckAnalyzerError, DeckLibraryError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Saved deck to {destination}.")
        return 0

    if args.command == "decks" and args.decks_command == "import-directory":
        try:
            imported = import_deck_directory(
                args.source,
                args.library_root,
                name_prefix=args.prefix,
                overwrite=args.overwrite,
            )
        except (DeckAnalyzerError, DeckLibraryError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for item in imported:
            print(f"{item.source} -> {item.destination}")
        print(f"Imported {len(imported)} deck(s).")
        return 0

    if args.command == "decks" and args.decks_command == "list":
        try:
            decks = list_saved_decks(args.library_root)
        except DeckLibraryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for deck in decks:
            print(
                f"{deck.path.name}\t{deck.name or '(unnamed)'}\t"
                f"main={deck.main_card_count}\tenergy={deck.energy_card_count}"
            )
        return 0

    if args.command == "decks" and args.decks_command == "load":
        try:
            deck = load_saved_deck(args.library_root, args.deck)
        except (DeckAnalyzerError, DeckLibraryError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(asdict(deck), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "decks" and args.decks_command == "rename":
        try:
            destination = rename_saved_deck(args.library_root, args.deck, args.name)
        except (DeckAnalyzerError, DeckLibraryError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Renamed deck to {destination}.")
        return 0

    if args.command == "decks" and args.decks_command == "delete":
        try:
            delete_saved_deck(args.library_root, args.deck)
        except (DeckAnalyzerError, DeckLibraryError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print("Deleted deck.")
        return 0

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
