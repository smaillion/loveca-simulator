from __future__ import annotations

import json
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


def test_cards_validate_command_reports_incremental_subset(tmp_path, capsys):
    report_path = tmp_path / "validate-report.md"

    exit_code = main(
        [
            "cards",
            "validate",
            "--input",
            str(
                PROJECT_ROOT
                / "data_samples"
                / "normalized"
                / "cards-cross-product-sample.json"
            ),
            "--normalization",
            str(PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"),
            "--card-set",
            "BP01",
            "--report",
            str(report_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validated 5/30 records" in captured.out
    assert report_path.exists()


def test_cards_import_command_supports_incremental_card_set_filter(tmp_path, capsys):
    database_path = tmp_path / "catalog.sqlite3"
    report_path = tmp_path / "import-report.md"

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
            str(PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"),
            "--card-set",
            "PR",
            "--report",
            str(report_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Imported 5/5 records" in captured.out
    assert report_path.exists()


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
            str(PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"),
            "--output",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"is_legal": true' in captured.out
    assert captured.err == ""


def test_cards_import_official_command_accepts_output_root_and_reports_result(
    tmp_path,
    monkeypatch,
    capsys,
):
    output_root = tmp_path / "official"

    class FakeSummary:
        cards = [
            {
                "card_id": "TEST-M-001",
                "card_code": "TEST-M-001",
                "card_type": "メンバー",
                "product": "テスト商品",
                "rarity": "R",
                "member_attributes": None,
                "live_attributes": None,
                "raw_effect_text": None,
                "image_url": None,
                "source_url": "https://llofficial-cardgame.com/cardlist/searchresults/?cardno=TEST-M-001",
                "fetched_at": "2026-06-14T00:00:00+00:00",
                "parser_version": "official_import_v1",
                "parse_notes": {},
            }
        ]
        normalized_path = output_root / "normalized" / "cards-official.json"
        db_import_summary = None

    def fake_import(**kwargs):
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "normalized").mkdir(parents=True, exist_ok=True)
        (output_root / "reports").mkdir(parents=True, exist_ok=True)
        (output_root / "normalized" / "cards-official.json").write_text(
            json.dumps(FakeSummary.cards, ensure_ascii=False),
            encoding="utf-8",
        )
        return FakeSummary()

    monkeypatch.setattr("loveca.cli.run_official_card_import", fake_import)

    exit_code = main(
        [
            "cards",
            "import-official",
            "--output-root",
            str(output_root),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Fetched 1 official card records" in captured.out


def test_cards_import_official_incremental_mode_requires_card_set(capsys):
    exit_code = main(
        [
            "cards",
            "import-official",
            "--mode",
            "incremental-set",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--mode incremental-set requires at least one --card-set" in captured.err
