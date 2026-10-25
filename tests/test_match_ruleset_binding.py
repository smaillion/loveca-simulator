from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation import runtime, rulesets, service as service_module
from loveca.simulation.models import ActionRequest, MatchState
from loveca.simulation.online import (
    CompatibilityFingerprint,
    build_compatibility_fingerprint,
    compatibility_report,
    match_state_hash,
)
from loveca.simulation.runtime import MatchRulesetMismatchError
from loveca.simulation.service import MatchService, MatchSetupError

ROOT = Path(__file__).parents[1]
IDENTITY_FIELDS = ("ruleset_id", "ruleset_fingerprint", "ruling_pack_version")


@pytest.fixture
def service(tmp_path):
    database = tmp_path / "cards.sqlite3"
    import_normalized_cards(
        database,
        ROOT / "data_samples/normalized/cards-cross-product-sample.json",
        ROOT / "data_sources/card-entity-normalization.json",
    )
    return MatchService(database, tmp_path / "matches.sqlite3")


def _create(service, **kwargs):
    deck = load_deck(ROOT / "tests/fixtures/legal-deck.json")
    return service.create_match(
        first_name="A", first_deck=deck, second_name="B", second_deck=deck,
        seed=42, first_player_id="player_1", **kwargs,
    )


def _action(state):
    return ActionRequest(
        action_type="submit_mulligan", player_id="player_1",
        expected_revision=state.revision, payload={"card_instance_ids": []},
    )


def _rewrite(service, match_id, changes, *, columns=None):
    columns = columns or ("initial_state_json", "current_state_json")
    with sqlite3.connect(service.repository.path) as connection:
        for column in columns:
            payload = json.loads(connection.execute(
                f"SELECT {column} FROM matches WHERE match_id = ?", (match_id,),
            ).fetchone()[0])
            for key, value in changes.items():
                if value is None:
                    payload.pop(key, None)
                else:
                    payload[key] = value
            connection.execute(
                f"UPDATE matches SET {column} = ? WHERE match_id = ?",
                (json.dumps(payload), match_id),
            )


def _database_dump(service):
    with sqlite3.connect(service.repository.path) as connection:
        return list(connection.iterdump())


@pytest.mark.parametrize("explicit", [False, True])
def test_new_match_pins_current_ruleset_and_round_trips(service, explicit):
    profile, fingerprint = rulesets.current_ruleset_identity()
    created = _create(service, **({"ruleset_id": profile.ruleset_id} if explicit else {}))
    state = created.state
    assert state.rule_version == profile.rule_version
    assert state.ruleset_id == profile.ruleset_id
    assert state.ruleset_fingerprint == fingerprint
    assert state.ruling_pack_version == profile.ruling_pack_version
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    assert service.repository.get_state(state.match_id) == state
    result = service.apply(state.match_id, _action(state))
    replay = service.repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["metadata"]["ruleset_compatibility"]["status"] == "compatible"
    for field in IDENTITY_FIELDS:
        assert replay["metadata"][field] == getattr(state, field)
        assert replay["initial_state"][field] == replay["final_state"][field]
    assert replay["metadata"]["final_state_hash"] == match_state_hash(result.state)


@pytest.mark.parametrize("ruleset_id", ["", "unknown-profile"])
def test_unknown_ruleset_rejected_without_creating_data(service, ruleset_id):
    before = _database_dump(service)
    with pytest.raises(MatchSetupError, match="unknown ruleset_id"):
        _create(service, ruleset_id=ruleset_id)
    assert _database_dump(service) == before


def test_known_but_inactive_profile_cannot_run_under_current_engine(service, monkeypatch):
    registry = rulesets.load_ruleset_registry()
    inactive = registry.profiles[0].model_copy(update={"ruleset_id": "archived"})
    registry = registry.model_copy(update={"profiles": (*registry.profiles, inactive)})
    monkeypatch.setattr(service_module, "load_ruleset_registry", lambda: registry)
    before = _database_dump(service)
    with pytest.raises(MatchSetupError, match="not supported"):
        _create(service, ruleset_id="archived")
    assert _database_dump(service) == before


def test_current_profile_cannot_enable_an_unsupported_engine_rule_version(service, monkeypatch):
    registry = rulesets.load_ruleset_registry()
    profile = rulesets.get_ruleset_profile(registry=registry).model_copy(update={"rule_version": "1.07"})
    registry = registry.model_copy(update={"profiles": (profile,)})
    monkeypatch.setattr(service_module, "load_ruleset_registry", lambda: registry)
    before = _database_dump(service)
    with pytest.raises(MatchSetupError, match="not supported"):
        _create(service)
    assert _database_dump(service) == before


def test_matching_snapshot_and_profile_still_require_engine_version_support(service, monkeypatch):
    state = _create(service).state
    registry = rulesets.load_ruleset_registry()
    profile = rulesets.get_ruleset_profile(registry=registry).model_copy(update={"rule_version": "1.07"})
    registry = registry.model_copy(update={"profiles": (profile,)})
    _rewrite(service, state.match_id, {
        "rule_version": profile.rule_version,
        "ruleset_fingerprint": rulesets.ruleset_fingerprint(profile, registry=registry),
    })
    monkeypatch.setattr(rulesets, "load_ruleset_registry", lambda: registry)
    saved = service.repository.get_state(state.match_id)
    before = _database_dump(service)
    with pytest.raises(MatchRulesetMismatchError):
        service.apply(state.match_id, _action(saved))
    replay = service.repository.replay(state.match_id)
    assert replay["metadata"]["ruleset_compatibility"]["status"] == "engine_rule_version_mismatch"
    assert replay["metadata"]["deterministic_replay_verified"] is False
    assert _database_dump(service) == before


def test_legacy_snapshot_omits_new_fields_and_keeps_its_hash(service):
    state = _create(service).state
    _rewrite(service, state.match_id, dict.fromkeys(IDENTITY_FIELDS))
    legacy = service.repository.get_state(state.match_id)
    payload = legacy.model_dump(mode="json")
    assert all(field not in payload for field in IDENTITY_FIELDS)
    assert MatchState.model_validate(payload).model_dump(mode="json") == payload
    assert match_state_hash(MatchState.model_validate(payload)) == match_state_hash(legacy)
    result = service.apply(legacy.match_id, _action(legacy))
    replay = service.repository.replay(legacy.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_compatibility"]["status"] == "legacy_unpinned"
    assert replay["metadata"]["ruleset_identity_verified"] is False
    assert all(field not in replay["final_state"] for field in IDENTITY_FIELDS)
    assert MatchState.model_validate(replay["final_state"]) == result.state


@pytest.mark.parametrize("changes", [
    {"ruleset_fingerprint": "0" * 64},
    {"ruleset_id": "missing"},
    {"ruling_pack_version": "future-pack"},
    {"rule_version": "future-rules"},
    {"ruleset_fingerprint": None},
    {"ruleset_id": None, "ruling_pack_version": None},
    {**dict.fromkeys(IDENTITY_FIELDS), "rule_version": "0.99"},
])
def test_incompatible_match_is_read_only_and_replay_never_executes(service, monkeypatch, changes):
    state = _create(service).state
    _rewrite(service, state.match_id, changes)
    saved = service.repository.get_state(state.match_id)
    before = _database_dump(service)

    def forbidden(*args, **kwargs):
        pytest.fail("incompatible ruleset reached Rule Engine")

    monkeypatch.setattr(runtime, "apply_action", forbidden)
    with pytest.raises(MatchRulesetMismatchError, match="read-only"):
        service.apply(saved.match_id, _action(saved))
    replay = service.repository.replay(saved.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is False
    assert replay["metadata"]["ruleset_identity_verified"] is False
    assert replay["metadata"]["ruleset_compatibility"]["can_execute"] is False
    assert MatchState.model_validate(replay["final_state"]) == saved
    assert replay["actions"]
    assert replay["metadata"]["final_state_hash"] == match_state_hash(saved)
    assert _database_dump(service) == before


def test_initial_final_ruleset_drift_is_not_reported_as_verified(service, monkeypatch):
    state = _create(service).state
    _rewrite(service, state.match_id, {"ruleset_fingerprint": "0" * 64}, columns=("initial_state_json",))
    monkeypatch.setattr(runtime, "apply_action", lambda *_: pytest.fail("must not replay"))
    replay = service.repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is False
    assert replay["metadata"]["ruleset_compatibility"]["status"] == "snapshot_ruleset_identity_mismatch"


def test_changed_active_source_hash_prevents_reexecution(service, monkeypatch):
    state = _create(service).state
    registry = rulesets.load_ruleset_registry()
    source_id = rulesets.get_ruleset_profile(registry=registry).source_ids[0]
    sources = tuple(
        item.model_copy(update={"sha256": "0" * 64}) if item.source_id == source_id else item
        for item in registry.sources
    )
    monkeypatch.setattr(rulesets, "load_ruleset_registry", lambda: registry.model_copy(update={"sources": sources}))
    with pytest.raises(MatchRulesetMismatchError):
        service.apply(state.match_id, _action(state))
    assert service.repository.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is False


@pytest.mark.parametrize("field,value", [
    ("ruleset_id", "other"), ("ruleset_fingerprint", "0" * 64),
    ("ruling_pack_version", "other"),
])
def test_online_compatibility_compares_all_ruleset_fields(field, value):
    local = build_compatibility_fingerprint()
    remote = local.model_copy(update={field: value})
    report = compatibility_report(local, remote)
    assert report["is_compatible"] is False
    assert report["mismatches"] == [field]
    assert CompatibilityFingerprint.model_validate_json(local.model_dump_json()) == local


def test_old_fingerprint_is_not_silently_promoted_to_current():
    old = CompatibilityFingerprint()
    assert old.ruleset_id is None
    assert not compatibility_report(build_compatibility_fingerprint(), old)["is_compatible"]


def test_fingerprint_rejects_conflicting_rule_version():
    with pytest.raises(ValueError, match="rule_version does not match"):
        build_compatibility_fingerprint(rule_version="0.99")
