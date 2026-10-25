from pathlib import Path
from types import SimpleNamespace

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    CardDefinition,
    CardInstance,
    GameEvent,
    MatchState,
    PlayerState,
)
from loveca.simulation.online import match_state_hash
from tools.ai_sandbox.simple_ai_acceptance import (
    SimpleAIMatchReport,
    acceptance_passed,
    continue_ai_vs_ai,
    run_acceptance_matches,
)

RULE_REFERENCE_IDS = ("8.2.2", "8.2.4", "8.3.6", "10.5.1")


def _state(members=5):
    state = MatchState(
        match_id="cycle",
        seed=7,
        phase="live_set_first",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(player_id="player_1", name="AI"),
            "player_2": PlayerState(player_id="player_2", name="Other"),
        },
        cards={},
    )
    for i in range(members):
        key = f"member-{i}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            card=CardDefinition(
                card_code=key,
                card_id=key,
                card_type="member",
                name_ja=key,
                cost=i + 1,
                blade=i + 1,
                basic_hearts={"heart01": i + 1},
            ),
        )
        state.players["player_1"].hand.append(key)
    for i in range(6):
        key = f"deck-{i}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            face_up=False,
            card=CardDefinition(
                card_code=key,
                card_id=key,
                card_type="live",
                name_ja=key,
                score=1,
                required_hearts={"heart0": 1},
            ),
        )
        state.players["player_1"].main_deck.append(key)
    state.cards["secret"] = state.cards["member-0"].model_copy(
        update={"instance_id": "secret", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["secret"]
    return state


def _choose(state, policy="simple_ai_v1_2", legal=None):
    result = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state,
        generate_legal_actions(state) if legal is None else legal,
        controlled_player_ids={"player_1"},
    )
    assert isinstance(result, SimpleAIDecision)
    return result


@pytest.mark.parametrize("members,expected", [(1, 0), (2, 0), (3, 1), (4, 2), (5, 3), (8, 3)])
def test_only_new_policy_cycles_surplus_members_and_keeps_two(members, expected):
    state = _state(members)
    before = state.model_dump(mode="json")
    decision = _choose(state)
    selected = decision.action.payload["card_instance_ids"]
    assert len(selected) == expected
    assert set(selected) <= set(state.players["player_1"].hand)
    assert not {f"member-{members - 1}", f"member-{members - 2}"} & set(selected)
    assert _choose(state, "simple_ai_v1_1").action.payload["card_instance_ids"] == []
    assert state.model_dump(mode="json") == before


def test_cycles_only_offered_members_and_respects_legal_maximum():
    state = _state(8)
    legal = [a for a in generate_legal_actions(state) if a.action_type == "set_live_cards"]
    legal[0].options.update(
        hand_instance_ids=["member-1", "member-3", "member-6", "secret"], maximum=1
    )
    assert _choose(state, legal=legal).action.payload["card_instance_ids"] == ["member-1"]


def test_live_in_hand_keeps_existing_live_plan_instead_of_member_cycle():
    state = _state()
    live = state.players["player_1"].main_deck.pop(0)
    state.players["player_1"].hand.append(live)
    decision = _choose(state)
    assert decision.action.payload["card_instance_ids"] == [live]
    assert decision.reason == "set_best_reachable_live_combo"


def test_cycle_does_not_depend_on_opponent_private_cards_or_own_deck_order():
    state = _state()
    expected = _choose(state).action
    changed = state.model_copy(deep=True)
    changed.cards["secret"].card.name_ja = "秘密変更"
    changed.cards["secret"].card.cost = 99
    changed.players["player_1"].main_deck.reverse()
    assert _choose(changed).action == expected


def test_cycle_replacement_draw_and_nonlive_reveal_use_native_rules_and_replay(tmp_path):
    from loveca.simulation.runtime import MatchRepository
    from loveca.webapp import _match_state_payload

    state = _state()
    repository = MatchRepository(tmp_path / "cycle.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    decision = _choose(state)
    selected = decision.action.payload["card_instance_ids"]
    result = repository.apply(state.match_id, decision.action)
    assert result.state.players["player_1"].live_area == selected
    assert len(result.state.players["player_1"].hand) == 5
    assert all(not result.state.cards[i].face_up for i in selected)
    visible = _match_state_payload(
        result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2"
    )
    assert not set(selected) & set(visible["state"]["cards"])
    events = list(result.events)
    for action in [
        ActionRequest(
            action_type="set_live_cards",
            player_id="player_2",
            expected_revision=1,
            payload={"card_instance_ids": []},
        ),
        ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=2),
    ]:
        result = repository.apply(state.match_id, action)
        events.extend(result.events)
    assert set(selected) <= set(result.state.players["player_1"].waiting_room)
    assert not result.state.players["player_1"].live_area
    assert not result.state.players["player_1"].success_live_area
    assert result.state.players["player_1"].live_result.total_score == 0
    assert not any(e.event_type == "yell_completed" for e in events)
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )


def test_default_and_old_policy_versions_remain_unchanged():
    from loveca.simulation.service import _new_match_controller_policy_versions

    assert SimpleAIPolicy().policy_version == "simple_ai_v1_1"
    assert _new_match_controller_policy_versions({"player_1": "simple_ai"}) == {
        "player_1": "simple_ai_v1_1"
    }
    state = _state()
    state.controller_policy_versions = {"player_1": "simple_ai_v1_2"}
    assert MatchState.model_validate_json(state.model_dump_json()) == state


def test_experimental_policy_retains_v11_efficient_match_point_live_plan():
    state = _state()
    player = state.players["player_1"]
    player.member_area["left"] = player.hand.pop()
    player.success_live_area = player.main_deck[:2]
    del player.main_deck[:2]
    player.hand.extend(player.main_deck[:2])
    del player.main_deck[:2]
    old = _choose(state, "simple_ai_v1_1").action.payload["card_instance_ids"]
    new = _choose(state).action.payload["card_instance_ids"]
    assert old == new and len(new) == 1


@pytest.mark.parametrize(
    "already,cap,expected", [(250, 300, [50]), (0, 600, [256, 256, 88]), (100, 100, [])]
)
def test_acceptance_cap_counts_all_previous_ai_actions(already, cap, expected):
    state = _state()
    events = [GameEvent(event_type="ai_action_selected") for _ in range(already)]
    calls = []

    def advance(match_id, result, *, max_ai_actions):
        calls.append(max_ai_actions)
        events.extend(GameEvent(event_type="ai_action_selected") for _ in range(max_ai_actions))
        return ActionResult(
            state=result.state.model_copy(update={"revision": result.state.revision + 1}),
            events=[],
            legal_actions=[],
        )

    service = SimpleNamespace(
        repository=SimpleNamespace(list_events=lambda _: events), advance_ai=advance
    )
    continue_ai_vs_ai(
        service, ActionResult(state=state, events=[], legal_actions=[]), max_actions=cap
    )
    assert calls == expected
    assert len(events) <= cap


@pytest.mark.parametrize("cap", [0, 3, 5])
def test_initial_service_auto_advance_is_also_inside_match_cap(tmp_path, cap):
    from tools.ai_sandbox.blackbox_playtest import build_decks

    database = Path("data/loveca.sqlite3")
    decks = build_decks(database, 2)
    reports = run_acceptance_matches(
        database,
        decks,
        mode="ai-vs-ai",
        match_count=1,
        max_actions=cap,
        policy_version="simple_ai_v1_2",
    )
    assert reports[0].ai_actions == cap
    assert reports[0].blocker == "max_actions:ai_action_cap_reached"
    assert reports[0].policy_version == "simple_ai_v1_2"
    assert reports[0].seed == 12000
    assert reports[0].replay_serialization_ok


@pytest.mark.parametrize(
    "blocker", ["engine_illegal_action", "runtime_exception", "stale_revision"]
)
def test_unsafe_failures_never_pass_acceptance_even_if_explained(blocker):
    report = SimpleAIMatchReport(
        match_index=1,
        mode="ai-vs-ai",
        first_deck="A",
        second_deck="B",
        status="blocked",
        final_phase="first_main",
        turn_number=1,
        revision=1,
        driven_human_actions=0,
        ai_actions=1,
        success_live_counts={},
        blocker=blocker,
        blocker_detail={"reason": blocker},
        replay_serialization_ok=True,
    )
    assert not acceptance_passed([report])


def test_explicit_error_skips_never_count_as_clean_acceptance():
    report = SimpleAIMatchReport(
        match_index=1,
        mode="ai-vs-ai",
        first_deck="A",
        second_deck="B",
        status="completed",
        final_phase="complete",
        turn_number=3,
        revision=60,
        driven_human_actions=0,
        ai_actions=59,
        success_live_counts={"player_1": 3, "player_2": 1},
        skipped_effects=[{"effect_id": "unsupported"}],
        replay_serialization_ok=True,
    )
    assert not acceptance_passed([report])
