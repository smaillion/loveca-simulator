import hashlib
import json
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation import engine
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.service import MatchService
from loveca.webapp import _match_state_payload


ROOT = Path(__file__).parents[1]


def _create(tmp_path, first):
    database = tmp_path / "cards.sqlite3"
    import_normalized_cards(database, ROOT / "data_samples/normalized/cards-cross-product-sample.json",
                            ROOT / "data_sources/card-entity-normalization.json")
    service = MatchService(database, tmp_path / "matches.sqlite3")
    deck = load_deck(ROOT / "tests/fixtures/legal-deck.json")
    result = service.create_match(first_name="A", first_deck=deck, second_name="B", second_deck=deck,
                                  seed=260603, match_id="mulligan-boundary", first_player_id=first)
    return service.repository, result.state


def _command(state, selected):
    return ActionRequest(action_type="submit_mulligan", player_id=state.active_player_id,
                         expected_revision=state.revision, payload={"card_instance_ids": selected})


def _replay(repo, state):
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["final_state"] == state.model_dump()


def _privacy(result):
    state = result.state
    for viewer in state.players:
        other = next(owner for owner in state.players if owner != viewer)
        hidden = state.players[other].hand + state.players[other].main_deck + state.players[viewer].main_deck
        payload = _match_state_payload(state, events=result.events, legal_actions=result.legal_actions,
                                       player_id=viewer)
        assert all(json.dumps(item) not in json.dumps(payload) for item in hidden)


def _assert_exchange(before, result, selected):
    owner = before.active_player_id
    old, new = before.players[owner], result.state.players[owner]
    count = len(selected)
    # CR 1.06 6.2.1.6 draws before returning the set-aside cards.
    assert new.hand == [item for item in old.hand if item not in selected] + old.main_deck[:count]
    assert len(new.hand) == 6 and len(new.main_deck) == 54
    assert set(new.main_deck) == set(old.main_deck[count:] + selected)
    assert set(new.hand).isdisjoint(new.main_deck)
    assert all(not result.state.cards[item].face_up for item in selected)
    if not selected:
        assert new.main_deck == old.main_deck
    completed = [event for event in result.events if event.event_type == "mulligan_completed"]
    assert len(completed) == 1 and completed[0].player_id == owner
    assert completed[0].data == {"replaced_count": count}
    other = next(player for player in before.players if player != owner)
    assert result.state.players[other].hand == before.players[other].hand
    assert result.state.players[other].main_deck == before.players[other].main_deck
    _privacy(result)


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("count", range(7))
def test_native_mulligan_draws_before_return_and_waits_for_both_players(tmp_path, monkeypatch, first, count):
    assert hashlib.sha256((ROOT / "raw_doc/LoveLiveTCG_cr_1.06_260428.pdf").read_bytes()).hexdigest() == "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
    repo, state = _create(tmp_path, first)
    shuffle = engine._deterministic_shuffle
    calls = []

    def observed_shuffle(cards, seed, reason):
        calls.append((list(cards), seed, reason))
        return shuffle(cards, seed, reason)

    monkeypatch.setattr(engine, "_deterministic_shuffle", observed_shuffle)
    second = state.second_player_id
    initial_energy = {owner: list(player.energy_deck) for owner, player in state.players.items()}
    for index, (owner, size) in enumerate(((first, count), (second, 6 - count))):
        assert state.active_player_id == state.pending_choice.player_id == owner
        assert state.pending_choice.choice_type == "mulligan"
        assert all(not player.energy_area for player in state.players.values())
        selected = state.players[owner].hand[:size]
        calls.clear()
        result = repo.apply(state.match_id, _command(state, selected))
        expected_pool = state.players[owner].main_deck[size:] + selected
        assert calls == ([(expected_pool, state.seed, f"mulligan:{owner}")] if size else [])
        _assert_exchange(state, result, selected)
        state = result.state
        _replay(repo, state)
        if index == 0:
            assert state.phase == "setup_mulligan_second"
            assert all(player.energy_deck == initial_energy[pid] for pid, player in state.players.items())
    assert state.pending_choice is None and state.phase == "first_active"
    assert state.active_player_id == first
    for owner, player in state.players.items():
        assert player.energy_area == initial_energy[owner][:3]
        assert player.energy_deck == initial_energy[owner][3:]


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["duplicate", "deck", "opponent", "wrong_player", "stale", "repeat"])
def test_invalid_mulligan_preserves_sql_actions_events_and_state(tmp_path, first, invalid):
    repo, state = _create(tmp_path, first)
    own = state.players[first]
    command = _command(state, [])
    error = IllegalActionError
    if invalid == "duplicate":
        command.payload["card_instance_ids"] = [own.hand[0], own.hand[0]]
    elif invalid == "deck":
        command.payload["card_instance_ids"] = own.main_deck[:1]
    elif invalid == "opponent":
        command.payload["card_instance_ids"] = state.players[state.second_player_id].hand[:1]
    elif invalid == "wrong_player":
        command.player_id = state.second_player_id
    elif invalid == "stale":
        command.expected_revision -= 1
        error = StaleRevisionError
    else:
        state = repo.apply(state.match_id, command).state
        command.expected_revision = state.revision
    before = repo.replay(state.match_id)
    with pytest.raises(error):
        repo.apply(state.match_id, command)
    assert repo.replay(state.match_id) == before


@pytest.mark.parametrize("first", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_mulligans_ignore_unseen_cards_and_execute_sql(tmp_path, first, policy):
    repo, state = _create(tmp_path, first)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for _ in range(2):
        owner = state.active_player_id
        other = next(player for player in state.players if player != owner)
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
        assert isinstance(decision, SimpleAIDecision)
        assert decision.action.action_type == "submit_mulligan" and decision.action.player_id == owner
        altered = state.model_copy(deep=True)
        hidden = state.players[other].hand + state.players[other].main_deck + state.players[owner].main_deck
        for item in hidden:
            altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
        altered_before = match_state_hash(altered)
        alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids={owner})
        assert isinstance(alternative, SimpleAIDecision)
        assert alternative.action.model_dump() == decision.action.model_dump()
        assert match_state_hash(state) == before and match_state_hash(altered) == altered_before
        selected = decision.action.payload["card_instance_ids"]
        result = repo.apply(state.match_id, decision.action)
        _assert_exchange(state, result, selected)
        state = result.state
        _replay(repo, state)
    assert state.phase == "first_active" and state.active_player_id == first
