from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from loveca.simulation.models import MatchState
from loveca.simulation.rulesets import (
    DEFAULT_RULESET_ID,
    DEFAULT_RULESET_REGISTRY,
    RuleConformanceResult,
    RulesetRegistry,
    current_ruleset_identity,
    get_ruleset_profile,
    load_ruleset_registry,
    ruleset_fingerprint,
)

PROJECT_ROOT = Path(__file__).parents[1]
RULE_PDF = PROJECT_ROOT / "raw_doc" / "LoveLiveTCG_cr_1.06_260428.pdf"


def _payload():
    return json.loads(DEFAULT_RULESET_REGISTRY.read_text(encoding="utf-8"))


def test_rule_conformance_result_round_trip():
    result = RuleConformanceResult(
        scenario_id="live-equal-score",
        title="Live equal score",
        category="live",
        status="not_run",
        rule_reference_ids=["cr-8.4.6", "cr-8.4.7.1"],
        evidence="tests/test_live_judgment_audit.py",
    )
    assert RuleConformanceResult.model_validate_json(result.model_dump_json()) == result


def test_rule_conformance_evidence_requires_rule_references():
    with pytest.raises(ValidationError):
        RuleConformanceResult(
            scenario_id="empty", title="Empty", category="live", status="pass",
            rule_reference_ids=[], evidence="not an audited scenario",
        )


def test_registry_has_pinned_pdf_and_inactive_unreviewed_qa():
    registry = load_ruleset_registry()
    profile, fingerprint = current_ruleset_identity()
    assert profile == get_ruleset_profile(DEFAULT_RULESET_ID, registry=registry)
    assert profile.rule_version == "1.06"
    assert profile.ruling_pack_version == "comprehensive-only-v1"
    assert profile.source_ids == ("comprehensive_rules_1_06",)
    assert len(profile.rule_references) == 49
    assert len(fingerprint) == 64
    qa = next(source for source in registry.sources if source.source_kind == "official_qa")
    assert qa.validation_status == "source_available_unreviewed"
    assert qa.sha256 is None
    assert qa.source_id not in profile.source_ids
    assert all(ref.validation_status == "source_confirmed" for ref in profile.rule_references)


@pytest.mark.parametrize("kind", ["source", "profile", "reference", "profile_source"])
def test_registry_rejects_duplicate_ids(kind):
    payload = _payload()
    if kind == "source":
        payload["sources"].append(payload["sources"][0])
    elif kind == "profile":
        payload["profiles"].append(payload["profiles"][0])
    elif kind == "reference":
        payload["profiles"][0]["rule_references"].append(
            payload["profiles"][0]["rule_references"][0]
        )
    else:
        payload["profiles"][0]["source_ids"].append("comprehensive_rules_1_06")
    with pytest.raises(ValidationError, match="duplicate"):
        RulesetRegistry.model_validate(payload)


@pytest.mark.parametrize("kind", ["profile_source", "reference_source", "outside_profile", "current"])
def test_registry_rejects_broken_links(kind):
    payload = _payload()
    if kind == "profile_source":
        payload["profiles"][0]["source_ids"].append("missing")
    elif kind == "reference_source":
        payload["profiles"][0]["rule_references"][0]["source_id"] = "missing"
    elif kind == "outside_profile":
        payload["profiles"][0]["rule_references"][0]["source_id"] = "official_rule_qa"
    else:
        payload["current_ruleset_id"] = "missing"
    with pytest.raises(ValidationError):
        RulesetRegistry.model_validate(payload)


def test_unreviewed_qa_cannot_be_activated_by_listing_its_source():
    payload = _payload()
    payload["profiles"][0]["source_ids"].append("official_rule_qa")
    with pytest.raises(ValidationError, match="unreviewed sources cannot be active"):
        RulesetRegistry.model_validate(payload)


@pytest.mark.parametrize("sha256", [None, "bad-hash", "A" * 64, "1" * 63])
def test_confirmed_source_requires_valid_sha256(sha256):
    payload = _payload()
    payload["sources"][0]["sha256"] = sha256
    with pytest.raises(ValidationError):
        RulesetRegistry.model_validate(payload)


def test_read_only_profile_does_not_share_mutable_lists():
    registry = load_ruleset_registry()
    profile = get_ruleset_profile(registry=registry)
    assert isinstance(registry.sources, tuple)
    assert isinstance(profile.source_ids, tuple)
    assert isinstance(profile.rule_references, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        profile.rule_version = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        profile.rule_references[0].summary_zh = "changed"


@pytest.mark.parametrize("ruleset_id", ["unknown-ruleset", ""])
def test_unknown_ruleset_id_is_rejected(ruleset_id):
    with pytest.raises(ValueError, match="unknown ruleset_id"):
        get_ruleset_profile(ruleset_id)


def test_fingerprint_ignores_paths_collection_order_and_inactive_sources():
    registry = load_ruleset_registry()
    profile = get_ruleset_profile(registry=registry)
    payload = registry.model_dump(mode="json")
    payload["sources"][0]["local_path"] = "C:/different-machine/rules.pdf"
    payload["sources"][1]["official_url"] = "https://example.invalid/inactive-qa"
    payload["sources"].reverse()
    payload["profiles"][0]["rule_references"].reverse()
    changed = RulesetRegistry.model_validate(payload)
    assert ruleset_fingerprint(profile, registry=registry) == ruleset_fingerprint(
        get_ruleset_profile(registry=changed), registry=changed,
    )


def test_fingerprint_ignores_active_source_order():
    payload = _payload()
    payload["sources"][1].update(validation_status="source_confirmed", sha256="1" * 64)
    payload["profiles"][0]["source_ids"].append("official_rule_qa")
    registry = RulesetRegistry.model_validate(payload)
    profile = get_ruleset_profile(registry=registry)
    payload["profiles"][0]["source_ids"].reverse()
    changed = RulesetRegistry.model_validate(payload)
    assert ruleset_fingerprint(profile, registry=registry) == ruleset_fingerprint(
        get_ruleset_profile(registry=changed), registry=changed,
    )


@pytest.mark.parametrize("field,value", [
    ("rule_version", "1.07"),
    ("ruling_pack_version", "reviewed-qa-v1"),
    ("summary_zh", "修订后的摘要"),
    ("reference_status", "rules_reviewed"),
    ("source_hash", "2" * 64),
])
def test_fingerprint_changes_with_rule_identity(field, value):
    registry = load_ruleset_registry()
    profile = get_ruleset_profile(registry=registry)
    payload = registry.model_dump(mode="json")
    if field == "source_hash":
        payload["sources"][0]["sha256"] = value
    elif field in {"summary_zh", "reference_status"}:
        key = "validation_status" if field == "reference_status" else field
        payload["profiles"][0]["rule_references"][0][key] = value
    else:
        payload["profiles"][0][field] = value
    changed = RulesetRegistry.model_validate(payload)
    assert ruleset_fingerprint(profile, registry=registry) != ruleset_fingerprint(
        get_ruleset_profile(registry=changed), registry=changed,
    )


@pytest.mark.parametrize("contents", ["{", "{}"])
def test_load_wraps_invalid_registry_as_value_error(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid ruleset registry"):
        load_ruleset_registry(path)


def test_load_wraps_missing_file_as_value_error(tmp_path):
    with pytest.raises(ValueError, match="invalid ruleset registry"):
        load_ruleset_registry(tmp_path / "missing.json")


def test_comprehensive_pdf_hash_and_all_clause_locations():
    if not RULE_PDF.exists():
        pytest.skip("official PDF is not included in this checkout")
    registry = load_ruleset_registry()
    source = next(item for item in registry.sources if item.source_id == "comprehensive_rules_1_06")
    assert hashlib.sha256(RULE_PDF.read_bytes()).hexdigest() == source.sha256
    text = "\n".join(page.extract_text() for page in PdfReader(RULE_PDF).pages)
    for reference in get_ruleset_profile(registry=registry).rule_references:
        assert re.search(r"(?m)^" + re.escape(reference.clause_id) + r"\.\s", text), reference


def test_source_profile_does_not_change_legacy_match_serialization():
    state = MatchState(match_id="legacy-match", seed=1, players={}, cards={})
    before = state.model_dump(mode="json")
    current_ruleset_identity()
    assert state.model_dump(mode="json") == before
    assert "ruleset_id" not in before
