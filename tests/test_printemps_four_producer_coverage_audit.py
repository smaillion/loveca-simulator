import hashlib

import pytest

from loveca.simulation.models import ActionRequest
from loveca.simulation.ready_history import current_qualified_effect_readied_members
from test_honoka_departed_scope_audit import EFFECT, _actual_state
from test_printemps_producer_coverage import _play_for, _producer_inventory
from test_printemps_ready_history_boundary import READY, _advance, _repo, _replay, _resolve
from test_waowao_ready_score_audit import _fixture


def _qualified(state, owner):
    return current_qualified_effect_readied_members(
        state, owner, source_owner_id=owner, effect_player_id=owner,
        unit_key="printemps", work_key="love_live",
    )


def test_actual_printemps_source_inventory_has_four_recording_producers():
    rows = _producer_inventory()
    assert {row["effect"]["effect_id"] for row in rows} == {
        "PL!-PR-001:1", "PL!-bp3-001:2", "PL!-bp6-008:1",
        "PL!-pb1-012:1", "PL!-pb1-028:1",
    }
    recording = set()
    for row in rows:
        card, effect = row["card"], row["effect"]
        assert "printemps" in card["unit_keys"]
        assert hashlib.sha256(card["raw_effect_text_ja"].encode()).hexdigest() == card["raw_text_hash"]
        assert effect["text_revision_id"] == card["text_revision_id"]
        assert effect["raw_text_hash"] == card["raw_text_hash"]
        if any("provenance" in action["action_type"] for action in effect["actions"]):
            recording.add(effect["effect_id"])
    assert recording == {"PL!-bp3-001:2", "PL!-bp6-008:1", "PL!-pb1-012:1", "PL!-pb1-028:1"}
    assert rows[next(i for i, row in enumerate(rows) if row["effect"]["effect_id"] == EFFECT)]["effect"]["actions"][0]["action_type"] == "ready_member"


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 3])
def test_formal_live_snapshot_records_actual_qualified_targets_sql(tmp_path, owner, waits):
    state = _fixture(owner, waits)
    state.member_ready_coverage_policy = "qualified_source_v1"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert len(_qualified(result, owner)) == waits
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_departed_old_source_keeps_qualified_scope_unknown_sql(tmp_path, owner):
    state = _actual_state(owner)
    state.member_ready_coverage_policy = "qualified_source_v1"
    state.effect_definitions[READY] = _fixture(owner, 0).effect_definitions[READY]
    play = _play_for(state)
    play.payload.update(slot="left", use_baton_touch=True, energy_instance_ids=[])
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, play).state
    invocation = next(i for i in current.pending_effects if i.effect_id == EFFECT)
    request = ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=current.revision,
        payload={"invocation_id": invocation.invocation_id, "accepted": True,
                 "selected_card_instance_ids": ["wrong-target"]})
    result = repo.apply(state.match_id, request).state
    assert result.cards["wrong-target"].orientation == "active"
    assert result.member_ready_qualified_coverage.unknown_changes[0].source is None
    assert _qualified(result, owner) is None
    _replay(repo, result)
