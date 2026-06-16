from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.effects import (
    EffectDefinition,
    EffectRegistry,
    validate_registry_for_cards,
)
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.engine import (
    _run_current_yell,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    GameEvent,
    ManualModifier,
    MatchState,
    PendingChoice,
    SpecialBladeHeart,
    PlayerState,
)
from loveca.simulation.service import MatchService

PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT / "data_samples" / "normalized" / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "tests" / "fixtures" / "legal-deck.json"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"
FULL_CARD_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"


def _require_full_card_database() -> Path:
    if not FULL_CARD_DATABASE.exists():
        pytest.skip("full local card database is not available in this test environment")
    return FULL_CARD_DATABASE


def test_registry_rejects_duplicate_effect_ids():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["effects"].append(payload["effects"][0])

    with pytest.raises(ValidationError, match="duplicate effect_id"):
        EffectRegistry.model_validate(payload)


def test_registry_rejects_unknown_operations():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["effects"][0]["actions"][0]["action_type"] = "invented_operation"

    with pytest.raises(ValidationError, match="unsupported effect operations"):
        EffectRegistry.model_validate(payload)


def test_registry_contains_all_matching_wait_energy_effects():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "PL!SP-PR-004": 764,
        "PL!SP-PR-006": 765,
        "PL!SP-PR-013": 771,
        "PL!SP-bp1-021": 652,
        "PL!SP-sd1-014": 705,
        "PL!SP-sd1-016": 706,
    }
    matching = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "place_energy_from_deck"
            and operation.orientation == "wait"
            for operation in effect.actions
        )
        and effect.trigger == "member_played"
    }

    assert set(matching) == set(expected)
    for card_code, revision_id in expected.items():
        effect = matching[card_code]
        assert effect.text_revision_id == revision_id
        assert effect.raw_text_hash == (
            "e265aa3650daa72a3459f55faf73e40226d3132d5a51e6efa97e0b63d13adb69"
        )
        assert effect.condition == {"minimum_energy_deck_cards": 1}
        assert effect.choice is not None
        assert effect.choice.zone == "hand"
        assert effect.choice.minimum == effect.choice.maximum == 1
        assert effect.actions[0].orientation == "wait"
    live_start = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "place_energy_from_deck"
            and operation.orientation == "wait"
            for operation in effect.actions
        )
        and effect.trigger == "live_started"
    }
    assert set(live_start) == {"PL!SP-bp5-222", "PL!SP-pb1-004"}
    assert live_start["PL!SP-bp5-222"].condition == {
        "minimum_active_energy": 1,
        "minimum_energy_deck_cards": 1,
    }
    assert live_start["PL!SP-pb1-004"].condition == {
        "minimum_active_energy": 2,
        "minimum_energy_deck_cards": 1,
    }


def test_registry_contains_expanded_exact_text_reorder_effects():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "PL!-bp3-014",
        "PL!-bp3-017",
        "PL!-bp3-018",
        "PL!N-bp3-022",
        "PL!N-bp4-016",
        "PL!S-bp6-018",
        "PL!HS-bp2-016",
        "PL!HS-pb1-024",
        "PL!-bp6-016",
        "PL!-sd1-019",
        "PL!N-bp1-002",
        "PL!S-PR-028",
        "PL!S-PR-032",
        "PL!S-PR-033",
    }
    registered = {
        effect.card_code: effect
        for effect in registry.effects
        if any(
            operation.action_type == "reorder_deck_top"
            for operation in effect.actions
        )
    }

    assert expected <= set(registered)
    assert registered["PL!-bp3-017"].choice is not None
    assert registered["PL!-bp3-017"].choice.amount == 2
    assert registered["PL!-bp3-017"].cost[0].action_type == "apply_wait"
    assert registered["PL!HS-bp2-016"].cost == []
    assert registered["PL!-bp6-016"].trigger == "live_succeeded"
    assert registered["PL!-bp6-016"].choice.minimum == 3
    assert registered["PL!S-PR-028"].trigger == "member_played"
    assert registered["PL!S-PR-028"].simulation_support == "test_validated_executable"
    assert registered["PL!S-PR-028"].choice.amount == 3
    assert registered["PL!N-bp1-002"].choice.maximum == 3


def test_effect_candidate_discovery_is_review_only_after_registry_update():
    database = _require_full_card_database()
    remaining = discover_effect_candidates(database)
    all_candidates = discover_effect_candidates(
        database,
        include_registered=True,
    )

    assert remaining == []
    assert len(all_candidates) >= 425
    assert len({candidate.card_code for candidate in all_candidates}) >= 417
    assert all(candidate.already_registered for candidate in all_candidates)
    assert {candidate.pattern_id for candidate in all_candidates} >= {
        "onplay_wait_inspect2_reorder_rest_wr",
        "onplay_inspect2_reorder_rest_wr",
        "onplay_inspect3_reorder_rest_wr",
        "live_success_inspect3_reorder_all_top",
        "live_success_inspect3_reorder_rest_wr",
        "activated_wait_ready_other_member",
        "onplay_choose_draw_discard_or_wait_opponent_cost2",
        "onplay_mill5",
        "onplay_reveal3_opponent_hand_draw_if_no_live",
        "onplay_both_deploy_cost2_waiting_member",
        "onplay_baton_lower_both_discard_to3_draw3",
        "onplay_energy11_return_live",
        "live_start_deep_success_count2_score5_replace_required_superstar",
        "live_start_deep_center_liella_cost_higher_than_opponent_score1",
        "live_start_deep_hasunosora_stage_distinct_score2_each",
        "live_start_deep_hasunosora_stage3_waiting_dream_believers_score1",
        "live_start_deep_stage_member_heart02_4_score2_replace_heart02_5",
        "live_start_deep_nijigasaki_live_or_success_required_heart01_4_score1",
        "live_start_deep_liella_stage_total_heart11_score1",
        "live_start_deep_success_score6_required_any_minus1_score9_plus1",
        "live_start_deep_success_score_values_1_or_5_bonus",
        "live_start_deep_success_emotion_each_score2_required_any_plus3",
        "live_start_deep_liella_stage_waiting_distinct5_replace_required_heart02_03_06",
        "live_start_deep_all_aqours_stage_blade1",
        "live_start_deep_live_area_other_aqours_live_stage_blade1",
        "live_start_deep_other_hasu_live_area_required_heart04_minus2_each",
        "live_start_deep_discard1_other_stage_members_blade1",
        "live_start_deep_stage_member_non_heart01_06_required_any_minus_each",
        "live_start_deep_center_muse_heart03_pairs_required_any_minus_max3",
        "live_start_deep_kosuzu_sayaka_cost_relation_required_any_minus3",
        "live_start_deep_hasunosora_member_replace_base_hearts_heart01",
        "live_start_deep_hasunosora_stage_cost20_inspect2_keep1_top_cost30_required_any_minus2",
        "live_start_deep_success_exists_choose_muse_member_heart1",
        "live_start_deep_nijigasaki_waiting_distinct_live4_score1_6_score2",
        "live_start_deep_left_liella_heart02_3_blade2",
        "live_start_deep_hasunosora_stage_waiting_distinct6_required_any_minus2",
        "live_start_deep_moved_liella_stage_blade1",
        "live_start_deep_moved_5yncri5e_required_any_minus_each",
        "live_start_deep_catchu_distinct2_ready_energy6_all_active_score1",
        "live_start_deep_replace_yell_blade_hearts_heart05",
        "live_start_deep_replace_yell_blade_hearts_heart06",
        "live_start_grouped_superstar_named_and_other_liella_blade",
        "live_start_pay2_or_discard2",
        "live_start_draw1_discard1",
        "manual_timing_fallback",
    }
    energy_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp1-007:1"
    )
    assert energy_return_candidate.simulation_support == "test_validated_executable"
    assert energy_return_candidate.condition == {"own_energy_count_at_least": 11}
    assert energy_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "minimum": 1,
        "maximum": 1,
    }
    assert energy_return_candidate.actions == [
        {"action_type": "return_from_waiting_room"}
    ]
    replace_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-023:1"
    )
    assert replace_candidate.simulation_support == "test_validated_executable"
    assert replace_candidate.condition == {"success_live_count_at_least": 2}
    assert [operation["action_type"] for operation in replace_candidate.actions] == [
        "modify_score",
        "replace_required_hearts",
    ]
    assert replace_candidate.actions[1]["value"] == {
        "heart0": 3,
        "heart02": 3,
        "heart03": 3,
        "heart06": 3,
    }
    center_cost_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-024:1"
    )
    assert center_cost_candidate.simulation_support == "test_validated_executable"
    assert center_cost_candidate.condition == {
        "center_member_work_cost_greater_than_opponent": {
            "work_key": "love_live_superstar",
        }
    }
    assert center_cost_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    hasu_distinct_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp2-020:2"
    )
    assert hasu_distinct_candidate.simulation_support == "test_validated_executable"
    assert hasu_distinct_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "own_stage_member_work_distinct_name_count",
            "multiplier": 2,
            "value": {"work_key": "hasunosora"},
        }
    ]
    heart_replace_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-028:1"
    )
    assert heart_replace_candidate.condition == {
        "own_stage_member_heart_at_least": {"color_slot": "heart02", "count": 4}
    }
    assert heart_replace_candidate.actions[1] == {
        "action_type": "replace_required_hearts",
        "value": {"heart02": 5},
    }
    aqours_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-sd1-022:1"
    )
    assert aqours_blade_candidate.actions == [
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 1,
            "value": {"unit_key": "aqours"},
        }
    ]
    aqours_live_area_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp2-023:1"
    )
    assert aqours_live_area_blade_candidate.condition == {
        "live_area_card_exists": {
            "card_type": "live",
            "work_key": "love_live_sunshine",
            "exclude_name_ja": "MY舞☆TONIGHT",
        }
    }
    assert aqours_live_area_blade_candidate.actions == [
        {"action_type": "gain_blade_to_stage_members", "amount": 1}
    ]
    hasu_live_area_required_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp5-019:1"
    )
    assert hasu_live_area_required_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount_source": "other_live_area_work_count",
            "multiplier": -2,
            "color_slot": "heart04",
            "value": {
                "card_type": "live",
                "work_key": "hasunosora",
            },
        }
    ]
    other_member_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-pb1-010:1"
    )
    assert other_member_blade_candidate.execution_mode == "prompt_then_resolve"
    assert other_member_blade_candidate.cost_choice == {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert other_member_blade_candidate.cost == [{"action_type": "discard_from_hand"}]
    assert other_member_blade_candidate.actions == [
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 1,
            "value": {"exclude_source": True},
        }
    ]
    grouped_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-023:1"
    )
    assert grouped_blade_candidate.simulation_support == "test_validated_executable"
    assert grouped_blade_candidate.choice is not None
    assert grouped_blade_candidate.choice["choice_type"] == "member_group_from_stage"
    assert grouped_blade_candidate.choice["selection_groups"][0]["name_ja_any"] == [
        "澁谷かのん",
        "ウィーン・マルガレーテ",
        "鬼塚冬毬",
    ]
    assert grouped_blade_candidate.choice["selection_groups"][1]["work_key"] == (
        "love_live_superstar"
    )
    assert grouped_blade_candidate.choice["selection_groups"][1]["exclude_group_ids"] == [
        "named_member"
    ]
    assert grouped_blade_candidate.actions == [
        {"action_type": "gain_blade", "amount": 1}
    ]
    nijigasaki_draw_top_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-031:1"
    )
    assert nijigasaki_draw_top_candidate.condition == {
        "own_stage_member_work_count_at_least": {
            "work_key": "nijigasaki",
            "count": 3,
        },
        "own_stage_member_work_cost_sum_at_least": {
            "work_key": "nijigasaki",
            "count": 20,
        },
    }
    assert nijigasaki_draw_top_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 3,
        "maximum": 3,
    }
    assert nijigasaki_draw_top_candidate.actions == [
        {"action_type": "draw_card", "amount": 3},
        {"action_type": "move_selected_to_deck_top"},
    ]
    hasunosora_baton_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp2-023:1"
    )
    assert hasunosora_baton_candidate.condition == {
        "own_baton_entered_stage_member_work_count_at_least": {
            "work_key": "hasunosora",
            "count": 2,
        }
    }
    assert hasunosora_baton_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount": -1,
            "color_slot": "heart05",
        }
    ]
    non_heart01_06_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp5-023:1"
    )
    assert non_heart01_06_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount_source": "stage_member_with_heart_excluding_colors_count",
            "multiplier": -1,
            "color_slot": "heart0",
            "value": {"exclude_color_slots": ["heart01", "heart06"]},
        }
    ]
    center_muse_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp5-020:1"
    )
    assert center_muse_heart_candidate.condition == {
        "own_stage_slot_member_work": {
            "slot": "center",
            "work_key": "love_live",
        }
    }
    assert center_muse_heart_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount_source": "stage_slot_member_heart_pair_count",
            "multiplier": -1,
            "color_slot": "heart0",
            "value": {
                "slot": "center",
                "work_key": "love_live",
                "color_slot": "heart03",
                "divisor": 2,
                "cap": 3,
            },
        }
    ]
    kosuzu_sayaka_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp2-024:1"
    )
    assert kosuzu_sayaka_candidate.condition == {
        "own_stage_named_member_cost_greater_than_named": {
            "lower_name_ja": "徒町小鈴",
            "higher_name_ja": "村野さやか",
        }
    }
    assert kosuzu_sayaka_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount": -3,
            "color_slot": "heart0",
        }
    ]
    replace_base_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp5-021:1"
    )
    assert replace_base_heart_candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "work_key": "hasunosora",
        "minimum": 1,
        "maximum": 1,
    }
    assert replace_base_heart_candidate.actions == [
        {"action_type": "replace_member_base_hearts", "color_slot": "heart01"}
    ]
    hasu_cost_inspect_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-029:1"
    )
    assert hasu_cost_inspect_candidate.condition == {
        "own_stage_member_work_cost_sum_at_least": {
            "work_key": "hasunosora",
            "count": 20,
        }
    }
    assert hasu_cost_inspect_candidate.choice == {
        "choice_type": "inspect_top_select",
        "amount": 2,
        "minimum": 1,
        "maximum": 1,
        "requires_order": False,
        "selected_destination": "hand",
        "unselected_destination": "main_deck_top_ordered",
        "reveal_selected_to_opponent": False,
    }
    assert hasu_cost_inspect_candidate.actions[-1] == {
        "action_type": "modify_required_heart",
        "amount_source": "stage_member_work_cost_sum_threshold_bonus",
        "color_slot": "heart0",
        "value": {
            "work_key": "hasunosora",
            "thresholds": {"30": -2},
        },
    }
    muse_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp3-024:1"
    )
    assert muse_heart_candidate.condition == {"success_live_count_at_least": 1}
    assert muse_heart_candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "work_key": "love_live",
        "color_slots": ["heart01", "heart03", "heart06"],
        "minimum": 1,
        "maximum": 1,
    }
    assert muse_heart_candidate.actions == [
        {"action_type": "gain_heart", "amount": 1}
    ]
    nijigasaki_waiting_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-028:1"
    )
    assert nijigasaki_waiting_candidate.condition == {
        "waiting_room_live_work_distinct_name_count_at_least": {
            "work_key": "nijigasaki",
            "count": 4,
        }
    }
    assert nijigasaki_waiting_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "waiting_room_live_work_distinct_name_threshold_bonus",
            "value": {
                "work_key": "nijigasaki",
                "thresholds": {"4": 1, "6": 2},
            },
        }
    ]
    left_liella_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-024:2"
    )
    assert left_liella_candidate.condition == {
        "own_stage_slot_member_heart_at_least": {
            "slot": "left",
            "work_key": "love_live_superstar",
            "color_slot": "heart02",
            "count": 3,
        }
    }
    assert left_liella_candidate.actions == [
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 2,
            "value": {"slot": "left", "work_key": "love_live_superstar"},
        }
    ]
    named_superstar_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp1-024:1"
    )
    assert named_superstar_candidate.simulation_support == "test_validated_executable"
    assert named_superstar_candidate.actions == [
        {
            "action_type": "gain_heart_to_stage_members",
            "amount": 1,
            "color_slot": "heart05",
            "value": {"name_ja": "澁谷かのん", "maximum": 1},
        },
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 1,
            "value": {"name_ja": "澁谷かのん", "maximum": 1},
        },
        {
            "action_type": "gain_heart_to_stage_members",
            "amount": 1,
            "color_slot": "heart01",
            "value": {"name_ja": "唐 可可", "maximum": 1},
        },
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 1,
            "value": {"name_ja": "唐 可可", "maximum": 1},
        },
    ]
    nijigasaki_ready_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-pb1-037:1"
    )
    assert nijigasaki_ready_candidate.condition == {
        "effect_ready_history": {"work_key": "nijigasaki", "ready_type": "energy"}
    }
    assert nijigasaki_ready_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "effect_ready_history_score_bonus",
            "value": {
                "work_key": "nijigasaki",
                "energy_bonus": 1,
                "member_bonus": 2,
            },
        }
    ]
    blue_yell_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-025:1"
    )
    assert blue_yell_candidate.simulation_support == "test_validated_executable"
    assert blue_yell_candidate.actions == [
        {
            "action_type": "replace_yell_blade_hearts",
            "color_slot": "heart05",
            "value": {"include_all_color": True},
        }
    ]
    purple_yell_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-023:2"
    )
    assert purple_yell_candidate.actions == [
        {
            "action_type": "replace_yell_blade_hearts",
            "color_slot": "heart06",
            "value": {"include_all_color": True},
        }
    ]
    moved_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp5-024:1"
    )
    assert moved_heart_candidate.execution_mode == "prompt_then_resolve"
    assert moved_heart_candidate.choice == {
        "choice_type": "choose_color",
        "color_slots": ["heart01", "heart02", "heart06"],
        "minimum": 0,
        "maximum": 0,
    }
    assert moved_heart_candidate.actions == [
        {
            "action_type": "gain_heart_to_stage_members",
            "amount": 1,
            "value": {"moved_this_turn": True},
        }
    ]
    nijigasaki_variety_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp1-027:1"
    )
    assert nijigasaki_variety_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "stage_member_heart_color_variety_count",
            "value": {
                "work_key": "nijigasaki",
                "color_slots": [
                    "heart01",
                    "heart04",
                    "heart05",
                    "heart02",
                    "heart03",
                    "heart06",
                ],
            },
        }
    ]
    live_start_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-030:1"
    )
    assert live_start_draw_discard_candidate.simulation_support == (
        "test_validated_executable"
    )
    assert live_start_draw_discard_candidate.timing == "live_start"
    assert live_start_draw_discard_candidate.trigger == "live_started"
    assert live_start_draw_discard_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert live_start_draw_discard_candidate.actions == [
        {"action_type": "draw_card", "amount": 1},
        {"action_type": "discard_from_hand"},
    ]
    live_success_return_member_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-025:2"
    )
    assert live_success_return_member_candidate.condition == {
        "own_hand_count_at_most": 6
    }
    assert live_success_return_member_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "member",
        "minimum": 1,
        "maximum": 1,
    }
    assert live_success_return_member_candidate.actions == [
        {"action_type": "return_from_waiting_room"}
    ]
    moved_liella_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-025:1"
    )
    assert moved_liella_candidate.simulation_support == "test_validated_executable"
    assert moved_liella_candidate.actions == [
        {
            "action_type": "gain_blade_to_stage_members",
            "amount": 1,
            "value": {
                "work_key": "love_live_superstar",
                "moved_this_turn": True,
            },
        }
    ]
    success_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp4-021:1"
    )
    assert success_score_candidate.condition == {"success_live_score_at_least": 6}
    assert success_score_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount": -1,
            "color_slot": "heart0",
        },
        {
            "action_type": "modify_score",
            "amount_source": "success_live_score_threshold_bonus",
            "value": {"thresholds": {"9": 1}},
        },
    ]
    success_score_values_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp3-026:1"
    )
    assert success_score_values_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "success_live_score_values_bonus",
            "value": {"scores": [1, 5]},
        }
    ]
    moved_5yncri5e_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-025:1"
    )
    assert moved_5yncri5e_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount_source": "moved_stage_member_count",
            "multiplier": -1,
            "color_slot": "heart0",
            "value": {"unit_key": "5yncri5e"},
        }
    ]
    catchu_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-023:1"
    )
    assert catchu_energy_candidate.condition == {
        "own_stage_member_unit_distinct_name_count_at_least": {
            "unit_key": "catchu",
            "count": 2,
        }
    }
    assert catchu_energy_candidate.choice == {
        "choice_type": "energy_from_area",
        "zone": "energy_area",
        "orientation": "wait",
        "minimum": 0,
        "maximum": 6,
    }
    assert catchu_energy_candidate.actions == [
        {"action_type": "ready_energy"},
        {"action_type": "modify_score", "amount_source": "all_energy_active_bonus"},
    ]
    emotion_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-027:1"
    )
    assert emotion_candidate.condition == {
        "success_live_name_count_at_least": {
            "name_ja": "EMOTION",
            "count": 1,
        }
    }
    assert emotion_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "success_live_name_count",
            "multiplier": 2,
            "value": {"name_ja": "EMOTION"},
        },
        {
            "action_type": "modify_required_heart",
            "amount_source": "success_live_name_count",
            "multiplier": 3,
            "color_slot": "heart0",
            "value": {"name_ja": "EMOTION"},
        },
    ]
    liella_replace_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp1-026:1"
    )
    assert liella_replace_candidate.condition == {
        "own_stage_waiting_member_work_distinct_name_count_at_least": {
            "work_key": "love_live_superstar",
            "count": 5,
        }
    }
    assert liella_replace_candidate.actions == [
        {
            "action_type": "replace_required_hearts",
            "value": {"heart02": 2, "heart03": 2, "heart06": 2},
        }
    ]
    pay_or_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-001:1"
    )
    assert pay_or_discard_candidate.simulation_support == (
        "test_validated_executable"
    )
    assert pay_or_discard_candidate.choice == {
        "choice_type": "choose_effect_branch",
        "zone": "hand",
        "branch_ids": ["pay_energy", "discard_hand"],
        "branch_selection_minimum": {"discard_hand": 2},
        "branch_selection_maximum": {"discard_hand": 2},
        "branch_energy_required": {"pay_energy": 2},
    }
    assert pay_or_discard_candidate.actions == [
        {"action_type": "pay_energy", "amount": 2, "branch": "pay_energy"},
        {"action_type": "discard_from_hand", "branch": "discard_hand"},
    ]


def test_effect_registry_timing_prompt_coverage_exceeds_target():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    registered_card_codes = {effect.card_code for effect in registry.effects}

    import sqlite3

    connection = sqlite3.connect(_require_full_card_database())
    try:
        cards_with_text = connection.execute(
            """
            SELECT COUNT(DISTINCT gameplay_card_id)
            FROM card_text_revisions
            WHERE raw_effect_text_ja IS NOT NULL
              AND TRIM(raw_effect_text_ja) <> ''
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert cards_with_text
    assert len(registered_card_codes) / cards_with_text >= 0.30


def test_place_energy_from_deck_requires_orientation():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    effect = next(
        item
        for item in payload["effects"]
        if item["card_code"] == "PL!SP-bp1-021"
    )
    del effect["actions"][0]["orientation"]

    with pytest.raises(ValidationError, match="requires an orientation"):
        EffectRegistry.model_validate(payload)


def test_required_heart_modifier_changes_live_requirement():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-required-heart:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="a" * 64,
            effect_index=1,
            label_ja="required heart test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount": -1,
                    "color_slot": "heart01",
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    from loveca.simulation.engine import _effective_required_hearts

    player = result.state.players["player_1"]
    assert _effective_required_hearts(
        player,
        "live-1",
        {"heart01": 2, "heart0": 1},
    ) == {"heart0": 1, "heart01": 1}


def test_baton_entered_hasunosora_condition_controls_required_heart_modifier():
    effect = EffectDefinition(
        effect_id="test-hasu-baton-required:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="c" * 64,
        effect_index=1,
        label_ja="hasunosora baton required heart test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_baton_entered_stage_member_work_count_at_least": {
                "work_key": "hasunosora",
                "count": 2,
            }
        },
        actions=[
            {
                "action_type": "modify_required_heart",
                "amount": -1,
                "color_slot": "heart05",
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    hasu_member = CardDefinition(
        card_code="TEST-HASU",
        card_id="TEST-HASU",
        name_ja="蓮ノ空テスト",
        card_type="member",
        work_keys=["hasunosora"],
    )
    for instance_id in ["left-member", "center-member"]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=hasu_member,
        )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": None,
    }
    player.member_areas_entered_this_turn = ["left", "center"]

    with pytest.raises(Exception, match="baton_entered_stage_member_work_count_too_low"):
        apply_action(
            state.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={"invocation_id": "inv-1", "accepted": True},
            ),
        )
    assert state.players["player_1"].manual_modifiers == []

    player.member_areas_baton_entered_this_turn = ["left", "center"]
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.color_slot, item.amount) for item in modifiers] == [
        ("required_heart", "heart05", -1)
    ]


def test_reveal_top_cards_score_modifier_counts_revealed_lives():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-reveal-score:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="b" * 64,
            effect_index=1,
            label_ja="reveal score test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {"action_type": "reveal_top_cards", "amount": 3},
                {"action_type": "modify_score", "amount_source": "revealed_live_count"},
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    player = result.state.players["player_1"]
    assert player.main_deck == []
    assert player.waiting_room == ["deck-live-1", "deck-member-1", "deck-live-2"]
    assert [modifier.modifier_type for modifier in player.manual_modifiers] == ["score"]
    assert player.manual_modifiers[0].amount == 2


def test_moved_liella_stage_member_blade_modifier_filters_by_turn_movement():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-moved-liella-blade:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="c" * 64,
            effect_index=1,
            label_ja="moved Liella blade test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {
                        "work_key": "love_live_superstar",
                        "moved_this_turn": True,
                    },
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    liella_moved = CardDefinition(
        card_code="TEST-LIELLA-MOVED",
        card_id="TEST-LIELLA-MOVED",
        name_ja="移動したLiella",
        card_type="member",
        work_keys=["love_live_superstar"],
    )
    liella_static = liella_moved.model_copy(
        update={"card_code": "TEST-LIELLA-STATIC", "card_id": "TEST-LIELLA-STATIC"}
    )
    aqours_moved = liella_moved.model_copy(
        update={
            "card_code": "TEST-AQOURS-MOVED",
            "card_id": "TEST-AQOURS-MOVED",
            "work_keys": ["love_live_sunshine"],
        }
    )
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=liella_moved,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=liella_static,
    )
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=aqours_moved,
    )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": "right-member",
    }
    player.member_areas_entered_this_turn = ["left", "right"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.target_card_instance_id) for item in modifiers] == [
        ("blade", "left-member")
    ]


def test_live_area_card_condition_grants_stage_wide_blade_modifier():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-live-area-aqours-blade:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="3" * 64,
            effect_index=1,
            label_ja="live area Aqours blade test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={
                "live_area_card_exists": {
                    "card_type": "live",
                    "work_key": "love_live_sunshine",
                    "exclude_name_ja": "MY舞☆TONIGHT",
                }
            },
            actions=[{"action_type": "gain_blade_to_stage_members", "amount": 1}],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    aqours_live = CardDefinition(
        card_code="TEST-AQOURS-LIVE",
        card_id="TEST-AQOURS-LIVE",
        name_ja="君のこころは輝いてるかい？",
        card_type="live",
        score=1,
        work_keys=["love_live_sunshine"],
    )
    member = CardDefinition(
        card_code="TEST-STAGE-MEMBER",
        card_id="TEST-STAGE-MEMBER",
        name_ja="ステージメンバー",
        card_type="member",
    )
    state.cards["live-1"].card = aqours_live
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=member,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=member.model_copy(
            update={"card_code": "TEST-STAGE-MEMBER-2", "card_id": "TEST-STAGE-MEMBER-2"}
        ),
    )
    state.players["player_1"].member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": None,
    }

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.target_card_instance_id) for item in modifiers] == [
        ("blade", "left-member"),
        ("blade", "center-member"),
    ]


def test_other_live_area_work_count_modifies_required_heart():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-other-hasu-live-required:1",
            card_code="TEST-HASU-LIVE",
            text_revision_id=1,
            raw_text_hash="4" * 64,
            effect_index=1,
            label_ja="other Hasunosora Live required Heart test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "other_live_area_work_count",
                    "multiplier": -2,
                    "color_slot": "heart04",
                    "value": {
                        "card_type": "live",
                        "work_key": "hasunosora",
                    },
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    source_live = CardDefinition(
        card_code="TEST-HASU-LIVE",
        card_id="TEST-HASU-LIVE",
        name_ja="蓮ノ空ソース",
        card_type="live",
        score=1,
        work_keys=["hasunosora"],
    )
    other_hasu_live = source_live.model_copy(
        update={"card_code": "TEST-HASU-OTHER", "card_id": "TEST-HASU-OTHER"}
    )
    non_hasu_live = source_live.model_copy(
        update={
            "card_code": "TEST-NON-HASU",
            "card_id": "TEST-NON-HASU",
            "work_keys": ["love_live_sunshine"],
        }
    )
    state.cards["source-live"].card = source_live
    state.cards["live-1"].card = source_live
    state.cards["other-hasu-1"] = CardInstance(
        instance_id="other-hasu-1",
        owner_id="player_1",
        card=other_hasu_live,
    )
    state.cards["other-hasu-2"] = CardInstance(
        instance_id="other-hasu-2",
        owner_id="player_1",
        card=other_hasu_live.model_copy(
            update={"card_code": "TEST-HASU-OTHER-2", "card_id": "TEST-HASU-OTHER-2"}
        ),
    )
    state.cards["other-work-live"] = CardInstance(
        instance_id="other-work-live",
        owner_id="player_1",
        card=non_hasu_live,
    )
    state.players["player_1"].live_area = [
        "source-live",
        "other-hasu-1",
        "other-hasu-2",
        "other-work-live",
    ]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.color_slot, item.amount) for item in modifiers] == [
        ("required_heart", "heart04", -4)
    ]


def test_other_stage_members_blade_modifier_excludes_source_after_discard_cost():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-other-stage-members-blade:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="5" * 64,
            effect_index=1,
            label_ja="other stage members blade test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=True,
            cost_choice={
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            cost=[{"action_type": "discard_from_hand"}],
            actions=[
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"exclude_source": True},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="ソースメンバー",
        card_type="member",
    )
    other_member = source_member.model_copy(
        update={"card_code": "TEST-OTHER-MEMBER", "card_id": "TEST-OTHER-MEMBER"}
    )
    hand_card = source_member.model_copy(
        update={"card_code": "TEST-HAND", "card_id": "TEST-HAND"}
    )
    state.cards["source-live"].card = source_member
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=other_member,
    )
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=other_member.model_copy(
            update={"card_code": "TEST-OTHER-MEMBER-2", "card_id": "TEST-OTHER-MEMBER-2"}
        ),
    )
    state.cards["hand-card"] = CardInstance(
        instance_id="hand-card",
        owner_id="player_1",
        card=hand_card,
    )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "source-live",
        "right": "right-member",
    }
    player.hand = ["hand-card"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_card_instance_ids": ["hand-card"],
            },
        ),
    )

    player = result.state.players["player_1"]
    assert player.hand == []
    assert player.waiting_room == ["hand-card"]
    assert [(item.modifier_type, item.target_card_instance_id) for item in player.manual_modifiers] == [
        ("blade", "left-member"),
        ("blade", "right-member"),
    ]


def test_stage_member_non_excluded_heart_colors_count_modifies_required_heart():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-non-excluded-heart-colors-required:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="6" * 64,
            effect_index=1,
            label_ja="non-excluded Heart color count test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "stage_member_with_heart_excluding_colors_count",
                    "multiplier": -1,
                    "color_slot": "heart0",
                    "value": {"exclude_color_slots": ["heart01", "heart06"]},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    heart01_member = CardDefinition(
        card_code="TEST-HEART01",
        card_id="TEST-HEART01",
        name_ja="ピンクのみ",
        card_type="member",
        basic_hearts={"heart01": 2},
    )
    heart02_member = heart01_member.model_copy(
        update={
            "card_code": "TEST-HEART02",
            "card_id": "TEST-HEART02",
            "basic_hearts": {"heart02": 1},
        }
    )
    heart06_plus_temp_member = heart01_member.model_copy(
        update={
            "card_code": "TEST-HEART06",
            "card_id": "TEST-HEART06",
            "basic_hearts": {"heart06": 1},
        }
    )
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=heart01_member,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=heart02_member,
    )
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=heart06_plus_temp_member,
    )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": "right-member",
    }
    player.manual_modifiers.append(
        ManualModifier(
            modifier_id="test:heart03:right",
            modifier_type="heart",
            duration="live",
            created_turn=state.turn_number,
            amount=1,
            color_slot="heart03",
            target_card_instance_id="right-member",
        )
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    required_modifiers = [
        modifier
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "required_heart"
    ]
    assert [(item.color_slot, item.amount) for item in required_modifiers] == [
        ("heart0", -2)
    ]


def test_center_member_heart_pairs_modify_required_heart_with_cap():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-center-heart-pairs-required:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="b" * 64,
            effect_index=1,
            label_ja="center Heart pair count test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={
                "own_stage_slot_member_work": {
                    "slot": "center",
                    "work_key": "love_live",
                }
            },
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "stage_slot_member_heart_pair_count",
                    "multiplier": -1,
                    "color_slot": "heart0",
                    "value": {
                        "slot": "center",
                        "work_key": "love_live",
                        "color_slot": "heart03",
                        "divisor": 2,
                        "cap": 3,
                    },
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    center_member = CardDefinition(
        card_code="TEST-MUSE-CENTER",
        card_id="TEST-MUSE-CENTER",
        name_ja="μ'sセンター",
        card_type="member",
        basic_hearts={"heart03": 7},
        work_keys=["love_live"],
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=center_member,
    )
    state.players["player_1"].member_area = {
        "left": None,
        "center": "center-member",
        "right": None,
    }

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    required_modifiers = [
        modifier
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "required_heart"
    ]
    assert [(item.color_slot, item.amount) for item in required_modifiers] == [
        ("heart0", -3)
    ]


def test_named_stage_member_cost_relation_modifies_required_heart():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-named-cost-required:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="c" * 64,
            effect_index=1,
            label_ja="named stage cost relation test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={
                "own_stage_named_member_cost_greater_than_named": {
                    "lower_name_ja": "徒町小鈴",
                    "higher_name_ja": "村野さやか",
                }
            },
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount": -3,
                    "color_slot": "heart0",
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    kosuzu = CardDefinition(
        card_code="TEST-KOSUZU",
        card_id="TEST-KOSUZU",
        name_ja="徒町小鈴",
        card_type="member",
        cost=2,
    )
    sayaka = kosuzu.model_copy(
        update={
            "card_code": "TEST-SAYAKA",
            "card_id": "TEST-SAYAKA",
            "name_ja": "村野さやか",
            "cost": 4,
        }
    )
    state.cards["kosuzu-member"] = CardInstance(
        instance_id="kosuzu-member",
        owner_id="player_1",
        card=kosuzu,
    )
    state.cards["sayaka-member"] = CardInstance(
        instance_id="sayaka-member",
        owner_id="player_1",
        card=sayaka,
    )
    state.players["player_1"].member_area = {
        "left": "kosuzu-member",
        "center": "sayaka-member",
        "right": None,
    }

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    required_modifiers = [
        modifier
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "required_heart"
    ]
    assert [(item.color_slot, item.amount) for item in required_modifiers] == [
        ("heart0", -3)
    ]


def test_replace_member_base_hearts_preserves_total_and_allows_temp_hearts():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-replace-base-hearts:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="d" * 64,
            effect_index=1,
            label_ja="replace base Heart test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            choice={
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "hasunosora",
                "minimum": 1,
                "maximum": 1,
            },
            actions=[
                {
                    "action_type": "replace_member_base_hearts",
                    "color_slot": "heart01",
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    target_member = CardDefinition(
        card_code="TEST-HASU-HEARTS",
        card_id="TEST-HASU-HEARTS",
        name_ja="蓮ノ空ハート",
        card_type="member",
        basic_hearts={"heart04": 2, "heart06": 1},
        work_keys=["hasunosora"],
    )
    state.cards["target-member"] = CardInstance(
        instance_id="target-member",
        owner_id="player_1",
        card=target_member,
    )
    state.players["player_1"].member_area = {
        "left": "target-member",
        "center": None,
        "right": None,
    }
    state.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="test:temp-heart06",
            modifier_type="heart",
            duration="live",
            created_turn=state.turn_number,
            amount=1,
            color_slot="heart06",
            target_card_instance_id="target-member",
        )
    )

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["target-member"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["target-member"],
            },
        ),
    )

    from loveca.simulation.engine import _member_heart_color_slots, _member_heart_count

    assert _member_heart_count(
        result.state, "player_1", "target-member", "heart01"
    ) == 3
    assert _member_heart_count(
        result.state, "player_1", "target-member", "heart04"
    ) == 0
    assert _member_heart_count(
        result.state, "player_1", "target-member", "heart06"
    ) == 1
    assert _member_heart_color_slots(
        result.state, "player_1", "target-member"
    ) == {"heart01", "heart06"}


def test_named_stage_member_heart_and_blade_modifiers_only_hit_named_targets():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-named-stage-modifiers:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="e" * 64,
            effect_index=1,
            label_ja="named stage modifier test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "gain_heart_to_stage_members",
                    "amount": 1,
                    "color_slot": "heart05",
                    "value": {"name_ja": "澁谷かのん", "maximum": 1},
                },
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"name_ja": "澁谷かのん", "maximum": 1},
                },
                {
                    "action_type": "gain_heart_to_stage_members",
                    "amount": 1,
                    "color_slot": "heart01",
                    "value": {"name_ja": "唐 可可", "maximum": 1},
                },
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"name_ja": "唐 可可", "maximum": 1},
                },
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    for instance_id, name in {
        "kanon": "澁谷かのん",
        "keke": "唐 可可",
        "other": "嵐 千砂都",
    }.items():
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{instance_id}",
                card_id=f"TEST-{instance_id}",
                name_ja=name,
                card_type="member",
                basic_hearts={},
                work_keys=["love_live_superstar"],
            ),
        )
    state.players["player_1"].member_area = {
        "left": "kanon",
        "center": "keke",
        "right": "other",
    }

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    )

    from loveca.simulation.engine import _member_heart_count, _target_modifier_total

    assert _member_heart_count(result.state, "player_1", "kanon", "heart05") == 1
    assert _member_heart_count(result.state, "player_1", "keke", "heart01") == 1
    assert _member_heart_count(result.state, "player_1", "other", "heart05") == 0
    assert _target_modifier_total(result.state.players["player_1"], "blade", "kanon") == 1
    assert _target_modifier_total(result.state.players["player_1"], "blade", "keke") == 1
    assert _target_modifier_total(result.state.players["player_1"], "blade", "other") == 0


def test_grouped_stage_member_choice_applies_blade_to_each_group_target():
    state = _minimal_effect_state(_grouped_stage_blade_effect())
    kanon = CardDefinition(
        card_code="TEST-KANON",
        card_id="TEST-KANON",
        name_ja="澁谷かのん",
        card_type="member",
        work_keys=["love_live_superstar"],
    )
    chisato = kanon.model_copy(
        update={
            "card_code": "TEST-CHISATO",
            "card_id": "TEST-CHISATO",
            "name_ja": "嵐 千砂都",
        }
    )
    honoka = kanon.model_copy(
        update={
            "card_code": "TEST-HONOKA",
            "card_id": "TEST-HONOKA",
            "name_ja": "高坂穂乃果",
            "work_keys": ["love_live"],
        }
    )
    state.cards["kanon-member"] = CardInstance(
        instance_id="kanon-member",
        owner_id="player_1",
        card=kanon,
    )
    state.cards["chisato-member"] = CardInstance(
        instance_id="chisato-member",
        owner_id="player_1",
        card=chisato,
    )
    state.cards["honoka-member"] = CardInstance(
        instance_id="honoka-member",
        owner_id="player_1",
        card=honoka,
    )
    state.players["player_1"].member_area = {
        "left": "kanon-member",
        "center": "chisato-member",
        "right": "honoka-member",
    }

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "member_group_from_stage"
    assert options["choice_groups"] == [
        {
            "group_id": "named_member",
            "label_ja": "指定名のメンバー",
            "candidate_card_instance_ids": ["kanon-member"],
            "exclude_group_ids": [],
            "minimum": 1,
            "maximum": 1,
        },
        {
            "group_id": "other_liella",
            "label_ja": "選んだメンバー以外の『Liella!』のメンバー",
            "candidate_card_instance_ids": ["kanon-member", "chisato-member"],
            "exclude_group_ids": ["named_member"],
            "minimum": 1,
            "maximum": 1,
        },
    ]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_card_instance_ids_by_group": {
                    "named_member": ["kanon-member"],
                    "other_liella": ["chisato-member"],
                },
            },
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.target_card_instance_id) for item in modifiers] == [
        ("blade", "kanon-member"),
        ("blade", "chisato-member"),
    ]
    assert result.events[-1].data["selected_card_instance_ids"] == [
        "kanon-member",
        "chisato-member",
    ]
    assert result.events[-1].data["selected_card_instance_ids_by_group"] == {
        "named_member": ["kanon-member"],
        "other_liella": ["chisato-member"],
    }


def test_grouped_stage_member_choice_rejects_duplicate_or_non_candidate_targets():
    state = _minimal_effect_state(_grouped_stage_blade_effect())
    kanon = CardDefinition(
        card_code="TEST-KANON",
        card_id="TEST-KANON",
        name_ja="澁谷かのん",
        card_type="member",
        work_keys=["love_live_superstar"],
    )
    honoka = kanon.model_copy(
        update={
            "card_code": "TEST-HONOKA",
            "card_id": "TEST-HONOKA",
            "name_ja": "高坂穂乃果",
            "work_keys": ["love_live"],
        }
    )
    state.cards["kanon-member"] = CardInstance(
        instance_id="kanon-member",
        owner_id="player_1",
        card=kanon,
    )
    state.cards["honoka-member"] = CardInstance(
        instance_id="honoka-member",
        owner_id="player_1",
        card=honoka,
    )
    state.players["player_1"].member_area = {
        "left": "kanon-member",
        "center": "honoka-member",
        "right": None,
    }

    with pytest.raises(Exception, match="grouped effect selection is not legal"):
        apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "invocation_id": "inv-1",
                    "accepted": True,
                    "selected_card_instance_ids_by_group": {
                        "named_member": ["kanon-member"],
                        "other_liella": ["kanon-member"],
                    },
                },
            ),
        )

    assert state.players["player_1"].manual_modifiers == []


def test_post_action_hand_selection_can_return_cards_to_deck_top():
    state = _minimal_effect_state(_draw_three_return_hand_three_to_top_effect())

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    drawn = ["deck-live-1", "deck-member-1", "deck-live-2"]
    assert state.players["player_1"].hand == drawn
    assert state.players["player_1"].main_deck == []
    assert state.pending_effects[0].resolution_stage == "after_cost"
    legal = generate_legal_actions(state)
    resolve_action = next(action for action in legal if action.action_type == "resolve_effect")
    invocation = resolve_action.options["invocations"][0]
    assert invocation["choice_type"] == "post_action_card_from_zone"
    assert invocation["candidate_card_instance_ids"] == drawn
    assert invocation["card_selection_minimum"] == 3
    assert invocation["card_selection_maximum"] == 3

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": [
                "deck-member-1",
                "deck-live-2",
                "deck-live-1",
            ],
        },
    )

    assert state.players["player_1"].hand == []
    assert state.players["player_1"].main_deck[:3] == [
        "deck-member-1",
        "deck-live-2",
        "deck-live-1",
    ]
    assert not state.pending_effects


def test_nijigasaki_effect_ready_history_scores_energy_or_member_bonus():
    ready_effect = EffectDefinition(
        effect_id="test-nijigasaki-ready:1",
        card_code="TEST-NIJIGASAKI",
        text_revision_id=1,
        raw_text_hash="f" * 64,
        effect_index=1,
        label_ja="Nijigasaki ready test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_energy", "amount": 1}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    score_effect = EffectDefinition(
        effect_id="test-nijigasaki-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="g" * 64,
        effect_index=1,
        label_ja="Nijigasaki ready score test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "effect_ready_history": {
                "work_key": "nijigasaki",
                "ready_type": "energy",
            }
        },
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "modify_score",
                "amount_source": "effect_ready_history_score_bonus",
                "value": {
                    "work_key": "nijigasaki",
                    "energy_bonus": 1,
                    "member_bonus": 2,
                },
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(ready_effect)
    state.cards["source-live"].card.work_keys = ["nijigasaki"]
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="テストエネルギー",
        card_type="energy",
    )
    state.cards["energy-wait"] = CardInstance(
        instance_id="energy-wait",
        owner_id="player_1",
        card=energy_card,
        orientation="wait",
    )
    state.cards["energy-active"] = CardInstance(
        instance_id="energy-active",
        owner_id="player_1",
        card=energy_card.model_copy(deep=True),
        orientation="active",
    )
    state.players["player_1"].energy_area = ["energy-wait", "energy-active"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.players["player_1"].effect_ready_flags_this_turn == [
        "nijigasaki:energy"
    ]

    state.effect_definitions[score_effect.effect_id] = score_effect
    state.pending_effects = [
        EffectInvocation(
            invocation_id="inv-score",
            effect_id=score_effect.effect_id,
            source_card_instance_id="source-live",
            player_id="player_1",
            trigger_event="live_started",
        )
    ]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-score"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in state.players["player_1"].manual_modifiers
    )

    state = _minimal_effect_state(score_effect)
    state.players["player_1"].effect_ready_flags_this_turn = [
        "nijigasaki:energy",
        "nijigasaki:member",
    ]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 2
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_yell_blade_heart_replacement_converts_regular_and_all_blade_hearts():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-yell-replacement:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="d" * 64,
            effect_index=1,
            label_ja="Yell Blade Heart replacement test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "replace_yell_blade_hearts",
                    "color_slot": "heart05",
                    "value": {"include_all_color": True},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    active_member = CardDefinition(
        card_code="TEST-ACTIVE-MEMBER",
        card_id="TEST-ACTIVE-MEMBER",
        name_ja="応援するメンバー",
        card_type="member",
        blade=2,
    )
    pink_blade_live = CardDefinition(
        card_code="TEST-PINK-BLADE",
        card_id="TEST-PINK-BLADE",
        name_ja="桃ブレード",
        card_type="live",
        blade_heart_color_slot="heart01",
    )
    all_blade_live = CardDefinition(
        card_code="TEST-ALL-BLADE",
        card_id="TEST-ALL-BLADE",
        name_ja="ALLブレード",
        card_type="live",
        special_blade_hearts=[
            SpecialBladeHeart(effect_type="all_color", value=1, source_alt="ALL1")
        ],
    )
    state.cards["active-member"] = CardInstance(
        instance_id="active-member",
        owner_id="player_1",
        card=active_member,
    )
    state.cards["pink-blade-live"] = CardInstance(
        instance_id="pink-blade-live",
        owner_id="player_1",
        card=pink_blade_live,
        face_up=False,
    )
    state.cards["all-blade-live"] = CardInstance(
        instance_id="all-blade-live",
        owner_id="player_1",
        card=all_blade_live,
        face_up=False,
    )
    player = state.players["player_1"]
    player.member_area = {"left": None, "center": "active-member", "right": None}
    player.main_deck = ["pink-blade-live", "all-blade-live"]

    resolved = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    ).state
    events: list[GameEvent] = []
    _run_current_yell(resolved, events)

    live_result = resolved.players["player_1"].live_result
    assert live_result.yell_hearts == {"heart05": 2}
    assert live_result.all_color_hearts == 0
    assert live_result.special_blade_heart_results == [
        {
            "card_instance_id": "all-blade-live",
            "effect_type": "all_color",
            "value": 1,
            "source_alt": "ALL1",
            "converted_to_color_slot": "heart05",
        }
    ]


def test_moved_stage_members_gain_selected_heart_until_live_end():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-moved-stage-heart:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="i" * 64,
            effect_index=1,
            label_ja="moved stage Heart test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            cost=[],
            choice={
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart02", "heart06"],
                "minimum": 0,
                "maximum": 0,
            },
            actions=[
                {
                    "action_type": "gain_heart_to_stage_members",
                    "amount": 1,
                    "value": {"moved_this_turn": True},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    member = CardDefinition(
        card_code="TEST-MEMBER",
        card_id="TEST-MEMBER",
        name_ja="移動メンバー",
        card_type="member",
    )
    for instance_id in ("left-member", "center-member", "right-member"):
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=member.model_copy(
                update={"card_code": f"TEST-{instance_id}", "card_id": f"TEST-{instance_id}"}
            ),
        )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": "right-member",
    }
    player.member_areas_entered_this_turn = ["left", "right"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "selected_color_slot": "heart02"},
        ),
    )

    from loveca.simulation.engine import _member_heart_count

    assert _member_heart_count(result.state, "player_1", "left-member", "heart02") == 1
    assert _member_heart_count(result.state, "player_1", "center-member", "heart02") == 0
    assert _member_heart_count(result.state, "player_1", "right-member", "heart02") == 1


def test_nijigasaki_stage_heart_color_variety_modifies_score():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-nijigasaki-heart-variety:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="j" * 64,
            effect_index=1,
            label_ja="Nijigasaki Heart variety score test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "modify_score",
                    "amount_source": "stage_member_heart_color_variety_count",
                    "value": {
                        "work_key": "nijigasaki",
                        "color_slots": [
                            "heart01",
                            "heart04",
                            "heart05",
                            "heart02",
                            "heart03",
                            "heart06",
                        ],
                    },
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    nijigasaki_member = CardDefinition(
        card_code="TEST-NIJIGASAKI-MEMBER",
        card_id="TEST-NIJIGASAKI-MEMBER",
        name_ja="虹ヶ咲メンバー",
        card_type="member",
        basic_hearts={"heart01": 1, "heart04": 1},
        work_keys=["nijigasaki"],
    )
    other_work_member = CardDefinition(
        card_code="TEST-OTHER-WORK",
        card_id="TEST-OTHER-WORK",
        name_ja="別作品メンバー",
        card_type="member",
        basic_hearts={"heart06": 1},
        work_keys=["love_live_superstar"],
    )
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=nijigasaki_member,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=nijigasaki_member.model_copy(
            update={
                "card_code": "TEST-NIJIGASAKI-MEMBER-2",
                "card_id": "TEST-NIJIGASAKI-MEMBER-2",
                "basic_hearts": {"heart05": 1, "heart02": 1},
            }
        ),
    )
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=other_work_member,
    )
    state.players["player_1"].member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": "right-member",
    }

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    )

    score_modifiers = [
        modifier
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    ]
    assert [modifier.amount for modifier in score_modifiers] == [4]


def test_inspection_choice_can_return_unselected_card_to_deck_top_and_apply_modifier():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-hasu-cost-inspect:1",
            card_code="TEST-HASU-LIVE",
            text_revision_id=1,
            raw_text_hash="7" * 64,
            effect_index=1,
            label_ja="Hasunosora cost inspect test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={
                "own_stage_member_work_cost_sum_at_least": {
                    "work_key": "hasunosora",
                    "count": 20,
                }
            },
            choice={
                "choice_type": "inspect_top_select",
                "amount": 2,
                "minimum": 1,
                "maximum": 1,
                "selected_destination": "hand",
                "unselected_destination": "main_deck_top_ordered",
            },
            actions=[
                {"action_type": "inspect_top_cards", "amount": 2},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "stage_member_work_cost_sum_threshold_bonus",
                    "color_slot": "heart0",
                    "value": {
                        "work_key": "hasunosora",
                        "thresholds": {"30": -2},
                    },
                },
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    hasu_member = CardDefinition(
        card_code="TEST-HASU-MEMBER",
        card_id="TEST-HASU-MEMBER",
        name_ja="蓮ノ空メンバー",
        card_type="member",
        cost=15,
        work_keys=["hasunosora"],
    )
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=hasu_member,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=hasu_member.model_copy(
            update={"card_code": "TEST-HASU-MEMBER-2", "card_id": "TEST-HASU-MEMBER-2"}
        ),
    )
    state.players["player_1"].member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": None,
    }
    inspected = list(state.players["player_1"].main_deck[:2])

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )
    state = result.state
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.pending_choice.options["inspected_card_instance_ids"] == inspected

    selected = inspected[0]
    unselected = inspected[1]
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect_choice",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"selected_card_instance_ids": [selected]},
        ),
    )

    player = result.state.players["player_1"]
    assert selected in player.hand
    assert player.main_deck[0] == unselected
    required_modifiers = [
        modifier
        for modifier in player.manual_modifiers
        if modifier.modifier_type == "required_heart"
    ]
    assert [(item.color_slot, item.amount) for item in required_modifiers] == [
        ("heart0", -2)
    ]


def test_success_live_score_threshold_modifies_required_heart_and_score():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-success-score-threshold:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="d" * 64,
            effect_index=1,
            label_ja="success score threshold test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={"success_live_score_at_least": 6},
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount": -1,
                    "color_slot": "heart0",
                },
                {
                    "action_type": "modify_score",
                    "amount_source": "success_live_score_threshold_bonus",
                    "value": {"thresholds": {"9": 1}},
                },
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    score4_live = CardDefinition(
        card_code="TEST-SCORE4-LIVE",
        card_id="TEST-SCORE4-LIVE",
        name_ja="スコア4",
        card_type="live",
        score=4,
    )
    score5_live = score4_live.model_copy(
        update={
            "card_code": "TEST-SCORE5-LIVE",
            "card_id": "TEST-SCORE5-LIVE",
            "score": 5,
        }
    )
    state.cards["success-4"] = CardInstance(
        instance_id="success-4",
        owner_id="player_1",
        card=score4_live,
    )
    state.cards["success-5"] = CardInstance(
        instance_id="success-5",
        owner_id="player_1",
        card=score5_live,
    )
    state.players["player_1"].success_live_area = ["success-4", "success-5"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.color_slot, item.amount) for item in modifiers] == [
        ("required_heart", "heart0", -1),
        ("score", None, 1),
    ]


def test_success_live_score_values_bonus_modifies_score():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-success-score-values:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="i" * 64,
            effect_index=1,
            label_ja="success score values test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            actions=[
                {
                    "action_type": "modify_score",
                    "amount_source": "success_live_score_values_bonus",
                    "value": {"scores": [1, 5]},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    score1_live = CardDefinition(
        card_code="TEST-SCORE1-LIVE",
        card_id="TEST-SCORE1-LIVE",
        name_ja="スコア1",
        card_type="live",
        score=1,
    )
    score5_live = CardDefinition(
        card_code="TEST-SCORE5-LIVE",
        card_id="TEST-SCORE5-LIVE",
        name_ja="スコア5",
        card_type="live",
        score=5,
    )
    state.cards["success-score-1"] = CardInstance(
        instance_id="success-score-1",
        owner_id="player_1",
        card=score1_live,
    )
    state.cards["success-score-5"] = CardInstance(
        instance_id="success-score-5",
        owner_id="player_1",
        card=score5_live,
    )
    state.players["player_1"].success_live_area = [
        "success-score-1",
        "success-score-5",
    ]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.amount) for item in modifiers] == [
        ("score", 2)
    ]


def test_member_choice_can_also_choose_heart_color():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-member-heart-choice:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="j" * 64,
            effect_index=1,
            label_ja="member heart choice test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={"success_live_count_at_least": 1},
            choice={
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live",
                "color_slots": ["heart01", "heart03", "heart06"],
                "minimum": 1,
                "maximum": 1,
            },
            actions=[{"action_type": "gain_heart", "amount": 1}],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    stage_member = CardDefinition(
        card_code="TEST-MUSE-MEMBER",
        card_id="TEST-MUSE-MEMBER",
        name_ja="μ'sテスト",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        work_keys=["love_live"],
    )
    state.cards["stage-muse"] = CardInstance(
        instance_id="stage-muse",
        owner_id="player_1",
        card=stage_member,
    )
    state.players["player_1"].member_area["center"] = "stage-muse"
    state.players["player_1"].success_live_area = ["live-1"]
    state.players["player_1"].live_area = []

    legal = generate_legal_actions(state)
    options = next(
        action.options["invocations"][0]
        for action in legal
        if action.action_type == "resolve_effect"
    )
    assert options["candidate_card_instance_ids"] == ["stage-muse"]
    assert options["color_slots"] == ["heart01", "heart03", "heart06"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_card_instance_ids": ["stage-muse"],
                "selected_color_slot": "heart03",
            },
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [
        (
            item.modifier_type,
            item.color_slot,
            item.amount,
            item.target_card_instance_id,
        )
        for item in modifiers
    ] == [("heart", "heart03", 1, "stage-muse")]


def test_success_live_name_count_amount_modifies_score_and_required_heart():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-success-name-count:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="g" * 64,
            effect_index=1,
            label_ja="success live name count test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={
                "success_live_name_count_at_least": {
                    "name_ja": "EMOTION",
                    "count": 1,
                }
            },
            actions=[
                {
                    "action_type": "modify_score",
                    "amount_source": "success_live_name_count",
                    "multiplier": 2,
                    "value": {"name_ja": "EMOTION"},
                },
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_name_count",
                    "multiplier": 3,
                    "color_slot": "heart0",
                    "value": {"name_ja": "EMOTION"},
                },
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    emotion_live = CardDefinition(
        card_code="TEST-EMOTION",
        card_id="TEST-EMOTION",
        name_ja="EMOTION",
        card_type="live",
        score=1,
    )
    other_live = emotion_live.model_copy(
        update={"card_code": "TEST-OTHER", "card_id": "TEST-OTHER", "name_ja": "OTHER"}
    )
    state.cards["emotion-1"] = CardInstance(
        instance_id="emotion-1",
        owner_id="player_1",
        card=emotion_live,
    )
    state.cards["emotion-2"] = CardInstance(
        instance_id="emotion-2",
        owner_id="player_1",
        card=emotion_live.model_copy(deep=True),
    )
    state.cards["other-live"] = CardInstance(
        instance_id="other-live",
        owner_id="player_1",
        card=other_live,
    )
    state.players["player_1"].success_live_area = [
        "emotion-1",
        "other-live",
        "emotion-2",
    ]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.color_slot, item.amount) for item in modifiers] == [
        ("score", None, 4),
        ("required_heart", "heart0", 6),
    ]


def test_moved_stage_member_count_required_heart_modifier_filters_by_unit():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-moved-5yncri5e-required:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="e" * 64,
            effect_index=1,
            label_ja="moved 5yncri5e required heart test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="auto_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            actions=[
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "moved_stage_member_count",
                    "multiplier": -1,
                    "color_slot": "heart0",
                    "value": {"unit_key": "5yncri5e"},
                }
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    unit_member = CardDefinition(
        card_code="TEST-5YN-MOVED",
        card_id="TEST-5YN-MOVED",
        name_ja="移動した5yncri5e",
        card_type="member",
        unit_keys=["5yncri5e"],
    )
    unit_static = unit_member.model_copy(
        update={"card_code": "TEST-5YN-STATIC", "card_id": "TEST-5YN-STATIC"}
    )
    other_moved = unit_member.model_copy(
        update={
            "card_code": "TEST-CATCHU-MOVED",
            "card_id": "TEST-CATCHU-MOVED",
            "unit_keys": ["catchu"],
        }
    )
    state.cards["left-member"] = CardInstance(
        instance_id="left-member",
        owner_id="player_1",
        card=unit_member,
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=unit_static,
    )
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=other_moved,
    )
    player = state.players["player_1"]
    player.member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": "right-member",
    }
    player.member_areas_entered_this_turn = ["left", "right"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )

    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.color_slot, item.amount) for item in modifiers] == [
        ("required_heart", "heart0", -1)
    ]


def test_ready_energy_then_all_active_score_bonus():
    state = _minimal_effect_state(
        EffectDefinition(
            effect_id="test-ready-energy-all-active:1",
            card_code="TEST-LIVE",
            text_revision_id=1,
            raw_text_hash="f" * 64,
            effect_index=1,
            label_ja="ready energy all active score test",
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            execution_mode="prompt_then_resolve",
            frequency_limit="once_per_live",
            is_optional=False,
            choice={
                "choice_type": "energy_from_area",
                "zone": "energy_area",
                "orientation": "wait",
                "minimum": 0,
                "maximum": 6,
            },
            actions=[
                {"action_type": "ready_energy"},
                {"action_type": "modify_score", "amount_source": "all_energy_active_bonus"},
            ],
            duration="live",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        )
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="テストエネルギー",
        card_type="energy",
    )
    for instance_id in ["energy-1", "energy-2"]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=energy,
            orientation="wait",
        )
    state.players["player_1"].energy_area = ["energy-1", "energy-2"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_card_instance_ids": ["energy-1", "energy-2"],
            },
        ),
    )

    assert [
        result.state.cards[item].orientation
        for item in result.state.players["player_1"].energy_area
    ] == ["active", "active"]
    modifiers = result.state.players["player_1"].manual_modifiers
    assert [(item.modifier_type, item.amount) for item in modifiers] == [
        ("score", 1)
    ]


def test_registry_hash_mismatch_is_explicit(tmp_path):
    service, _ = _create_match(tmp_path)
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    broken = registry.model_copy(deep=True)
    target = next(effect for effect in broken.effects if effect.effect_id == "LL-bp1-001:1")
    target.raw_text_hash = "0" * 64

    from loveca.db.bootstrap import connect_database

    connection = connect_database(service.card_database_path)
    try:
        valid, errors = validate_registry_for_cards(
            connection, broken, {"LL-bp1-001"}
        )
    finally:
        connection.close()

    assert "LL-bp1-001:1" not in valid
    assert errors["LL-bp1-001"] == [
        "LL-bp1-001:1: raw effect text hash mismatch"
    ]


def test_on_play_discard_adds_top_energy_in_wait_state(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    discard = next(
        item for item in state.players["player_1"].hand if item != source
    )
    top_energy = state.players["player_1"].energy_deck[0]

    play_result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": source,
                "slot": "center",
                "energy_instance_ids": [],
                "use_baton_touch": False,
            },
        ),
    )
    state = play_result.state
    assert state.pending_effects[0].effect_id == "test-wait-energy:1"
    legal = generate_legal_actions(state)
    invocation = legal[0].options["invocations"][0]
    assert invocation["candidate_card_instance_ids"] == state.players["player_1"].hand
    assert invocation["card_selection_minimum"] == 1
    assert invocation["card_selection_maximum"] == 1

    before_resolution = state.model_copy(deep=True)
    action = ActionRequest(
        action_type="resolve_effect",
        expected_revision=state.revision,
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
            "selected_card_instance_ids": [discard],
        },
    )
    result = apply_action(state, action)
    replay_result = apply_action(before_resolution, action)
    state = result.state

    assert discard in state.players["player_1"].waiting_room
    assert top_energy not in state.players["player_1"].energy_deck
    assert top_energy in state.players["player_1"].energy_area
    assert state.cards[top_energy].orientation == "wait"
    assert state.cards[top_energy].face_up is True
    assert state.model_dump(mode="json") == replay_result.state.model_dump(mode="json")
    assert [event.event_type for event in result.events] == [
        "effect_cost_paid",
        "energy_added",
        "effect_resolved",
    ]
    assert result.events[0].data["selected_card_instance_ids"] == [discard]
    assert result.events[1].data["instance_ids"] == [top_energy]
    assert result.events[1].data["orientation"] == "wait"
    assert result.events[1].data["reason"] == "effect:test-wait-energy:1"


def test_optional_wait_energy_effect_may_be_declined(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    state = _play_wait_energy_source(state, source)
    before = state.model_copy(deep=True)

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": state.pending_effects[0].invocation_id,
                "accepted": False,
            },
        ),
    )

    player = result.state.players["player_1"]
    assert player.hand == before.players["player_1"].hand
    assert player.waiting_room == before.players["player_1"].waiting_room
    assert player.energy_deck == before.players["player_1"].energy_deck
    assert player.energy_area == before.players["player_1"].energy_area
    assert not result.state.pending_effects
    assert result.events[0].event_type == "effect_declined"


@pytest.mark.parametrize("missing_zone", ["hand", "energy_deck"])
def test_wait_energy_effect_is_not_offered_without_required_resources(
    tmp_path, missing_zone
):
    state, source = _state_with_wait_energy_effect(tmp_path)
    if missing_zone == "hand":
        state.players["player_1"].hand = [source]
    else:
        state.players["player_1"].energy_deck = []

    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": source,
                "slot": "center",
                "energy_instance_ids": [],
                "use_baton_touch": False,
            },
        ),
    )

    assert not result.state.pending_effects
    unavailable = next(
        event for event in result.events if event.event_type == "effect_not_activatable"
    )
    expected_reason = (
        "choice_candidates_unavailable"
        if missing_zone == "hand"
        else "energy_deck_empty"
    )
    assert unavailable.data["reason"] == expected_reason


def test_wait_energy_effect_resolution_is_atomic_if_energy_deck_changes(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    state = _play_wait_energy_source(state, source)
    discard = state.players["player_1"].hand[0]
    state.players["player_1"].energy_deck = []
    before = state.model_dump(mode="json")

    with pytest.raises(Exception, match="energy_deck_empty"):
        apply_action(
            state,
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "invocation_id": state.pending_effects[0].invocation_id,
                    "accepted": True,
                    "selected_card_instance_ids": [discard],
                },
            ),
        )

    assert state.model_dump(mode="json") == before


def test_on_play_returns_selected_member_from_waiting_room(tmp_path):
    service, match_id = _create_match(tmp_path, seed=31)
    service, match_id = _create_match(tmp_path, seed=223)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "LL-bp1-001", zone="main_deck")
    target = _instance(state, "player_1", "PL!-bp3-002", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "hand")
    state = _manual_move(service, match_id, state, target, "waiting_room")
    state.cards[source].card.cost = 0

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )

    assert state.pending_effects[0].effect_id == "LL-bp1-001:1"
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [target],
        },
    )
    assert target in state.players["player_1"].hand
    assert target not in state.players["player_1"].waiting_room


def test_activated_draw_discard_is_once_per_turn(tmp_path):
    service, match_id = _create_match(tmp_path, seed=44)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp3-001", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "member_center")
    initial_hand = len(state.players["player_1"].hand)

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": "PL!-bp3-001:1",
            "source_card_instance_id": source,
        },
    )
    assert state.cards[source].orientation == "wait"
    assert len(state.players["player_1"].hand) == initial_hand + 1
    discard = state.players["player_1"].hand[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    from loveca.simulation.engine import generate_legal_actions

    assert not any(
        action.action_type == "activate_effect"
        for action in generate_legal_actions(state)
    )


def test_live_start_optional_blade_pays_energy_and_expires(tmp_path):
    service, match_id = _create_match(tmp_path, seed=51)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)

    invocation = next(
        item for item in state.pending_effects if item.effect_id == "PL!N-bp1-001:1"
    )
    energy = next(
        item
        for item in state.players["player_1"].energy_area
        if state.cards[item].orientation == "active"
    )
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "accepted": True,
            "energy_instance_ids": [energy],
        },
    )
    assert state.cards[energy].orientation == "wait"
    assert any(
        modifier.modifier_type == "blade" and modifier.duration == "live"
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_live_start_color_choice_grants_temporary_heart(tmp_path):
    service, match_id = _create_match(tmp_path, seed=52)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-color-heart:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "1" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ開始時】好きなハートの色を1つ指定する。"
                "ライブ終了時まで、そのハートを1つ得る。"
            ),
            "effect_type": "triggered",
            "timing": "live_start",
            "trigger": "live_started",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"],
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[source].card.effect_ids = [effect.effect_id]
    state = _advance_to_live_start_direct(state, live)

    invocation = next(
        item for item in state.pending_effects if item.effect_id == effect.effect_id
    )
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_color_slot": "heart03",
        },
    )

    assert any(
        modifier.modifier_type == "heart"
        and modifier.color_slot == "heart03"
        and modifier.amount == 1
        and modifier.duration == "live"
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_energy_choice_can_apply_wait_and_ready_energy(tmp_path):
    state, source = _state_with_wait_energy_effect(tmp_path)
    active_energy = state.players["player_1"].energy_area[0]
    wait_energy = state.players["player_1"].energy_area[1]
    state.cards[wait_energy].orientation = "wait"
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-energy-state:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "2" * 64,
            "effect_index": 1,
            "label_ja": "【登場】エネルギーを1枚ウェイトにし、エネルギーを1枚アクティブにする。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "energy_from_area",
                "orientation": "active",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_energy", "amount": 1}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _play_wait_energy_source(state, source)
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [active_energy],
        },
    )
    assert state.cards[active_energy].orientation == "wait"

    ready_effect = effect.model_copy(deep=True)
    ready_effect.effect_id = "test-energy-state:2"
    ready_effect.choice.orientation = "wait"
    ready_effect.actions = [
        ready_effect.actions[0].model_copy(
            update={"action_type": "ready_energy", "amount": 1}
        )
    ]
    state.pending_effects.clear()
    state.effect_definitions = {ready_effect.effect_id: ready_effect}
    state.cards[source].card.effect_ids = [ready_effect.effect_id]
    state.cards[source].orientation = "active"
    state.pending_effects.append(
        _effect_invocation_for_test(state, ready_effect.effect_id, source)
    )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [wait_energy],
        },
    )
    assert state.cards[wait_energy].orientation == "active"


def test_activated_wait_can_ready_another_member(tmp_path):
    service, match_id = _create_match(tmp_path, seed=57)
    state = _reach_first_main(service, match_id)
    candidates = [
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_code == "PL!-bp3-001"
    ]
    assert len(candidates) >= 2
    source, target = candidates[:2]
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, target, "member_left")
    state.cards[target].orientation = "wait"
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-ready-other:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "4" * 64,
            "effect_index": 1,
            "label_ja": (
                "【起動】【ターン1回】このメンバーをウェイトにする："
                "自分のステージにいるほかのメンバー1人をアクティブにする。"
            ),
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_turn",
            "is_optional": False,
            "condition": {"source_zone": "stage", "source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "orientation": "wait",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "ready_member"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    legal = generate_legal_actions(state)
    activation = next(
        entry
        for action in legal
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
        if entry["effect_id"] == effect.effect_id
    )
    assert activation["source_card_instance_id"] == source

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": source,
        },
    )
    assert state.cards[source].orientation == "wait"
    assert state.cards[target].orientation == "wait"
    invocation = state.pending_effects[0]
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert source not in options["candidate_card_instance_ids"]
    assert target in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": [target],
        },
    )

    assert state.cards[source].orientation == "wait"
    assert state.cards[target].orientation == "active"
    assert not state.pending_effects


def test_same_player_may_choose_pending_effect_resolution_order(tmp_path):
    service, match_id = _create_match(tmp_path, seed=58)
    state = _reach_first_main(service, match_id)
    readied = _instance(state, "player_1", "PL!-bp3-001", zone="main_deck")
    blade = _instance(state, "player_1", "PL!N-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, readied, "member_left")
    state = _manual_move(service, match_id, state, blade, "member_center")
    discard = state.players["player_1"].hand[0]
    state = _apply(
        service,
        match_id,
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": "PL!-bp3-001:1",
            "source_card_instance_id": readied,
        },
    )
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)

    invocation_ids = [item.effect_id for item in state.pending_effects]
    assert "PL!-bp3-001:2" in invocation_ids
    assert "PL!N-bp1-001:1" in invocation_ids

    optional_invocation = next(
        item for item in state.pending_effects if item.effect_id == "PL!N-bp1-001:1"
    )
    energy = next(
        item
        for item in state.players["player_1"].energy_area
        if state.cards[item].orientation == "active"
    )
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": optional_invocation.invocation_id,
            "accepted": True,
            "energy_instance_ids": [energy],
        },
    )
    assert any(
        modifier.modifier_type == "blade"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert any(item.effect_id == "PL!-bp3-001:2" for item in state.pending_effects)


def test_baton_touch_auto_readies_two_energy(tmp_path):
    service, match_id = _create_match(tmp_path, seed=67)
    state = _reach_first_main(service, match_id)
    old = _instance(state, "player_1", "PL!HS-sd1-001", zone="main_deck")
    new = _instance(state, "player_1", "PL!HS-sd1-002", zone="main_deck")
    state = _manual_move(service, match_id, state, old, "member_center")
    state = _manual_move(service, match_id, state, new, "hand")
    state.players["player_1"].member_areas_entered_this_turn.clear()
    old_cost = state.cards[old].card.cost or 0
    new_cost = state.cards[new].card.cost or 0
    payment = max(0, new_cost - old_cost)
    active_energy = [
        item
        for item in state.players["player_1"].energy_area
        if state.cards[item].orientation == "active"
    ][:payment]
    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": new,
            "slot": "center",
            "energy_instance_ids": active_energy,
            "use_baton_touch": True,
        },
    )
    assert sum(
        state.cards[item].orientation == "active"
        for item in state.players["player_1"].energy_area
    ) >= 2
    assert not state.pending_effects


def test_live_success_trigger_auto_resolves_before_turn_completion(tmp_path):
    service, match_id = _create_match(tmp_path, seed=69)
    state = _reach_first_main(service, match_id)
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state.players["player_1"].main_deck.remove(live)
    state.players["player_1"].live_area.append(live)
    state.cards[live].face_up = True
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-live-success:1",
            "card_code": state.cards[live].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "3" * 64,
            "effect_index": 1,
            "label_ja": "【ライブ成功時】カードを1枚引く。",
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "auto_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[live].card.effect_ids = [effect.effect_id]
    state.phase = "live_judgment"
    state.active_player_id = None
    state.players["player_1"].live_result.requirements_satisfied = True
    state.players["player_1"].live_result.total_score = 1
    state.players["player_2"].live_result.requirements_satisfied = False
    hand_count = len(state.players["player_1"].hand)

    result = apply_action(
        state,
        ActionRequest(
            action_type="advance_phase",
            expected_revision=state.revision,
            player_id=None,
            payload={},
        ),
    )

    assert result.state.phase == "turn_complete"
    assert live in result.state.players["player_1"].success_live_area
    assert len(result.state.players["player_1"].hand) == hand_count + 1
    assert any(event.event_type == "effect_auto_resolved" for event in result.events)
    assert result.state.success_live_moved_instance_ids == {"player_1": [live]}


def test_manual_resolution_requires_pending_invocation_binding(tmp_path):
    service, match_id = _create_match(tmp_path, seed=71)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "LL-bp1-001", zone="main_deck")
    live = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, live, "hand")
    state = _advance_to_live_start(service, match_id, state, live)
    manual_invocation = next(
        item for item in state.pending_effects if item.effect_id == "LL-bp1-001:2"
    )

    with pytest.raises(Exception, match="source_invocation_id"):
        _apply(
            service,
            match_id,
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "manual live-start effect",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "adjustments": [
                    {
                        "adjustment_type": "modify_score",
                        "target_player_id": "player_1",
                        "amount": 3,
                        "duration": "live",
                    }
                ],
            },
        )

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "manual live-start effect",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "source_invocation_id": manual_invocation.invocation_id,
            "source_effect_id": manual_invocation.effect_id,
            "source_card_instance_id": manual_invocation.source_card_instance_id,
            "adjustments": [
                {
                    "adjustment_type": "modify_score",
                    "target_player_id": "player_1",
                    "amount": 3,
                    "duration": "live",
                }
            ],
        },
    )
    assert not any(item.effect_id == "LL-bp1-001:2" for item in state.pending_effects)


def test_replay_uses_match_effect_snapshot_after_registry_changes(tmp_path):
    registry_copy = tmp_path / "effect-registry.json"
    registry_copy.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(
        card_database,
        tmp_path / "matches.sqlite3",
        registry_copy,
    )
    created = service.create_match(
        first_name="A",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="B",
        second_deck=load_deck(SAMPLE_DECK),
        seed=99,
    )
    match_id = created.state.match_id
    state = _apply(
        service,
        match_id,
        created.state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    registry_copy.write_text("{not valid json", encoding="utf-8")

    replay = service.repository.replay(match_id)

    assert replay["final_state"]["revision"] == state.revision
    assert replay["final_state"]["effect_registry_version"] == "effect-registry.v0"
    assert "PL!-bp3-001:1" in replay["final_state"]["effect_definitions"]


def test_manual_top_deck_inspection_selects_revealed_card_and_discards_rest(
    tmp_path,
):
    service, match_id = _create_match(tmp_path, seed=123)
    state = _reach_first_main(service, match_id)
    expected = state.players["player_1"].main_deck[:3]

    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "manual search effect",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "inspect_top_cards",
                    "target_player_id": "player_1",
                    "amount": 3,
                    "minimum": 0,
                    "maximum": 1,
                    "reveal_selected_to_opponent": True,
                }
            ],
        },
    )

    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "manual_card_selection"
    assert state.pending_choice.options["inspected_card_instance_ids"] == expected
    assert all(item in state.players["player_1"].resolution_area for item in expected)

    selected = expected[0]
    state = _apply(
        service,
        match_id,
        state,
        "resolve_manual_inspection",
        player_id="player_1",
        payload={"selected_card_instance_ids": [selected]},
    )

    assert state.pending_choice is None
    assert selected in state.players["player_1"].hand
    assert all(
        item in state.players["player_1"].waiting_room for item in expected[1:]
    )
    replay = service.repository.replay(match_id)
    event = next(
        item
        for item in replay["events"]
        if item["event_type"] == "manual_card_inspection_resolved"
    )
    assert event["data"]["reveal_selected_to_opponent"] is True
    assert event["data"]["selected_card_instance_ids"] == [selected]


def test_on_play_inspection_reorders_kept_cards_and_records_replay(tmp_path):
    service, match_id = _create_match(tmp_path, seed=141)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp3-014", zone="main_deck")
    state = _manual_move(service, match_id, state, source, "hand")
    extra_energy = state.players["player_1"].energy_deck[0]
    state = _manual_move(service, match_id, state, extra_energy, "energy_area")
    expected = state.players["player_1"].main_deck[:2]

    state = _apply(
        service,
        match_id,
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": state.players["player_1"].energy_area[:4],
            "use_baton_touch": False,
        },
    )

    assert state.pending_effects[0].effect_id == "PL!-bp3-014:1"
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
        },
    )

    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.cards[source].orientation == "wait"
    state = _apply(
        service,
        match_id,
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={
            "selected_card_instance_ids": [expected[1], expected[0]],
            "ordered_card_instance_ids": [expected[1], expected[0]],
        },
    )

    assert state.players["player_1"].main_deck[:2] == [expected[1], expected[0]]
    assert not state.players["player_1"].resolution_area
    replay = service.repository.replay(match_id)
    event = next(
        item
        for item in replay["events"]
        if item["event_type"] == "effect_resolved"
        and item["data"]["effect_id"] == "PL!-bp3-014:1"
    )
    assert event["data"]["ordered_card_instance_ids"] == [expected[1], expected[0]]


def test_on_play_inspection_filter_only_accepts_matching_candidate(tmp_path):
    service, match_id = _create_match(tmp_path, seed=177)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp6-002", zone="main_deck")
    state.players["player_1"].main_deck.remove(source)
    state.players["player_1"].hand.append(source)
    state.cards[source].face_up = True
    state.cards[source].card.cost = 0
    valid = state.players["player_1"].main_deck[0]
    invalid = state.players["player_1"].main_deck[1]
    state.cards[valid].card.work_keys = ["muse"]
    state.cards[valid].card.ability_bucket = "static_only"
    state.cards[invalid].card.work_keys = ["hasunosora"]
    state.cards[invalid].card.ability_bucket = "other"
    _stack_main_deck_top(state, "player_1", [valid, invalid])

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": invocation.invocation_id},
    )

    assert state.pending_choice is not None
    assert state.pending_choice.options["candidate_card_instance_ids"] == [valid]

    with pytest.raises(Exception, match="selection is not legal"):
        _apply_direct(
            state,
            "resolve_effect_choice",
            player_id="player_1",
            payload={"selected_card_instance_ids": [invalid]},
        )

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": [valid]},
    )
    assert valid in state.players["player_1"].hand
    assert invalid in state.players["player_1"].waiting_room


def test_onplay_branch_choice_can_draw_discard_or_wait_opponent_cost2(tmp_path):
    service, match_id = _create_match(tmp_path, seed=221)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-branch:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "b" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】以下から1つを選ぶ。 "
                "・カードを1枚引き、手札を1枚控え室に置く。 "
                "・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "choose_effect_branch",
                "zone": "hand",
                "branch_ids": ["draw_discard", "wait_opponent_cost2"],
                "branch_selection_minimum": {"draw_discard": 1},
                "branch_selection_maximum": {"draw_discard": 1},
            },
            "actions": [
                {"action_type": "draw_card", "amount": 1, "branch": "draw_discard"},
                {"action_type": "discard_from_hand", "branch": "draw_discard"},
                {
                    "action_type": "apply_wait_member",
                    "target": "opponent_stage_cost2_all",
                    "branch": "wait_opponent_cost2",
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    first_hand_count = len(state.players["player_1"].hand)
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_branch": "draw_discard",
        },
    )
    assert state.pending_effects[0].trigger_data["selected_branch"] == "draw_discard"
    assert len(state.players["player_1"].hand) == first_hand_count + 1
    discard = state.players["player_1"].hand[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    assert not state.pending_effects

    service, match_id = _create_match(tmp_path, seed=223)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    opponent_members = [
        item
        for item in state.players["player_2"].main_deck
        if state.cards[item].card.card_type == "member"
    ][:2]
    low_cost, high_cost = opponent_members
    for instance_id in opponent_members:
        state.players["player_2"].main_deck.remove(instance_id)
    state.players["player_2"].member_area["left"] = low_cost
    state.players["player_2"].member_area["center"] = high_cost
    state.cards[low_cost].card.cost = 2
    state.cards[high_cost].card.cost = 3
    state.cards[low_cost].orientation = "active"
    state.cards[high_cost].orientation = "active"

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_branch": "wait_opponent_cost2",
        },
    )
    assert state.cards[low_cost].orientation == "wait"
    assert state.cards[high_cost].orientation == "active"


def test_live_start_branch_choice_can_pay_energy_or_discard_hand():
    effect = _pay_or_discard_live_start_effect()
    state = _minimal_effect_state(effect)
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="テストエネルギー",
        card_type="energy",
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
        orientation="active",
    )
    state.cards["energy-2"] = CardInstance(
        instance_id="energy-2",
        owner_id="player_1",
        card=energy_card,
        orientation="active",
    )
    state.players["player_1"].energy_area = ["energy-1", "energy-2"]

    legal = generate_legal_actions(state)
    options = next(
        action.options["invocations"][0]
        for action in legal
        if action.action_type == "resolve_effect"
    )
    assert options["branch_ids"] == ["pay_energy", "discard_hand"]
    assert options["branch_energy_required"] == {"pay_energy": 2}
    assert "energy_required" not in options
    assert options["energy_instance_ids"] == ["energy-1", "energy-2"]

    with pytest.raises(Exception, match="requires exactly 2 Active Energy"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_branch": "pay_energy",
            },
        )
    assert state.cards["energy-1"].orientation == "active"
    assert state.cards["energy-2"].orientation == "active"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "pay_energy",
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    assert not state.pending_effects


def test_live_start_branch_choice_can_discard_two_hand_cards():
    effect = _pay_or_discard_live_start_effect()
    state = _minimal_effect_state(effect)
    hand_cards = ["hand-1", "hand-2"]
    for instance_id in hand_cards:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=state.cards["deck-member-1"].card.model_copy(deep=True),
        )
    state.players["player_1"].hand = hand_cards.copy()

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "discard_hand",
        },
    )

    assert state.pending_effects[0].resolution_stage == "after_cost"
    assert state.pending_effects[0].trigger_data["selected_branch"] == "discard_hand"
    legal = generate_legal_actions(state)
    options = next(
        action.options["invocations"][0]
        for action in legal
        if action.action_type == "resolve_effect"
    )
    assert options["selected_branch"] == "discard_hand"
    assert options["card_selection_minimum"] == 2
    assert options["card_selection_maximum"] == 2
    assert options["candidate_card_instance_ids"] == hand_cards

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": hand_cards,
        },
    )

    assert all(item in state.players["player_1"].waiting_room for item in hand_cards)
    assert not state.players["player_1"].hand
    assert not state.pending_effects


def test_onplay_reveals_opponent_hand_and_draws_if_no_live(tmp_path):
    service, match_id = _create_match(tmp_path, seed=224)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    selected = state.players["player_2"].hand[:3]
    for instance_id in selected:
        state.cards[instance_id].card.card_type = "member"
        state.cards[instance_id].face_up = False
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-opponent-hand-reveal:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "d" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】相手の手札を、自分は見ないで3枚選び公開する。"
                "これにより公開されたカードの中にライブカードがない場合、カードを1枚引く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "target_player": "opponent",
                "minimum": 3,
                "maximum": 3,
            },
            "actions": [
                {"action_type": "reveal_selected_cards"},
                {
                    "action_type": "draw_if_selected_none_card_type",
                    "card_type": "live",
                    "amount": 1,
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    hand_count = len(state.players["player_1"].hand)
    invocation = state.pending_effects[0]
    legal = generate_legal_actions(state)
    options = next(
        action.options["invocations"][0]
        for action in legal
        if action.action_type == "resolve_effect"
    )
    assert options["candidate_card_instance_ids"] == state.players["player_2"].hand

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": selected,
        },
    )

    assert all(instance_id in state.players["player_2"].hand for instance_id in selected)
    assert all(state.cards[instance_id].face_up for instance_id in selected)
    assert len(state.players["player_1"].hand) == hand_count + 1


def test_multi_player_effect_deploys_waiting_room_members_for_both_players(tmp_path):
    service, match_id = _create_match(tmp_path, seed=225)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    own_target = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member" and item != source
    )
    opponent_target = next(
        item
        for item in state.players["player_2"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    for player_id, instance_id in (
        ("player_1", own_target),
        ("player_2", opponent_target),
    ):
        state.players[player_id].main_deck.remove(instance_id)
        state.players[player_id].waiting_room.append(instance_id)
        state.cards[instance_id].card.cost = 2
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-multi-deploy:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "e" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】自分と相手はそれぞれ、自身の控え室からコスト2以下の"
                "メンバーカードを1枚、メンバーのいないエリアにウェイト状態で"
                "登場させる。（この効果で登場したメンバーのいるエリアには、"
                "このターンにメンバーは登場できない。）"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "multi_player_deploy_waiting_member",
                "zone": "waiting_room",
                "card_type": "member",
                "maximum_cost": 2,
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "multi_player_effect_selection"
    assert state.pending_choice.player_id == "player_1"
    assert own_target in state.pending_choice.options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_id": own_target, "slot": "left"},
    )
    assert state.players["player_1"].member_area["left"] == own_target
    assert state.cards[own_target].orientation == "wait"
    assert state.pending_choice.player_id == "player_2"

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_id": opponent_target, "slot": "center"},
    )
    assert state.players["player_2"].member_area["center"] == opponent_target
    assert state.cards[opponent_target].orientation == "wait"
    assert "left" in state.players["player_1"].member_areas_entered_this_turn
    assert "center" in state.players["player_2"].member_areas_entered_this_turn
    assert state.pending_choice is None
    assert not state.pending_effects


def test_multi_player_effect_discards_to_three_then_draws_three(tmp_path):
    service, match_id = _create_match(tmp_path, seed=226)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    replacement = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member" and item != source
    )
    state.cards[source].card.cost = 4
    state.cards[replacement].card.cost = 1
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-hand-reset:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "f" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】このメンバーよりコストが低いメンバーからバトンタッチして"
                "登場した場合、自分と相手はそれぞれ自身の手札の枚数が3枚になるまで"
                "手札を控え室に置き、その後、自分と相手はそれぞれカードを3枚引く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"replacement_member_cost_less_than_source": True},
            "cost": [],
            "choice": {
                "choice_type": "multi_player_discard_to_hand_size_then_draw",
                "zone": "hand",
                "target_hand_size": 3,
                "amount": 3,
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.pending_effects.append(
        _effect_invocation_for_test(state, effect.effect_id, source)
    )
    state.pending_effects[0].trigger_data["replacement_card_instance_id"] = replacement
    player_1_discards = state.players["player_1"].hand[
        : len(state.players["player_1"].hand) - 3
    ]
    player_2_discards = state.players["player_2"].hand[
        : len(state.players["player_2"].hand) - 3
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert state.pending_choice is not None
    assert state.pending_choice.options["minimum"] == len(player_1_discards)

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": player_1_discards},
    )
    assert state.pending_choice.player_id == "player_2"
    assert state.pending_choice.options["minimum"] == len(player_2_discards)

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_ids": player_2_discards},
    )
    assert all(item in state.players["player_1"].waiting_room for item in player_1_discards)
    assert all(item in state.players["player_2"].waiting_room for item in player_2_discards)
    assert len(state.players["player_1"].hand) == 6
    assert len(state.players["player_2"].hand) == 6
    assert state.pending_choice is None
    assert not state.pending_effects


def test_pending_effect_can_be_skipped_with_a_debug_event(tmp_path):
    service, match_id = _create_match(tmp_path, seed=227)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-manual-skip:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "1" * 64,
            "effect_index": 1,
            "label_ja": "【登場】未対応の能力。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "manual_resolution",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "actions": [],
            "duration": None,
            "simulation_support": "manual_resolution",
            "review_status": "provisional",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    invocation = _effect_invocation_for_test(state, effect.effect_id, source)
    state.pending_effects.append(invocation)

    legal = generate_legal_actions(state)
    assert any(action.action_type == "skip_effect" for action in legal)

    result = apply_action(
        state,
        ActionRequest(
            action_type="skip_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "reason": "test skip",
                "error_message": "fixture unsupported",
            },
        ),
    )

    assert not result.state.pending_effects
    assert result.events[-1].event_type == "effect_skipped_due_to_error"
    assert result.events[-1].source == "manual"
    assert result.events[-1].data["effect_id"] == effect.effect_id
    assert result.events[-1].data["error_message"] == "fixture unsupported"


def test_skipping_effect_choice_cleans_inspected_cards_for_debug_continuation(tmp_path):
    service, match_id = _create_match(tmp_path, seed=228)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    inspected = state.players["player_1"].main_deck[:2]
    for instance_id in inspected:
        state.players["player_1"].main_deck.remove(instance_id)
        state.players["player_1"].resolution_area.append(instance_id)
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-inspection-skip:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "2" * 64,
            "effect_index": 1,
            "label_ja": "【登場】デッキの上からカードを2枚見る。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 2,
                "minimum": 0,
                "maximum": 2,
                "requires_order": True,
                "selected_destination": "main_deck_top_ordered",
                "unselected_destination": "waiting_room",
            },
            "actions": [],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    invocation = _effect_invocation_for_test(state, effect.effect_id, source)
    state.pending_effects.append(invocation)
    state.pending_choice = PendingChoice(
        choice_type="effect_inspection_selection",
        player_id="player_1",
        message_ja="確認したカードの処理を選んでください。",
        message_zh="请选择检查后的卡牌处理结果。",
        options={
            "invocation_id": invocation.invocation_id,
            "effect_id": effect.effect_id,
            "source_card_instance_id": source,
            "inspected_card_instance_ids": list(inspected),
            "candidate_card_instance_ids": list(inspected),
            "minimum": 0,
            "maximum": 2,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": "waiting_room",
        },
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="skip_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "reason": "choice UI failed",
                "error_message": "cannot submit choice",
            },
        ),
    )

    assert result.state.pending_choice is None
    assert not result.state.pending_effects
    assert all(
        item not in result.state.players["player_1"].resolution_area
        for item in inspected
    )
    assert all(item in result.state.players["player_1"].waiting_room for item in inspected)
    event = result.events[-1]
    assert event.event_type == "effect_skipped_due_to_error"
    assert event.data["pending_choice_type"] == "effect_inspection_selection"
    assert event.data["cleaned_resolution_area_instance_ids"] == inspected


def test_onplay_mill5_auto_moves_top_cards_to_waiting_room(tmp_path):
    service, match_id = _create_match(tmp_path, seed=222)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    expected = state.players["player_1"].main_deck[:5]
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-mill5:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "c" * 64,
            "effect_index": 1,
            "label_ja": "【登場】デッキの上からカードを5枚控え室に置く。",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "auto_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "mill_top_cards", "amount": 5}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )

    assert all(item in state.players["player_1"].waiting_room for item in expected)
    assert not state.pending_effects


def test_effect_inspection_pending_choice_blocks_manual_adjustment(tmp_path):
    service, match_id = _create_match(tmp_path, seed=211)
    state = _reach_first_main(service, match_id)
    source = _instance(state, "player_1", "PL!-bp6-002", zone="main_deck")
    state.players["player_1"].main_deck.remove(source)
    state.players["player_1"].hand.append(source)
    state.cards[source].face_up = True
    state.cards[source].card.cost = 0

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    invocation = state.pending_effects[0]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": invocation.invocation_id},
    )

    with pytest.raises(Exception, match="structured effect inspection"):
        _apply_direct(
            state,
            "manual_adjustment",
            player_id="player_1",
            payload={
                "reason": "incorrect fallback",
                "requires_confirmation": True,
                "confirmed_by": "tester",
                "source_invocation_id": invocation.invocation_id,
                "source_effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "adjustments": [
                    {
                        "adjustment_type": "draw_card",
                        "target_player_id": "player_1",
                        "amount": 1,
                    }
                ],
            },
        )


def test_optional_discard_cost_enters_structured_inspection_choice(tmp_path):
    service, match_id = _create_match(tmp_path, seed=501)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    state.cards[source].card.cost = 0
    discard = next(item for item in state.players["player_1"].hand if item != source)
    inspected = state.players["player_1"].main_deck[:3]
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-discard-inspect3:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "8" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】手札を1枚控え室に置いてもよい："
                "自分のデッキの上からカードを3枚見る。"
                "その中から1枚を手札に加え、残りを控え室に置く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {},
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 3,
                "minimum": 1,
                "maximum": 1,
                "selected_destination": "hand",
                "unselected_destination": "waiting_room",
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 3},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]

    state = _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["choice_type"] == "card_from_zone"
    assert options["cost_choice"]["zone"] == "hand"
    assert discard in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    assert state.pending_choice is not None
    assert state.pending_choice.choice_type == "effect_inspection_selection"
    assert state.pending_choice.options["inspected_card_instance_ids"] == inspected

    selected = inspected[1]
    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": [selected]},
    )
    assert selected in state.players["player_1"].hand
    assert all(
        item in state.players["player_1"].waiting_room
        for item in inspected
        if item != selected
    )
    assert not state.pending_effects


def test_source_to_waiting_cost_allows_post_cost_waiting_room_choice(tmp_path):
    service, match_id = _create_match(tmp_path, seed=502)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    target = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "live"
    )
    state = _manual_move(service, match_id, state, source, "member_center")
    state = _manual_move(service, match_id, state, target, "waiting_room")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-source-to-wr-return-live:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "9" * 64,
            "effect_index": 1,
            "label_ja": (
                "【起動】このメンバーをステージから控え室に置く："
                "自分の控え室からライブカードを1枚手札に加える。"
            ),
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"source_zone": "stage"},
            "cost": [{"action_type": "source_to_waiting_room"}],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions = {effect.effect_id: effect}
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.pending_effects.append(_effect_invocation_for_test(state, effect.effect_id, source))

    legal = generate_legal_actions(state)
    initial_options = legal[0].options["invocations"][0]
    assert initial_options["candidate_card_instance_ids"] == []

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": state.pending_effects[0].invocation_id},
    )
    assert source in state.players["player_1"].waiting_room
    assert state.pending_effects[0].resolution_stage == "after_cost"
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert target in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [target],
        },
    )
    assert target in state.players["player_1"].hand
    assert not state.pending_effects


def test_live_success_hand6_or_less_returns_member_from_waiting_room():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-live-success-return-member:1",
            "card_code": "TEST-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "a" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ成功時】自分の手札が6枚以下の場合、"
                "自分の控え室からメンバーカードを1枚手札に加える。"
            ),
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {"own_hand_count_at_most": 6},
            "cost": [],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state = _minimal_effect_state(effect)
    player = state.players["player_1"]
    target = "deck-member-1"
    player.main_deck.remove(target)
    player.waiting_room.append(target)

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert target in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [target],
        },
    )

    assert target in state.players["player_1"].hand
    assert target not in state.players["player_1"].waiting_room
    assert not state.pending_effects


def _create_match(tmp_path: Path, seed: int = 7):
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3", REGISTRY)
    result = service.create_match(
        first_name="A",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="B",
        second_deck=load_deck(SAMPLE_DECK),
        seed=seed,
    )
    return service, result.state.match_id


def _minimal_effect_state(effect: EffectDefinition) -> MatchState:
    member = CardDefinition(
        card_code="TEST-MEMBER",
        card_id="TEST-MEMBER",
        name_ja="テストメンバー",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    live = CardDefinition(
        card_code="TEST-LIVE",
        card_id="TEST-LIVE",
        name_ja="テストライブ",
        card_type="live",
        score=1,
        required_hearts={"heart01": 2, "heart0": 1},
    )
    cards = {
        "source-live": CardInstance(
            instance_id="source-live",
            owner_id="player_1",
            card=live,
        ),
        "live-1": CardInstance(
            instance_id="live-1",
            owner_id="player_1",
            card=live,
        ),
        "deck-live-1": CardInstance(
            instance_id="deck-live-1",
            owner_id="player_1",
            card=live.model_copy(deep=True),
            face_up=False,
        ),
        "deck-member-1": CardInstance(
            instance_id="deck-member-1",
            owner_id="player_1",
            card=member,
            face_up=False,
        ),
        "deck-live-2": CardInstance(
            instance_id="deck-live-2",
            owner_id="player_1",
            card=live.model_copy(deep=True),
            face_up=False,
        ),
    }
    return MatchState(
        match_id="test-match",
        seed=1,
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                main_deck=["deck-live-1", "deck-member-1", "deck-live-2"],
                live_area=["live-1"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="inv-1",
                effect_id=effect.effect_id,
                source_card_instance_id="source-live",
                player_id="player_1",
                trigger_event=effect.trigger,
            )
        ],
    )


def _pay_or_discard_live_start_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-pay-or-discard:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】【E】【E】支払わないかぎり、"
            "自分の手札を2枚控え室に置く。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "choose_effect_branch",
            "zone": "hand",
            "branch_ids": ["pay_energy", "discard_hand"],
            "branch_selection_minimum": {"discard_hand": 2},
            "branch_selection_maximum": {"discard_hand": 2},
            "branch_energy_required": {"pay_energy": 2},
        },
        actions=[
            {"action_type": "pay_energy", "amount": 2, "branch": "pay_energy"},
            {"action_type": "discard_from_hand", "branch": "discard_hand"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _grouped_stage_blade_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-grouped-stage-blade:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="g" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】ライブ終了時まで、自分のステージにいる、"
            "「澁谷かのん」「ウィーン・マルガレーテ」「鬼塚冬毬」のうちのメンバー1人と、"
            "これにより選んだメンバー以外の『Liella!』のメンバー1人は、【ブレード】を得る。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_group_from_stage",
            "selection_groups": [
                {
                    "group_id": "named_member",
                    "label_ja": "指定名のメンバー",
                    "zone": "stage",
                    "card_type": "member",
                    "name_ja_any": [
                        "澁谷かのん",
                        "ウィーン・マルガレーテ",
                        "鬼塚冬毬",
                    ],
                    "minimum": 1,
                    "maximum": 1,
                },
                {
                    "group_id": "other_liella",
                    "label_ja": "選んだメンバー以外の『Liella!』のメンバー",
                    "zone": "stage",
                    "card_type": "member",
                    "work_key": "love_live_superstar",
                    "exclude_group_ids": ["named_member"],
                    "minimum": 1,
                    "maximum": 1,
                },
            ],
        },
        actions=[{"action_type": "gain_blade", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _draw_three_return_hand_three_to_top_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-draw3-hand3-top:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="d" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】カードを3枚引き、"
            "自分の手札を3枚好きな順番でデッキの上に置く。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 3,
            "maximum": 3,
        },
        actions=[
            {"action_type": "draw_card", "amount": 3},
            {"action_type": "move_selected_to_deck_top"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _state_with_wait_energy_effect(tmp_path: Path):
    service, match_id = _create_match(tmp_path, seed=313)
    state = _reach_first_main(service, match_id)
    source = next(
        item
        for item in state.players["player_1"].main_deck
        if state.cards[item].card.card_type == "member"
    )
    state = _manual_move(service, match_id, state, source, "hand")
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-wait-energy:1",
            "card_code": state.cards[source].card.card_code,
            "text_revision_id": 1,
            "raw_text_hash": "0" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】手札を1枚控え室に置いてもよい："
                "自分のエネルギーデッキから、"
                "エネルギーカードを1枚ウェイト状態で置く。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {"minimum_energy_deck_cards": 1},
            "cost": [{"action_type": "discard_from_hand"}],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state.effect_definitions[effect.effect_id] = effect
    state.cards[source].card.effect_ids = [effect.effect_id]
    state.cards[source].card.cost = 0
    return state, source


def _play_wait_energy_source(state, source: str):
    return _apply_direct(
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": source,
            "slot": "center",
            "energy_instance_ids": [],
            "use_baton_touch": False,
        },
    )


def _apply(
    service: MatchService,
    match_id: str,
    state,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict | None = None,
):
    return service.apply(
        match_id,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state


def _apply_direct(
    state,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict | None = None,
):
    return apply_action(
        state,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state


def _reach_first_main(service: MatchService, match_id: str):
    state = service.repository.get_state(match_id)
    state = _apply(
        service,
        match_id,
        state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    state = _apply(
        service, match_id, state, "submit_mulligan", player_id="player_1",
        payload={"card_instance_ids": []},
    )
    state = _apply(
        service, match_id, state, "submit_mulligan", player_id="player_2",
        payload={"card_instance_ids": []},
    )
    for _ in range(3):
        state = _apply(
            service, match_id, state, "advance_phase", player_id="player_1"
        )
    return state


def _advance_to_live_start(
    service: MatchService,
    match_id: str,
    state,
    live_instance_id: str,
):
    state = _apply(
        service, match_id, state, "end_main_phase", player_id="player_1"
    )
    for _ in range(3):
        state = _apply(
            service, match_id, state, "advance_phase", player_id="player_2"
        )
    state = _apply(
        service, match_id, state, "end_main_phase", player_id="player_2"
    )
    state = _apply(
        service, match_id, state, "set_live_cards", player_id="player_1",
        payload={"card_instance_ids": [live_instance_id]},
    )
    state = _apply(
        service, match_id, state, "set_live_cards", player_id="player_2",
        payload={"card_instance_ids": []},
    )
    return _apply(
        service, match_id, state, "advance_phase", player_id="player_1"
    )


def _advance_to_live_start_direct(state, live_instance_id: str):
    state = _apply_direct(state, "end_main_phase", player_id="player_1")
    for _ in range(3):
        state = _apply_direct(state, "advance_phase", player_id="player_2")
    state = _apply_direct(state, "end_main_phase", player_id="player_2")
    state = _apply_direct(
        state,
        "set_live_cards",
        player_id="player_1",
        payload={"card_instance_ids": [live_instance_id]},
    )
    state = _apply_direct(
        state,
        "set_live_cards",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    return _apply_direct(state, "advance_phase", player_id="player_1")


def _instance(state, player_id: str, card_code: str, *, zone: str) -> str:
    player = state.players[player_id]
    ids = getattr(player, zone)
    return next(
        instance_id
        for instance_id in ids
        if state.cards[instance_id].card.card_code == card_code
    )


def _manual_move(
    service: MatchService,
    match_id: str,
    state,
    instance_id: str,
    zone: str,
):
    return _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "effect test setup",
            "requires_confirmation": True,
            "confirmed_by": "test",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": instance_id,
                    "to_zone": zone,
                }
            ],
        },
    )


def _stack_main_deck_top(state, player_id: str, ordered_ids: list[str]):
    deck = state.players[player_id].main_deck
    for instance_id in reversed(ordered_ids):
        deck.remove(instance_id)
        deck.insert(0, instance_id)


def _effect_invocation_for_test(
    state,
    effect_id: str,
    source_instance_id: str,
) -> EffectInvocation:
    return EffectInvocation(
        invocation_id=f"test:{effect_id}",
        effect_id=effect_id,
        source_card_instance_id=source_instance_id,
        player_id=state.cards[source_instance_id].owner_id,
        trigger_event=state.effect_definitions[effect_id].trigger,
    )
