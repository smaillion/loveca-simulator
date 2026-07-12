from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    _baton_replacement_static_restrictions_allow,
    _move_top_member_off_stage,
    _operation_amount,
    _ready_player_cards,
    _resolve_automatic_effects,
    _stage_member_targets_for_operation,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    GameEvent,
    MatchState,
    PlayerState,
)

PROJECT_ROOT = Path(__file__).parents[1]
DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"

FINAL_EFFECT_IDS = {
    "LL-bp2-001:2",
    "PL!-bp4-020:1",
    "PL!-pb1-017:1",
    "PL!HS-bp5-003:1",
    "PL!HS-pb1-001:1",
    "PL!HS-pb1-008:1",
    "PL!HS-pb1-008:2",
    "PL!N-bp4-023:1",
    "PL!N-bp5-005:1",
    "PL!N-bp5-006:1",
    "PL!N-pb1-001:1",
    "PL!S-bp5-001:1",
    "PL!S-bp6-001:1",
    "PL!S-sd1-006:1",
    "PL!SP-bp4-003:1",
}


def test_phase5_v1_final_exact_text_candidates_are_all_structured():
    candidates = discover_effect_candidates(
        DATABASE,
        registry_path=REGISTRY,
        include_registered=True,
    )
    final = {
        candidate.effect_id: candidate
        for candidate in candidates
        if candidate.pattern_id.startswith("phase5_v1_final")
        or candidate.pattern_id.startswith("phase5_v1_static")
    }

    assert set(final) == FINAL_EFFECT_IDS
    assert all(
        candidate.simulation_support == "test_validated_executable"
        and candidate.review_status == "test_validated"
        and candidate.execution_mode != "manual_resolution"
        for candidate in final.values()
    )


def test_selected_count_amount_applies_divisor_and_multiplier():
    operation = SimpleNamespace(
        amount=None,
        amount_source="selected_count",
        multiplier=2,
        value={"divisor": 2},
    )

    assert _operation_amount(operation, selected_count=5) == 4


def test_printemps_baton_skips_only_the_conditional_discard_step():
    effect = _registry_effect("PL!-pb1-017:1")
    state = _conditional_discard_state(effect, replacement_units=["printemps"])

    result = _apply(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-conditional", "accepted": True},
    )

    assert result.state.pending_effects == []
    assert result.state.cards["source"].orientation == "wait"
    assert result.state.players["player_1"].hand == ["spare", "drawn"]
    assert result.state.players["player_1"].waiting_room == []


def test_non_printemps_baton_requires_the_post_draw_discard_step():
    effect = _registry_effect("PL!-pb1-017:1")
    state = _conditional_discard_state(effect, replacement_units=["bibi"])

    first = _apply(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-conditional", "accepted": True},
    )

    assert len(first.state.pending_effects) == 1
    assert first.state.pending_effects[0].resolution_stage == "after_cost"
    second = _apply(
        first.state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-conditional",
            "selected_card_instance_ids": ["spare"],
        },
    )
    assert second.state.pending_effects == []
    assert second.state.players["player_1"].hand == ["drawn"]
    assert second.state.players["player_1"].waiting_room == ["spare"]


def test_baton_leave_trigger_uses_replacement_data_for_energy_and_draw():
    effect = _registry_effect("PL!N-bp5-005:1")
    source = _member("source", "PL!N-bp5-005", effect_ids=[effect.effect_id])
    replacement = _member(
        "replacement",
        "TEST-NIJI-15",
        cost=15,
        work_keys=["nijigasaki"],
    )
    cards = {
        "source": source,
        "replacement": replacement,
        "energy-1": _energy("energy-1", orientation="wait"),
        "energy-2": _energy("energy-2", orientation="wait"),
        "drawn": _member("drawn", "DRAWN"),
    }
    state = MatchState(
        match_id="baton-trigger-data",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "source", "right": None},
                energy_area=["energy-1", "energy-2"],
                main_deck=["drawn"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={effect.effect_id: effect},
    )
    events: list[GameEvent] = []

    _move_top_member_off_stage(
        state,
        "player_1",
        "center",
        "waiting_room",
        events,
        reason="baton_touch",
        trigger_data={
            "replacement_card_instance_id": "replacement",
            "used_baton_touch": True,
        },
    )
    _resolve_automatic_effects(state, events)

    assert state.pending_effects == []
    assert state.players["player_1"].waiting_room == ["source"]
    assert state.players["player_1"].hand == ["drawn"]
    assert all(
        state.cards[energy_id].orientation == "active"
        for energy_id in ("energy-1", "energy-2")
    )


def test_effect_deployment_emits_member_played_trigger_for_deployed_member():
    deploy_effect = EffectDefinition.model_validate(
        {
            "effect_id": "deploy:1",
            "card_code": "DEPLOY-SOURCE",
            "text_revision_id": 1,
            "raw_text_hash": "d" * 64,
            "effect_index": 1,
            "label_ja": "控え室から登場させる。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "waiting_room",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    onplay_effect = EffectDefinition.model_validate(
        {
            "effect_id": "deployed-onplay:1",
            "card_code": "DEPLOY-TARGET",
            "text_revision_id": 1,
            "raw_text_hash": "e" * 64,
            "effect_index": 1,
            "label_ja": "【登場】カードを1枚引く。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "auto_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"played_from_zone": "waiting_room"},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    state = MatchState(
        match_id="effect-deploy-trigger",
        seed=2,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "source", "right": None},
                waiting_room=["target"],
                main_deck=["drawn"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source": _member("source", "DEPLOY-SOURCE"),
            "target": _member(
                "target",
                "DEPLOY-TARGET",
                effect_ids=[onplay_effect.effect_id],
            ),
            "drawn": _member("drawn", "DRAWN"),
        },
        effect_definitions={
            deploy_effect.effect_id: deploy_effect,
            onplay_effect.effect_id: onplay_effect,
        },
        pending_effects=[
            EffectInvocation(
                invocation_id="deploy-invocation",
                effect_id=deploy_effect.effect_id,
                source_card_instance_id="source",
                player_id="player_1",
                trigger_event="member_played",
            )
        ],
    )

    result = _apply(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "deploy-invocation",
            "selected_card_instance_ids": ["target"],
            "selected_position_slot": "left",
        },
    )

    assert result.state.players["player_1"].member_area["left"] == "target"
    assert result.state.players["player_1"].hand == ["drawn"]
    assert result.state.pending_effects == []
    assert any(
        event.event_type == "effect_auto_resolved"
        and event.data.get("effect_id") == onplay_effect.effect_id
        for event in result.events
    )


def test_static_baton_prevention_is_applied_by_shared_rule_validation():
    effect = _registry_effect("LL-bp2-001:2")
    state = MatchState(
        match_id="static-baton-prevention",
        seed=3,
        phase="first_main",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "source", "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source": _member(
                "source",
                "LL-bp2-001",
                effect_ids=[effect.effect_id],
            ),
            "replacement": _member("replacement", "REPLACEMENT", cost=3),
        },
        effect_definitions={effect.effect_id: effect},
    )

    assert not _baton_replacement_static_restrictions_allow(
        state,
        "player_1",
        "source",
        "replacement",
    )


def test_activated_effect_is_not_legal_without_its_fixed_energy_cost():
    effect = _registry_effect("PL!HS-bp1-003:2")
    state = MatchState(
        match_id="activation-energy-gate",
        seed=4,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "source", "right": None},
                waiting_room=["target"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source": _member(
                "source",
                "PL!HS-bp1-003",
                effect_ids=[effect.effect_id],
            ),
            "target": _member(
                "target",
                "TARGET",
                cost=4,
                work_keys=["hasunosora"],
            ),
        },
        effect_definitions={effect.effect_id: effect},
    )

    assert all(
        action.action_type != "activate_effect"
        for action in generate_legal_actions(state)
    )


def test_low_original_blade_members_on_both_stages_are_set_to_wait():
    effect = _registry_effect("PL!HS-pb1-008:1")
    state = MatchState(
        match_id="wait-both-stages",
        seed=5,
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": "source", "center": "high", "right": None},
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="Player 2",
                member_area={"left": None, "center": "opponent", "right": None},
            ),
        },
        cards={
            "source": _member("source", "PL!HS-pb1-008", blade=3),
            "high": _member("high", "HIGH-BLADE", blade=4),
            "opponent": _member(
                "opponent",
                "OPPONENT",
                blade=2,
                owner_id="player_2",
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="wait-both",
                effect_id=effect.effect_id,
                source_card_instance_id="source",
                player_id="player_1",
                trigger_event="member_played",
            )
        ],
    )

    events: list[GameEvent] = []
    _resolve_automatic_effects(state, events)

    assert state.cards["source"].orientation == "wait"
    assert state.cards["opponent"].orientation == "wait"
    assert state.cards["high"].orientation == "active"
    assert state.pending_effects == []


def test_static_active_phase_ready_restrictions_do_not_block_energy():
    own_effect = _registry_effect("PL!N-bp5-006:1")
    opponent_effect = _registry_effect("PL!HS-pb1-008:2")
    state = MatchState(
        match_id="static-active-ready",
        seed=6,
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": "own-source", "center": "own-other", "right": None},
                energy_area=["energy"],
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="Player 2",
                member_area={"left": None, "center": "opponent-source", "right": None},
            ),
        },
        cards={
            "own-source": _member(
                "own-source",
                "PL!N-bp5-006",
                effect_ids=[own_effect.effect_id],
                orientation="wait",
            ),
            "own-other": _member(
                "own-other",
                "OWN-OTHER",
                orientation="wait",
            ),
            "opponent-source": _member(
                "opponent-source",
                "PL!HS-pb1-008",
                effect_ids=[opponent_effect.effect_id],
                owner_id="player_2",
            ),
            "energy": _energy("energy", orientation="wait"),
        },
        effect_definitions={
            own_effect.effect_id: own_effect,
            opponent_effect.effect_id: opponent_effect,
        },
    )

    events: list[GameEvent] = []
    _ready_player_cards(state, "player_1", events)

    assert state.cards["own-source"].orientation == "wait"
    assert state.cards["own-other"].orientation == "wait"
    assert state.cards["energy"].orientation == "active"
    assert set(events[-1].data["skipped_instance_ids"]) == {
        "own-source",
        "own-other",
    }


def test_stage_operation_targets_members_in_areas_entered_this_turn():
    player = PlayerState(
        player_id="player_1",
        name="Player 1",
        member_area={"left": "entered", "center": "old", "right": "excluded"},
        member_areas_entered_this_turn=["left", "right"],
    )
    state = MatchState(
        match_id="entered-this-turn-targets",
        seed=7,
        players={
            "player_1": player,
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source": _member("source", "SOURCE"),
            "entered": _member("entered", "ENTERED", work_keys=["nijigasaki"]),
            "old": _member("old", "OLD", work_keys=["nijigasaki"]),
            "excluded": _member(
                "excluded",
                "EXCLUDED",
                work_keys=["love_live_sunshine"],
            ),
        },
    )
    invocation = EffectInvocation(
        invocation_id="entered-targets",
        effect_id="TEST:1",
        source_card_instance_id="source",
        player_id="player_1",
        trigger_event="live_started",
    )
    operation = SimpleNamespace(
        value={
            "played_this_turn": True,
            "exclude_work_key": "love_live_sunshine",
        }
    )

    assert _stage_member_targets_for_operation(
        state,
        player,
        invocation,
        operation,
    ) == ["entered"]


def _conditional_discard_state(
    effect: EffectDefinition,
    *,
    replacement_units: list[str],
) -> MatchState:
    return MatchState(
        match_id="conditional-discard",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "source", "right": None},
                main_deck=["drawn"],
                hand=["spare"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "source": _member("source", "PL!-pb1-017", effect_ids=[effect.effect_id]),
            "replacement": _member(
                "replacement",
                "REPLACED",
                unit_keys=replacement_units,
            ),
            "spare": _member("spare", "SPARE"),
            "drawn": _member("drawn", "DRAWN"),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="inv-conditional",
                effect_id=effect.effect_id,
                source_card_instance_id="source",
                player_id="player_1",
                trigger_event="member_played",
                trigger_data={"replacement_card_instance_id": "replacement"},
            )
        ],
    )


def _registry_effect(effect_id: str) -> EffectDefinition:
    return next(
        effect for effect in load_effect_registry(REGISTRY).effects if effect.effect_id == effect_id
    )


def _member(
    instance_id: str,
    card_code: str,
    *,
    cost: int = 1,
    work_keys: list[str] | None = None,
    unit_keys: list[str] | None = None,
    effect_ids: list[str] | None = None,
    blade: int | None = None,
    orientation: str = "active",
    owner_id: str = "player_1",
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id=owner_id,
        orientation=orientation,
        card=CardDefinition(
            card_code=card_code,
            card_id=card_code,
            name_ja=card_code,
            card_type="member",
            cost=cost,
            blade=blade,
            work_keys=work_keys or [],
            unit_keys=unit_keys or [],
            effect_ids=effect_ids or [],
        ),
    )


def _energy(instance_id: str, *, orientation: str) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        orientation=orientation,
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=instance_id,
            card_type="energy",
        ),
    )


def _apply(
    state: MatchState,
    action_type: str,
    *,
    player_id: str,
    payload: dict[str, object],
):
    return apply_action(
        state,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload,
        ),
    )
