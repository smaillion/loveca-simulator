from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sandbox.rules_audit_pack import (
    AUDIT_SCHEMA_VERSION,
    build_rules_audit_pack,
    write_audit_pack,
)

PROJECT_ROOT = Path(__file__).parents[1]
CARD_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"


@pytest.mark.sandbox
def test_rules_audit_pack_writes_human_and_json_reports(tmp_path):
    if not CARD_DATABASE.exists():
        pytest.skip("local full card database is required for rules audit pack")

    rules = tmp_path / "rules.txt"
    rules.write_text("総合ルール ver.1.06\nライブ判定\nバトンタッチ\n" * 3, encoding="utf-8")
    pack = build_rules_audit_pack(
        CARD_DATABASE,
        decks=2,
        loops=1,
        max_actions=8,
        manual_policy="skip",
        rules_pdf=rules,
        rule_context_chars=80,
    )

    assert pack.schema_version == AUDIT_SCHEMA_VERSION
    assert pack.rule_context.loaded is True
    assert len(pack.deck_summaries) == 2
    assert len(pack.matches) == 1
    assert pack.matches[0].timeline
    assert pack.matches[0].notable_steps

    output = tmp_path / "rules_audit"
    write_audit_pack(output, pack)
    json_payload = json.loads((output / "audit-pack.json").read_text(encoding="utf-8"))
    markdown = (output / "audit-pack.md").read_text(encoding="utf-8")

    assert json_payload["schema_version"] == AUDIT_SCHEMA_VERSION
    assert json_payload["matches"][0]["timeline"]
    assert "# ルール監査用 Sandbox Pack" in markdown
    assert "Audit Questions" in markdown
