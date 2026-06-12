from __future__ import annotations

from pathlib import Path

from loveca import __version__
from loveca.cards.importer import import_normalized_cards
from loveca.cli import main


PROJECT_ROOT = Path(__file__).parents[1]


def test_cli_without_args_prints_help(capsys):
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Local card database" in captured.out


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert f"loveca {__version__}" in captured.out


def test_planned_command_reports_not_implemented(capsys):
    try:
        main(["cards", "search"])
    except SystemExit as exc:
        assert exc.code == 2

    captured = capsys.readouterr()

    assert "command is planned but not implemented yet" in captured.err


def test_cards_init_command_creates_database(tmp_path, capsys):
    database_path = tmp_path / "catalog.sqlite3"

    exit_code = main(
        [
            "cards",
            "init",
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert database_path.exists()
    assert "schema v2" in captured.out


def test_cards_import_command_imports_local_sample(tmp_path, capsys):
    database_path = tmp_path / "catalog.sqlite3"

    exit_code = main(
        [
            "cards",
            "import",
            "--database",
            str(database_path),
            "--input",
            str(
                PROJECT_ROOT
                / "data_samples"
                / "normalized"
                / "cards-cross-product-sample.json"
            ),
            "--normalization",
            str(
                PROJECT_ROOT
                / "data_sources"
                / "card-entity-normalization.json"
            ),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Imported 30/30 records" in captured.out
    assert captured.err == ""


def test_decks_analyze_command_outputs_json_for_sample_deck(tmp_path, capsys):
    database_path = tmp_path / "catalog.sqlite3"
    import_normalized_cards(
        database_path,
        PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json",
        PROJECT_ROOT / "data_sources" / "card-entity-normalization.json",
    )

    exit_code = main(
        [
            "decks",
            "analyze",
            "--database",
            str(database_path),
            "--deck",
            str(PROJECT_ROOT / "examples" / "decks" / "sample-deck.json"),
            "--output",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"is_legal": true' in captured.out
    assert captured.err == ""
