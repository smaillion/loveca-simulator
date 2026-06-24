from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.effect_candidates import (
    _effect_text_rows,
    _timing_segments,
    discover_effect_candidates,
)
from loveca.simulation.effects import (
    EffectDefinition,
    EffectRegistry,
    validate_registry_for_cards,
)
from loveca.simulation.engine import (
    IllegalActionError,
    _queue_live_success_effects,
    _resolve_automatic_effects,
    _run_current_yell,
    _static_heart_bonus,
    _static_numeric_bonus,
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
    PlayerState,
    SpecialBladeHeart,
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


def test_effect_candidate_discovery_structures_pl_hs_bp6_014_hand_activation():
    database = _require_full_card_database()
    candidates = discover_effect_candidates(database, include_registered=True)
    candidate = next(
        item for item in candidates if item.effect_id == "PL!HS-bp6-014:1"
    )

    assert candidate.pattern_id == "activated_hand_source_draw_blade_named_member"
    assert candidate.condition == {"source_zone": "hand"}
    assert candidate.cost == [{"action_type": "source_to_waiting_room"}]
    assert candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "name_ja_any": ["藤島 慈", "大沢瑠璃乃"],
        "minimum": 0,
        "maximum": 1,
    }
    assert candidate.actions == [
        {"action_type": "draw_card", "amount": 1},
        {"action_type": "gain_blade", "target": "selected", "amount": 1},
    ]


def test_effect_candidate_discovery_structures_pl_bp6_003_source_attachment():
    database = _require_full_card_database()
    candidates = discover_effect_candidates(database, include_registered=True)
    by_id = {item.effect_id: item for item in candidates}

    live_start = by_id["PL!-bp6-003:1"]
    assert (
        live_start.pattern_id
        == "pl_bp6_003_live_start_center_attach_hand_muse_cost2_gain_chosen_heart"
    )
    assert live_start.condition == {"source_slot": "center"}
    assert live_start.choice == {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "card_type": "member",
        "work_key": "love_live",
        "maximum_cost": 2,
        "minimum": 1,
        "maximum": 1,
        "color_slots": [
            "heart01",
            "heart02",
            "heart03",
            "heart04",
            "heart05",
            "heart06",
        ],
    }
    assert live_start.actions == [
        {"action_type": "attach_selected_under_source"},
        {"action_type": "gain_heart", "target": "source", "amount": 1},
    ]

    live_success = by_id["PL!-bp6-003:2"]
    assert live_success.pattern_id == "pl_bp6_003_live_success_deploy_attached_muse_cost2_member"
    assert live_success.choice == {
        "choice_type": "deploy_member_from_waiting_room",
        "zone": "source_attachments",
        "card_type": "member",
        "work_key": "love_live",
        "maximum_cost": 2,
        "minimum": 1,
        "maximum": 1,
    }
    assert live_success.actions == [{"action_type": "deploy_selected_to_empty_stage"}]


def test_effect_candidate_discovery_structures_attached_energy_family():
    database = _require_full_card_database()
    candidates = discover_effect_candidates(database, include_registered=True)
    by_id = {item.effect_id: item for item in candidates}

    expected_patterns = {
        "PL!N-bp3-001:1": "live_start_attach_energy_draw1_stage_members_blade2",
        "PL!N-bp3-013:1": "onplay_attach_energy_draw2",
        "PL!N-pb1-002:1": "onplay_attach_two_energy",
        "PL!N-pb1-002:2": "static_attached_energy2_score1",
        "PL!HS-pb1-002:1": "activated_reveal_hand_sayaka_attach_under_source",
        "PL!N-bp5-008:1": "activated_attach_energy_ready2",
        "PL!N-bp5-012:1": "activated_attach_energy_draw1_gain_heart01",
        "PL!N-bp5-012:2": "live_success_source_attached_energy_plus1_place_wait_energy",
        "PL!N-pb1-011:1": "static_source_attached_energy_count_blade",
        "PL!N-pb1-011:2": "activated_attach_energy_return_nijigasaki_live",
    }
    for effect_id, pattern_id in expected_patterns.items():
        assert by_id[effect_id].pattern_id == pattern_id
        assert by_id[effect_id].simulation_support == "test_validated_executable"


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
    direct_expected = {
        "PL!SP-pb1-005": 608,
        "PL!SP-bp4-001": 376,
        "PL!SP-bp4-005": 380,
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

    assert set(matching) == set(expected) | set(direct_expected)
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
    direct_effect = matching["PL!SP-pb1-005"]
    assert direct_effect.text_revision_id == direct_expected["PL!SP-pb1-005"]
    assert direct_effect.choice is None
    assert direct_effect.condition == {"minimum_energy_deck_cards": 1}
    assert direct_effect.actions[0].orientation == "wait"
    liella_energy_effect = matching["PL!SP-bp4-001"]
    assert liella_energy_effect.text_revision_id == direct_expected["PL!SP-bp4-001"]
    assert liella_energy_effect.choice is None
    assert liella_energy_effect.condition == {
        "minimum_energy_deck_cards": 1,
        "own_energy_count_at_least": 7,
        "own_stage_members_only_work_key": "love_live_superstar",
    }
    assert liella_energy_effect.actions[0].orientation == "wait"
    liella_baton_energy_effect = matching["PL!SP-bp4-005"]
    assert liella_baton_energy_effect.text_revision_id == direct_expected["PL!SP-bp4-005"]
    assert liella_baton_energy_effect.choice is None
    assert liella_baton_energy_effect.condition == {
        "requires_baton_touch": True,
        "replacement_member_work_key": "love_live_superstar",
        "own_energy_count_at_least": 7,
        "minimum_energy_deck_cards": 2,
    }
    assert liella_baton_energy_effect.actions[0].amount == 2
    assert liella_baton_energy_effect.actions[0].orientation == "wait"
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
        "onplay_choose_mill3_or_wait_opponent_cost2",
        "onplay_pay1_choose_wait_opponent_cost4_or_draw1",
        "onplay_mill5",
        "static_blade_per_opponent_wait_member",
        "static_heart06_per_opponent_wait_member",
        "static_stage_name_fujishima_megumi_blade2",
        "static_center_heart03_3",
        "static_right_heart05_3",
        "live_success_optional_pay3_draw1",
        "live_success_revealed_live1_place_wait_energy",
        "live_success_opponent_place_wait_energy",
        "onplay_reveal3_opponent_hand_draw_if_no_live",
        "onplay_both_deploy_cost2_waiting_member",
        "activated_pay2_deploy_waiting_member_cost2",
        "activated_pay4_deploy_waiting_hasu_member_cost4",
        "activated_pay2_discard1_aqours_live",
        "activated_discard2_aqours_score_live",
        "onplay_baton_lower_both_discard_to3_draw3",
        "onplay_right_side_ready_energy",
        "onplay_optional_pay2_left_side_draw2",
        "onplay_optional_pay2_return_liella_member",
        "onplay_place_wait_energy",
        "onplay_gain_live_score1",
        "onplay_center_gain_blade2",
        "onplay_other_5yncri5e_draw1",
        "onplay_left_side_draw2_discard1",
        "onplay_optional_waiting_card_to_deck_top",
        "onplay_optional_pay2_deploy_hand_uehara_ayumu_member_cost4",
        "onplay_optional_pay2_deploy_hand_osaka_shizuku_member_cost4",
        "onplay_optional_pay2_deploy_hand_miyashita_ai_member_cost4",
        "onplay_optional_pay2_deploy_hand_mia_taylor_member_cost4",
        "live_start_pay1_choose_any_heart1",
        "live_start_discard1_gain_blade1",
        "live_start_wait_source_center_muse_blade2",
        "live_start_wait_source_center_muse_blade1",
        "onplay_wait_source_wait_opponent_cost9_member",
        "onplay_wait_source_ready_energy_per_printemps_member",
        "onplay_wait_source_bibi_only_wait_opponent_original_blade3",
        "live_start_wait_source_bibi_only_wait_opponent_original_blade3",
        "onplay_wait_source_wait_opponent_original_blade4",
        "live_start_wait_source_wait_opponent_original_blade4",
        "onplay_baton_liella_energy7_place_two_wait_energy",
        "activated_wait_source_or_discard1_ready_energy1",
        "activated_wait_source_miracra_park_member_gain_blade1",
        "onplay_optional_discard1_live_draw3",
        "onplay_draw_per_energy6",
        "onplay_from_waiting_draw2_discard1",
        "onplay_other_heart06_member_gain_heart06",
        "onplay_liella_only_energy7_place_wait_energy",
        "onplay_draw2_from_waiting_gain_blade3",
        "onplay_other_stage_member_moved_this_turn_draw1",
        "live_start_center_live_area_muse_stage_muse_blade1",
        "live_start_mill4_all_hasunosora_gain_blade1",
        "live_start_inspect1_optional_send_to_waiting",
        "live_start_discard1_gain_blade2_per_success_live",
        "live_start_stage_attached_energy_member_gain_heart01",
        "live_start_stage_all_heart_colors_gain_blade2",
        "live_start_own_member_higher_than_all_opponent_cost_gain_blade2",
        "live_start_moved_stage_members_blade1",
        "live_start_left_source_moved_this_turn_blade2",
        "live_start_right_source_moved_this_turn_blade2",
        "live_start_center_ready_all_liella_members_and_energy",
        "live_start_discard1_miracra_park_member_gain_heart01",
        "live_start_discard1_hasunosora_member_gain_heart05",
        "live_start_pay1_other_hasunosora_member_gain_heart01_blade1",
        "live_start_pay1_other_nijigasaki_members_gain_blade1",
        "live_start_energy7_source_and_other_liella_member_gain_blade1",
        "onplay_energy11_return_live",
        "onplay_choose_waiting_live_distinct_name_or_group",
        "live_start_muse_stage_draw_discard_heart03_score",
        "live_start_waiting_love_live_card25_score1",
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
        "live_start_deep_hasunosora_baton_entered2_required_heart04_minus1",
        "live_start_deep_miracra_park_extra_heart_count_draw_required_any_minus2",
        "live_start_deep_hasunosora_stage_cost20_inspect2_keep1_top_cost30_required_any_minus2",
        "live_start_deep_success_exists_choose_muse_member_heart1",
        "live_start_choose_aqours_center9_blade2_or_wait_opponent_cost4",
        "live_start_deep_nijigasaki_waiting_distinct_live4_score1_6_score2",
        "live_start_deep_success_count_equal_opponent_heart02_2",
        "live_start_deep_left_liella_heart02_3_blade2",
        "live_start_deep_hasunosora_stage_waiting_distinct6_required_any_minus2",
        "live_start_deep_moved_liella_stage_blade1",
        "live_start_deep_member_entered2_score1",
        "live_start_deep_moved_5yncri5e_required_any_minus_each",
        "live_start_deep_catchu_distinct2_ready_energy6_all_active_score1",
        "live_start_deep_replace_yell_blade_hearts_heart05",
        "live_start_deep_replace_yell_blade_hearts_heart06",
        "live_start_choose_heart01_02_06_replace_source_base_hearts",
        "onplay_optional_source_position_change",
        "live_start_optional_source_position_change",
        "activated_pay2_source_position_change",
        "auto_moved_source_gain_blade1",
        "auto_moved_source_gain_blade1_opponent_effect",
        "auto_moved_source_gain_heart02",
        "auto_moved_source_gain_heart03",
        "auto_moved_source_gain_heart06",
        "auto_moved_source_draw1",
        "auto_moved_source_place_wait_energy",
        "auto_moved_source_ready_energy2",
        "auto_moved_source_wait_opponent_original_blade2",
        "auto_stage_to_waiting_ready_member_up_to1",
        "auto_stage_to_waiting_inspect5_member_keep1",
        "auto_stage_to_waiting_inspect5_live_keep1",
        "auto_stage_to_waiting_draw2_discard1",
        "auto_stage_to_waiting_draw2_discard2",
        "auto_stage_to_waiting_optional_discard1_return_aqours_live",
        "auto_stage_to_waiting_optional_discard1_stage_member_heart05_blade1",
        "static_success_score_higher_than_opponent_blade2",
        "static_blade_per_opponent_success_lead",
        "static_blade_per_other_miracra_park_member",
        "static_blade2_per_cost4_non_cerise_bouquet_member",
        "static_other_edel_note_member_blade2",
        "static_own_stage2_opponent_stage3_heart06",
        "static_opponent_excess_heart2_score1",
        "static_center_side_original_blade2_score1",
        "static_source_most_stage_hearts_score1",
        "static_center_highest_cost_heart03",
        "static_liella_live_required_heart8_heart03",
        "static_opposing_member_higher_cost_heart01",
        "static_source_not_moved_this_turn_blade2",
        "static_attached_energy2_score1",
        "live_success_revealed_all_blade_score1",
        "live_success_center_revealed_aqours_score_live_score1",
        "live_success_any_success2_revealed_score_live_score2",
        "live_success_stage_kanon_keke_draw1",
        "onplay_baton_return_replaced_liella_member",
        "live_success_revealed_distinct_liella_member5_score1",
        "live_success_revealed_nijigasaki_member_all_heart_colors_score1",
        "live_success_revealed_muse_member_without_blade_heart_draw1_discard1",
        "live_success_optional_yell_revealed_card_to_deck_top",
        "live_success_yell_revealed_live_up_to1_to_deck_bottom",
        "live_success_revealed_liella_card7_place_wait_energy",
        "live_success_stage_kanon_margarete_tomari_distinct2_yell_card_to_hand",
        "live_success_draw_discard_per_aqours_stage_member",
        "live_success_revealed_distinct_liella_member3_liella_live_to_hand",
        "live_success_center_liella_moved_this_turn_score1",
        "live_success_draw1_source_moved_extra_draw1",
        "live_success_revealed_live2_or_stage_heart_variety5_or_member_moved_score1",
        "live_success_reveal_top_to_hand_non_blade_member_score1",
        "live_success_no_excess_score1_excess2_score_minus1",
        "live_success_source_attached_energy_plus1_place_wait_energy",
        "live_success_equal_score_prevent_success_live_placement",
        "onplay_only_5yncri5e_rotate_both_stage_members",
        "live_start_no_timing_live_other_member_gain_blade2",
        "live_success_cerise_stage_optional_mill4",
        "live_success_optional_place_wait_energy_opponent_draw1",
        "live_success_no_excess_heart_score1",
        "live_success_fewer_yell_revealed_cards_than_opponent_draw1",
        "live_success_discard1_yell_revealed_cost2_member_or_score2_live_to_hand",
        "live_success_higher_score_hasu_stage_place_wait_energy",
        "live_success_equal_score_yell_revealed_member_cost9_to_hand",
        "live_success_higher_score_yell_revealed_nijigasaki_to_hand",
        "live_success_excess_heart1_draw2_discard1",
        "live_success_source_score3_return_nijigasaki_card",
        "live_success_other_stage_member_wait_source",
        "live_success_bibi_distinct2_return_bibi_member",
        "live_success_stage_total_heart_more_than_opponent_score1",
        "live_success_stage2_return_score3_live",
        "live_start_source_attached_member_count_heart05_max3",
        "live_success_aqours_heart05_4_opponent_success_no_excess_score2",
        "live_start_deep_source_blade8_draw2_discard1",
        "live_start_wait_opponent_cost9_member",
        "onplay_wait_opponent_cost9_member",
        "onplay_wait_opponent_cost2_member",
        "onplay_stage_cost10_wait_opponent_cost4_member",
        "live_start_stage_cost10_wait_opponent_cost4_member",
        "onplay_wait_opponent_original_blade3_non_dollchestra_member",
        "live_start_wait_opponent_original_blade3_non_dollchestra_member",
        "live_start_draw1_wait_opponent_cost9_member_up_to1",
        "live_start_stage_total_heart5_wait_opponent_cost2_member",
        "live_start_deep_choose_aqours_member_blade6_score1",
        "onplay_named_baton_nakasu_kasumi_draw2_discard1",
        "activated_discard2_return_live_required_heart03_3",
        "onplay_optional_discard1_inspect4_keep1_heart04_2_member_or_live",
        "onplay_other_nijigasaki_ready_energy",
        "onplay_named_stage_ready_energy_return_hasu_live",
        "onplay_optional_discard1_mill2_return_member",
        "onplay_optional_pay1_discard1_mill3_return_cerise_bouquet_live",
        "onplay_center_baton_two_liella_draw2_deploy_waiting_member_cost4",
        "onplay_baton_non_kachimachi_hasunosora_return_live",
        "live_success_inspect4_member_heart04_2_keep1",
        "live_success_excess_heart_inspect2_reorder_rest_wr",
        "live_start_deep_center_liella_base_blade3",
        "live_start_grouped_superstar_named_and_other_liella_blade",
        "live_start_grouped_edel_note_blade2_and_other_name_heart06_2",
        "live_start_opponent_wait_count_nijigasaki_members_to_deck_top",
        "live_start_pay_up_to2_gain_blade_per_energy",
        "live_start_discard_two_same_group_heart01_2",
        "live_start_discard_two_same_unit_heart04_2_blade2",
        "live_start_discard_two_same_unit_heart05_2_blade2",
        "live_start_reduce_yell_count_by8_if_other_member",
        "live_start_inspect4_nakasu_kasumi_gain_selected_heart_colors",
        "live_start_reveal_top_cost9_member_to_hand_position_change",
        "live_start_pay2_or_discard2",
        "live_start_draw1_discard1",
        "manual_timing_fallback",
    }
    attached_member_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-002:2"
    )
    assert attached_member_candidate.execution_mode == "auto_resolve"
    assert attached_member_candidate.actions == [
        {
            "action_type": "gain_heart",
            "amount_source": "source_attached_member_count",
            "value": {"max": 3, "cost_bonus_per_member": 4},
            "color_slot": "heart05",
        }
    ]
    aqours_no_excess_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-021:1"
    )
    assert aqours_no_excess_candidate.condition == {
        "own_stage_heart_at_least": {
            "color_slot": "heart05",
            "count": 4,
            "unit_key": "aqours",
        },
        "opponent_success_excess_heart_count_at_most": 0,
    }
    assert aqours_no_excess_candidate.actions == [
        {"action_type": "modify_score", "amount": 2}
    ]
    nijigasaki_top_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-004:2"
    )
    assert nijigasaki_top_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "member",
        "work_key": "nijigasaki",
        "minimum": 0,
        "maximum": 3,
        "amount_source": "opponent_stage_wait_member_count",
        "requires_order": True,
    }
    assert nijigasaki_top_candidate.actions == [
        {"action_type": "move_selected_to_deck_top"}
    ]
    hasu_baton_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-sd1-005:1"
    )
    assert hasu_baton_candidate.condition == {
        "requires_baton_touch": True,
        "replacement_member_work_key": "hasunosora",
        "replacement_member_name_ja_not": "徒町小鈴",
    }
    assert hasu_baton_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "minimum": 1,
        "maximum": 1,
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
    wait_opponent_cost9_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-004:2"
    )
    assert wait_opponent_cost9_candidate.simulation_support == (
        "test_validated_executable"
    )
    assert wait_opponent_cost9_candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "target_player": "opponent",
        "card_type": "member",
        "maximum_cost": 9,
        "minimum": 1,
        "maximum": 1,
    }
    assert wait_opponent_cost9_candidate.actions == [
        {"action_type": "apply_wait_member", "target": "selected"}
    ]
    onplay_wait_cost2_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-015:1"
    )
    assert onplay_wait_cost2_candidate.choice["maximum_cost"] == 2
    assert onplay_wait_cost2_candidate.timing == "on_play"
    stage_cost_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-010:2"
    )
    assert stage_cost_wait_candidate.condition == {"own_stage_member_cost_at_least": 10}
    assert stage_cost_wait_candidate.choice["maximum_cost"] == 4
    draw_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp4-004:1"
    )
    assert draw_wait_candidate.choice["minimum"] == 0
    assert draw_wait_candidate.actions == [
        {"action_type": "draw_card", "amount": 1},
        {"action_type": "apply_wait_member", "target": "selected"},
    ]
    stage_heart_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-PR-021:1"
    )
    assert stage_heart_wait_candidate.condition == {
        "own_stage_total_heart_at_least": {"count": 5}
    }
    assert stage_heart_wait_candidate.choice["maximum_cost"] == 2
    activated_position_change_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-002:1"
    )
    assert activated_position_change_candidate.effect_type == "activated"
    assert activated_position_change_candidate.timing == "activated_main"
    assert activated_position_change_candidate.condition == {
        "source_zone": "stage",
        "minimum_active_energy": 2,
    }
    assert activated_position_change_candidate.cost == [
        {"action_type": "pay_energy", "amount": 2}
    ]
    assert activated_position_change_candidate.choice == {
        "choice_type": "position_change_source",
        "minimum": 1,
        "maximum": 1,
    }
    assert activated_position_change_candidate.actions == [
        {"action_type": "position_change_source"}
    ]
    moved_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-002:2"
    )
    assert moved_heart_candidate.effect_type == "triggered"
    assert moved_heart_candidate.timing == "auto_triggered_event"
    assert moved_heart_candidate.trigger == "member_moved"
    assert moved_heart_candidate.execution_mode == "auto_resolve"
    assert moved_heart_candidate.frequency_limit == "once_per_turn"
    assert moved_heart_candidate.condition == {"source_zone": "stage"}
    assert moved_heart_candidate.actions == [
        {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
    ]
    yell_reduce_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp2-010:2"
    )
    assert yell_reduce_candidate.pattern_id == (
        "live_start_reduce_yell_count_by8_if_other_member"
    )
    assert yell_reduce_candidate.execution_mode == "auto_resolve"
    assert yell_reduce_candidate.condition == {"own_stage_member_count_at_least": 2}
    assert yell_reduce_candidate.actions == [
        {"action_type": "modify_yell_count", "amount": -8}
    ]
    kasumi_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-029:1"
    )
    assert kasumi_heart_candidate.pattern_id == (
        "live_start_inspect4_nakasu_kasumi_gain_selected_heart_colors"
    )
    assert kasumi_heart_candidate.choice["choice_type"] == "inspect_top_select"
    assert kasumi_heart_candidate.choice["amount"] == 4
    assert kasumi_heart_candidate.choice["name_ja_any"] == ["中須かすみ"]
    assert kasumi_heart_candidate.actions == [
        {
            "action_type": "gain_heart_from_selected_card_colors",
            "target": "selected",
            "value": {"target_stage_member_name_ja": "中須かすみ"},
        }
    ]
    reveal_position_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-pb1-004:2"
    )
    assert reveal_position_candidate.pattern_id == (
        "live_start_reveal_top_cost9_member_to_hand_position_change"
    )
    assert reveal_position_candidate.execution_mode == "auto_resolve"
    assert reveal_position_candidate.actions == [
        {
            "action_type": "reveal_top_matching_to_hand_else_waiting",
            "amount": 1,
            "card_type": "member",
            "value": {"maximum_cost": 9},
        },
        {
            "action_type": "position_change_source",
            "value": {"condition": {"last_revealed_top_matched": True}},
        },
    ]
    deploy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp5-002:2"
    )
    assert deploy_candidate.effect_type == "activated"
    assert deploy_candidate.timing == "activated_main"
    assert deploy_candidate.condition == {
        "source_zone": "stage",
        "minimum_active_energy": 2,
    }
    assert deploy_candidate.cost == [{"action_type": "pay_energy", "amount": 2}]
    assert deploy_candidate.choice == {
        "choice_type": "deploy_member_from_waiting_room",
        "zone": "waiting_room",
        "card_type": "member",
        "maximum_cost": 2,
        "minimum": 1,
        "maximum": 1,
    }
    assert deploy_candidate.actions == [
        {"action_type": "deploy_selected_to_empty_stage"}
    ]
    hasu_deploy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-016:1"
    )
    assert hasu_deploy_candidate.choice["work_key"] == "hasunosora"
    assert hasu_deploy_candidate.choice["maximum_cost"] == 4
    assert hasu_deploy_candidate.cost == [
        {"action_type": "pay_energy", "amount": 4}
    ]
    aqours_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-sd1-005:1"
    )
    assert aqours_return_candidate.condition == {
        "source_zone": "stage",
        "minimum_active_energy": 2,
    }
    assert aqours_return_candidate.cost == [
        {"action_type": "pay_energy", "amount": 2},
        {"action_type": "discard_from_hand"},
    ]
    assert aqours_return_candidate.cost_choice == {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert aqours_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "minimum": 1,
        "maximum": 1,
        "work_key": "love_live_sunshine",
    }
    score_live_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-sd1-007:1"
    )
    assert score_live_return_candidate.choice["work_key"] == "love_live_sunshine"
    assert score_live_return_candidate.choice["minimum_score"] == 1
    right_ready_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-008:2"
    )
    assert right_ready_candidate.condition == {"source_slot": "right"}
    assert right_ready_candidate.actions == [
        {"action_type": "ready_energy", "amount": 2}
    ]
    left_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp1-002:1"
    )
    assert left_draw_candidate.condition == {
        "minimum_active_energy": 2,
        "source_slot": "left",
    }
    assert left_draw_candidate.cost == [{"action_type": "pay_energy", "amount": 2}]
    assert left_draw_candidate.actions == [{"action_type": "draw_card", "amount": 2}]
    liella_member_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd1-007:1"
    )
    assert liella_member_return_candidate.condition == {"minimum_active_energy": 2}
    assert liella_member_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "minimum": 1,
        "maximum": 1,
        "card_type": "member",
        "work_key": "love_live_superstar",
    }
    assert liella_member_return_candidate.actions == [
        {"action_type": "return_from_waiting_room"}
    ]
    liella_double_baton_static_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-004:1"
    )
    assert liella_double_baton_static_candidate.effect_type == "static"
    assert liella_double_baton_static_candidate.timing == "static_always"
    assert liella_double_baton_static_candidate.trigger == "static_always"
    liella_baton_deploy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-004:2"
    )
    assert liella_baton_deploy_candidate.condition == {
        "source_slot": "center",
        "requires_baton_touch": True,
        "replacement_member_work_key": "love_live_superstar",
        "own_baton_entered_stage_member_work_count_at_least": {
            "work_key": "love_live_superstar",
            "count": 2,
        },
    }
    assert liella_baton_deploy_candidate.choice == {
        "choice_type": "deploy_member_from_waiting_room",
        "zone": "waiting_room",
        "card_type": "member",
        "work_key": "love_live_superstar",
        "maximum_cost": 4,
        "minimum": 1,
        "maximum": 1,
    }
    assert liella_baton_deploy_candidate.actions == [
        {"action_type": "draw_card", "amount": 2},
        {"action_type": "deploy_selected_to_empty_stage"},
    ]
    left_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-008:1"
    )
    assert left_draw_discard_candidate.condition == {"source_slot": "left"}
    assert left_draw_discard_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert left_draw_discard_candidate.actions == [
        {"action_type": "draw_card", "amount": 2},
        {"action_type": "discard_from_hand"},
    ]
    branch_ready_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp5-001:3"
    )
    assert branch_ready_candidate.choice["branch_ids"] == [
        "wait_source",
        "discard_hand",
    ]
    assert branch_ready_candidate.choice["branch_conditions"] == {
        "wait_source": {"source_orientation": "active"}
    }
    assert branch_ready_candidate.actions == [
        {"action_type": "apply_wait", "target": "source", "branch": "wait_source"},
        {
            "action_type": "ready_energy",
            "target": "auto",
            "amount": 1,
            "branch": "wait_source",
        },
        {
            "action_type": "ready_energy",
            "target": "auto",
            "amount": 1,
            "branch": "discard_hand",
        },
        {"action_type": "discard_from_hand", "branch": "discard_hand"},
    ]
    color_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp1-003:2"
    )
    assert color_heart_candidate.condition == {"minimum_active_energy": 1}
    assert color_heart_candidate.choice["choice_type"] == "choose_color"
    assert color_heart_candidate.actions == [
        {"action_type": "gain_heart", "amount": 1}
    ]
    place_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-005:1"
    )
    assert place_energy_candidate.execution_mode == "auto_resolve"
    assert place_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "self",
            "amount": 1,
            "orientation": "wait",
        }
    ]
    onplay_branch_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-cl1-004:1"
    )
    assert onplay_branch_candidate.choice["branch_ids"] == [
        "mill3",
        "wait_opponent_cost2",
    ]
    assert onplay_branch_candidate.choice["branch_choice_filters"][
        "wait_opponent_cost2"
    ]["maximum_cost"] == 2
    assert onplay_branch_candidate.actions == [
        {"action_type": "mill_top_cards", "amount": 3, "branch": "mill3"},
        {
            "action_type": "apply_wait_member",
            "target": "selected",
            "branch": "wait_opponent_cost2",
        },
    ]
    aqours_saint_snow_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-004:1"
    )
    assert aqours_saint_snow_candidate.choice["branch_ids"] == [
        "aqours_blade",
        "saint_snow_position_change",
    ]
    assert aqours_saint_snow_candidate.choice["branch_choice_filters"][
        "aqours_blade"
    ] == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "work_key": "love_live_sunshine",
        "target_player": "self",
        "exclude_source": True,
    }
    assert aqours_saint_snow_candidate.choice["branch_choice_filters"][
        "saint_snow_position_change"
    ] == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "unit_key": "saint_snow",
        "target_player": "self",
    }
    assert aqours_saint_snow_candidate.actions == [
        {
            "action_type": "gain_blade",
            "target": "selected",
            "amount": 1,
            "branch": "aqours_blade",
        },
        {
            "action_type": "position_change_selected",
            "branch": "saint_snow_position_change",
        },
    ]
    pay1_branch_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp5-001:1"
    )
    assert pay1_branch_candidate.is_optional is True
    assert pay1_branch_candidate.condition == {"minimum_active_energy": 1}
    assert pay1_branch_candidate.cost == [{"action_type": "pay_energy", "amount": 1}]
    assert pay1_branch_candidate.choice["branch_ids"] == [
        "wait_opponent_cost4",
        "draw1",
    ]
    assert pay1_branch_candidate.choice["branch_choice_filters"][
        "wait_opponent_cost4"
    ]["maximum_cost"] == 4
    assert pay1_branch_candidate.actions == [
        {
            "action_type": "apply_wait_member",
            "target": "selected",
            "branch": "wait_opponent_cost4",
        },
        {"action_type": "draw_card", "amount": 1, "branch": "draw1"},
    ]
    heart05_mill_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-sd1-013:1"
    )
    assert heart05_mill_candidate.actions == [
        {"action_type": "mill_top_cards", "amount": 3},
        {
            "action_type": "gain_heart_if_milled_all_have_heart",
            "color_slot": "heart05",
            "amount": 1,
        },
    ]
    aqours_stage_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-sd1-020:1"
    )
    assert aqours_stage_draw_discard_candidate.condition == {
        "own_stage_member_unit_count_at_least": {"unit_key": "aqours", "count": 1}
    }
    assert aqours_stage_draw_discard_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "amount_source": "own_stage_member_unit_count",
        "amount_source_unit_key": "aqours",
    }
    assert aqours_stage_draw_discard_candidate.actions == [
        {"action_type": "draw_card_per_stage_member", "value": {"unit_key": "aqours"}},
        {"action_type": "discard_from_hand"},
    ]
    choose_number_reveal_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-005:1"
    )
    assert choose_number_reveal_candidate.simulation_support == "test_validated_executable"
    assert choose_number_reveal_candidate.choice == {
        "choice_type": "choose_count",
        "minimum": 0,
        "maximum": 10,
    }
    assert choose_number_reveal_candidate.actions == [
        {
            "action_type": "reveal_top_matching_to_hand_else_deck_top",
            "amount": 1,
            "card_type": "member",
            "value": {"minimum_cost_source": "selected_count"},
        },
        {
            "action_type": "gain_blade",
            "amount": 2,
            "value": {
                "condition": {"last_revealed_top_member_cost_at_most_selected_count": True}
            },
        },
    ]
    equal_score_prevention_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-022:1"
    )
    assert (
        equal_score_prevention_candidate.pattern_id
        == "live_success_equal_score_prevent_success_live_placement"
    )
    assert equal_score_prevention_candidate.condition == {
        "live_judgment_basis": "equal_total_score"
    }
    assert equal_score_prevention_candidate.actions == [
        {"action_type": "prevent_equal_score_success_live_placement"}
    ]
    rotate_5yncri5e_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-003:1"
    )
    assert (
        rotate_5yncri5e_candidate.pattern_id
        == "onplay_only_5yncri5e_rotate_both_stage_members"
    )
    assert rotate_5yncri5e_candidate.execution_mode == "auto_resolve"
    assert rotate_5yncri5e_candidate.condition == {
        "own_stage_members_only_unit_key": "5yncri5e"
    }
    assert rotate_5yncri5e_candidate.actions == [
        {"action_type": "rotate_stage_members", "target": "both"}
    ]
    no_timing_live_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp4-014:1"
    )
    assert (
        no_timing_live_blade_candidate.pattern_id
        == "live_start_no_timing_live_other_member_gain_blade2"
    )
    assert no_timing_live_blade_candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "exclude_source": True,
        "minimum": 1,
        "maximum": 1,
    }
    assert no_timing_live_blade_candidate.condition == {
        "source_zone": "stage",
        "own_live_has_card_without_live_start_or_success_effects": True,
        "own_stage_member_count_at_least": 2,
    }
    assert no_timing_live_blade_candidate.actions == [
        {"action_type": "gain_blade", "target": "selected", "amount": 2}
    ]
    moved_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-011:1"
    )
    assert moved_blade_candidate.trigger == "member_moved"
    assert moved_blade_candidate.actions == [
        {"action_type": "gain_blade", "amount": 1}
    ]
    moved_heart02_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-sd2-012:1"
    )
    assert moved_heart02_candidate.actions == [
        {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"}
    ]
    moved_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-020:1"
    )
    assert moved_draw_candidate.trigger == "member_moved"
    assert moved_draw_candidate.frequency_limit == "none"
    assert moved_draw_candidate.actions == [{"action_type": "draw_card", "amount": 1}]
    moved_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp2-003:1"
    )
    assert moved_energy_candidate.condition == {
        "source_zone": "stage",
        "minimum_energy_deck_cards": 1,
    }
    assert moved_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "self",
            "amount": 1,
            "orientation": "wait",
        }
    ]
    moved_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-111:2"
    )
    assert moved_wait_candidate.choice["target_player"] == "opponent"
    assert moved_wait_candidate.choice["maximum_blade"] == 2
    assert moved_wait_candidate.actions == [
        {"action_type": "apply_wait_member", "target": "selected"}
    ]
    success_equal_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-007:1"
    )
    assert success_equal_candidate.condition == {
        "own_success_live_count_equals_opponent": True
    }
    assert success_equal_candidate.actions == [
        {"action_type": "gain_heart", "amount": 2, "color_slot": "heart02"}
    ]
    opponent_wait_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp3-002:2"
    )
    assert opponent_wait_blade_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount_source": "opponent_stage_wait_member_count",
        }
    ]
    opponent_wait_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-pb1-002:3"
    )
    assert opponent_wait_heart_candidate.actions == [
        {
            "action_type": "gain_heart",
            "amount_source": "opponent_stage_wait_member_count",
            "color_slot": "heart06",
        }
    ]
    success_score_lead_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp4-018:1"
    )
    assert success_score_lead_candidate.condition == {
        "success_live_score_more_than_opponent": True
    }
    assert success_score_lead_candidate.actions == [
        {"action_type": "gain_blade", "amount": 2}
    ]
    opponent_success_lead_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-009:1"
    )
    assert opponent_success_lead_candidate.condition == {
        "own_success_live_count_less_than_opponent": True
    }
    assert opponent_success_lead_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount_source": "opponent_success_live_count_difference",
        }
    ]
    miracra_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp2-006:2"
    )
    assert miracra_blade_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount_source": "own_stage_member_unit_count",
            "value": {"unit_key": "miracra_park", "exclude_source": True},
        }
    ]
    non_cerise_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp5-004:1"
    )
    assert non_cerise_blade_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount_source": "own_stage_member_filter_count",
            "multiplier": 2,
            "value": {"minimum_cost": 4, "exclude_unit_key": "cerise_bouquet"},
        }
    ]
    edel_note_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp5-007:2"
    )
    assert edel_note_candidate.condition == {
        "own_stage_other_member_unit_count_at_least": {
            "unit_key": "edel_note",
            "count": 1,
        }
    }
    stage_count_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-007:2"
    )
    assert stage_count_heart_candidate.condition == {
        "own_stage_member_count_exact": 2,
        "opponent_stage_member_count_at_least": 3,
    }
    opponent_excess_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-008:1"
    )
    assert opponent_excess_score_candidate.condition == {
        "opponent_excess_heart_count_at_least": 2
    }
    assert opponent_excess_score_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    center_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp5-011:2"
    )
    assert center_heart_candidate.condition == {"source_slot": "center"}
    assert center_heart_candidate.actions == [
        {"action_type": "gain_heart", "amount": 3, "color_slot": "heart03"}
    ]
    pay3_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-pb1-004:2"
    )
    assert pay3_draw_candidate.is_optional is True
    assert pay3_draw_candidate.condition == {"minimum_active_energy": 3}
    assert pay3_draw_candidate.cost == [{"action_type": "pay_energy", "amount": 3}]
    assert pay3_draw_candidate.actions == [{"action_type": "draw_card", "amount": 1}]
    revealed_live_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-007:1"
    )
    assert revealed_live_energy_candidate.condition == {
        "yell_revealed_card_type_count_at_least": {"card_type": "live", "count": 1},
        "minimum_energy_deck_cards": 1,
    }
    assert revealed_live_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "self",
            "amount": 1,
            "orientation": "wait",
        }
    ]
    all_blade_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp3-030:1"
    )
    assert all_blade_score_candidate.condition == {
        "own_yell_revealed_special_blade_heart_count_at_least": {
            "effect_type": "all_color",
            "count": 1,
        }
    }
    assert all_blade_score_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    aqours_score_live_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-009:2"
    )
    assert aqours_score_live_candidate.condition == {
        "source_slot": "center",
        "own_yell_revealed_special_blade_heart_count_at_least": {
            "effect_type": "score",
            "card_type": "live",
            "work_key": "love_live_sunshine",
            "count": 1,
        },
    }
    success_score_live_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp5-023:1"
    )
    assert success_score_live_candidate.condition == {
        "any_success_live_count_at_least": 2,
        "own_yell_revealed_special_blade_heart_count_at_least": {
            "effect_type": "score",
            "card_type": "live",
            "count": 1,
        },
    }
    assert success_score_live_candidate.actions == [
        {"action_type": "modify_score", "amount": 2}
    ]
    kanon_keke_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp1-024:2"
    )
    assert kanon_keke_candidate.condition == {
        "own_stage_member_names_present": ["澁谷かのん", "唐 可可"]
    }
    assert kanon_keke_candidate.actions == [
        {"action_type": "draw_card", "amount": 1}
    ]
    opponent_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-019:2"
    )
    assert opponent_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "opponent",
            "amount": 1,
            "orientation": "wait",
        }
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
    edel_grouped_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-030:1"
    )
    assert edel_grouped_candidate.choice["selection_groups"][0]["unit_key"] == (
        "edel_note"
    )
    assert edel_grouped_candidate.choice["selection_groups"][1]["exclude_group_names"] == [
        "blade_member"
    ]
    assert edel_grouped_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount": 2,
            "value": {"target_group_id": "blade_member"},
        },
        {
            "action_type": "gain_heart",
            "amount": 2,
            "color_slot": "heart06",
            "value": {"target_group_id": "heart_member"},
        },
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
    hasunosora_heart04_baton_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp2-021:1"
    )
    assert hasunosora_heart04_baton_candidate.condition == {
        "own_baton_entered_stage_member_work_count_at_least": {
            "work_key": "hasunosora",
            "count": 2,
        }
    }
    assert hasunosora_heart04_baton_candidate.actions == [
        {
            "action_type": "modify_required_heart",
            "amount": -1,
            "color_slot": "heart04",
        }
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
    miracra_extra_heart_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-029:1"
    )
    assert miracra_extra_heart_candidate.condition == {
        "own_stage_member_more_than_original_heart_count_at_least": {
            "unit_key": "miracra_park",
            "count": 1,
        }
    }
    assert miracra_extra_heart_candidate.actions == [
        {"action_type": "draw_card", "amount": 1},
        {
            "action_type": "modify_required_heart",
            "amount_source": "stage_member_more_than_original_heart_count",
            "color_slot": "heart0",
            "value": {
                "unit_key": "miracra_park",
                "thresholds": {"2": -2},
            },
        },
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
    base_heart_choice_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-pb1-036:1"
    )
    assert base_heart_choice_candidate.choice == {
        "choice_type": "choose_color",
        "color_slots": ["heart01", "heart02", "heart06"],
        "minimum": 1,
        "maximum": 1,
    }
    assert base_heart_choice_candidate.actions == [
        {"action_type": "replace_member_base_hearts"}
    ]
    named_baton_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-pb1-014:1"
    )
    assert named_baton_candidate.condition == {
        "requires_baton_touch": True,
        "replacement_member_name_ja": "中須かすみ",
    }
    assert named_baton_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert named_baton_candidate.actions == [
        {"action_type": "draw_card", "amount": 2},
        {"action_type": "discard_from_hand"},
    ]
    required_heart_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-PR-003:1"
    )
    assert required_heart_return_candidate.cost_choice == {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 2,
        "maximum": 2,
    }
    assert required_heart_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "minimum": 1,
        "maximum": 1,
        "required_heart_color_slot": "heart03",
        "minimum_required_heart": 3,
    }
    assert required_heart_return_candidate.actions == [
        {"action_type": "return_from_waiting_room"}
    ]
    heart_inspect_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-013:1"
    )
    assert heart_inspect_candidate.choice == {
        "choice_type": "inspect_top_select",
        "amount": 4,
        "minimum": 0,
        "maximum": 1,
        "requires_order": False,
        "selected_destination": "hand",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": True,
        "heart_color_slot": "heart04",
        "minimum_heart_count": 2,
    }
    assert heart_inspect_candidate.actions == [
        {"action_type": "inspect_top_cards", "amount": 4},
        {"action_type": "select_to_hand_from_inspected"},
        {"action_type": "move_remaining_cards"},
    ]
    nijigasaki_ready_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp1-004:1"
    )
    assert nijigasaki_ready_candidate.condition == {
        "own_stage_member_work_count_at_least": {
            "work_key": "nijigasaki",
            "count": 2,
        }
    }
    assert nijigasaki_ready_candidate.actions == [
        {"action_type": "ready_energy", "amount": 1}
    ]
    hasu_ready_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-sd1-006:1"
    )
    assert hasu_ready_return_candidate.condition == {
        "own_stage_member_name_any": ["大沢瑠璃乃", "百生吟子", "徒町小鈴"]
    }
    assert hasu_ready_return_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "work_key": "hasunosora",
        "minimum": 0,
        "maximum": 1,
    }
    assert hasu_ready_return_candidate.actions == [
        {"action_type": "ready_energy", "target": "auto", "amount": 1},
        {"action_type": "return_from_waiting_room"},
    ]
    live_success_heart_inspect_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-007:1"
    )
    assert live_success_heart_inspect_candidate.is_optional is True
    assert live_success_heart_inspect_candidate.choice == {
        "choice_type": "inspect_top_select",
        "amount": 4,
        "minimum": 0,
        "maximum": 1,
        "requires_order": False,
        "card_type": "member",
        "heart_color_slot": "heart04",
        "minimum_heart_count": 2,
        "selected_destination": "hand",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": True,
    }
    assert live_success_heart_inspect_candidate.actions == [
        {"action_type": "inspect_top_cards", "amount": 4},
        {"action_type": "select_to_hand_from_inspected"},
        {"action_type": "move_remaining_cards"},
    ]
    excess_heart_inspect_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-028:1"
    )
    assert excess_heart_inspect_candidate.condition == {
        "own_excess_heart_count_at_least": 1
    }
    assert excess_heart_inspect_candidate.choice == {
        "choice_type": "inspect_top_select",
        "amount": 2,
        "minimum": 0,
        "maximum": 2,
        "requires_order": True,
        "selected_destination": "main_deck_top_ordered",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": False,
    }
    assert excess_heart_inspect_candidate.actions == [
        {"action_type": "inspect_top_cards", "amount": 2},
        {"action_type": "reorder_deck_top"},
        {"action_type": "move_remaining_cards"},
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
    waiting_love_live_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-sd1-009:1"
    )
    assert waiting_love_live_score_candidate.condition == {
        "waiting_room_work_count_at_least": {
            "work_key": "love_live",
            "count": 25,
        }
    }
    assert waiting_love_live_score_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    source_blade_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-009:2"
    )
    assert source_blade_draw_discard_candidate.condition == {
        "source_blade_at_least": 8
    }
    assert source_blade_draw_discard_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert source_blade_draw_discard_candidate.actions == [
        {"action_type": "draw_card", "amount": 2},
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
    center_liella_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-025:1"
    )
    assert center_liella_blade_candidate.actions == [
        {
            "action_type": "replace_member_base_blade",
            "amount": 3,
            "value": {
                "slot": "center",
                "work_key": "love_live_superstar",
            },
        }
    ]
    onplay_position_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-013:1"
    )
    assert onplay_position_candidate.choice == {
        "choice_type": "position_change_source",
        "minimum": 1,
        "maximum": 1,
    }
    assert onplay_position_candidate.actions == [
        {"action_type": "position_change_source"}
    ]
    live_start_position_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-008:3"
    )
    assert live_start_position_candidate.timing == "live_start"
    assert live_start_position_candidate.actions == [
        {"action_type": "position_change_source"}
    ]
    forced_non_center_position_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp4-005:3"
    )
    assert forced_non_center_position_candidate.is_optional is False
    assert forced_non_center_position_candidate.condition == {
        "own_stage_member_work_blade_count_at_most": {
            "work_key": "love_live",
            "minimum_blade": 5,
            "count": 0,
        }
    }
    assert forced_non_center_position_candidate.choice == {
        "choice_type": "position_change_source",
        "minimum": 1,
        "maximum": 1,
        "excluded_position_slots": ["center"],
    }
    baton_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp2-006:1"
    )
    assert baton_return_candidate.condition == {
        "requires_baton_touch": True,
        "replacement_member_work_key": "love_live_superstar",
    }
    assert baton_return_candidate.actions == [
        {"action_type": "return_baton_replaced_member_to_hand"}
    ]
    distinct_liella_yell_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp4-026:1"
    )
    assert distinct_liella_yell_candidate.condition == {
        "own_yell_revealed_member_distinct_name_count_at_least": {
            "work_key": "love_live_superstar",
            "count": 5,
        }
    }
    assert distinct_liella_yell_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    hasu_yell_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp1-022:1"
    )
    assert hasu_yell_candidate.condition == {
        "own_yell_revealed_member_work_count_at_least": {
            "work_key": "hasunosora",
            "count": 10,
        }
    }
    assert hasu_yell_candidate.actions == [{"action_type": "modify_score", "amount": 1}]
    hand_blade_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!SP-bp2-009:1"
    )
    assert hand_blade_candidate.actions == [
        {
            "action_type": "gain_blade",
            "amount_source": "own_hand_count_divided_by",
            "value": {"divisor": 2},
        }
    ]
    love_live_extra_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp6-023:1"
    )
    assert love_live_extra_draw_candidate.actions == [
        {"action_type": "draw_card", "amount": 1},
        {
            "action_type": "draw_card",
            "amount": 1,
            "value": {
                "condition": {
                    "success_live_work_count_at_least": {
                        "work_key": "love_live",
                        "count": 1,
                    }
                }
            },
        },
    ]
    higher_score_hasu_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp1-023:1"
    )
    assert higher_score_hasu_energy_candidate.condition == {
        "live_score_relation": "greater_than_opponent",
        "own_stage_member_work_count_at_least": {
            "work_key": "hasunosora",
            "count": 1,
        },
        "minimum_energy_deck_cards": 1,
    }
    assert higher_score_hasu_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "self",
            "amount": 1,
            "orientation": "wait",
        }
    ]
    excess_heart04_energy_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp3-027:1"
    )
    assert excess_heart04_energy_candidate.condition == {
        "own_excess_heart_color_count_at_least": {
            "color_slot": "heart04",
            "count": 1,
        },
        "own_stage_member_work_count_at_least": {
            "work_key": "nijigasaki",
            "count": 1,
        },
        "minimum_energy_deck_cards": 1,
    }
    assert excess_heart04_energy_candidate.actions == [
        {
            "action_type": "place_energy_from_deck",
            "target": "self",
            "amount": 1,
            "orientation": "wait",
        }
    ]
    score3_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-bp6-025:2"
    )
    assert score3_return_candidate.condition == {"own_stage_member_count_at_least": 2}
    assert score3_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "maximum_score": 3,
        "minimum": 1,
        "maximum": 1,
    }
    assert score3_return_candidate.actions == [
        {"action_type": "return_from_waiting_room"}
    ]
    no_excess_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp3-025:1"
    )
    assert no_excess_score_candidate.condition == {"own_excess_heart_count_at_most": 0}
    assert no_excess_score_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    wait_stage_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp3-031:1"
    )
    assert wait_stage_score_candidate.actions == [
        {
            "action_type": "modify_score",
            "amount_source": "own_wait_stage_member_count",
        }
    ]
    extra_heart_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-PR-028:1"
    )
    assert extra_heart_draw_candidate.condition == {
        "own_stage_member_more_than_original_heart_count_at_least": {"count": 1}
    }
    assert extra_heart_draw_candidate.actions == [
        {"action_type": "draw_card", "amount": 1}
    ]
    excess_heart01_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp4-023:1"
    )
    assert excess_heart01_draw_candidate.condition == {
        "own_excess_heart_color_count_at_least": {
            "color_slot": "heart01",
            "count": 1,
        }
    }
    assert excess_heart01_draw_candidate.actions == [
        {"action_type": "draw_card", "amount": 1}
    ]
    stage_heart_more_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp3-026:2"
    )
    assert stage_heart_more_candidate.condition == {
        "own_stage_total_heart_more_than_opponent": True
    }
    assert stage_heart_more_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
    ]
    excess_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-007:2"
    )
    assert excess_draw_discard_candidate.condition == {
        "own_excess_heart_count_at_least": 1
    }
    assert excess_draw_discard_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert excess_draw_discard_candidate.actions == [
        {"action_type": "draw_card", "amount": 2},
        {"action_type": "discard_from_hand"},
    ]
    source_score_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-026:2"
    )
    assert source_score_return_candidate.condition == {"source_score_exact": 3}
    assert source_score_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "work_key": "nijigasaki",
        "minimum": 1,
        "maximum": 1,
    }
    source_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp5-006:2"
    )
    assert source_wait_candidate.condition == {
        "source_orientation": "active",
        "own_stage_member_count_at_least": 2,
    }
    assert source_wait_candidate.actions == [{"action_type": "apply_wait"}]
    bibi_return_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-pb1-030:2"
    )
    assert bibi_return_candidate.condition == {
        "own_stage_member_unit_distinct_name_count_at_least": {
            "unit_key": "bibi",
            "count": 2,
        }
    }
    assert bibi_return_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": "member",
        "unit_key": "bibi",
        "minimum": 1,
        "maximum": 1,
    }
    fewer_revealed_draw_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp3-005:1"
    )
    assert fewer_revealed_draw_candidate.condition == {
        "yell_revealed_card_count_less_than_opponent": True
    }
    assert fewer_revealed_draw_candidate.actions == [
        {"action_type": "draw_card", "amount": 1}
    ]
    replace_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp3-019:1"
    )
    assert replace_score_candidate.condition == {
        "own_yell_no_blade_heartless_or_excess_heart_count_at_least": 2
    }
    assert replace_score_candidate.actions == [
        {"action_type": "replace_score", "amount": 4}
    ]
    assert replace_score_candidate.duration == "game"
    refreshed_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp2-022:1"
    )
    assert refreshed_score_candidate.condition == {
        "own_deck_refreshed_this_turn": True
    }
    assert refreshed_score_candidate.actions == [
        {"action_type": "modify_score", "amount": 2}
    ]
    success2_revealed_member_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-019:1"
    )
    assert success2_revealed_member_candidate.condition == {
        "any_success_live_count_at_least": 2
    }
    assert success2_revealed_member_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "resolution_area",
        "card_type": "member",
        "minimum": 0,
        "maximum": 2,
    }
    assert success2_revealed_member_candidate.actions == [
        {"action_type": "move_selected_to_hand"}
    ]
    discard_revealed_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-PR-027:1"
    )
    assert discard_revealed_candidate.simulation_support == (
        "test_validated_executable"
    )
    assert discard_revealed_candidate.is_optional
    assert discard_revealed_candidate.cost_choice == {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    assert discard_revealed_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "resolution_area",
        "minimum": 1,
        "maximum": 1,
        "value": {
            "card_type_stat_filters": [
                {"card_type": "member", "maximum_cost": 2},
                {"card_type": "live", "maximum_score": 2},
            ]
        },
    }
    assert discard_revealed_candidate.actions == [
        {"action_type": "move_selected_to_hand"}
    ]
    equal_score_cost9_member_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-cl1-012:1"
    )
    assert equal_score_cost9_member_candidate.condition == {
        "live_score_relation": "equal_to_opponent"
    }
    assert equal_score_cost9_member_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "resolution_area",
        "card_type": "member",
        "minimum_cost": 9,
        "minimum": 1,
        "maximum": 1,
    }
    higher_score_nijigasaki_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!N-bp1-026:1"
    )
    assert higher_score_nijigasaki_candidate.condition == {
        "live_score_relation": "greater_than_opponent"
    }
    assert higher_score_nijigasaki_candidate.choice == {
        "choice_type": "card_from_zone",
        "zone": "resolution_area",
        "work_key": "nijigasaki",
        "minimum": 1,
        "maximum": 1,
    }
    disable_success_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-pb1-019:1"
    )
    assert disable_success_candidate.condition == {
        "own_stage_heart_at_least": {
            "unit_key": "aqours",
            "color_slot": "heart02",
            "count": 6,
        }
    }
    assert disable_success_candidate.actions == [
        {"action_type": "disable_source_live_success_effects"}
    ]
    side_cost_wait_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-002:1"
    )
    assert side_cost_wait_candidate.condition == {
        "source_slot": "center",
        "own_side_stage_member_costs_equal": True,
    }
    assert side_cost_wait_candidate.actions == [
        {
            "action_type": "apply_wait_member",
            "target": "opponent_stage_original_blade_at_most",
            "amount": 3,
        }
    ]
    clear_excess_score_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp5-020:1"
    )
    assert clear_excess_score_candidate.condition == {
        "own_excess_heart_count_at_least": 3
    }
    assert clear_excess_score_candidate.actions == [
        {"action_type": "clear_excess_hearts"},
        {"action_type": "modify_score", "amount": 1},
    ]
    opponent_clear_excess_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-024:1"
    )
    assert opponent_clear_excess_candidate.actions == [
        {"action_type": "clear_excess_hearts", "target": "opponent"},
        {
            "action_type": "modify_score",
            "amount": 1,
            "value": {
                "condition": {"last_cleared_excess_heart_count_at_least": 2}
            },
        },
    ]
    aqours_blade_choice_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp3-025:1"
    )
    assert aqours_blade_choice_candidate.choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "work_key": "love_live_sunshine",
        "minimum_blade": 6,
        "minimum": 1,
        "maximum": 1,
    }
    assert aqours_blade_choice_candidate.actions == [
        {"action_type": "modify_score", "amount": 1}
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
    bulk_waiting_bottom_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!HS-pb1-012:1"
    )
    assert bulk_waiting_bottom_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "waiting_room",
        "card_type": "live",
        "minimum": 1,
        "maximum": 1,
        "post_action_condition_key": "bulk_moved_waiting_room_member_count",
        "post_action_condition_minimum": 20,
    }
    assert bulk_waiting_bottom_candidate.actions == [
        {
            "action_type": "move_waiting_room_members_to_deck_bottom",
            "target": "both",
        },
        {"action_type": "return_from_waiting_room"},
        {"action_type": "gain_blade", "amount": 2},
    ]
    muse_draw_discard_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!-bp5-021:1"
    )
    assert muse_draw_discard_candidate.choice == {
        "choice_type": "multi_player_draw_then_discard",
        "zone": "hand",
        "amount": 1,
        "discard_amount": 1,
    }
    assert muse_draw_discard_candidate.follow_up_choice == {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "card_type": "member",
        "work_key": "love_live",
        "minimum": 1,
        "maximum": 1,
        "condition": {"own_stage_member_count_at_least": 2},
    }
    assert muse_draw_discard_candidate.actions == [
        {
            "action_type": "gain_heart",
            "target": "selected",
            "amount": 1,
            "color_slot": "heart03",
            "value": {"condition": {"own_stage_member_count_at_least": 2}},
        },
        {
            "action_type": "modify_score",
            "amount": 1,
            "value": {
                "condition": {"own_stage_member_distinct_name_count_at_least": 3}
            },
        },
    ]
    all_aqours_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-019:1"
    )
    assert all_aqours_candidate.condition == {
        "own_stage_members_only_work_key": "love_live_sunshine"
    }
    assert all_aqours_candidate.choice == {
        "choice_type": "post_action_card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
        "destination_options": ["main_deck_top", "main_deck_bottom"],
    }
    assert all_aqours_candidate.actions == [
        {"action_type": "modify_score", "amount": 1},
        {"action_type": "draw_card", "amount": 1},
        {"action_type": "move_selected_to_deck_top_or_bottom"},
    ]
    aqours_branch_candidate = next(
        candidate
        for candidate in all_candidates
        if candidate.effect_id == "PL!S-bp6-020:1"
    )
    assert aqours_branch_candidate.choice == {
        "choice_type": "choose_effect_branch",
        "branch_ids": [
            "grant_success_draw",
            "baton_aqours_heart",
            "success2_score",
        ],
        "branch_selection_minimum": {"baton_aqours_heart": 1},
        "branch_selection_maximum": {"baton_aqours_heart": 1},
        "branch_conditions": {
            "success2_score": {"success_live_count_at_least": 2}
        },
        "branch_choice_filters": {
            "baton_aqours_heart": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live_sunshine",
                "target_player": "self",
                "baton_entered_this_turn": True,
            }
        },
    }
    assert aqours_branch_candidate.actions == [
        {
            "action_type": "grant_live_success_draw",
            "amount": 1,
            "branch": "grant_success_draw",
        },
        {
            "action_type": "gain_heart",
            "target": "selected",
            "amount": 1,
            "color_slot": "heart02",
            "branch": "baton_aqours_heart",
        },
        {
            "action_type": "modify_score",
            "amount": 1,
            "branch": "success2_score",
        },
    ]


def test_effect_registry_timing_prompt_coverage_exceeds_target():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    registered_segments = {
        (effect.card_code, effect.raw_text_hash, effect.effect_index)
        for effect in registry.effects
    }

    connection = sqlite3.connect(_require_full_card_database())
    connection.row_factory = sqlite3.Row
    try:
        segments = [
            (row["card_code"], row["raw_text_hash"], effect_index)
            for row in _effect_text_rows(connection)
            for effect_index, _label in _timing_segments(row)
        ]
    finally:
        connection.close()

    assert segments
    covered = sum(segment in registered_segments for segment in segments)
    assert covered / len(segments) >= 0.75


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
        execution_mode="prompt_then_resolve",
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


def test_named_baton_condition_controls_draw_then_discard_prompt():
    effect = EffectDefinition(
        effect_id="test-named-baton-draw:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="d" * 64,
        effect_index=1,
        label_ja="named baton draw discard test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_name_ja": "中須かすみ",
        },
        actions=[
            {"action_type": "draw_card", "amount": 2},
            {"action_type": "discard_from_hand"},
        ],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.pending_effects[0].trigger_data = {
        "used_baton_touch": True,
        "replacement_card_instance_id": "replacement-member",
    }
    state.cards["replacement-member"] = CardInstance(
        instance_id="replacement-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-REPLACED",
            card_id="TEST-REPLACED",
            name_ja="優木せつ菜",
            card_type="member",
        ),
    )

    with pytest.raises(Exception, match="replacement_member_name_mismatch"):
        apply_action(
            state.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={"invocation_id": "inv-1"},
            ),
        )

    state.cards["replacement-member"].card.name_ja = "中須かすみ"
    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    )

    assert result.state.pending_choice is None
    assert result.state.pending_effects[0].resolution_stage == "after_cost"
    assert [event.event_type for event in result.events] == [
        "cards_drawn",
        "effect_choice_started",
    ]
    choice_event = result.events[-1]
    assert choice_event.data["effect_id"] == "test-named-baton-draw:1"
    assert choice_event.data["reason"] == "post_action_card_choice"
    assert choice_event.data["choice_type"] == "post_action_card_from_zone"
    assert choice_event.data["card_selection_minimum"] == 1
    assert choice_event.data["card_selection_maximum"] == 1
    assert len(result.state.players["player_1"].hand) == 2
    selected = result.state.players["player_1"].hand[:1]
    resolved = apply_action(
        result.state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=result.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": selected,
            },
        ),
    )

    assert resolved.state.pending_effects == []
    assert selected[0] in resolved.state.players["player_1"].waiting_room
    assert len(resolved.state.players["player_1"].hand) == 1


def test_waiting_room_live_choice_filters_by_required_heart():
    effect = EffectDefinition(
        effect_id="test-required-heart-return:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="f" * 64,
        effect_index=1,
        label_ja="required Heart return test",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={},
        actions=[{"action_type": "return_from_waiting_room"}],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum": 1,
            "maximum": 1,
            "required_heart_color_slot": "heart03",
            "minimum_required_heart": 3,
        },
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    low_live = CardDefinition(
        card_code="TEST-LOW-LIVE",
        card_id="TEST-LOW-LIVE",
        name_ja="低必要ハートライブ",
        card_type="live",
        required_hearts={"heart03": 2},
    )
    high_live = low_live.model_copy(
        update={
            "card_code": "TEST-HIGH-LIVE",
            "card_id": "TEST-HIGH-LIVE",
            "required_hearts": {"heart03": 3},
        }
    )
    state.cards["low-live"] = CardInstance(
        instance_id="low-live",
        owner_id="player_1",
        card=low_live,
    )
    state.cards["high-live"] = CardInstance(
        instance_id="high-live",
        owner_id="player_1",
        card=high_live,
    )
    state.players["player_1"].waiting_room = ["low-live", "high-live"]

    with pytest.raises(Exception, match="effect card selection is not legal"):
        apply_action(
            state.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "invocation_id": "inv-1",
                    "selected_card_instance_ids": ["low-live"],
                },
            ),
        )

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["high-live"],
            },
        ),
    )

    assert "high-live" in result.state.players["player_1"].hand
    assert "high-live" not in result.state.players["player_1"].waiting_room
    assert "low-live" in result.state.players["player_1"].waiting_room


def test_inspection_choice_filters_by_member_or_live_heart_count():
    effect = EffectDefinition(
        effect_id="test-heart-filter-inspect:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="g" * 64,
        effect_index=1,
        label_ja="Heart filtered inspection test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=True,
        condition={},
        actions=[
            {"action_type": "inspect_top_cards", "amount": 4},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 4,
            "minimum": 0,
            "maximum": 1,
            "requires_order": False,
            "selected_destination": "hand",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": True,
            "heart_color_slot": "heart04",
            "minimum_heart_count": 2,
        },
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    high_member = CardDefinition(
        card_code="TEST-HIGH-MEMBER",
        card_id="TEST-HIGH-MEMBER",
        name_ja="高ハートメンバー",
        card_type="member",
        basic_hearts={"heart04": 2},
    )
    low_member = high_member.model_copy(
        update={
            "card_code": "TEST-LOW-MEMBER",
            "card_id": "TEST-LOW-MEMBER",
            "basic_hearts": {"heart04": 1},
        }
    )
    high_live = CardDefinition(
        card_code="TEST-HIGH-LIVE",
        card_id="TEST-HIGH-LIVE",
        name_ja="高必要ハートライブ",
        card_type="live",
        required_hearts={"heart04": 2},
    )
    low_live = high_live.model_copy(
        update={
            "card_code": "TEST-LOW-LIVE",
            "card_id": "TEST-LOW-LIVE",
            "required_hearts": {"heart04": 1},
        }
    )
    state.cards.update(
        {
            "low-member": CardInstance(
                instance_id="low-member",
                owner_id="player_1",
                card=low_member,
                face_up=False,
            ),
            "high-live": CardInstance(
                instance_id="high-live",
                owner_id="player_1",
                card=high_live,
                face_up=False,
            ),
            "low-live": CardInstance(
                instance_id="low-live",
                owner_id="player_1",
                card=low_live,
                face_up=False,
            ),
            "high-member": CardInstance(
                instance_id="high-member",
                owner_id="player_1",
                card=high_member,
                face_up=False,
            ),
        }
    )
    state.players["player_1"].main_deck = [
        "low-member",
        "high-live",
        "low-live",
        "high-member",
    ]

    inspected = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    ).state

    assert inspected.pending_choice is not None
    assert inspected.pending_choice.options["candidate_card_instance_ids"] == [
        "high-live",
        "high-member",
    ]

    with pytest.raises(Exception, match="effect inspection selection is not legal"):
        apply_action(
            inspected.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect_choice",
                expected_revision=inspected.revision,
                player_id="player_1",
                payload={"selected_card_instance_ids": ["low-live"]},
            ),
        )

    result = apply_action(
        inspected,
        ActionRequest(
            action_type="resolve_effect_choice",
            expected_revision=inspected.revision,
            player_id="player_1",
            payload={"selected_card_instance_ids": ["high-member"]},
        ),
    )

    assert "high-member" in result.state.players["player_1"].hand
    assert "low-member" in result.state.players["player_1"].waiting_room
    assert "low-live" in result.state.players["player_1"].waiting_room
    assert "high-live" in result.state.players["player_1"].waiting_room


def test_excess_heart_condition_controls_live_success_inspection():
    effect = EffectDefinition(
        effect_id="test-excess-heart-inspect:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="m" * 64,
        effect_index=1,
        label_ja="excess Heart inspect test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_excess_heart_count_at_least": 1},
        cost=[],
        actions=[
            {"action_type": "inspect_top_cards", "amount": 2},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 2,
            "minimum": 0,
            "maximum": 2,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": False,
        },
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]

    with pytest.raises(Exception, match="excess_heart_count_too_low"):
        apply_action(
            state.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={"invocation_id": "inv-1"},
            ),
        )

    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart04": 1}, "remaining_all_color_hearts": 0}
    ]
    inspected = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    ).state

    assert inspected.pending_choice is not None
    assert inspected.pending_choice.options["inspected_card_instance_ids"] == [
        "deck-live-1",
        "deck-member-1",
    ]


def test_extra_heart_member_count_draws_and_modifies_required_heart():
    effect = EffectDefinition(
        effect_id="test-extra-heart-count:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="e" * 64,
        effect_index=1,
        label_ja="extra Heart count test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_member_more_than_original_heart_count_at_least": {
                "unit_key": "miracra_park",
                "count": 1,
            }
        },
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {
                "action_type": "modify_required_heart",
                "amount_source": "stage_member_more_than_original_heart_count",
                "color_slot": "heart0",
                "value": {
                    "unit_key": "miracra_park",
                    "thresholds": {"2": -2},
                },
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    miracra_member = CardDefinition(
        card_code="TEST-MIRACRA",
        card_id="TEST-MIRACRA",
        name_ja="みらくらぱーく！テスト",
        card_type="member",
        basic_hearts={"heart01": 1},
        unit_keys=["miracra_park"],
    )

    state = _minimal_effect_state(effect)
    for instance_id in ["left-member", "center-member"]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=miracra_member,
        )
    state.players["player_1"].member_area = {
        "left": "left-member",
        "center": "center-member",
        "right": None,
    }

    with pytest.raises(
        Exception,
        match="stage_member_more_than_original_heart_count_too_low",
    ):
        apply_action(
            state.model_copy(deep=True),
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=state.revision,
                player_id="player_1",
                payload={"invocation_id": "inv-1", "accepted": True},
            ),
        )

    one_extra = state.model_copy(deep=True)
    one_extra.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="test:heart:left",
            modifier_type="heart",
            duration="live",
            created_turn=one_extra.turn_number,
            amount=1,
            color_slot="heart02",
            target_card_instance_id="left-member",
        )
    )
    before_hand = len(one_extra.players["player_1"].hand)
    one_result = apply_action(
        one_extra,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=one_extra.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )
    assert len(one_result.state.players["player_1"].hand) == before_hand + 1
    assert not any(
        item.modifier_type == "required_heart" and item.amount == -2
        for item in one_result.state.players["player_1"].manual_modifiers
    )

    two_extra = state.model_copy(deep=True)
    for target_id in ["left-member", "center-member"]:
        two_extra.players["player_1"].manual_modifiers.append(
            ManualModifier(
                modifier_id=f"test:heart:{target_id}",
                modifier_type="heart",
                duration="live",
                created_turn=two_extra.turn_number,
                amount=1,
                color_slot="heart02",
                target_card_instance_id=target_id,
            )
        )
    two_result = apply_action(
        two_extra,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=two_extra.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "accepted": True},
        ),
    )
    assert any(
        item.modifier_type == "required_heart"
        and item.color_slot == "heart0"
        and item.amount == -2
        for item in two_result.state.players["player_1"].manual_modifiers
    )


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
    player.member_areas_moved_this_turn = ["left", "right"]

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
            "exclude_group_names": [],
            "minimum": 1,
            "maximum": 1,
        },
        {
            "group_id": "other_liella",
            "label_ja": "選んだメンバー以外の『Liella!』のメンバー",
            "candidate_card_instance_ids": ["kanon-member", "chisato-member"],
            "exclude_group_ids": ["named_member"],
            "exclude_group_names": [],
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


def test_grouped_stage_member_choice_can_apply_different_modifiers_by_group():
    effect = EffectDefinition(
        effect_id="test-grouped-edel-note:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="e" * 64,
        effect_index=1,
        label_ja="Edel Note grouped modifier test",
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
                    "group_id": "blade_member",
                    "label_ja": "Blade target",
                    "zone": "stage",
                    "card_type": "member",
                    "unit_key": "edel_note",
                    "minimum": 1,
                    "maximum": 1,
                },
                {
                    "group_id": "heart_member",
                    "label_ja": "Heart target",
                    "zone": "stage",
                    "card_type": "member",
                    "unit_key": "edel_note",
                    "exclude_group_ids": ["blade_member"],
                    "exclude_group_names": ["blade_member"],
                    "minimum": 1,
                    "maximum": 1,
                },
            ],
        },
        actions=[
            {
                "action_type": "gain_blade",
                "amount": 2,
                "value": {"target_group_id": "blade_member"},
            },
            {
                "action_type": "gain_heart",
                "amount": 2,
                "color_slot": "heart06",
                "value": {"target_group_id": "heart_member"},
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    member = CardDefinition(
        card_code="TEST-EDEL-A",
        card_id="TEST-EDEL-A",
        name_ja="Edel A",
        card_type="member",
        unit_keys=["edel_note"],
    )
    state.cards["edel-a-1"] = CardInstance(
        instance_id="edel-a-1",
        owner_id="player_1",
        card=member,
    )
    state.cards["edel-a-2"] = CardInstance(
        instance_id="edel-a-2",
        owner_id="player_1",
        card=member.model_copy(
            update={"card_code": "TEST-EDEL-A2", "card_id": "TEST-EDEL-A2"}
        ),
    )
    state.cards["edel-b"] = CardInstance(
        instance_id="edel-b",
        owner_id="player_1",
        card=member.model_copy(
            update={
                "card_code": "TEST-EDEL-B",
                "card_id": "TEST-EDEL-B",
                "name_ja": "Edel B",
            }
        ),
    )
    state.players["player_1"].member_area = {
        "left": "edel-a-1",
        "center": "edel-a-2",
        "right": "edel-b",
    }

    with pytest.raises(Exception, match="grouped effect selection is not legal"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids_by_group": {
                    "blade_member": ["edel-a-1"],
                    "heart_member": ["edel-a-2"],
                },
            },
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids_by_group": {
                "blade_member": ["edel-a-1"],
                "heart_member": ["edel-b"],
            },
        },
    )

    assert [
        (modifier.modifier_type, modifier.amount, modifier.target_card_instance_id)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [
        ("blade", 2, "edel-a-1"),
        ("heart", 2, "edel-b"),
    ]
    assert resolved.players["player_1"].manual_modifiers[1].color_slot == "heart06"


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


def test_onplay_bulk_waiting_members_to_deck_bottom_unlocks_return_live_and_blade():
    state = _minimal_effect_state(_bulk_waiting_members_to_bottom_effect())
    member = CardDefinition(
        card_code="TEST-WAITING-MEMBER",
        card_id="TEST-WAITING-MEMBER",
        name_ja="控え室メンバー",
        card_type="member",
    )
    live = CardDefinition(
        card_code="TEST-WAITING-LIVE",
        card_id="TEST-WAITING-LIVE",
        name_ja="控え室ライブ",
        card_type="live",
        score=1,
    )
    state.cards["source-live"].card = member.model_copy(
        update={"card_code": "TEST-SOURCE-MEMBER", "card_id": "TEST-SOURCE-MEMBER"}
    )
    own_members = [f"own-waiting-member-{index}" for index in range(11)]
    opponent_members = [f"opponent-waiting-member-{index}" for index in range(9)]
    for instance_id in own_members:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=member,
        )
        state.players["player_1"].waiting_room.append(instance_id)
    state.cards["own-waiting-live"] = CardInstance(
        instance_id="own-waiting-live",
        owner_id="player_1",
        card=live,
    )
    state.players["player_1"].waiting_room.append("own-waiting-live")
    for instance_id in opponent_members:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=member,
        )
        state.players["player_2"].waiting_room.append(instance_id)

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    invocation = state.pending_effects[0]
    assert invocation.resolution_stage == "after_cost"
    assert invocation.trigger_data["bulk_moved_waiting_room_member_count"] == 20
    assert state.players["player_1"].waiting_room == ["own-waiting-live"]
    assert state.players["player_2"].waiting_room == []
    assert set(state.players["player_1"].main_deck[-len(own_members) :]) == set(
        own_members
    )
    assert set(state.players["player_2"].main_deck) == set(opponent_members)
    assert all(
        not state.cards[instance_id].face_up
        for instance_id in [*own_members, *opponent_members]
    )
    legal = generate_legal_actions(state)
    resolve_action = next(action for action in legal if action.action_type == "resolve_effect")
    options = resolve_action.options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["own-waiting-live"]
    assert options["card_selection_minimum"] == 1
    assert options["card_selection_maximum"] == 1

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["own-waiting-live"],
        },
    )

    assert "own-waiting-live" in state.players["player_1"].hand
    assert state.players["player_1"].waiting_room == []
    assert not state.pending_effects
    modifier = state.players["player_1"].manual_modifiers[-1]
    assert modifier.modifier_type == "blade"
    assert modifier.amount == 2
    assert modifier.target_card_instance_id == "source-live"


def test_onplay_bulk_waiting_members_to_deck_bottom_finishes_under_threshold():
    state = _minimal_effect_state(_bulk_waiting_members_to_bottom_effect())
    member = CardDefinition(
        card_code="TEST-WAITING-MEMBER",
        card_id="TEST-WAITING-MEMBER",
        name_ja="控え室メンバー",
        card_type="member",
    )
    live = CardDefinition(
        card_code="TEST-WAITING-LIVE",
        card_id="TEST-WAITING-LIVE",
        name_ja="控え室ライブ",
        card_type="live",
        score=1,
    )
    own_members = [f"own-waiting-member-{index}" for index in range(10)]
    opponent_members = [f"opponent-waiting-member-{index}" for index in range(9)]
    for instance_id in own_members:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=member,
        )
        state.players["player_1"].waiting_room.append(instance_id)
    state.cards["own-waiting-live"] = CardInstance(
        instance_id="own-waiting-live",
        owner_id="player_1",
        card=live,
    )
    state.players["player_1"].waiting_room.append("own-waiting-live")
    for instance_id in opponent_members:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=member,
        )
        state.players["player_2"].waiting_room.append(instance_id)

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert not state.pending_effects
    assert state.players["player_1"].waiting_room == ["own-waiting-live"]
    assert "own-waiting-live" not in state.players["player_1"].hand
    assert state.players["player_1"].manual_modifiers == []
    assert set(state.players["player_1"].main_deck[-len(own_members) :]) == set(
        own_members
    )
    assert set(state.players["player_2"].main_deck) == set(opponent_members)


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


def test_replace_member_base_blade_changes_yell_blade_count():
    effect = EffectDefinition(
        effect_id="test-replace-base-blade:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="n" * 64,
        effect_index=1,
        label_ja="replace base Blade test",
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
                "action_type": "replace_member_base_blade",
                "amount": 3,
                "value": {
                    "slot": "center",
                    "work_key": "love_live_superstar",
                },
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    center_member = CardDefinition(
        card_code="TEST-LIELLA-CENTER",
        card_id="TEST-LIELLA-CENTER",
        name_ja="Liella center",
        card_type="member",
        blade=1,
        work_keys=["love_live_superstar"],
    )
    state.cards["center-member"] = CardInstance(
        instance_id="center-member",
        owner_id="player_1",
        card=center_member,
    )
    state.players["player_1"].member_area["center"] = "center-member"

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "base_blade_replacement"
        and modifier.amount == 3
        and modifier.target_card_instance_id == "center-member"
        for modifier in resolved.players["player_1"].manual_modifiers
    )

    events: list[GameEvent] = []
    _run_current_yell(resolved, events)

    assert resolved.players["player_1"].live_result.blade_count == 3
    assert resolved.players["player_1"].live_result.revealed_instance_ids == [
        "deck-live-1",
        "deck-member-1",
        "deck-live-2",
    ]


def test_source_position_change_choice_swaps_member_slots():
    effect = EffectDefinition(
        effect_id="test-position-change:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="o" * 64,
        effect_index=1,
        label_ja="position change test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[],
        choice={
            "choice_type": "position_change_source",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "position_change_source"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    right_member = CardDefinition(
        card_code="TEST-RIGHT-MEMBER",
        card_id="TEST-RIGHT-MEMBER",
        name_ja="right member",
        card_type="member",
        blade=1,
        basic_hearts={"heart02": 1},
    )
    state.cards["source-live"].card = source_member
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=right_member,
    )
    state.players["player_1"].member_area["center"] = "source-live"
    state.players["player_1"].member_area["right"] = "right-member"

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["choice_type"] == "position_change_source"
    assert options["position_change_slots"] == ["left", "right"]

    with pytest.raises(Exception, match="position change selection is not legal"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1", "to_slot": "center"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "to_slot": "right"},
    )

    player = resolved.players["player_1"]
    assert player.member_area["center"] == "right-member"
    assert player.member_area["right"] == "source-live"


def test_position_change_triggers_moved_source_heart_modifier():
    position_effect = EffectDefinition(
        effect_id="test-position-change:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="o" * 64,
        effect_index=1,
        label_ja="position change test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[],
        choice={
            "choice_type": "position_change_source",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "position_change_source"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    moved_effect = EffectDefinition(
        effect_id="test-moved-heart:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="r" * 64,
        effect_index=2,
        label_ja="moved heart test",
        effect_type="triggered",
        timing="auto_triggered_event",
        trigger="member_moved",
        execution_mode="auto_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[],
        choice=None,
        actions=[{"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(position_effect)
    state.effect_definitions[moved_effect.effect_id] = moved_effect
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[moved_effect.effect_id],
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area["center"] = "source-live"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "to_slot": "right"},
    )

    assert state.players["player_1"].member_area["right"] == "source-live"
    assert not state.pending_effects
    assert any(
        modifier.modifier_type == "heart"
        and modifier.color_slot == "heart06"
        and modifier.amount == 1
        and modifier.target_card_instance_id == "source-live"
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_activated_pay_energy_simple_effect_resolves_and_hides_activation():
    effect = EffectDefinition(
        effect_id="test-activated-simple-pay-energy:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="q" * 64,
        effect_index=1,
        label_ja="activated simple pay Energy test",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "minimum_active_energy": 1},
        cost=[{"action_type": "pay_energy", "amount": 1}],
        choice=None,
        actions=[{"action_type": "gain_blade", "amount": 1}],
        duration="turn",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="test energy",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.players["player_1"].member_area["center"] = "source-live"
    state.players["player_1"].energy_area = ["energy-1"]

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert not state.pending_effects
    assert any(
        modifier.modifier_type == "blade"
        and modifier.amount == 1
        and modifier.target_card_instance_id == "source-live"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert any(
        usage.effect_id == effect.effect_id
        and usage.source_card_instance_id == "source-live"
        for usage in state.effect_usage
    )
    assert not any(
        entry["effect_id"] == effect.effect_id
        for action in generate_legal_actions(state)
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
    )


def test_pl_hs_bp1_007_paid_activation_draws_and_hides_button():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!HS-bp1-007:1"]
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="PL!HS-bp1-007",
        card_id="PL!HS-bp1-007",
        name_ja="百生 吟子",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area["center"] = "source-live"
    for instance_id in ["energy-1", "energy-2"]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=energy_card,
        )
    state.players["player_1"].energy_area = ["energy-1", "energy-2"]

    legal = generate_legal_actions(state)
    assert any(
        entry["effect_id"] == effect.effect_id
        for action in legal
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
    )

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    assert "deck-live-1" in state.players["player_1"].hand
    assert not state.pending_effects
    assert not any(
        entry["effect_id"] == effect.effect_id
        for action in generate_legal_actions(state)
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
    )


def test_pl_hs_bp6_014_activates_from_hand_and_grants_blade():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!HS-bp6-014:1"]
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    hand_source = CardDefinition(
        card_code="PL!HS-bp6-014",
        card_id="PL!HS-bp6-014",
        name_ja="手札起動テスト",
        card_type="member",
        effect_ids=[effect.effect_id],
    )
    megumi = CardDefinition(
        card_code="TEST-MEGUMI",
        card_id="TEST-MEGUMI",
        name_ja="藤島 慈",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    rurino = megumi.model_copy(
        update={
            "card_code": "TEST-RURINO",
            "card_id": "TEST-RURINO",
            "name_ja": "大沢瑠璃乃",
        }
    )
    other_member = megumi.model_copy(
        update={
            "card_code": "TEST-OTHER",
            "card_id": "TEST-OTHER",
            "name_ja": "乙宗 梢",
        }
    )
    state.cards["hand-source"] = CardInstance(
        instance_id="hand-source",
        owner_id="player_1",
        card=hand_source,
    )
    state.cards["megumi"] = CardInstance(
        instance_id="megumi",
        owner_id="player_1",
        card=megumi,
    )
    state.cards["rurino"] = CardInstance(
        instance_id="rurino",
        owner_id="player_1",
        card=rurino,
    )
    state.cards["other-member"] = CardInstance(
        instance_id="other-member",
        owner_id="player_1",
        card=other_member,
    )
    player = state.players["player_1"]
    player.hand = ["hand-source"]
    player.member_area = {
        "left": "megumi",
        "center": "other-member",
        "right": "rurino",
    }

    activation = next(
        entry
        for action in generate_legal_actions(state)
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
        if entry["effect_id"] == effect.effect_id
    )
    assert activation["source_card_instance_id"] == "hand-source"

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "hand-source",
        },
    )

    player = state.players["player_1"]
    assert "hand-source" not in player.hand
    assert "hand-source" in player.waiting_room
    assert "deck-live-1" in player.hand
    invocation = state.pending_effects[0]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "member_from_stage"
    assert options["candidate_card_instance_ids"] == ["megumi", "rurino"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["rurino"],
        },
    )

    assert any(
        modifier.modifier_type == "blade"
        and modifier.amount == 1
        and modifier.target_card_instance_id == "rurino"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert not state.pending_effects


def test_pl_hs_bp6_014_resolves_from_hand_without_named_stage_target():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!HS-bp6-014:1"]
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    hand_source = CardDefinition(
        card_code="PL!HS-bp6-014",
        card_id="PL!HS-bp6-014",
        name_ja="手札起動テスト",
        card_type="member",
        effect_ids=[effect.effect_id],
    )
    other_member = CardDefinition(
        card_code="TEST-OTHER",
        card_id="TEST-OTHER",
        name_ja="乙宗 梢",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    state.cards["hand-source"] = CardInstance(
        instance_id="hand-source",
        owner_id="player_1",
        card=hand_source,
    )
    state.cards["other-member"] = CardInstance(
        instance_id="other-member",
        owner_id="player_1",
        card=other_member,
    )
    player = state.players["player_1"]
    player.hand = ["hand-source"]
    player.member_area = {"left": None, "center": "other-member", "right": None}

    activation = next(
        entry
        for action in generate_legal_actions(state)
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
        if entry["effect_id"] == effect.effect_id
    )
    assert activation["source_card_instance_id"] == "hand-source"

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "hand-source",
        },
    )

    player = state.players["player_1"]
    assert "hand-source" not in player.hand
    assert "hand-source" in player.waiting_room
    assert "deck-live-1" in player.hand

    invocation = state.pending_effects[0]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "member_from_stage"
    assert options["candidate_card_instance_ids"] == []
    assert options["card_selection_minimum"] == 0
    assert options["card_selection_maximum"] == 1

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": [],
        },
    )

    assert not state.players["player_1"].manual_modifiers
    assert not state.pending_effects


def test_pl_bp6_003_live_start_attaches_hand_member_and_gains_chosen_heart():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!-bp6-003:1"]
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="PL!-bp6-003",
        card_id="PL!-bp6-003-R+",
        name_ja="南ことり",
        card_type="member",
        cost=15,
        blade=7,
        basic_hearts={"heart01": 1},
    )
    low_muse = CardDefinition(
        card_code="PL!-bp6-017",
        card_id="PL!-bp6-017-N",
        name_ja="小泉花陽",
        card_type="member",
        cost=2,
        blade=0,
        basic_hearts={"heart01": 1},
        work_keys=["love_live"],
    )
    high_muse = low_muse.model_copy(
        update={"card_code": "PL!-bp6-008", "card_id": "PL!-bp6-008-P", "cost": 7}
    )
    other_work = low_muse.model_copy(
        update={
            "card_code": "PL!SP-bp6-001",
            "card_id": "PL!SP-bp6-001-R",
            "work_keys": ["love_live_superstar"],
        }
    )
    state.cards["source-live"].card = source_member
    state.cards["low-muse"] = CardInstance(
        instance_id="low-muse",
        owner_id="player_1",
        card=low_muse,
    )
    state.cards["high-muse"] = CardInstance(
        instance_id="high-muse",
        owner_id="player_1",
        card=high_muse,
    )
    state.cards["other-work"] = CardInstance(
        instance_id="other-work",
        owner_id="player_1",
        card=other_work,
    )
    player = state.players["player_1"]
    player.member_area = {"left": None, "center": "source-live", "right": None}
    player.hand = ["low-muse", "high-muse", "other-work"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["low-muse"]
    assert set(options["color_slots"]) == {
        "heart01",
        "heart02",
        "heart03",
        "heart04",
        "heart05",
        "heart06",
    }

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["low-muse"],
            "selected_color_slot": "heart03",
        },
    )

    player = state.players["player_1"]
    assert "low-muse" not in player.hand
    assert player.member_area_attachments["center"] == ["low-muse"]
    assert state.cards["low-muse"].face_up is True
    assert any(
        modifier.modifier_type == "heart"
        and modifier.color_slot == "heart03"
        and modifier.amount == 1
        and modifier.target_card_instance_id == "source-live"
        for modifier in player.manual_modifiers
    )
    assert not state.pending_effects


def test_pl_bp6_003_live_success_deploys_attached_member_to_empty_center():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!-bp6-003:2"]
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="PL!-bp6-003",
        card_id="PL!-bp6-003-R+",
        name_ja="南ことり",
        card_type="member",
        cost=15,
        blade=7,
        basic_hearts={"heart01": 1},
    )
    attached_member = CardDefinition(
        card_code="PL!-bp6-017",
        card_id="PL!-bp6-017-N",
        name_ja="小泉花陽",
        card_type="member",
        cost=2,
        blade=0,
        basic_hearts={"heart01": 1},
        work_keys=["love_live"],
    )
    high_attached = attached_member.model_copy(
        update={"card_code": "PL!-bp6-008", "card_id": "PL!-bp6-008-P", "cost": 7}
    )
    state.cards["source-live"].card = source_member
    state.cards["attached-low"] = CardInstance(
        instance_id="attached-low",
        owner_id="player_1",
        card=attached_member,
    )
    state.cards["attached-high"] = CardInstance(
        instance_id="attached-high",
        owner_id="player_1",
        card=high_attached,
    )
    player = state.players["player_1"]
    player.member_area = {"left": "source-live", "center": None, "right": None}
    player.member_area_attachments["left"] = ["attached-low", "attached-high"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["attached-low"]
    assert options["available_slots"] == ["center", "right"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["attached-low"],
            "to_slot": "center",
        },
    )

    player = state.players["player_1"]
    assert player.member_area["center"] == "attached-low"
    assert player.member_area_attachments["left"] == ["attached-high"]
    assert "center" in player.member_areas_entered_this_turn
    assert state.cards["attached-low"].orientation == "wait"
    assert not state.pending_effects


def test_onplay_energy_attachment_draws_cards():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!N-bp3-013:1"]
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="PL!N-bp3-013",
        card_id="PL!N-bp3-013-R",
        name_ja="上原歩夢",
        card_type="member",
        cost=4,
        blade=1,
        basic_hearts={"heart01": 1},
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area["center"] = "source-live"
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.players["player_1"].energy_area = ["energy-1"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["energy-1"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["energy-1"],
        },
    )

    player = state.players["player_1"]
    assert player.energy_area == []
    assert player.member_area_attachments["center"] == ["energy-1"]
    assert "deck-live-1" in player.hand
    assert "deck-member-1" in player.hand
    assert not state.pending_effects


def test_activated_energy_attachment_can_continue_to_waiting_room_live_choice():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!N-pb1-011:2"]
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="PL!N-pb1-011",
        card_id="PL!N-pb1-011-R",
        name_ja="優木せつ菜",
        card_type="member",
        cost=4,
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    nijigasaki_live = CardDefinition(
        card_code="PL!N-LIVE-TEST",
        card_id="PL!N-LIVE-TEST",
        name_ja="虹ヶ咲ライブ",
        card_type="live",
        score=1,
        required_hearts={"heart01": 1},
        work_keys=["nijigasaki"],
    )
    other_live = nijigasaki_live.model_copy(
        update={"card_code": "OTHER-LIVE", "card_id": "OTHER-LIVE", "work_keys": []}
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area["center"] = "source-live"
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.cards["niji-live"] = CardInstance(
        instance_id="niji-live",
        owner_id="player_1",
        card=nijigasaki_live,
    )
    state.cards["other-live"] = CardInstance(
        instance_id="other-live",
        owner_id="player_1",
        card=other_live,
    )
    player = state.players["player_1"]
    player.energy_area = ["energy-1"]
    player.waiting_room = ["niji-live", "other-live"]

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
            "selected_card_instance_ids": ["energy-1"],
        },
    )

    player = state.players["player_1"]
    assert player.energy_area == []
    assert player.member_area_attachments["center"] == ["energy-1"]
    assert state.pending_effects[0].resolution_stage == "after_cost"
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["niji-live"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["niji-live"],
        },
    )

    player = state.players["player_1"]
    assert "niji-live" in player.hand
    assert "niji-live" not in player.waiting_room
    assert not state.pending_effects


def test_activated_hand_member_attachment_reveals_and_attaches_named_card():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!HS-pb1-002:1"]
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="PL!HS-pb1-002",
        card_id="PL!HS-pb1-002-R",
        name_ja="村野さやか",
        card_type="member",
        cost=4,
        blade=1,
        basic_hearts={"heart05": 1},
        effect_ids=[effect.effect_id],
    )
    sayaka = source_member.model_copy(
        update={"card_code": "PL!HS-bp1-001", "card_id": "PL!HS-bp1-001"}
    )
    other_member = source_member.model_copy(
        update={
            "card_code": "PL!HS-bp1-002",
            "card_id": "PL!HS-bp1-002",
            "name_ja": "夕霧綴理",
        }
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area["center"] = "source-live"
    state.cards["sayaka"] = CardInstance(
        instance_id="sayaka",
        owner_id="player_1",
        card=sayaka,
    )
    state.cards["other-member"] = CardInstance(
        instance_id="other-member",
        owner_id="player_1",
        card=other_member,
    )
    state.players["player_1"].hand = ["sayaka", "other-member"]

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["sayaka"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["sayaka"],
        },
    )

    player = state.players["player_1"]
    assert player.hand == ["other-member"]
    assert player.member_area_attachments["center"] == ["sayaka"]
    assert state.cards["sayaka"].face_up is True
    assert not state.pending_effects


def test_onplay_discard_up_to_three_draws_same_number_of_cards():
    registry = EffectRegistry.model_validate_json(REGISTRY.read_text(encoding="utf-8"))
    effect = {effect.effect_id: effect for effect in registry.effects}["PL!HS-bp1-005:1"]
    state = _minimal_effect_state(effect)
    state.pending_effects[0].trigger_event = "member_played"
    hand_card = CardDefinition(
        card_code="TEST-HAND",
        card_id="TEST-HAND",
        name_ja="手札カード",
        card_type="member",
    )
    state.cards["hand-a"] = CardInstance(
        instance_id="hand-a",
        owner_id="player_1",
        card=hand_card,
    )
    state.cards["hand-b"] = CardInstance(
        instance_id="hand-b",
        owner_id="player_1",
        card=hand_card.model_copy(deep=True),
    )
    state.cards["hand-c"] = CardInstance(
        instance_id="hand-c",
        owner_id="player_1",
        card=hand_card.model_copy(deep=True),
    )
    player = state.players["player_1"]
    player.hand = ["hand-a", "hand-b", "hand-c"]
    player.main_deck = ["deck-live-1", "deck-member-1", "deck-live-2"]

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["hand-a", "hand-b"],
            },
        ),
    )
    state = result.state

    assert "hand-a" in state.players["player_1"].waiting_room
    assert "hand-b" in state.players["player_1"].waiting_room
    assert state.players["player_1"].hand == [
        "hand-c",
        "deck-live-1",
        "deck-member-1",
    ]
    assert state.players["player_1"].main_deck == ["deck-live-2"]
    assert not state.pending_effects
    assert any(
        event.event_type == "effect_resolved"
        and event.data["effect_id"] == effect.effect_id
        and event.data["selected_count"] == 2
        for event in result.events
    )


def test_activated_pay_energy_source_position_change_swaps_member_slots():
    effect = EffectDefinition(
        effect_id="test-activated-position-change:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="q" * 64,
        effect_index=1,
        label_ja="activated position change test",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "minimum_active_energy": 2},
        cost=[{"action_type": "pay_energy", "amount": 2}],
        choice={
            "choice_type": "position_change_source",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "position_change_source"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    right_member = CardDefinition(
        card_code="TEST-RIGHT-MEMBER",
        card_id="TEST-RIGHT-MEMBER",
        name_ja="right member",
        card_type="member",
        blade=1,
        basic_hearts={"heart02": 1},
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="test energy",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=right_member,
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.cards["energy-2"] = CardInstance(
        instance_id="energy-2",
        owner_id="player_1",
        card=energy_card.model_copy(deep=True),
    )
    state.players["player_1"].member_area["center"] = "source-live"
    state.players["player_1"].member_area["right"] = "right-member"
    state.players["player_1"].energy_area = ["energy-1", "energy-2"]

    legal = generate_legal_actions(state)
    activation = next(
        entry
        for action in legal
        if action.action_type == "activate_effect"
        for entry in action.options["activations"]
        if entry["effect_id"] == effect.effect_id
    )
    assert activation["source_card_instance_id"] == "source-live"

    auto_paid = _apply_direct(
        state.model_copy(deep=True),
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
        },
    )
    assert auto_paid.cards["energy-1"].orientation == "wait"
    assert auto_paid.cards["energy-2"].orientation == "wait"
    assert auto_paid.pending_effects[0].effect_id == effect.effect_id

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )
    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    invocation = state.pending_effects[0]
    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["choice_type"] == "position_change_source"
    assert options["position_change_slots"] == ["left", "right"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": invocation.invocation_id, "to_slot": "right"},
    )

    player = state.players["player_1"]
    assert player.member_area["center"] == "right-member"
    assert player.member_area["right"] == "source-live"
    assert not state.pending_effects


def test_activated_pay_energy_deploys_waiting_member_to_empty_stage():
    effect = EffectDefinition(
        effect_id="test-activated-deploy:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="s" * 64,
        effect_index=1,
        label_ja="activated deploy test",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "minimum_active_energy": 2},
        cost=[{"action_type": "pay_energy", "amount": 2}],
        choice={
            "choice_type": "deploy_member_from_waiting_room",
            "zone": "waiting_room",
            "card_type": "member",
            "maximum_cost": 2,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "deploy_selected_to_empty_stage"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    waiting_member = CardDefinition(
        card_code="TEST-WAITING-MEMBER",
        card_id="TEST-WAITING-MEMBER",
        name_ja="waiting member",
        card_type="member",
        cost=2,
        blade=1,
        basic_hearts={"heart02": 1},
    )
    high_cost_member = waiting_member.model_copy(
        update={
            "card_code": "TEST-HIGH-COST-MEMBER",
            "card_id": "TEST-HIGH-COST-MEMBER",
            "cost": 3,
        }
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="test energy",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.cards["waiting-member"] = CardInstance(
        instance_id="waiting-member",
        owner_id="player_1",
        card=waiting_member,
    )
    state.cards["high-cost-member"] = CardInstance(
        instance_id="high-cost-member",
        owner_id="player_1",
        card=high_cost_member,
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.cards["energy-2"] = CardInstance(
        instance_id="energy-2",
        owner_id="player_1",
        card=energy_card.model_copy(deep=True),
    )
    player = state.players["player_1"]
    player.member_area["center"] = "source-live"
    player.waiting_room = ["waiting-member", "high-cost-member"]
    player.energy_area = ["energy-1", "energy-2"]

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    invocation = state.pending_effects[0]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "deploy_member_from_waiting_room"
    assert options["candidate_card_instance_ids"] == ["waiting-member"]
    assert options["available_slots"] == ["left", "right"]

    with pytest.raises(Exception, match="deploy slot selection is not legal"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": invocation.invocation_id,
                "selected_card_instance_ids": ["waiting-member"],
                "slot": "center",
            },
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["waiting-member"],
            "slot": "left",
        },
    )

    player = state.players["player_1"]
    assert player.member_area["left"] == "waiting-member"
    assert "waiting-member" not in player.waiting_room
    assert "left" in player.member_areas_entered_this_turn
    assert state.cards["waiting-member"].orientation == "wait"
    assert not state.pending_effects


def test_activated_pay_energy_discard_cost_returns_waiting_room_live():
    effect = EffectDefinition(
        effect_id="test-activated-pay-discard-return:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="t" * 64,
        effect_index=1,
        label_ja="activated pay discard return test",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "minimum_active_energy": 2},
        cost=[
            {"action_type": "pay_energy", "amount": 2},
            {"action_type": "discard_from_hand"},
        ],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "work_key": "love_live_sunshine",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.phase = "first_main"
    state.pending_effects = []
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
        effect_ids=[effect.effect_id],
    )
    discard_card = CardDefinition(
        card_code="TEST-DISCARD",
        card_id="TEST-DISCARD",
        name_ja="discard card",
        card_type="member",
    )
    aqours_live = CardDefinition(
        card_code="TEST-AQOURS-LIVE",
        card_id="TEST-AQOURS-LIVE",
        name_ja="aqours live",
        card_type="live",
        work_keys=["love_live_sunshine"],
        score=1,
    )
    other_live = aqours_live.model_copy(
        update={
            "card_code": "TEST-OTHER-LIVE",
            "card_id": "TEST-OTHER-LIVE",
            "work_keys": ["nijigasaki"],
        }
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="test energy",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.cards["discard-card"] = CardInstance(
        instance_id="discard-card",
        owner_id="player_1",
        card=discard_card,
    )
    state.cards["aqours-live"] = CardInstance(
        instance_id="aqours-live",
        owner_id="player_1",
        card=aqours_live,
    )
    state.cards["other-live"] = CardInstance(
        instance_id="other-live",
        owner_id="player_1",
        card=other_live,
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.cards["energy-2"] = CardInstance(
        instance_id="energy-2",
        owner_id="player_1",
        card=energy_card.model_copy(deep=True),
    )
    player = state.players["player_1"]
    player.member_area["center"] = "source-live"
    player.hand = ["discard-card"]
    player.waiting_room = ["aqours-live", "other-live"]
    player.energy_area = ["energy-1", "energy-2"]

    state = _apply_direct(
        state,
        "activate_effect",
        player_id="player_1",
        payload={
            "effect_id": effect.effect_id,
            "source_card_instance_id": "source-live",
        },
    )

    assert state.cards["energy-1"].orientation == "active"
    assert state.cards["energy-2"].orientation == "active"
    player = state.players["player_1"]
    assert player.hand == ["discard-card"]
    invocation = state.pending_effects[0]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "card_from_zone"
    assert options["choice_zone"] == "hand"
    assert options["candidate_card_instance_ids"] == ["discard-card"]
    assert options["energy_required"] == 2
    assert options["energy_instance_ids"] == ["energy-1", "energy-2"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["discard-card"],
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    player = state.players["player_1"]
    assert "discard-card" not in player.hand
    assert "discard-card" in player.waiting_room
    invocation = state.pending_effects[0]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["aqours-live"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": invocation.invocation_id,
            "selected_card_instance_ids": ["aqours-live"],
        },
    )

    player = state.players["player_1"]
    assert "aqours-live" in player.hand
    assert "aqours-live" not in player.waiting_room
    assert "other-live" in player.waiting_room
    assert not state.pending_effects


def test_onplay_pay_energy_draw_requires_left_source_slot():
    effect = EffectDefinition(
        effect_id="test-onplay-left-pay-draw:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="u" * 64,
        effect_index=1,
        label_ja="on-play left pay draw test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=True,
        condition={"minimum_active_energy": 2, "source_slot": "left"},
        cost=[{"action_type": "pay_energy", "amount": 2}],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 2}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    energy_card = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="test energy",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy_card,
    )
    state.cards["energy-2"] = CardInstance(
        instance_id="energy-2",
        owner_id="player_1",
        card=energy_card.model_copy(deep=True),
    )
    player = state.players["player_1"]
    player.energy_area = ["energy-1", "energy-2"]
    player.member_area["center"] = "source-live"

    with pytest.raises(Exception, match="source_slot_mismatch"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "energy_instance_ids": ["energy-1", "energy-2"],
            },
        )

    player.member_area["center"] = None
    player.member_area["left"] = "source-live"
    result = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "accepted": True,
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )

    player = result.players["player_1"]
    assert result.cards["energy-1"].orientation == "wait"
    assert result.cards["energy-2"].orientation == "wait"
    assert len(player.hand) == 2
    assert len(player.main_deck) == 1
    assert not result.pending_effects


def test_source_position_change_can_require_no_high_blade_muse_and_exclude_center():
    effect = EffectDefinition(
        effect_id="test-position-change-no-muse-blade5:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="p" * 64,
        effect_index=1,
        label_ja="non-center position change test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_member_work_blade_count_at_most": {
                "work_key": "love_live",
                "minimum_blade": 5,
                "count": 0,
            }
        },
        cost=[],
        choice={
            "choice_type": "position_change_source",
            "minimum": 1,
            "maximum": 1,
            "excluded_position_slots": ["center"],
        },
        actions=[{"action_type": "position_change_source"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        work_keys=["love_live"],
        blade=4,
        basic_hearts={"heart01": 1},
    )
    right_member = CardDefinition(
        card_code="TEST-RIGHT-MEMBER",
        card_id="TEST-RIGHT-MEMBER",
        name_ja="right member",
        card_type="member",
        blade=1,
        basic_hearts={"heart02": 1},
    )
    state.cards["source-live"].card = source_member
    state.cards["right-member"] = CardInstance(
        instance_id="right-member",
        owner_id="player_1",
        card=right_member,
    )
    state.players["player_1"].member_area["left"] = "source-live"
    state.players["player_1"].member_area["right"] = "right-member"

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["position_change_slots"] == ["right"]

    with pytest.raises(Exception, match="position change selection is not legal"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1", "to_slot": "center"},
        )

    blocked = state.model_copy(deep=True)
    blocked.cards["right-member"].card = right_member.model_copy(
        update={"work_keys": ["love_live"], "blade": 5}
    )
    with pytest.raises(Exception, match="stage_member_work_blade_count_too_high"):
        _apply_direct(
            blocked.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1", "to_slot": "right"},
        )

    stale_queued = blocked.model_copy(deep=True)
    stale_queued.pending_effects[0].trigger_data["_condition_checked_at_trigger"] = True
    result = apply_action(
        stale_queued,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=stale_queued.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1", "to_slot": "right"},
        ),
    )
    assert result.state.players["player_1"].member_area["left"] == "source-live"
    assert result.state.players["player_1"].member_area["right"] == "right-member"
    assert result.state.pending_effects == []
    assert result.events[-1].event_type == "effect_not_activatable"
    assert (
        result.events[-1].data["reason"]
        == "stage_member_work_blade_count_too_high"
    )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "to_slot": "right"},
    )
    player = resolved.players["player_1"]
    assert player.member_area["left"] == "right-member"
    assert player.member_area["right"] == "source-live"
    assert player.member_areas_entered_this_turn == []
    assert set(player.member_areas_moved_this_turn) >= {"left", "right"}


def test_baton_replaced_member_returns_to_hand_only_from_trigger_data():
    effect = EffectDefinition(
        effect_id="test-baton-return:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="p" * 64,
        effect_index=1,
        label_ja="baton return test",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_work_key": "love_live_superstar",
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "return_baton_replaced_member_to_hand"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    replaced_member = CardDefinition(
        card_code="TEST-REPLACED-LIELLA",
        card_id="TEST-REPLACED-LIELLA",
        name_ja="replaced Liella",
        card_type="member",
        blade=1,
        work_keys=["love_live_superstar"],
    )
    state.cards["replaced-member"] = CardInstance(
        instance_id="replaced-member",
        owner_id="player_1",
        card=replaced_member,
    )
    state.players["player_1"].waiting_room.append("replaced-member")
    state.pending_effects[0].trigger_data = {
        "used_baton_touch": True,
        "replacement_card_instance_id": "replaced-member",
    }

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert "replaced-member" in resolved.players["player_1"].hand
    assert "replaced-member" not in resolved.players["player_1"].waiting_room

    no_baton = _minimal_effect_state(effect)
    no_baton.cards["replaced-member"] = CardInstance(
        instance_id="replaced-member",
        owner_id="player_1",
        card=replaced_member,
    )
    no_baton.players["player_1"].waiting_room.append("replaced-member")
    no_baton.pending_effects[0].trigger_data = {
        "used_baton_touch": False,
        "replacement_card_instance_id": "replaced-member",
    }
    with pytest.raises(Exception, match="baton_touch_required"):
        _apply_direct(
            no_baton,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_yell_revealed_distinct_work_member_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-yell-distinct-liella:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="q" * 64,
        effect_index=1,
        label_ja="distinct Yell member test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_member_distinct_name_count_at_least": {
                "work_key": "love_live_superstar",
                "count": 5,
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    revealed_ids: list[str] = []
    for index, name in enumerate(["Kanon", "Keke", "Chisato", "Sumire", "Ren"]):
        instance_id = f"revealed-liella-{index}"
        revealed_ids.append(instance_id)
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-LIELLA-{index}",
                card_id=f"TEST-LIELLA-{index}",
                name_ja=name,
                card_type="member",
                blade=1,
                work_keys=["love_live_superstar"],
            ),
        )
    state.players["player_1"].live_result.revealed_instance_ids = list(revealed_ids)
    duplicate_name = state.model_copy(deep=True)
    duplicate_name.cards[revealed_ids[-1]].card.name_ja = "Kanon"

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )

    with pytest.raises(
        Exception,
        match="yell_revealed_member_distinct_name_count_too_low",
    ):
        _apply_direct(
            duplicate_name,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_yell_revealed_work_member_count_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-yell-hasu-count:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="q" * 64,
        effect_index=1,
        label_ja="Yell Hasunosora member count test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_member_work_count_at_least": {
                "work_key": "hasunosora",
                "count": 10,
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    revealed_ids: list[str] = []
    for index in range(10):
        instance_id = f"revealed-hasu-{index}"
        revealed_ids.append(instance_id)
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-HASU-{index}",
                card_id=f"TEST-HASU-{index}",
                name_ja=f"Hasu {index}",
                card_type="member",
                work_keys=["hasunosora"],
            ),
        )
    state.players["player_1"].live_result.revealed_instance_ids = list(revealed_ids)
    blocked = state.model_copy(deep=True)
    blocked.players["player_1"].live_result.revealed_instance_ids = revealed_ids[:-1]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )

    with pytest.raises(Exception, match="yell_revealed_member_work_count_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_yell_revealed_member_heart_colors_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-yell-nijigasaki-heart-colors:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="q" * 64,
        effect_index=1,
        label_ja="Nijigasaki revealed member Heart colors score",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_member_heart_colors_present": {
                "work_key": "nijigasaki",
                "color_slots": [
                    "heart01",
                    "heart02",
                    "heart03",
                    "heart04",
                    "heart05",
                    "heart06",
                ],
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    for index, color_slot in enumerate(
        ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06"],
        start=1,
    ):
        instance_id = f"revealed-niji-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-NIJI-{index}",
                card_id=f"TEST-NIJI-{index}",
                name_ja=f"Niji {index}",
                card_type="member",
                work_keys=["nijigasaki"],
                basic_hearts={color_slot: 1},
            ),
        )
        state.players["player_1"].live_result.revealed_instance_ids.append(
            instance_id
        )

    resolved = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [("score", 1)]

    missing_color = state.model_copy(deep=True)
    missing_color.cards["revealed-niji-6"].card.basic_hearts = {"heart05": 1}
    with pytest.raises(Exception, match="yell_revealed_member_heart_colors_missing"):
        _apply_direct(
            missing_color,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_yell_revealed_resolution_card_moves_to_deck_top_and_bottom():
    top_effect = EffectDefinition(
        effect_id="test-yell-card-top:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "move_selected_to_deck_top"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(top_effect)
    state.players["player_1"].resolution_area.append("deck-member-1")

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-member-1"],
        },
    )

    assert resolved.players["player_1"].main_deck[0] == "deck-member-1"
    assert "deck-member-1" not in resolved.players["player_1"].resolution_area
    assert not resolved.cards["deck-member-1"].face_up

    bottom_payload = top_effect.model_dump()
    bottom_payload.update(
        {
            "effect_id": "test-yell-live-bottom:1",
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "card_type": "live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_deck_bottom"}],
        }
    )
    bottom_effect = EffectDefinition.model_validate(bottom_payload)
    bottom_state = _minimal_effect_state(bottom_effect)
    bottom_state.players["player_1"].resolution_area.append("deck-live-1")

    bottom_resolved = _apply_direct(
        bottom_state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-live-1"],
        },
    )

    assert bottom_resolved.players["player_1"].main_deck[-1] == "deck-live-1"
    assert "deck-live-1" not in bottom_resolved.players["player_1"].resolution_area
    assert not bottom_resolved.cards["deck-live-1"].face_up


def test_yell_revealed_work_count_places_wait_energy():
    effect = EffectDefinition(
        effect_id="test-yell-liella-count-energy:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_work_count_at_least": {
                "work_key": "love_live_superstar",
                "count": 7,
            },
            "minimum_energy_deck_cards": 1,
        },
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "target": "self",
                "amount": 1,
                "orientation": "wait",
            }
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    liella_card = CardDefinition(
        card_code="LIELLA-MEMBER",
        card_id="LIELLA-MEMBER",
        name_ja="Liella test",
        card_type="member",
        work_keys=["love_live_superstar"],
    )
    for index in range(7):
        instance_id = f"revealed-liella-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=liella_card,
            face_up=True,
        )
        state.players["player_1"].resolution_area.append(instance_id)
        state.players["player_1"].live_result.revealed_instance_ids.append(instance_id)
    energy = CardDefinition(
        card_code="ENERGY",
        card_id="ENERGY",
        name_ja="Energy",
        card_type="energy",
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy,
    )
    state.players["player_1"].energy_deck.append("energy-1")

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.players["player_1"].energy_area == ["energy-1"]
    assert resolved.cards["energy-1"].orientation == "wait"


def test_named_stage_distinct_condition_recovers_yell_revealed_card():
    effect = EffectDefinition(
        effect_id="test-stage-names-yell-card:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_member_names_any_distinct_count_at_least": {
                "name_ja_any": ["澁谷かのん", "ウィーン・マルガレーテ", "鬼塚冬毬"],
                "count": 2,
            }
        },
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "move_selected_to_hand"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    for slot, name in [("left", "澁谷かのん"), ("center", "鬼塚冬毬")]:
        instance_id = f"stage-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"MEMBER-{slot}",
                card_id=f"MEMBER-{slot}",
                name_ja=name,
                card_type="member",
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id
    state.players["player_1"].resolution_area.append("deck-member-1")

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-member-1"],
        },
    )

    assert "deck-member-1" in resolved.players["player_1"].hand
    assert "deck-member-1" not in resolved.players["player_1"].resolution_area


def test_source_moved_this_turn_operation_condition_draws_extra_card():
    effect = EffectDefinition(
        effect_id="test-source-moved-extra-draw:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {
                "action_type": "draw_card",
                "amount": 1,
                "value": {"condition": {"source_moved_this_turn": True}},
            },
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-MEMBER",
            card_id="TEST-MEMBER",
            name_ja="source",
            card_type="member",
        ),
    )
    state.players["player_1"].member_area["center"] = "source-member"
    state.pending_effects[0].source_card_instance_id = "source-member"
    state.players["player_1"].member_areas_moved_this_turn = ["center"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.players["player_1"].hand == ["deck-live-1", "deck-member-1"]


def test_live_success_or_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-live-success-or-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "live_success_any_revealed_live2_stage_heart_variety5_or_member_moved": True
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.revealed_instance_ids = [
        "deck-live-1",
        "deck-live-2",
    ]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [("score", 1)]

    blocked = _minimal_effect_state(effect)
    blocked.players["player_1"].live_result.revealed_instance_ids = ["deck-member-1"]
    with pytest.raises(Exception, match="live_success_complex_score_condition_not_met"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_reveal_top_to_hand_non_blade_member_modifies_score():
    effect = EffectDefinition(
        effect_id="test-reveal-top-hand-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "reveal_top_to_hand", "amount": 1},
            {
                "action_type": "modify_score",
                "amount": 1,
                "value": {
                    "condition": {
                        "last_revealed_top_member_without_blade_heart": True
                    }
                },
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].main_deck = ["deck-member-1", "deck-live-1"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.players["player_1"].hand == ["deck-member-1"]
    assert resolved.cards["deck-member-1"].face_up
    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [("score", 1)]


def test_excess_heart_conditional_score_modifiers():
    effect = EffectDefinition(
        effect_id="test-excess-heart-plus-minus:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "modify_score",
                "amount": 1,
                "value": {"condition": {"own_excess_heart_count_at_most": 0}},
            },
            {
                "action_type": "modify_score",
                "amount": -1,
                "value": {"condition": {"own_excess_heart_count_at_least": 2}},
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    no_excess = _minimal_effect_state(effect)
    no_excess.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]

    plus = _apply_direct(
        no_excess,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert [(item.modifier_type, item.amount) for item in plus.players["player_1"].manual_modifiers] == [
        ("score", 1)
    ]

    excess = _minimal_effect_state(effect)
    excess.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 2}, "remaining_all_color_hearts": 0}
    ]
    minus = _apply_direct(
        excess,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert [(item.modifier_type, item.amount) for item in minus.players["player_1"].manual_modifiers] == [
        ("score", -1)
    ]


def test_source_attached_energy_count_places_wait_energy():
    effect = EffectDefinition(
        effect_id="test-source-attached-energy-place:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "live_score_relation": "greater_than_opponent",
            "minimum_energy_deck_cards": 1,
        },
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "amount_source": "source_attached_energy_count_plus",
                "value": {"add": 1},
                "target": "self",
                "orientation": "wait",
            }
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.total_score = 3
    state.players["player_2"].live_result.total_score = 1
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-MEMBER",
            card_id="TEST-MEMBER",
            name_ja="source",
            card_type="member",
        ),
    )
    state.players["player_1"].member_area["center"] = "source-member"
    state.pending_effects[0].source_card_instance_id = "source-member"
    energy = CardDefinition(
        card_code="ENERGY",
        card_id="ENERGY",
        name_ja="Energy",
        card_type="energy",
    )
    for instance_id in ["attached-energy", "energy-1", "energy-2"]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=energy,
        )
    state.players["player_1"].member_area_attachments["center"] = ["attached-energy"]
    state.players["player_1"].energy_deck = ["energy-1", "energy-2"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.players["player_1"].energy_area == ["energy-1", "energy-2"]
    assert all(resolved.cards[item].orientation == "wait" for item in ["energy-1", "energy-2"])


def test_optional_place_wait_energy_draws_for_opponent():
    effect = EffectDefinition(
        effect_id="test-place-energy-opponent-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={"minimum_energy_deck_cards": 1},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "target": "self",
                "amount": 1,
                "orientation": "wait",
            },
            {"action_type": "draw_card", "target": "opponent", "amount": 1},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    energy = CardDefinition(
        card_code="ENERGY",
        card_id="ENERGY",
        name_ja="Energy",
        card_type="energy",
    )
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=energy,
    )
    state.players["player_1"].energy_deck = ["energy-1"]
    state.cards["opponent-draw"] = state.cards["deck-live-1"].model_copy(
        deep=True,
        update={"instance_id": "opponent-draw", "owner_id": "player_2"},
    )
    state.players["player_2"].main_deck = ["opponent-draw"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "accepted": True},
    )

    assert resolved.players["player_1"].energy_area == ["energy-1"]
    assert resolved.cards["energy-1"].orientation == "wait"
    assert resolved.players["player_2"].hand == ["opponent-draw"]


def test_live_start_gain_blade_counts_two_cards_per_hand_pair():
    effect = EffectDefinition(
        effect_id="test-hand-pair-blade:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="b" * 64,
        effect_index=1,
        label_ja="hand count Blade test",
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
                "action_type": "gain_blade",
                "amount_source": "own_hand_count_divided_by",
                "value": {"divisor": 2},
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    hand_ids = [f"hand-card-{index}" for index in range(5)]
    for instance_id in hand_ids:
        state.cards[instance_id] = state.cards["deck-member-1"].model_copy(
            deep=True,
            update={"instance_id": instance_id},
        )
    state.players["player_1"].hand = hand_ids

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert [
        (modifier.modifier_type, modifier.amount, modifier.target_card_instance_id)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [("blade", 2, "source-live")]


def test_operation_condition_can_gate_success_live_work_extra_draw():
    effect = EffectDefinition(
        effect_id="test-success-love-live-extra-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="d" * 64,
        effect_index=1,
        label_ja="success live extra draw test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {
                "action_type": "draw_card",
                "amount": 1,
                "value": {
                    "condition": {
                        "success_live_work_count_at_least": {
                            "work_key": "love_live",
                            "count": 1,
                        }
                    }
                },
            },
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.cards["source-live"].card.work_keys = ["love_live"]
    with_success = state.model_copy(deep=True)
    with_success.players["player_1"].success_live_area = ["source-live"]

    without_success = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    with_success = _apply_direct(
        with_success,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert without_success.players["player_1"].hand == ["deck-live-1"]
    assert with_success.players["player_1"].hand == ["deck-live-1", "deck-member-1"]


def test_no_excess_heart_condition_modifies_score_only_without_remaining_heart():
    effect = EffectDefinition(
        effect_id="test-no-excess-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="r" * 64,
        effect_index=1,
        label_ja="no excess Heart score test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_excess_heart_count_at_most": 0},
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]
    excess = state.model_copy(deep=True)
    excess.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 1}, "remaining_all_color_hearts": 0}
    ]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )
    with pytest.raises(Exception, match="excess_heart_count_too_high"):
        _apply_direct(
            excess,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_excess_heart_color_condition_controls_draw():
    effect = EffectDefinition(
        effect_id="test-excess-heart01-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="x" * 64,
        effect_index=1,
        label_ja="excess heart01 draw test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_excess_heart_color_count_at_least": {
                "color_slot": "heart01",
                "count": 1,
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 1}, "remaining_all_color_hearts": 0}
    ]
    wrong_color = state.model_copy(deep=True)
    wrong_color.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart04": 1}, "remaining_all_color_hearts": 0}
    ]

    with pytest.raises(Exception, match="excess_heart_color_count_too_low"):
        _apply_direct(
            wrong_color,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert resolved.players["player_1"].hand == ["deck-live-1"]


def test_wait_stage_member_count_amount_source_modifies_score():
    effect = EffectDefinition(
        effect_id="test-wait-stage-member-count-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="z" * 64,
        effect_index=1,
        label_ja="wait stage member count score test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "modify_score",
                "amount_source": "own_wait_stage_member_count",
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    for index, slot in enumerate(["left", "right"], start=1):
        instance_id = f"wait-member-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-WAIT-MEMBER-{index}",
                card_id=f"TEST-WAIT-MEMBER-{index}",
                name_ja=f"ウェイトメンバー{index}",
                card_type="member",
                blade=1,
                basic_hearts={"heart01": 1},
            ),
            orientation="wait",
        )
        state.players["player_1"].member_area[slot] = instance_id

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 2
        for modifier in resolved.players["player_1"].manual_modifiers
    )


def test_extra_heart_stage_member_condition_controls_draw():
    effect = EffectDefinition(
        effect_id="test-extra-heart-stage-member-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="0" * 64,
        effect_index=1,
        label_ja="extra heart stage member draw test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_member_more_than_original_heart_count_at_least": {"count": 1}
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.cards["stage-member"] = CardInstance(
        instance_id="stage-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-HEART-MEMBER",
            card_id="TEST-HEART-MEMBER",
            name_ja="ハートメンバー",
            card_type="member",
            blade=1,
            basic_hearts={"heart01": 1},
        ),
    )
    state.players["player_1"].member_area["center"] = "stage-member"
    boosted = state.model_copy(deep=True)
    boosted.players["player_1"].manual_modifiers.append(
        ManualModifier(
            modifier_id="test-heart-plus",
            modifier_type="heart",
            amount=1,
            color_slot="heart02",
            target_card_instance_id="stage-member",
            duration="live",
            created_turn=state.turn_number,
        )
    )

    with pytest.raises(Exception, match="stage_member_more_than_original_heart_count_too_low"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        boosted,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert resolved.players["player_1"].hand == ["deck-live-1"]


def test_clear_excess_heart_operation_consumes_remaining_heart_then_scores():
    effect = EffectDefinition(
        effect_id="test-clear-excess-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="u" * 64,
        effect_index=1,
        label_ja="clear excess Heart score test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_excess_heart_count_at_least": 3},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "clear_excess_hearts"},
            {"action_type": "modify_score", "amount": 1},
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.live_allocations = [
        {
            "remaining_hearts": {"heart01": 2},
            "remaining_all_color_hearts": 1,
        }
    ]
    low_excess = state.model_copy(deep=True)
    low_excess.players["player_1"].live_result.live_allocations = [
        {
            "remaining_hearts": {"heart01": 1},
            "remaining_all_color_hearts": 1,
        }
    ]

    with pytest.raises(Exception, match="excess_heart_count_too_low"):
        _apply_direct(
            low_excess,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    allocation = resolved.players["player_1"].live_result.live_allocations[-1]
    assert allocation["remaining_hearts"] == {}
    assert allocation["remaining_all_color_hearts"] == 0
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )


def test_excess_heart_color_and_stage_work_condition_places_wait_energy():
    effect = EffectDefinition(
        effect_id="test-excess-heart04-nijigasaki-energy:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="y" * 64,
        effect_index=1,
        label_ja="excess heart04 nijigasaki wait energy test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_excess_heart_color_count_at_least": {
                "color_slot": "heart04",
                "count": 1,
            },
            "own_stage_member_work_count_at_least": {
                "work_key": "nijigasaki",
                "count": 1,
            },
            "minimum_energy_deck_cards": 1,
        },
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "target": "self",
                "amount": 1,
                "orientation": "wait",
            }
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.cards["stage-member"] = CardInstance(
        instance_id="stage-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-NIJIGASAKI-MEMBER",
            card_id="TEST-NIJIGASAKI-MEMBER",
            name_ja="虹ヶ咲メンバー",
            card_type="member",
            work_keys=["nijigasaki"],
            blade=1,
            basic_hearts={"heart01": 1},
        ),
    )
    state.players["player_1"].member_area["center"] = "stage-member"
    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart04": 1}, "remaining_all_color_hearts": 0}
    ]
    state.cards["energy-1"] = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-ENERGY",
            card_id="TEST-ENERGY",
            name_ja="テストエネルギー",
            card_type="energy",
        ),
    )
    state.players["player_1"].energy_deck = ["energy-1"]
    no_stage = state.model_copy(deep=True)
    no_stage.cards["stage-member"].card.work_keys = []

    with pytest.raises(Exception, match="stage_member_work_count_too_low"):
        _apply_direct(
            no_stage,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert resolved.players["player_1"].energy_deck == []
    assert resolved.players["player_1"].energy_area == ["energy-1"]
    assert resolved.cards["energy-1"].orientation == "wait"


def test_clear_opponent_excess_heart_count_can_gate_score_modifier():
    effect = EffectDefinition(
        effect_id="test-clear-opponent-excess-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="w" * 64,
        effect_index=1,
        label_ja="clear opponent excess Heart score test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "clear_excess_hearts", "target": "opponent"},
            {
                "action_type": "modify_score",
                "amount": 1,
                "value": {
                    "condition": {"last_cleared_excess_heart_count_at_least": 2}
                },
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 1}, "remaining_all_color_hearts": 1}
    ]
    low_excess = state.model_copy(deep=True)
    low_excess.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 1}, "remaining_all_color_hearts": 0}
    ]

    low_resolved = _apply_direct(
        low_excess,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    low_allocation = low_resolved.players["player_2"].live_result.live_allocations[-1]
    allocation = resolved.players["player_2"].live_result.live_allocations[-1]
    assert low_allocation["remaining_hearts"] == {}
    assert low_allocation["remaining_all_color_hearts"] == 0
    assert allocation["remaining_hearts"] == {}
    assert allocation["remaining_all_color_hearts"] == 0
    assert not any(
        modifier.modifier_type == "score"
        for modifier in low_resolved.players["player_1"].manual_modifiers
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
        )


def test_yell_revealed_card_count_less_than_opponent_controls_draw():
    effect = EffectDefinition(
        effect_id="test-yell-revealed-count-less-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="1" * 64,
        effect_index=1,
        label_ja="fewer yell revealed cards draw test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"yell_revealed_card_count_less_than_opponent": True},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    for instance_id, owner_id in [
        ("own-revealed", "player_1"),
        ("opp-revealed-1", "player_2"),
        ("opp-revealed-2", "player_2"),
    ]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id=owner_id,
            card=state.cards["live-1"].card.model_copy(deep=True),
        )
    state.players["player_1"].live_result.revealed_instance_ids = ["own-revealed"]
    state.players["player_2"].live_result.revealed_instance_ids = [
        "opp-revealed-1",
        "opp-revealed-2",
    ]
    blocked = state.model_copy(deep=True)
    blocked.players["player_1"].live_result.revealed_instance_ids.append(
        "deck-live-1"
    )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert resolved.players["player_1"].hand == ["deck-live-1"]
    with pytest.raises(
        Exception, match="yell_revealed_card_count_not_less_than_opponent"
    ):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_live_success_revealed_card_choices_filter_by_score_cost_and_work():
    equal_score_effect = EffectDefinition(
        effect_id="test-equal-score-cost9-member:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="2" * 64,
        effect_index=1,
        label_ja="equal score cost9 member test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"live_score_relation": "equal_to_opponent"},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "card_type": "member",
            "minimum_cost": 9,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "move_selected_to_hand"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(equal_score_effect)
    state.players["player_1"].live_result.total_score = 3
    state.players["player_2"].live_result.total_score = 3
    for instance_id, cost in [("low-member", 8), ("high-member", 9)]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{instance_id}",
                card_id=f"TEST-{instance_id}",
                name_ja=instance_id,
                card_type="member",
                cost=cost,
                blade=1,
                basic_hearts={"heart01": 1},
            ),
        )
    state.players["player_1"].resolution_area = ["low-member", "high-member"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["high-member"]
    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["high-member"],
        },
    )
    assert "high-member" in resolved.players["player_1"].hand
    assert "low-member" in resolved.players["player_1"].resolution_area

    work_payload = equal_score_effect.model_dump(mode="python")
    work_payload.update(
        {
            "effect_id": "test-higher-score-nijigasaki:1",
            "condition": {"live_score_relation": "greater_than_opponent"},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
        },
    )
    work_effect = EffectDefinition.model_validate(work_payload)
    work_state = _minimal_effect_state(work_effect)
    work_state.players["player_1"].live_result.total_score = 4
    work_state.players["player_2"].live_result.total_score = 3
    for instance_id, work_keys in [
        ("other-card", ["love_live"]),
        ("nijigasaki-card", ["nijigasaki"]),
    ]:
        work_state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{instance_id}",
                card_id=f"TEST-{instance_id}",
                name_ja=instance_id,
                card_type="member",
                work_keys=work_keys,
                blade=1,
                basic_hearts={"heart01": 1},
            ),
        )
    work_state.players["player_1"].resolution_area = [
        "other-card",
        "nijigasaki-card",
    ]
    options = generate_legal_actions(work_state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["nijigasaki-card"]


def test_live_success_discard_cost_recovers_cost2_member_or_score2_live():
    effect = EffectDefinition(
        effect_id="test-discard-revealed-cost2-or-score2:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="discard then recover revealed cost2 member or score2 live",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={},
        cost=[{"action_type": "discard_from_hand"}],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        choice={
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "minimum": 1,
            "maximum": 1,
            "value": {
                "card_type_stat_filters": [
                    {"card_type": "member", "maximum_cost": 2},
                    {"card_type": "live", "maximum_score": 2},
                ]
            },
        },
        actions=[{"action_type": "move_selected_to_hand"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    discard = "discard-card"
    state.cards[discard] = CardInstance(
        instance_id=discard,
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-DISCARD",
            card_id="TEST-DISCARD",
            name_ja="discard",
            card_type="member",
        ),
    )
    state.players["player_1"].hand.append(discard)
    revealed_cards = {
        "cost2-member": CardDefinition(
            card_code="TEST-COST2",
            card_id="TEST-COST2",
            name_ja="cost2",
            card_type="member",
            cost=2,
        ),
        "cost3-member": CardDefinition(
            card_code="TEST-COST3",
            card_id="TEST-COST3",
            name_ja="cost3",
            card_type="member",
            cost=3,
        ),
        "score2-live": CardDefinition(
            card_code="TEST-SCORE2",
            card_id="TEST-SCORE2",
            name_ja="score2",
            card_type="live",
            score=2,
        ),
        "score3-live": CardDefinition(
            card_code="TEST-SCORE3",
            card_id="TEST-SCORE3",
            name_ja="score3",
            card_type="live",
            score=3,
        ),
    }
    for instance_id, card in revealed_cards.items():
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=card,
            face_up=True,
        )
    state.players["player_1"].resolution_area = list(revealed_cards)

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["cost_choice"]["zone"] == "hand"
    assert discard in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "accepted": True,
            "selected_card_instance_ids": [discard],
        },
    )
    assert discard in state.players["player_1"].waiting_room
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["cost2-member", "score2-live"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["score2-live"],
        },
    )
    assert "score2-live" in state.players["player_1"].hand
    assert "score2-live" not in state.players["player_1"].resolution_area
    assert "cost3-member" in state.players["player_1"].resolution_area
    assert "score3-live" in state.players["player_1"].resolution_area


def test_excess_heart_draw2_discard1_uses_post_action_hand_choice():
    effect = EffectDefinition(
        effect_id="test-excess-heart-draw2-discard1:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="3" * 64,
        effect_index=1,
        label_ja="excess heart draw2 discard1 test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_excess_heart_count_at_least": 1},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card", "amount": 2},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 1}, "remaining_all_color_hearts": 0}
    ]
    blocked = state.model_copy(deep=True)
    blocked.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]

    with pytest.raises(Exception, match="excess_heart_count_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.pending_effects[0].resolution_stage == "after_cost"
    assert state.players["player_1"].hand == ["deck-live-1", "deck-member-1"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-member-1"],
        },
    )
    assert "deck-member-1" in state.players["player_1"].waiting_room
    assert state.players["player_1"].hand == ["deck-live-1"]


def test_yell_revealed_member_without_blade_heart_draws_then_discards():
    effect = EffectDefinition(
        effect_id="test-revealed-muse-without-blade-heart:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="3" * 64,
        effect_index=1,
        label_ja="revealed muse member without Blade Heart draw discard",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_member_without_blade_heart_count_at_least": {
                "work_key": "love_live",
                "count": 1,
            }
        },
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.cards["revealed-muse"] = CardInstance(
        instance_id="revealed-muse",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-MUSE",
            card_id="TEST-MUSE",
            name_ja="Muse Member",
            card_type="member",
            work_keys=["love_live"],
        ),
    )
    state.players["player_1"].live_result.revealed_instance_ids = ["revealed-muse"]

    blocked = state.model_copy(deep=True)
    blocked.cards["revealed-muse"].card.blade_heart_color_slot = "heart01"
    with pytest.raises(
        Exception,
        match="yell_revealed_member_without_blade_heart_count_too_low",
    ):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.pending_effects[0].resolution_stage == "after_cost"
    assert state.players["player_1"].hand == ["deck-live-1"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-live-1"],
        },
    )
    assert "deck-live-1" in state.players["player_1"].waiting_room
    assert not state.players["player_1"].hand


def test_source_score_exact_condition_returns_waiting_room_work_card():
    effect = EffectDefinition(
        effect_id="test-source-score3-return-work:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="4" * 64,
        effect_index=1,
        label_ja="source score return work test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"source_score_exact": 3},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "work_key": "nijigasaki",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.cards["source-live"].card.score = 3
    state.cards["target-card"] = CardInstance(
        instance_id="target-card",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-NIJIGASAKI",
            card_id="TEST-NIJIGASAKI",
            name_ja="虹ヶ咲カード",
            card_type="member",
            work_keys=["nijigasaki"],
            blade=1,
            basic_hearts={"heart01": 1},
        ),
    )
    state.players["player_1"].waiting_room = ["target-card"]
    blocked = state.model_copy(deep=True)
    blocked.cards["source-live"].card.score = 2

    with pytest.raises(Exception, match="source_score_mismatch"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["target-card"],
            },
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["target-card"],
        },
    )
    assert "target-card" in resolved.players["player_1"].hand


def test_other_stage_member_condition_waits_source_member():
    effect = EffectDefinition(
        effect_id="test-other-stage-member-wait-source:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="5" * 64,
        effect_index=1,
        label_ja="other stage member wait source test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "source_orientation": "active",
            "own_stage_member_count_at_least": 2,
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "apply_wait"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="source member",
        card_type="member",
        blade=1,
        basic_hearts={"heart01": 1},
    )
    state.cards["source-live"].card = member
    state.players["player_1"].member_area["center"] = "source-live"
    state.cards["other-member"] = CardInstance(
        instance_id="other-member",
        owner_id="player_1",
        card=member.model_copy(update={"card_code": "TEST-OTHER"}),
    )
    state.players["player_1"].member_area["left"] = "other-member"
    blocked = state.model_copy(deep=True)
    blocked.players["player_1"].member_area["left"] = None

    with pytest.raises(Exception, match="stage_member_count_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert resolved.cards["source-live"].orientation == "wait"


def test_bibi_distinct_stage_condition_returns_bibi_member():
    effect = EffectDefinition(
        effect_id="test-bibi-distinct-return:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="6" * 64,
        effect_index=1,
        label_ja="bibi distinct return test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_member_unit_distinct_name_count_at_least": {
                "unit_key": "bibi",
                "count": 2,
            }
        },
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "member",
            "unit_key": "bibi",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    for slot, name in [("left", "絢瀬絵里"), ("right", "西木野真姫")]:
        instance_id = f"bibi-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-BIBI-{slot}",
                card_id=f"TEST-BIBI-{slot}",
                name_ja=name,
                card_type="member",
                unit_keys=["bibi"],
                blade=1,
                basic_hearts={"heart01": 1},
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id
    state.cards["waiting-bibi"] = CardInstance(
        instance_id="waiting-bibi",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-WAITING-BIBI",
            card_id="TEST-WAITING-BIBI",
            name_ja="矢澤にこ",
            card_type="member",
            unit_keys=["bibi"],
            blade=1,
            basic_hearts={"heart01": 1},
        ),
    )
    state.players["player_1"].waiting_room = ["waiting-bibi"]
    blocked = state.model_copy(deep=True)
    blocked.cards["bibi-right"].card.name_ja = "絢瀬絵里"

    with pytest.raises(Exception, match="stage_unit_distinct_name_count_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["waiting-bibi"],
            },
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["waiting-bibi"],
        },
    )
    assert "waiting-bibi" in resolved.players["player_1"].hand


def test_source_blade_condition_draw2_discard1_uses_post_action_choice():
    effect = EffectDefinition(
        effect_id="test-source-blade8-draw2-discard1:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="7" * 64,
        effect_index=1,
        label_ja="source blade draw2 discard1 test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"source_blade_at_least": 8},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card", "amount": 2},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    state.cards["source-live"].card = CardDefinition(
        card_code="TEST-BLADE-MEMBER",
        card_id="TEST-BLADE-MEMBER",
        name_ja="blade member",
        card_type="member",
        blade=8,
        basic_hearts={"heart01": 1},
    )
    blocked = state.model_copy(deep=True)
    blocked.cards["source-live"].card.blade = 7

    with pytest.raises(Exception, match="source_blade_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.pending_effects[0].resolution_stage == "after_cost"
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["deck-live-1"],
        },
    )
    assert "deck-live-1" in state.players["player_1"].waiting_room


def test_waiting_room_work_count_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-waiting-work25-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="8" * 64,
        effect_index=1,
        label_ja="waiting work count score test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "waiting_room_work_count_at_least": {
                "work_key": "love_live",
                "count": 25,
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    waiting_ids: list[str] = []
    for index in range(25):
        instance_id = f"waiting-muse-{index}"
        waiting_ids.append(instance_id)
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-MUSE-{index}",
                card_id=f"TEST-MUSE-{index}",
                name_ja=f"μ's {index}",
                card_type="member",
                work_keys=["love_live"],
                blade=1,
                basic_hearts={"heart01": 1},
            ),
        )
    state.players["player_1"].waiting_room = waiting_ids
    blocked = state.model_copy(deep=True)
    blocked.players["player_1"].waiting_room = waiting_ids[:-1]

    with pytest.raises(Exception, match="waiting_room_work_count_too_low"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )


def test_stage_total_heart_more_than_opponent_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-stage-heart-more-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="9" * 64,
        effect_index=1,
        label_ja="stage total heart more score test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_total_heart_more_than_opponent": True},
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    for player_id, instance_id, hearts in [
        ("player_1", "own-heart-member", {"heart01": 2}),
        ("player_2", "opp-heart-member", {"heart01": 1}),
    ]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id=player_id,
            card=CardDefinition(
                card_code=f"TEST-{instance_id}",
                card_id=f"TEST-{instance_id}",
                name_ja=instance_id,
                card_type="member",
                blade=1,
                basic_hearts=hearts,
            ),
        )
        state.players[player_id].member_area["center"] = instance_id
    blocked = state.model_copy(deep=True)
    blocked.cards["opp-heart-member"].card.basic_hearts = {"heart01": 2}

    with pytest.raises(
        Exception, match="stage_total_heart_count_not_higher_than_opponent"
    ):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )


def test_live_success_can_take_yell_revealed_members_when_any_success_count2():
    effect = EffectDefinition(
        effect_id="test-yell-revealed-members-to-hand:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="v" * 64,
        effect_index=1,
        label_ja="yell revealed members to hand test",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"any_success_live_count_at_least": 2},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "card_type": "member",
            "minimum": 0,
            "maximum": 2,
        },
        actions=[{"action_type": "move_selected_to_hand"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    member = CardDefinition(
        card_code="TEST-MEMBER-REVEALED",
        card_id="TEST-MEMBER-REVEALED",
        name_ja="公開メンバー",
        card_type="member",
    )
    live = state.cards["live-1"].card
    for instance_id in ("revealed-member-1", "revealed-member-2", "revealed-live"):
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=member if "member" in instance_id else live.model_copy(deep=True),
        )
        state.players["player_1"].resolution_area.append(instance_id)
    state.players["player_1"].live_result.revealed_instance_ids = [
        "revealed-member-1",
        "revealed-member-2",
        "revealed-live",
    ]
    low_success = state.model_copy(deep=True)
    for instance_id in ("opp-success-1", "opp-success-2"):
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=live.model_copy(deep=True),
        )
        state.players["player_2"].success_live_area.append(instance_id)

    with pytest.raises(Exception, match="any_success_live_count_too_low"):
        _apply_direct(
            low_success,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == [
        "revealed-member-1",
        "revealed-member-2",
    ]
    assert "revealed-live" not in options["candidate_card_instance_ids"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": [
                "revealed-member-1",
                "revealed-member-2",
            ],
        },
    )

    player = resolved.players["player_1"]
    assert player.hand[-2:] == ["revealed-member-1", "revealed-member-2"]
    assert "revealed-member-1" not in player.resolution_area
    assert "revealed-member-2" not in player.resolution_area
    assert "revealed-live" in player.resolution_area


def test_stage_member_choice_can_filter_by_effective_blade_count():
    effect = EffectDefinition(
        effect_id="test-minimum-blade-choice:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="s" * 64,
        effect_index=1,
        label_ja="minimum Blade choice test",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "card_type": "member",
            "work_key": "love_live_sunshine",
            "minimum_blade": 6,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    high_member = CardDefinition(
        card_code="TEST-HIGH-BLADE-AQOURS",
        card_id="TEST-HIGH-BLADE-AQOURS",
        name_ja="high Blade Aqours",
        card_type="member",
        blade=6,
        work_keys=["love_live_sunshine"],
    )
    low_member = CardDefinition(
        card_code="TEST-LOW-BLADE-AQOURS",
        card_id="TEST-LOW-BLADE-AQOURS",
        name_ja="low Blade Aqours",
        card_type="member",
        blade=5,
        work_keys=["love_live_sunshine"],
    )
    state.cards["high-blade-member"] = CardInstance(
        instance_id="high-blade-member",
        owner_id="player_1",
        card=high_member,
    )
    state.cards["low-blade-member"] = CardInstance(
        instance_id="low-blade-member",
        owner_id="player_1",
        card=low_member,
    )
    state.players["player_1"].member_area["left"] = "low-blade-member"
    state.players["player_1"].member_area["center"] = "high-blade-member"

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["high-blade-member"]

    with pytest.raises(Exception, match="effect card selection is not legal"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["low-blade-member"],
            },
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["high-blade-member"],
        },
    )

    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )


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
    player.member_areas_moved_this_turn = ["left", "right"]

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


def test_live_start_member_entered_count_condition_modifies_score():
    effect = EffectDefinition(
        effect_id="test-member-entered-count-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="m" * 64,
        effect_index=1,
        label_ja="member entered twice score",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_member_entered_count_this_turn_at_least": 2},
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].member_entered_count_this_turn = 1
    with pytest.raises(Exception, match="member_entered_count_this_turn_too_low"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state.players["player_1"].member_entered_count_this_turn = 2
    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in resolved.players["player_1"].manual_modifiers
    ] == [("score", 1)]


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
    player.member_areas_moved_this_turn = ["left", "right"]

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


def test_onplay_named_stage_ready_energy_then_returns_hasu_live():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-hasu-ready-return-live:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "h" * 64,
            "effect_index": 1,
            "label_ja": "named Hasunosora ready and return test",
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {
                "own_stage_member_name_any": ["大沢瑠璃乃", "百生吟子", "徒町小鈴"]
            },
            "cost": [],
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "hasunosora",
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "ready_energy", "target": "auto", "amount": 1},
                {"action_type": "return_from_waiting_room"},
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state = _minimal_effect_state(effect)
    player = state.players["player_1"]
    state.cards["source-live"].card = CardDefinition(
        card_code="TEST-RURINO",
        card_id="TEST-RURINO",
        name_ja="大沢瑠璃乃",
        card_type="member",
        work_keys=["hasunosora"],
    )
    player.member_area["center"] = "source-live"
    state.cards["wait-energy"] = CardInstance(
        instance_id="wait-energy",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-ENERGY",
            card_id="TEST-ENERGY",
            name_ja="テストエネルギー",
            card_type="energy",
        ),
        orientation="wait",
    )
    player.energy_area = ["wait-energy"]
    state.cards["hasu-live"] = CardInstance(
        instance_id="hasu-live",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-HASU-LIVE",
            card_id="TEST-HASU-LIVE",
            name_ja="蓮ノ空ライブ",
            card_type="live",
            work_keys=["hasunosora"],
        ),
    )
    player.waiting_room = ["hasu-live"]

    legal = generate_legal_actions(state)
    initial_options = legal[0].options["invocations"][0]
    assert initial_options["candidate_card_instance_ids"] == []
    with pytest.raises(Exception, match="accepts card selections after its first step"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["hasu-live"],
            },
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.cards["wait-energy"].orientation == "active"
    assert state.pending_effects[0].resolution_stage == "after_cost"
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["hasu-live"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["hasu-live"],
        },
    )

    assert "hasu-live" in state.players["player_1"].hand
    assert not state.pending_effects


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
        first_player_id="player_1",
    )
    match_id = created.state.match_id
    state = created.state
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
    assert event["data"]["revealed_cards"][0]["instance_id"] == selected
    assert event["data"]["revealed_cards"][0]["name_ja"] == (
        state.cards[selected].card.name_ja
    )


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

    result = apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect_choice",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"selected_card_instance_ids": [valid]},
        ),
    )
    state = result.state
    assert valid in state.players["player_1"].hand
    assert invalid in state.players["player_1"].waiting_room
    resolved_event = next(
        event for event in result.events if event.event_type == "effect_resolved"
    )
    assert resolved_event.data["reveal_selected_to_opponent"] is True
    assert resolved_event.data["revealed_cards"] == [
        {
            "instance_id": valid,
            "owner_id": "player_1",
            "card_code": state.cards[valid].card.card_code,
            "card_id": state.cards[valid].card.card_id,
            "name_ja": state.cards[valid].card.name_ja,
            "card_type": state.cards[valid].card.card_type,
            "image_url": state.cards[valid].card.image_url,
        }
    ]


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


def test_onplay_branch_choice_can_grant_aqours_blade_or_position_saint_snow():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-aqours-saint-snow-branch:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "s" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】以下から1つを選ぶ。 "
                "・自分のステージにいるこのメンバー以外の『Aqours』の"
                "メンバー1人は、ライブ終了時まで、【ブレード】を得る。 "
                "・自分のステージにいる『Saint Snow』のメンバー1人を"
                "ポジションチェンジさせる。"
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
                "branch_ids": ["aqours_blade", "saint_snow_position_change"],
                "branch_selection_minimum": {
                    "aqours_blade": 1,
                    "saint_snow_position_change": 1,
                },
                "branch_selection_maximum": {
                    "aqours_blade": 1,
                    "saint_snow_position_change": 1,
                },
                "branch_choice_filters": {
                    "aqours_blade": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "card_type": "member",
                        "work_key": "love_live_sunshine",
                        "target_player": "self",
                        "exclude_source": True,
                    },
                    "saint_snow_position_change": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "card_type": "member",
                        "unit_key": "saint_snow",
                        "target_player": "self",
                    },
                },
            },
            "actions": [
                {
                    "action_type": "gain_blade",
                    "target": "selected",
                    "amount": 1,
                    "branch": "aqours_blade",
                },
                {
                    "action_type": "position_change_selected",
                    "branch": "saint_snow_position_change",
                },
            ],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )

    def setup_state() -> MatchState:
        state = _minimal_effect_state(effect)
        source_card = CardDefinition(
            card_code="TEST-SOURCE-AQOURS",
            card_id="TEST-SOURCE-AQOURS",
            name_ja="渡辺曜",
            card_type="member",
            work_keys=["love_live_sunshine"],
            unit_keys=["aqours"],
        )
        aqours_card = source_card.model_copy(
            update={
                "card_code": "TEST-OTHER-AQOURS",
                "card_id": "TEST-OTHER-AQOURS",
                "name_ja": "高海千歌",
            }
        )
        saint_snow_card = CardDefinition(
            card_code="TEST-SAINT-SNOW",
            card_id="TEST-SAINT-SNOW",
            name_ja="鹿角聖良",
            card_type="member",
            unit_keys=["saint_snow"],
        )
        state.cards["source-live"].card = source_card
        state.cards["aqours-target"] = CardInstance(
            instance_id="aqours-target",
            owner_id="player_1",
            card=aqours_card,
        )
        state.cards["saint-snow-target"] = CardInstance(
            instance_id="saint-snow-target",
            owner_id="player_1",
            card=saint_snow_card,
        )
        state.players["player_1"].member_area = {
            "left": "source-live",
            "center": "aqours-target",
            "right": "saint-snow-target",
        }
        return state

    state = setup_state()
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == [
        "aqours_blade",
        "saint_snow_position_change",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_branch": "aqours_blade"},
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["aqours-target"]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["aqours-target"],
        },
    )
    assert [
        (
            modifier.modifier_type,
            modifier.amount,
            modifier.target_card_instance_id,
        )
        for modifier in state.players["player_1"].manual_modifiers
    ] == [("blade", 1, "aqours-target")]
    assert not state.pending_effects

    state = setup_state()
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "saint_snow_position_change",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["saint-snow-target"]
    assert options["position_change_slots_by_candidate"] == {
        "saint-snow-target": ["left", "center"]
    }
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["saint-snow-target"],
            "to_slot": "left",
        },
    )
    assert state.players["player_1"].member_area == {
        "left": "saint-snow-target",
        "center": "aqours-target",
        "right": "source-live",
    }
    assert not state.pending_effects


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


def test_live_start_choose_count_energy_payment_uses_selected_count():
    effect = EffectDefinition(
        effect_id="test-pay-selected-count-blade:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="c" * 64,
        effect_index=1,
        label_ja="pay up to two Energy for Blade",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={},
        cost=[{"action_type": "pay_energy", "amount_source": "selected_count"}],
        choice={"choice_type": "choose_count", "minimum": 1, "maximum": 2},
        actions=[{"action_type": "gain_blade", "amount_source": "selected_count"}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
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
        card=energy_card.model_copy(deep=True),
        orientation="active",
    )
    state.players["player_1"].energy_area = ["energy-1", "energy-2"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "choose_count"
    assert options["energy_required_source"] == "selected_count"
    assert options["energy_instance_ids"] == ["energy-1", "energy-2"]

    with pytest.raises(Exception, match="requires exactly 2 Active Energy"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_count": 2,
                "energy_instance_ids": ["energy-1"],
            },
        )
    assert state.cards["energy-1"].orientation == "active"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "accepted": True,
            "selected_count": 2,
            "energy_instance_ids": ["energy-1", "energy-2"],
        },
    )

    assert state.cards["energy-1"].orientation == "wait"
    assert state.cards["energy-2"].orientation == "wait"
    modifier = next(
        item
        for item in state.players["player_1"].manual_modifiers
        if item.modifier_type == "blade"
    )
    assert modifier.amount == 2
    assert modifier.target_card_instance_id == "source-live"


def test_live_start_choose_number_reveal_top_compares_member_cost():
    effect = EffectDefinition(
        effect_id="test-choose-number-reveal:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="n" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】数1つを選ぶ。自分のデッキの一番上のカードを公開する。"
            "公開したカードがメンバーカードで、かつコストが選んだ数以上の場合、"
            "公開したカードを手札に加える。選んだ数以下の場合、ライブ終了時まで、"
            "【ブレード】【ブレード】を得る。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={"choice_type": "choose_count", "minimum": 0, "maximum": 10},
        actions=[
            {
                "action_type": "reveal_top_matching_to_hand_else_deck_top",
                "amount": 1,
                "card_type": "member",
                "value": {"minimum_cost_source": "selected_count"},
            },
            {
                "action_type": "gain_blade",
                "amount": 2,
                "value": {
                    "condition": {
                        "last_revealed_top_member_cost_at_most_selected_count": True
                    }
                },
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="テストソース",
        card_type="member",
    )

    high_cost_state = _minimal_effect_state(effect)
    high_cost_state.cards["source-live"].card = source_member
    high_cost_state.players["player_1"].member_area["center"] = "source-live"
    high_cost_state.cards["deck-member-1"].card = high_cost_state.cards[
        "deck-member-1"
    ].card.model_copy(update={"cost": 7})
    high_cost_state.players["player_1"].main_deck = ["deck-member-1", "deck-live-1"]

    high_cost_state = _apply_direct(
        high_cost_state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_count": 5},
    )

    assert "deck-member-1" in high_cost_state.players["player_1"].hand
    assert high_cost_state.players["player_1"].main_deck == ["deck-live-1"]
    assert not high_cost_state.players["player_1"].manual_modifiers

    low_cost_state = _minimal_effect_state(effect)
    low_cost_state.cards["source-live"].card = source_member
    low_cost_state.players["player_1"].member_area["center"] = "source-live"
    low_cost_state.cards["deck-member-1"].card = low_cost_state.cards[
        "deck-member-1"
    ].card.model_copy(update={"cost": 3})
    low_cost_state.players["player_1"].main_deck = ["deck-member-1", "deck-live-1"]

    low_cost_state = _apply_direct(
        low_cost_state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_count": 5},
    )

    assert "deck-member-1" not in low_cost_state.players["player_1"].hand
    assert low_cost_state.players["player_1"].main_deck[0] == "deck-member-1"
    modifier = next(
        item
        for item in low_cost_state.players["player_1"].manual_modifiers
        if item.modifier_type == "blade"
    )
    assert modifier.amount == 2

    live_state = _minimal_effect_state(effect)
    live_state.cards["source-live"].card = source_member
    live_state.players["player_1"].member_area["center"] = "source-live"
    live_state.players["player_1"].main_deck = ["deck-live-1", "deck-member-1"]

    live_state = _apply_direct(
        live_state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_count": 5},
    )

    assert "deck-live-1" not in live_state.players["player_1"].hand
    assert live_state.players["player_1"].main_deck[0] == "deck-live-1"
    assert not live_state.players["player_1"].manual_modifiers


def test_cost_choice_can_require_selected_cards_to_share_unit_key():
    effect = EffectDefinition(
        effect_id="test-same-unit-cost:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="u" * 64,
        effect_index=1,
        label_ja="discard two cards with same unit",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={},
        cost=[{"action_type": "discard_from_hand"}],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 2,
            "maximum": 2,
            "condition": {"selected_share_unit_key": True},
        },
        choice=None,
        actions=[
            {"action_type": "gain_heart", "amount": 2, "color_slot": "heart04"}
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = _minimal_effect_state(effect)
    base_card = CardDefinition(
        card_code="TEST-HAND",
        card_id="TEST-HAND",
        name_ja="同ユニット",
        card_type="member",
        unit_keys=["unit_a"],
    )
    state.cards["hand-a1"] = CardInstance(
        instance_id="hand-a1",
        owner_id="player_1",
        card=base_card,
    )
    state.cards["hand-a2"] = CardInstance(
        instance_id="hand-a2",
        owner_id="player_1",
        card=base_card.model_copy(deep=True),
    )
    state.cards["hand-b1"] = CardInstance(
        instance_id="hand-b1",
        owner_id="player_1",
        card=base_card.model_copy(update={"unit_keys": ["unit_b"]}, deep=True),
    )
    state.players["player_1"].hand = ["hand-a1", "hand-a2", "hand-b1"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["cost_choice"]["condition"] == {"selected_share_unit_key": True}
    assert set(options["candidate_card_instance_ids"]) == {
        "hand-a1",
        "hand-a2",
        "hand-b1",
    }

    with pytest.raises(Exception, match="effect cost card selection is not legal"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "accepted": True,
                "selected_card_instance_ids": ["hand-a1", "hand-b1"],
            },
        )
    assert state.players["player_1"].hand == ["hand-a1", "hand-a2", "hand-b1"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "accepted": True,
            "selected_card_instance_ids": ["hand-a1", "hand-a2"],
        },
    )

    assert "hand-a1" not in state.players["player_1"].hand
    assert "hand-a2" not in state.players["player_1"].hand
    assert {"hand-a1", "hand-a2"}.issubset(state.players["player_1"].waiting_room)
    modifier = next(
        item
        for item in state.players["player_1"].manual_modifiers
        if item.modifier_type == "heart"
    )
    assert modifier.amount == 2
    assert modifier.color_slot == "heart04"


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


def test_branch_choice_can_filter_on_source_orientation_and_auto_ready_energy():
    effect = EffectDefinition(
        effect_id="test-wait-or-discard-ready:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="wait or discard ready energy",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "choose_effect_branch",
            "zone": "hand",
            "branch_ids": ["wait_source", "discard_hand"],
            "branch_selection_minimum": {"discard_hand": 1},
            "branch_selection_maximum": {"discard_hand": 1},
            "branch_conditions": {"wait_source": {"source_orientation": "active"}},
        },
        actions=[
            {"action_type": "apply_wait", "target": "source", "branch": "wait_source"},
            {
                "action_type": "ready_energy",
                "target": "auto",
                "amount": 1,
                "branch": "wait_source",
            },
            {
                "action_type": "ready_energy",
                "target": "auto",
                "amount": 1,
                "branch": "discard_hand",
            },
            {"action_type": "discard_from_hand", "branch": "discard_hand"},
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="Source",
        card_type="member",
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="Energy",
        card_type="energy",
    )
    hand_card = member.model_copy(
        update={"card_code": "TEST-HAND", "card_id": "TEST-HAND"}
    )

    state = _minimal_effect_state(effect)
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=member,
        orientation="active",
    )
    state.cards["wait-energy"] = CardInstance(
        instance_id="wait-energy",
        owner_id="player_1",
        card=energy,
        orientation="wait",
    )
    state.cards["hand-card"] = CardInstance(
        instance_id="hand-card",
        owner_id="player_1",
        card=hand_card,
    )
    state.players["player_1"].member_area["center"] = "source-member"
    state.players["player_1"].energy_area = ["wait-energy"]
    state.players["player_1"].hand = ["hand-card"]
    state.pending_effects[0].source_card_instance_id = "source-member"

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == ["wait_source", "discard_hand"]
    waited = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_branch": "wait_source"},
    )
    assert waited.cards["source-member"].orientation == "wait"
    assert waited.cards["wait-energy"].orientation == "active"
    assert not waited.pending_effects

    state.cards["source-member"].orientation = "wait"
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == ["discard_hand"]
    with pytest.raises(Exception, match="branch selection is unavailable"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1", "selected_branch": "wait_source"},
        )

    discard_branch = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_branch": "discard_hand"},
    )
    assert discard_branch.cards["wait-energy"].orientation == "active"
    assert discard_branch.pending_effects[0].trigger_data["selected_branch"] == (
        "discard_hand"
    )
    resolved = _apply_direct(
        discard_branch,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["hand-card"],
        },
    )
    assert "hand-card" in resolved.players["player_1"].waiting_room
    assert not resolved.pending_effects


def test_onplay_branch_choice_can_mill_or_wait_filtered_opponent_member():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-mill-or-wait:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "i" * 64,
            "effect_index": 1,
            "label_ja": "mill or wait opponent cost2",
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
                "branch_ids": ["mill3", "wait_opponent_cost2"],
                "branch_selection_minimum": {"wait_opponent_cost2": 1},
                "branch_selection_maximum": {"wait_opponent_cost2": 1},
                "branch_choice_filters": {
                    "wait_opponent_cost2": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "target_player": "opponent",
                        "card_type": "member",
                        "maximum_cost": 2,
                    }
                },
            },
            "actions": [
                {"action_type": "mill_top_cards", "amount": 3, "branch": "mill3"},
                {
                    "action_type": "apply_wait_member",
                    "target": "selected",
                    "branch": "wait_opponent_cost2",
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    low_member = CardDefinition(
        card_code="TEST-LOW-COST",
        card_id="TEST-LOW-COST",
        name_ja="Low",
        card_type="member",
        cost=2,
    )
    high_member = low_member.model_copy(
        update={"card_code": "TEST-HIGH-COST", "card_id": "TEST-HIGH-COST", "cost": 3}
    )
    state = _minimal_effect_state(effect)
    state.cards["opponent-low"] = CardInstance(
        instance_id="opponent-low",
        owner_id="player_2",
        card=low_member,
        orientation="active",
    )
    state.cards["opponent-high"] = CardInstance(
        instance_id="opponent-high",
        owner_id="player_2",
        card=high_member,
        orientation="active",
    )
    state.players["player_2"].member_area["left"] = "opponent-low"
    state.players["player_2"].member_area["right"] = "opponent-high"

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == ["mill3", "wait_opponent_cost2"]

    milled = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_branch": "mill3"},
    )
    assert milled.players["player_1"].main_deck == []
    assert milled.players["player_1"].waiting_room == [
        "deck-live-1",
        "deck-member-1",
        "deck-live-2",
    ]
    assert not milled.pending_effects

    pending_wait = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1", "selected_branch": "wait_opponent_cost2"},
    )
    wait_options = generate_legal_actions(pending_wait)[0].options["invocations"][0]
    assert wait_options["candidate_card_instance_ids"] == ["opponent-low"]

    resolved = _apply_direct(
        pending_wait,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["opponent-low"],
        },
    )
    assert resolved.cards["opponent-low"].orientation == "wait"
    assert resolved.cards["opponent-high"].orientation == "active"
    assert not resolved.pending_effects


def test_static_opponent_wait_member_amount_source_uses_match_state():
    blade_effect = EffectDefinition(
        effect_id="test-static-wait-blade:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="j" * 64,
        effect_index=1,
        label_ja="opponent wait blade",
        effect_type="static",
        timing="static_always",
        trigger="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "gain_blade",
                "amount_source": "opponent_stage_wait_member_count",
            }
        ],
        duration="game",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    heart_effect = EffectDefinition(
        effect_id="test-static-wait-heart:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="k" * 64,
        effect_index=2,
        label_ja="opponent wait heart",
        effect_type="static",
        timing="static_always",
        trigger="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "gain_heart",
                "amount_source": "opponent_stage_wait_member_count",
                "color_slot": "heart06",
            }
        ],
        duration="game",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="Source",
        card_type="member",
        effect_ids=[blade_effect.effect_id, heart_effect.effect_id],
    )
    opponent_member = CardDefinition(
        card_code="TEST-OPPONENT",
        card_id="TEST-OPPONENT",
        name_ja="Opponent",
        card_type="member",
    )
    state = _minimal_effect_state(blade_effect)
    state.effect_definitions = {
        blade_effect.effect_id: blade_effect,
        heart_effect.effect_id: heart_effect,
    }
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=source_member,
    )
    state.players["player_1"].member_area["center"] = "source-member"
    for slot, orientation in {
        "left": "wait",
        "center": "active",
        "right": "wait",
    }.items():
        instance_id = f"opponent-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=opponent_member,
            orientation=orientation,
        )
        state.players["player_2"].member_area[slot] = instance_id

    assert _static_numeric_bonus(
        state, "player_1", "source-member", "gain_blade"
    ) == 2
    assert _static_heart_bonus(state, "player_1", "source-member")["heart06"] == 2


def test_static_stage_and_success_amount_sources_use_match_state():
    effects = [
        EffectDefinition(
            effect_id="test-static-unit-count:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="u" * 64,
            effect_index=1,
            label_ja="unit count blade",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "gain_blade",
                    "amount_source": "own_stage_member_unit_count",
                    "value": {"unit_key": "miracra_park", "exclude_source": True},
                }
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-filter-count:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="v" * 64,
            effect_index=2,
            label_ja="filtered count blade",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "gain_blade",
                    "amount_source": "own_stage_member_filter_count",
                    "multiplier": 2,
                    "value": {"minimum_cost": 4, "exclude_unit_key": "cerise_bouquet"},
                }
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-opponent-success-lead:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="w" * 64,
            effect_index=3,
            label_ja="opponent success lead blade",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"own_success_live_count_less_than_opponent": True},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "gain_blade",
                    "amount_source": "opponent_success_live_count_difference",
                }
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-other-edel:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="x" * 64,
            effect_index=4,
            label_ja="other edel blade",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={
                "own_stage_other_member_unit_count_at_least": {
                    "unit_key": "edel_note",
                    "count": 1,
                }
            },
            cost=[],
            choice=None,
            actions=[{"action_type": "gain_blade", "amount": 2}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-opponent-excess:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="y" * 64,
            effect_index=5,
            label_ja="opponent excess score",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"opponent_excess_heart_count_at_least": 2},
            cost=[],
            choice=None,
            actions=[{"action_type": "modify_score", "amount": 1}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
    ]
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="Source",
        card_type="member",
        cost=3,
        unit_keys=["miracra_park", "edel_note"],
        effect_ids=[effect.effect_id for effect in effects],
    )
    state = _minimal_effect_state(effects[0])
    state.effect_definitions = {effect.effect_id: effect for effect in effects}
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=source_member,
    )
    state.players["player_1"].member_area["center"] = "source-member"
    for slot, cost, unit_keys in [
        ("left", 5, ["miracra_park", "edel_note"]),
        ("right", 4, ["dollchestra"]),
    ]:
        instance_id = f"own-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{slot.upper()}",
                card_id=f"TEST-{slot.upper()}",
                name_ja=f"Member {slot}",
                card_type="member",
                cost=cost,
                unit_keys=unit_keys,
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id
    state.players["player_1"].success_live_area = ["source-live"]
    for index in range(3):
        instance_id = f"opponent-success-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=state.cards["source-live"].card.model_copy(deep=True),
        )
        state.players["player_2"].success_live_area.append(instance_id)
    state.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 2}, "remaining_all_color_hearts": 0}
    ]

    assert _static_numeric_bonus(
        state, "player_1", "source-member", "gain_blade"
    ) == 9
    assert _static_numeric_bonus(
        state, "player_1", "source-member", "modify_score"
    ) == 1

    no_excess = state.model_copy(deep=True)
    no_excess.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]
    assert _static_numeric_bonus(
        no_excess, "player_1", "source-member", "modify_score"
    ) == 0


def test_static_position_heart_and_live_area_conditions_gate_modifiers():
    effects = [
        EffectDefinition(
            effect_id="test-static-side-blade-score:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="a" * 64,
            effect_index=1,
            label_ja="center side original blade score",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={
                "source_slot": "center",
                "own_side_stage_member_original_blade_exact": 2,
            },
            cost=[],
            choice=None,
            actions=[{"action_type": "modify_score", "amount": 1}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-most-hearts-score:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="b" * 64,
            effect_index=2,
            label_ja="source most stage hearts score",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_has_most_stage_hearts": True},
            cost=[],
            choice=None,
            actions=[{"action_type": "modify_score", "amount": 1}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-center-highest-cost:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="c" * 64,
            effect_index=3,
            label_ja="center highest cost heart",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"own_center_member_highest_cost": True},
            cost=[],
            choice=None,
            actions=[
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-liella-live-required-heart:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="d" * 64,
            effect_index=4,
            label_ja="liella live required heart total heart",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={
                "live_area_work_required_heart_total_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 8,
                }
            },
            cost=[],
            choice=None,
            actions=[
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
    ]
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="Source",
        card_type="member",
        cost=5,
        basic_hearts={"heart01": 3},
        effect_ids=[effect.effect_id for effect in effects],
    )
    state = _minimal_effect_state(effects[0])
    state.effect_definitions = {effect.effect_id: effect for effect in effects}
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=source_member,
    )
    state.players["player_1"].member_area = {
        "left": "own-left",
        "center": "source-member",
        "right": "own-right",
    }
    for slot, cost in [("left", 5), ("right", 4)]:
        instance_id = f"own-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{slot.upper()}",
                card_id=f"TEST-{slot.upper()}",
                name_ja=f"Own {slot}",
                card_type="member",
                cost=cost,
                blade=2,
                basic_hearts={"heart02": 1},
            ),
        )
    for slot, hearts in [("left", 2), ("center", 1), ("right", 0)]:
        instance_id = f"opp-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=CardDefinition(
                card_code=f"TEST-OPP-{slot.upper()}",
                card_id=f"TEST-OPP-{slot.upper()}",
                name_ja=f"Opponent {slot}",
                card_type="member",
                basic_hearts={"heart01": hearts},
            ),
        )
        state.players["player_2"].member_area[slot] = instance_id
    state.cards["liella-live"] = CardInstance(
        instance_id="liella-live",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-LIELLA-LIVE",
            card_id="TEST-LIELLA-LIVE",
            name_ja="Liella Live",
            card_type="live",
            work_keys=["love_live_superstar"],
            required_hearts={"heart01": 4, "heart02": 4},
        ),
    )
    state.players["player_1"].live_area = ["liella-live"]

    assert _static_numeric_bonus(
        state, "player_1", "source-member", "modify_score"
    ) == 2
    assert _static_heart_bonus(state, "player_1", "source-member")["heart03"] == 2

    side_mismatch = state.model_copy(deep=True)
    side_mismatch.cards["own-right"].card.blade = 3
    assert _static_numeric_bonus(
        side_mismatch, "player_1", "source-member", "modify_score"
    ) == 1

    not_most_hearts = state.model_copy(deep=True)
    not_most_hearts.cards["opp-left"].card.basic_hearts = {"heart01": 3}
    assert _static_numeric_bonus(
        not_most_hearts, "player_1", "source-member", "modify_score"
    ) == 1

    not_highest_cost = state.model_copy(deep=True)
    not_highest_cost.cards["own-right"].card.cost = 6
    assert (
        _static_heart_bonus(not_highest_cost, "player_1", "source-member")[
            "heart03"
        ]
        == 1
    )

    no_liella_live = state.model_copy(deep=True)
    no_liella_live.players["player_1"].live_area = []
    assert _static_heart_bonus(no_liella_live, "player_1", "source-member")[
        "heart03"
    ] == 1


def test_static_opposing_movement_and_attachment_conditions_gate_modifiers():
    effects = [
        EffectDefinition(
            effect_id="test-static-opposing-cost-heart:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="e" * 64,
            effect_index=1,
            label_ja="opposing cost heart",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"opposing_member_cost_greater_than_source": True},
            cost=[],
            choice=None,
            actions=[
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-not-moved-blade:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="f" * 64,
            effect_index=2,
            label_ja="not moved blade",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_not_moved_this_turn": True},
            cost=[],
            choice=None,
            actions=[{"action_type": "gain_blade", "amount": 2}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
        EffectDefinition(
            effect_id="test-static-attached-energy-score:1",
            card_code="TEST-MEMBER",
            text_revision_id=1,
            raw_text_hash="g" * 64,
            effect_index=3,
            label_ja="attached energy score",
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_attached_energy_count_at_least": 2},
            cost=[],
            choice=None,
            actions=[{"action_type": "modify_score", "amount": 1}],
            duration="game",
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test fixture",
        ),
    ]
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="Source",
        card_type="member",
        cost=4,
        effect_ids=[effect.effect_id for effect in effects],
    )
    state = _minimal_effect_state(effects[0])
    state.effect_definitions = {effect.effect_id: effect for effect in effects}
    state.cards["source-member"] = CardInstance(
        instance_id="source-member",
        owner_id="player_1",
        card=source_member,
    )
    state.players["player_1"].member_area["center"] = "source-member"
    state.cards["opposing-member"] = CardInstance(
        instance_id="opposing-member",
        owner_id="player_2",
        card=CardDefinition(
            card_code="TEST-OPPOSING",
            card_id="TEST-OPPOSING",
            name_ja="Opposing",
            card_type="member",
            cost=5,
        ),
    )
    state.players["player_2"].member_area["center"] = "opposing-member"
    for index in range(2):
        instance_id = f"attached-energy-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-ENERGY-{index}",
                card_id=f"TEST-ENERGY-{index}",
                name_ja=f"Energy {index}",
                card_type="energy",
            ),
        )
        state.players["player_1"].member_area_attachments["center"].append(
            instance_id
        )

    assert _static_heart_bonus(state, "player_1", "source-member")["heart01"] == 1
    assert _static_numeric_bonus(
        state, "player_1", "source-member", "gain_blade"
    ) == 2
    assert _static_numeric_bonus(
        state, "player_1", "source-member", "modify_score"
    ) == 1

    lower_opposing_cost = state.model_copy(deep=True)
    lower_opposing_cost.cards["opposing-member"].card.cost = 4
    assert (
        _static_heart_bonus(lower_opposing_cost, "player_1", "source-member")[
            "heart01"
        ]
        == 0
    )

    moved_source = state.model_copy(deep=True)
    moved_source.players["player_1"].member_areas_moved_this_turn = ["center"]
    assert _static_numeric_bonus(
        moved_source, "player_1", "source-member", "gain_blade"
    ) == 0

    one_attached_energy = state.model_copy(deep=True)
    one_attached_energy.players["player_1"].member_area_attachments["center"] = [
        "attached-energy-0"
    ]
    assert _static_numeric_bonus(
        one_attached_energy, "player_1", "source-member", "modify_score"
    ) == 0


def test_place_energy_from_deck_can_target_opponent():
    effect = EffectDefinition(
        effect_id="test-opponent-energy:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="l" * 64,
        effect_index=1,
        label_ja="opponent places wait energy",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "target": "opponent",
                "amount": 1,
                "orientation": "wait",
            }
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="Energy",
        card_type="energy",
    )
    state = _minimal_effect_state(effect)
    state.cards["opponent-energy"] = CardInstance(
        instance_id="opponent-energy",
        owner_id="player_2",
        card=energy,
        face_up=False,
    )
    state.players["player_2"].energy_deck = ["opponent-energy"]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.players["player_2"].energy_deck == []
    assert resolved.players["player_2"].energy_area == ["opponent-energy"]
    assert resolved.cards["opponent-energy"].orientation == "wait"


def test_live_start_branch_choice_uses_branch_specific_stage_filters():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-aqours-branch-filter:1",
            "card_code": "TEST-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "q" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ開始時】自分のステージのセンターエリアにコスト9以上の"
                "『Aqours』のメンバーがいる場合、以下から1つを選ぶ。 "
                "・ライブ終了時まで、自分のステージにいるメンバー1人は、"
                "【ブレード】【ブレード】を得る。 "
                "・相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
            ),
            "effect_type": "triggered",
            "timing": "live_start",
            "trigger": "live_started",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {
                "own_center_member_work_cost_at_least": {
                    "work_key": "love_live_sunshine",
                    "count": 9,
                }
            },
            "cost": [],
            "choice": {
                "choice_type": "choose_effect_branch",
                "branch_ids": ["gain_blade", "wait_opponent_cost4"],
                "branch_selection_minimum": {
                    "gain_blade": 1,
                    "wait_opponent_cost4": 1,
                },
                "branch_selection_maximum": {
                    "gain_blade": 1,
                    "wait_opponent_cost4": 1,
                },
                "branch_choice_filters": {
                    "gain_blade": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "card_type": "member",
                        "target_player": "self",
                    },
                    "wait_opponent_cost4": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "card_type": "member",
                        "target_player": "opponent",
                        "maximum_cost": 4,
                    },
                },
            },
            "actions": [
                {
                    "action_type": "gain_blade",
                    "target": "selected",
                    "amount": 2,
                    "branch": "gain_blade",
                },
                {
                    "action_type": "apply_wait_member",
                    "target": "selected",
                    "branch": "wait_opponent_cost4",
                },
            ],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    aqours_center = CardDefinition(
        card_code="TEST-AQOURS-CENTER",
        card_id="TEST-AQOURS-CENTER",
        name_ja="高海千歌",
        card_type="member",
        cost=9,
        work_keys=["love_live_sunshine"],
    )
    own_target = CardDefinition(
        card_code="TEST-AQOURS-TARGET",
        card_id="TEST-AQOURS-TARGET",
        name_ja="桜内梨子",
        card_type="member",
        cost=3,
        work_keys=["love_live_sunshine"],
    )
    opponent_cost4 = CardDefinition(
        card_code="TEST-OPPONENT-COST4",
        card_id="TEST-OPPONENT-COST4",
        name_ja="相手コスト4",
        card_type="member",
        cost=4,
    )
    opponent_cost5 = CardDefinition(
        card_code="TEST-OPPONENT-COST5",
        card_id="TEST-OPPONENT-COST5",
        name_ja="相手コスト5",
        card_type="member",
        cost=5,
    )

    state = _minimal_effect_state(effect)
    state.cards.update(
        {
            "own-center": CardInstance(
                instance_id="own-center",
                owner_id="player_1",
                card=aqours_center,
            ),
            "own-target": CardInstance(
                instance_id="own-target",
                owner_id="player_1",
                card=own_target,
            ),
            "opp-cost4": CardInstance(
                instance_id="opp-cost4",
                owner_id="player_2",
                card=opponent_cost4,
            ),
            "opp-cost5": CardInstance(
                instance_id="opp-cost5",
                owner_id="player_2",
                card=opponent_cost5,
            ),
        }
    )
    state.players["player_1"].member_area["center"] = "own-center"
    state.players["player_1"].member_area["left"] = "own-target"
    state.players["player_2"].member_area["left"] = "opp-cost4"
    state.players["player_2"].member_area["right"] = "opp-cost5"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_branch": "gain_blade",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["selected_branch"] == "gain_blade"
    assert options["choice_zone"] == "stage"
    assert options["target_player"] == "self"
    assert "own-target" in options["candidate_card_instance_ids"]
    assert "opp-cost4" not in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["own-target"],
        },
    )
    assert any(
        modifier.modifier_type == "blade"
        and modifier.amount == 2
        and modifier.target_card_instance_id == "own-target"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert not state.pending_effects

    state = _minimal_effect_state(effect)
    state.cards.update(
        {
            "own-center": CardInstance(
                instance_id="own-center",
                owner_id="player_1",
                card=aqours_center,
            ),
            "own-target": CardInstance(
                instance_id="own-target",
                owner_id="player_1",
                card=own_target,
            ),
            "opp-cost4": CardInstance(
                instance_id="opp-cost4",
                owner_id="player_2",
                card=opponent_cost4,
            ),
            "opp-cost5": CardInstance(
                instance_id="opp-cost5",
                owner_id="player_2",
                card=opponent_cost5,
            ),
        }
    )
    state.players["player_1"].member_area["center"] = "own-center"
    state.players["player_1"].member_area["left"] = "own-target"
    state.players["player_2"].member_area["left"] = "opp-cost4"
    state.players["player_2"].member_area["right"] = "opp-cost5"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_branch": "wait_opponent_cost4",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["selected_branch"] == "wait_opponent_cost4"
    assert options["target_player"] == "opponent"
    assert options["candidate_card_instance_ids"] == ["opp-cost4"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["opp-cost4"],
        },
    )
    assert state.cards["opp-cost4"].orientation == "wait"
    assert state.cards["opp-cost5"].orientation == "active"
    assert not state.pending_effects


def test_draw_then_optional_wait_opponent_member_can_choose_no_target():
    effect = EffectDefinition(
        effect_id="test-draw-optional-opponent-wait:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="draw then optional opponent wait",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": 9,
            "minimum": 0,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {"action_type": "apply_wait_member", "target": "selected"},
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    opponent_cost9 = CardDefinition(
        card_code="OPP-COST9",
        card_id="OPP-COST9",
        name_ja="対手9",
        card_type="member",
        cost=9,
    )
    opponent_cost10 = CardDefinition(
        card_code="OPP-COST10",
        card_id="OPP-COST10",
        name_ja="対手10",
        card_type="member",
        cost=10,
    )
    state = _minimal_effect_state(effect)
    state.cards.update(
        {
            "opp-cost9": CardInstance(
                instance_id="opp-cost9",
                owner_id="player_2",
                card=opponent_cost9,
            ),
            "opp-cost10": CardInstance(
                instance_id="opp-cost10",
                owner_id="player_2",
                card=opponent_cost10,
            ),
        }
    )
    state.players["player_2"].member_area["left"] = "opp-cost9"
    state.players["player_2"].member_area["right"] = "opp-cost10"

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["target_player"] == "opponent"
    assert options["candidate_card_instance_ids"] == ["opp-cost9"]

    hand_count = len(state.players["player_1"].hand)
    source_orientation = state.cards["source-live"].orientation
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [],
        },
    )
    assert len(state.players["player_1"].hand) == hand_count + 1
    assert state.cards["source-live"].orientation == source_orientation
    assert state.cards["opp-cost9"].orientation == "active"
    assert state.cards["opp-cost10"].orientation == "active"
    assert not state.pending_effects


def test_wait_opponent_member_checks_own_stage_cost_condition():
    effect = EffectDefinition(
        effect_id="test-own-stage-cost-opponent-wait:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="h" * 64,
        effect_index=1,
        label_ja="own stage cost condition then opponent wait",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_member_cost_at_least": 10},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": 4,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    own_cost9 = CardDefinition(
        card_code="OWN-COST9",
        card_id="OWN-COST9",
        name_ja="自分9",
        card_type="member",
        cost=9,
    )
    own_cost10 = CardDefinition(
        card_code="OWN-COST10",
        card_id="OWN-COST10",
        name_ja="自分10",
        card_type="member",
        cost=10,
    )
    opponent_cost4 = CardDefinition(
        card_code="OPP-COST4",
        card_id="OPP-COST4",
        name_ja="対手4",
        card_type="member",
        cost=4,
    )
    state = _minimal_effect_state(effect)
    state.cards.update(
        {
            "own-cost9": CardInstance(
                instance_id="own-cost9",
                owner_id="player_1",
                card=own_cost9,
            ),
            "opp-cost4": CardInstance(
                instance_id="opp-cost4",
                owner_id="player_2",
                card=opponent_cost4,
            ),
        }
    )
    state.players["player_1"].member_area["center"] = "own-cost9"
    state.players["player_2"].member_area["center"] = "opp-cost4"

    with pytest.raises(Exception, match="stage_member_cost_too_low"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": state.pending_effects[0].invocation_id,
                "selected_card_instance_ids": ["opp-cost4"],
            },
        )

    state.cards["own-cost9"].card = own_cost10
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": ["opp-cost4"],
        },
    )
    assert state.cards["opp-cost4"].orientation == "wait"
    assert not state.pending_effects


def test_live_start_branch_can_grant_live_success_draw():
    state = _minimal_effect_state(_aqours_live_start_branch_effect())

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == ["grant_success_draw"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "grant_success_draw",
        },
    )

    modifiers = state.players["player_1"].manual_modifiers
    assert [
        (
            modifier.modifier_type,
            modifier.flag,
            modifier.target_card_instance_id,
            modifier.value,
        )
        for modifier in modifiers
    ] == [
        (
            "flag",
            "granted_live_success_draw",
            "source-live",
            {"amount": 1},
        )
    ]

    events: list[GameEvent] = []
    state.success_live_moved_instance_ids = {"player_1": ["source-live"]}
    _queue_live_success_effects(state, events)

    assert state.players["player_1"].hand == ["deck-live-1"]
    assert any(
        event.event_type == "granted_live_success_draw_resolved"
        and event.data["live_card_instance_id"] == "source-live"
        for event in events
    )


def test_live_start_can_disable_source_live_success_effects():
    disable_effect = EffectDefinition(
        effect_id="test-disable-live-success:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="d" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のステージにいる『Aqours』のメンバーが持つ"
            "ハートに、【heart02】が合計6個以上ある場合、このカードの"
            "【ライブ成功時】能力を無効にする。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_heart_at_least": {
                "unit_key": "aqours",
                "color_slot": "heart02",
                "count": 6,
            }
        },
        actions=[{"action_type": "disable_source_live_success_effects"}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="parsed_draft",
        source_reference="unit test",
    )
    success_effect = EffectDefinition(
        effect_id="test-disable-live-success:2",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="d" * 64,
        effect_index=2,
        label_ja="【ライブ成功時】相手は、エネルギーデッキからエネルギーカードを1枚ウェイト状態で置く。",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="manual_resolution",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        actions=[{"action_type": "manual_resolution"}],
        duration="live",
        simulation_support="manual_resolution",
        review_status="parsed_draft",
        source_reference="unit test",
    )
    state = _minimal_effect_state(disable_effect)
    state.effect_definitions[success_effect.effect_id] = success_effect
    state.cards["source-live"].card.effect_ids = [
        disable_effect.effect_id,
        success_effect.effect_id,
    ]
    aqours_member = CardDefinition(
        card_code="TEST-AQOURS",
        card_id="TEST-AQOURS",
        name_ja="高海千歌",
        card_type="member",
        basic_hearts={"heart02": 3},
        unit_keys=["aqours"],
    )
    for slot, instance_id in {"left": "aqours-left", "center": "aqours-center"}.items():
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=aqours_member.model_copy(
                update={"card_code": f"TEST-{slot.upper()}", "card_id": f"TEST-{slot.upper()}"}
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id

    low_state = state.model_copy(deep=True)
    low_state.cards["aqours-center"].card.basic_hearts = {"heart02": 2}
    with pytest.raises(Exception, match="stage_heart_count_too_low"):
        _apply_direct(
            low_state,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert [
        (
            modifier.modifier_type,
            modifier.flag,
            modifier.target_card_instance_id,
            modifier.value,
        )
        for modifier in state.players["player_1"].manual_modifiers
    ] == [
        (
            "flag",
            "disabled_live_success_effects",
            "source-live",
            {"trigger": "live_succeeded"},
        )
    ]

    events: list[GameEvent] = []
    state.success_live_moved_instance_ids = {"player_1": ["source-live"]}
    state.live_success_effects_queued = False
    _queue_live_success_effects(state, events)

    assert state.pending_effects == []
    assert any(
        event.event_type == "effect_trigger_disabled"
        and event.data["effect_id"] == success_effect.effect_id
        and event.data["source_card_instance_id"] == "source-live"
        for event in events
    )


def test_live_success_replaces_source_score_when_yell_has_no_blade_heartless_or_excess2():
    effect = EffectDefinition(
        effect_id="test-replace-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="r" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ成功時】このターン、エールにより公開された自分のカードの中に"
            "ブレードハートを持たないカードが0枚の場合か、または自分が余剰ハートを"
            "2つ以上持っている場合、このカードのスコアは４になる。"
        ),
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_yell_no_blade_heartless_or_excess_heart_count_at_least": 2},
        cost=[],
        choice=None,
        actions=[{"action_type": "replace_score", "amount": 4}],
        duration="game",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    player = state.players["player_1"]
    player.success_live_area = ["source-live"]
    player.live_result.revealed_instance_ids = ["blade-member", "special-live"]
    player.live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 0}, "remaining_all_color_hearts": 0}
    ]
    state.cards["blade-member"] = CardInstance(
        instance_id="blade-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-BLADE-MEMBER",
            card_id="TEST-BLADE-MEMBER",
            name_ja="ブレード持ち",
            card_type="member",
            blade_heart_color_slot="heart01",
        ),
    )
    state.cards["special-live"] = CardInstance(
        instance_id="special-live",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-SPECIAL-LIVE",
            card_id="TEST-SPECIAL-LIVE",
            name_ja="特殊ブレード持ち",
            card_type="live",
            special_blade_hearts=[
                SpecialBladeHeart(effect_type="score", value=1, source_alt="スコア1")
            ],
        ),
    )
    state.cards["plain-member"] = CardInstance(
        instance_id="plain-member",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-PLAIN-MEMBER",
            card_id="TEST-PLAIN-MEMBER",
            name_ja="ブレードなし",
            card_type="member",
        ),
    )

    result = apply_action(
        state.model_copy(deep=True),
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    )
    assert [
        (modifier.modifier_type, modifier.amount, modifier.target_card_instance_id)
        for modifier in result.state.players["player_1"].manual_modifiers
    ] == [("score_replacement", 4, "source-live")]

    blocked_state = state.model_copy(deep=True)
    blocked_state.players["player_1"].live_result.revealed_instance_ids = [
        "blade-member",
        "plain-member",
    ]
    with pytest.raises(Exception, match="yell_revealed_non_blade_heart_exists"):
        apply_action(
            blocked_state,
            ActionRequest(
                action_type="resolve_effect",
                expected_revision=blocked_state.revision,
                player_id="player_1",
                payload={"invocation_id": "inv-1"},
            ),
        )

    excess_state = blocked_state.model_copy(deep=True)
    excess_state.players["player_1"].live_result.live_allocations = [
        {"remaining_hearts": {"heart01": 2}, "remaining_all_color_hearts": 0}
    ]
    result = apply_action(
        excess_state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=excess_state.revision,
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        ),
    )
    assert sum(
        modifier.modifier_type == "score_replacement"
        for modifier in result.state.players["player_1"].manual_modifiers
    ) == 1


def test_live_success_special_blade_heart_condition_filters_revealed_cards():
    effect = EffectDefinition(
        effect_id="test-revealed-score-live:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="s" * 64,
        effect_index=1,
        label_ja="【ライブ成功時】エール公開の【スコア】ライブを確認する。",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_yell_revealed_special_blade_heart_count_at_least": {
                "effect_type": "score",
                "card_type": "live",
                "work_key": "love_live_sunshine",
                "count": 1,
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    state.players["player_1"].live_result.revealed_instance_ids = ["aqours-live"]
    state.cards["aqours-live"] = CardInstance(
        instance_id="aqours-live",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-AQOURS-LIVE",
            card_id="TEST-AQOURS-LIVE",
            name_ja="Aqours スコアライブ",
            card_type="live",
            work_keys=["love_live_sunshine"],
            special_blade_hearts=[
                SpecialBladeHeart(effect_type="score", value=1, source_alt="スコア1")
            ],
        ),
    )

    resolved = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in resolved.players["player_1"].manual_modifiers
    )

    mismatch = state.model_copy(deep=True)
    mismatch.cards["aqours-live"].card.work_keys = ["nijigasaki"]
    with pytest.raises(
        Exception,
        match="yell_revealed_special_blade_heart_count_too_low",
    ):
        _apply_direct(
            mismatch,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_stage_member_names_present_condition_requires_all_names():
    effect = EffectDefinition(
        effect_id="test-stage-names-draw:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="n" * 64,
        effect_index=1,
        label_ja="【ライブ成功時】ステージに指定名がいる場合、カードを1枚引く。",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_member_names_present": ["澁谷かのん", "唐 可可"]},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    for slot, name in [("left", "澁谷かのん"), ("right", "唐 可可")]:
        instance_id = f"stage-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{slot.upper()}",
                card_id=f"TEST-{slot.upper()}",
                name_ja=name,
                card_type="member",
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id

    resolved = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert len(resolved.players["player_1"].hand) == 1

    missing = state.model_copy(deep=True)
    missing.players["player_1"].member_area["right"] = None
    with pytest.raises(Exception, match="stage_member_names_missing"):
        _apply_direct(
            missing,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_live_success_score_bonus_requires_deck_refreshed_this_turn():
    effect = EffectDefinition(
        effect_id="test-refresh-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="f" * 64,
        effect_index=1,
        label_ja="【ライブ成功時】このターン、自分のデッキがリフレッシュしていた場合、このカードのスコアを＋２する。",
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_deck_refreshed_this_turn": True},
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 2}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)

    with pytest.raises(Exception, match="deck_not_refreshed_this_turn"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    refreshed_state = state.model_copy(deep=True)
    refreshed_state.players["player_1"].refreshed_this_turn = True
    refreshed_state = _apply_direct(
        refreshed_state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in refreshed_state.players["player_1"].manual_modifiers
    ] == [("score", 2)]

    refreshed_state.phase = "turn_complete"
    refreshed_state.next_first_player_id = "player_1"
    result = apply_action(
        refreshed_state,
        ActionRequest(
            action_type="start_next_turn",
            expected_revision=refreshed_state.revision,
            player_id="player_1",
            payload={},
        ),
    )
    assert result.state.players["player_1"].refreshed_this_turn is False


def test_live_start_center_side_cost_equal_waits_opponent_original_blade3_members():
    effect = EffectDefinition(
        effect_id="test-side-cost-wait:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="e" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】【センター】自分のステージの右サイドエリアと"
            "左サイドエリアにいるメンバーのコストが同じ場合、相手の"
            "ステージにいる元々持つ【ブレード】の数が3つ以下のすべての"
            "メンバーをウェイトにする。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "source_slot": "center",
            "own_side_stage_member_costs_equal": True,
        },
        actions=[
            {
                "action_type": "apply_wait_member",
                "target": "opponent_stage_original_blade_at_most",
                "amount": 3,
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="parsed_draft",
        source_reference="unit test",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE",
        card_id="TEST-SOURCE",
        name_ja="渡辺曜",
        card_type="member",
        cost=5,
    )
    side_member = CardDefinition(
        card_code="TEST-SIDE",
        card_id="TEST-SIDE",
        name_ja="サイド",
        card_type="member",
        cost=4,
    )
    low_blade = CardDefinition(
        card_code="TEST-LOW-BLADE",
        card_id="TEST-LOW-BLADE",
        name_ja="低ブレード",
        card_type="member",
        blade=3,
    )
    high_blade = low_blade.model_copy(
        update={
            "card_code": "TEST-HIGH-BLADE",
            "card_id": "TEST-HIGH-BLADE",
            "name_ja": "高ブレード",
            "blade": 4,
        }
    )
    zero_blade = low_blade.model_copy(
        update={
            "card_code": "TEST-ZERO-BLADE",
            "card_id": "TEST-ZERO-BLADE",
            "name_ja": "ゼロブレード",
            "blade": 0,
        }
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area = {
        "left": "own-left",
        "center": "source-live",
        "right": "own-right",
    }
    state.cards["own-left"] = CardInstance(
        instance_id="own-left",
        owner_id="player_1",
        card=side_member,
    )
    state.cards["own-right"] = CardInstance(
        instance_id="own-right",
        owner_id="player_1",
        card=side_member.model_copy(
            update={"card_code": "TEST-SIDE-2", "card_id": "TEST-SIDE-2"}
        ),
    )
    state.cards["opp-low"] = CardInstance(
        instance_id="opp-low",
        owner_id="player_2",
        card=low_blade,
        orientation="active",
    )
    state.cards["opp-high"] = CardInstance(
        instance_id="opp-high",
        owner_id="player_2",
        card=high_blade,
        orientation="active",
    )
    state.cards["opp-zero"] = CardInstance(
        instance_id="opp-zero",
        owner_id="player_2",
        card=zero_blade,
        orientation="active",
    )
    state.players["player_2"].member_area = {
        "left": "opp-low",
        "center": "opp-high",
        "right": "opp-zero",
    }

    mismatch = state.model_copy(deep=True)
    mismatch.cards["own-right"].card.cost = 6
    with pytest.raises(Exception, match="side_stage_member_cost_mismatch"):
        _apply_direct(
            mismatch,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert resolved.cards["opp-low"].orientation == "wait"
    assert resolved.cards["opp-zero"].orientation == "wait"
    assert resolved.cards["opp-high"].orientation == "active"
    assert not resolved.pending_effects


def test_live_start_branch_targets_baton_entered_aqours_member():
    state = _minimal_effect_state(_aqours_live_start_branch_effect())
    aqours_member = CardDefinition(
        card_code="TEST-AQOURS",
        card_id="TEST-AQOURS",
        name_ja="高海千歌",
        card_type="member",
        work_keys=["love_live_sunshine"],
    )
    other_work_member = aqours_member.model_copy(
        update={
            "card_code": "TEST-NON-AQOURS",
            "card_id": "TEST-NON-AQOURS",
            "name_ja": "高坂穂乃果",
            "work_keys": ["love_live"],
        }
    )
    state.cards["baton-aqours"] = CardInstance(
        instance_id="baton-aqours",
        owner_id="player_1",
        card=aqours_member,
    )
    state.cards["baton-other-work"] = CardInstance(
        instance_id="baton-other-work",
        owner_id="player_1",
        card=other_work_member,
    )
    state.cards["non-baton-aqours"] = CardInstance(
        instance_id="non-baton-aqours",
        owner_id="player_1",
        card=aqours_member.model_copy(
            update={"card_code": "TEST-AQOURS-2", "card_id": "TEST-AQOURS-2"}
        ),
    )
    player = state.players["player_1"]
    player.member_area = {
        "left": "baton-aqours",
        "center": "baton-other-work",
        "right": "non-baton-aqours",
    }
    player.member_areas_baton_entered_this_turn = ["left", "center"]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == [
        "grant_success_draw",
        "baton_aqours_heart",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "baton_aqours_heart",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["selected_branch"] == "baton_aqours_heart"
    assert options["candidate_card_instance_ids"] == ["baton-aqours"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["baton-aqours"],
        },
    )

    modifiers = state.players["player_1"].manual_modifiers
    assert [
        (
            modifier.modifier_type,
            modifier.color_slot,
            modifier.amount,
            modifier.target_card_instance_id,
        )
        for modifier in modifiers
    ] == [("heart", "heart02", 1, "baton-aqours")]
    assert not state.pending_effects


def test_live_start_branch_requires_success2_for_score_branch():
    state = _minimal_effect_state(_aqours_live_start_branch_effect())
    live = state.cards["live-1"].card
    for instance_id in ("success-live-1", "success-live-2"):
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=live.model_copy(deep=True),
        )
    state.players["player_1"].success_live_area = [
        "success-live-1",
        "success-live-2",
    ]

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == [
        "grant_success_draw",
        "success2_score",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "success2_score",
        },
    )

    assert [
        (modifier.modifier_type, modifier.amount)
        for modifier in state.players["player_1"].manual_modifiers
    ] == [("score", 1)]
    assert not state.pending_effects


def test_live_start_all_aqours_drawn_hand_card_can_go_to_deck_top_or_bottom():
    state = _minimal_effect_state(_all_aqours_draw_top_or_bottom_effect())
    aqours_member = CardDefinition(
        card_code="TEST-AQOURS",
        card_id="TEST-AQOURS",
        name_ja="高海千歌",
        card_type="member",
        work_keys=["love_live_sunshine"],
    )
    other_member = aqours_member.model_copy(
        update={
            "card_code": "TEST-OTHER",
            "card_id": "TEST-OTHER",
            "work_keys": ["love_live"],
        }
    )
    hand_card = CardDefinition(
        card_code="TEST-HAND",
        card_id="TEST-HAND",
        name_ja="手札",
        card_type="member",
    )
    draw_card = hand_card.model_copy(
        update={"card_code": "TEST-DRAW", "card_id": "TEST-DRAW"}
    )
    state.cards["aqours-left"] = CardInstance(
        instance_id="aqours-left",
        owner_id="player_1",
        card=aqours_member,
    )
    state.cards["other-center"] = CardInstance(
        instance_id="other-center",
        owner_id="player_1",
        card=other_member,
    )
    state.players["player_1"].member_area = {
        "left": "aqours-left",
        "center": "other-center",
        "right": None,
    }

    with pytest.raises(Exception, match="stage_member_work_mismatch"):
        _apply_direct(
            state.model_copy(deep=True),
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    state.cards["aqours-center"] = CardInstance(
        instance_id="aqours-center",
        owner_id="player_1",
        card=aqours_member.model_copy(
            update={"card_code": "TEST-AQOURS-2", "card_id": "TEST-AQOURS-2"}
        ),
    )
    state.cards["hand-old"] = CardInstance(
        instance_id="hand-old",
        owner_id="player_1",
        card=hand_card,
    )
    state.cards["drawn-card"] = CardInstance(
        instance_id="drawn-card",
        owner_id="player_1",
        card=draw_card,
        face_up=False,
    )
    state.players["player_1"].member_area["center"] = "aqours-center"
    state.players["player_1"].hand = ["hand-old"]
    state.players["player_1"].main_deck = ["drawn-card", "deck-live-1"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert state.pending_effects[0].resolution_stage == "after_cost"
    assert state.players["player_1"].hand == ["hand-old", "drawn-card"]
    assert state.players["player_1"].main_deck == ["deck-live-1"]
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in state.players["player_1"].manual_modifiers
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["candidate_card_instance_ids"] == ["hand-old", "drawn-card"]
    assert options["destination_options"] == ["main_deck_top", "main_deck_bottom"]

    top_state = _apply_direct(
        state.model_copy(deep=True),
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["drawn-card"],
            "selected_destination": "main_deck_top",
        },
    )
    assert top_state.players["player_1"].main_deck[:2] == [
        "drawn-card",
        "deck-live-1",
    ]

    bottom_state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["drawn-card"],
            "selected_destination": "main_deck_bottom",
        },
    )
    assert bottom_state.players["player_1"].main_deck[-2:] == [
        "deck-live-1",
        "drawn-card",
    ]


def test_live_success_draw_discard_uses_aqours_stage_member_count():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-aqours-stage-draw-discard:1",
            "card_code": "TEST-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "a" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ成功時】自分のステージにいる『Aqours』のメンバー1人につき、"
                "カードを1枚引く。その後、これにより引いた枚数と同じ枚数を"
                "手札から控え室に置く。"
            ),
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {
                "own_stage_member_unit_count_at_least": {
                    "unit_key": "aqours",
                    "count": 1,
                }
            },
            "cost": [],
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "amount_source": "own_stage_member_unit_count",
                "amount_source_unit_key": "aqours",
            },
            "actions": [
                {
                    "action_type": "draw_card_per_stage_member",
                    "value": {"unit_key": "aqours"},
                },
                {"action_type": "discard_from_hand"},
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    state = _minimal_effect_state(effect)
    aqours_member = CardDefinition(
        card_code="TEST-AQOURS",
        card_id="TEST-AQOURS",
        name_ja="高海千歌",
        card_type="member",
        work_keys=["love_live_sunshine"],
        unit_keys=["aqours"],
    )
    other_member = aqours_member.model_copy(
        update={
            "card_code": "TEST-OTHER",
            "card_id": "TEST-OTHER",
            "work_keys": ["love_live"],
            "unit_keys": [],
        }
    )
    for slot, card in {
        "left": aqours_member,
        "center": aqours_member.model_copy(
            update={"card_code": "TEST-AQOURS-2", "card_id": "TEST-AQOURS-2"}
        ),
        "right": other_member,
    }.items():
        instance_id = f"stage-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=card,
        )
        state.players["player_1"].member_area[slot] = instance_id
    state.cards["hand-old"] = CardInstance(
        instance_id="hand-old",
        owner_id="player_1",
        card=aqours_member,
    )
    state.players["player_1"].hand = ["hand-old"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert state.players["player_1"].hand == [
        "hand-old",
        "deck-live-1",
        "deck-member-1",
    ]
    assert state.players["player_1"].main_deck == ["deck-live-2"]
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["card_selection_minimum"] == 2
    assert options["card_selection_maximum"] == 2
    assert options["candidate_card_instance_ids"] == [
        "hand-old",
        "deck-live-1",
        "deck-member-1",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["hand-old", "deck-live-1"],
        },
    )

    assert state.players["player_1"].hand == ["deck-member-1"]
    assert state.players["player_1"].waiting_room[-2:] == ["hand-old", "deck-live-1"]
    assert not state.pending_effects


def test_equal_score_live_success_effect_prevents_success_live_placement():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-equal-score-prevent-success:1",
            "card_code": "TEST-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "e" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ成功時】このターン、ライブに勝利するプレイヤーを決定するとき、"
                "自分と相手のライブの合計スコアが同じ場合、ライブ終了時まで、"
                "自分と相手は成功ライブカード置き場にカードを置くことができない。"
            ),
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "auto_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {"live_judgment_basis": "equal_total_score"},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "prevent_equal_score_success_live_placement"}],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    state = _minimal_effect_state(effect)
    state.phase = "live_judgment"
    state.live_success_effects_queued = True
    state.live_judgment_summary = {
        "basis": "equal_total_score",
        "winner_ids": ["player_1", "player_2"],
        "players": {},
    }
    state.live_winner_ids = ["player_1", "player_2"]
    state.players["player_1"].live_area = []
    state.players["player_1"].success_live_area = ["live-1"]
    state.cards["opponent-live"] = CardInstance(
        instance_id="opponent-live",
        owner_id="player_2",
        card=state.cards["live-1"].card.model_copy(
            update={"card_code": "TEST-OP-LIVE", "card_id": "TEST-OP-LIVE"}
        ),
    )
    state.players["player_2"].success_live_area = ["opponent-live"]
    state.success_live_moved_player_ids = ["player_1", "player_2"]
    state.success_live_moved_instance_ids = {
        "player_1": ["live-1"],
        "player_2": ["opponent-live"],
    }

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert state.players["player_1"].success_live_area == []
    assert state.players["player_2"].success_live_area == []
    assert "live-1" in state.players["player_1"].waiting_room
    assert "opponent-live" in state.players["player_2"].waiting_room
    assert state.success_live_moved_player_ids == []
    assert state.success_live_moved_instance_ids == {}
    assert state.phase == "turn_complete"


def test_onplay_5yncri5e_effect_rotates_both_stage_member_groups():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-rotate-5yncri5e:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "5" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】自分のステージにいるメンバーが『5yncri5e!』のみの場合、"
                "自分と対戦相手は、センターエリアのメンバーを左サイドエリアに、"
                "左サイドエリアのメンバーを右サイドエリアに、"
                "右サイドエリアのメンバーをセンターエリアに、それぞれ移動させる。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "auto_resolve",
            "frequency_limit": "none",
            "is_optional": False,
            "condition": {"own_stage_members_only_unit_key": "5yncri5e"},
            "cost": [],
            "choice": None,
            "actions": [{"action_type": "rotate_stage_members", "target": "both"}],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    state = _minimal_effect_state(effect)
    base_member = state.cards["deck-member-1"].card.model_copy(
        update={"unit_keys": ["5yncri5e"]}
    )
    for instance_id in [
        "p1-left",
        "source-live",
        "p1-right",
        "p2-left",
        "p2-center",
        "p2-right",
    ]:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id=(
                "player_1"
                if instance_id.startswith("p1") or instance_id == "source-live"
                else "player_2"
            ),
            card=base_member.model_copy(
                update={
                    "card_code": f"TEST-{instance_id}",
                    "card_id": f"TEST-{instance_id}",
                }
            ),
        )
    state.players["player_1"].member_area = {
        "left": "p1-left",
        "center": "source-live",
        "right": "p1-right",
    }
    state.players["player_2"].member_area = {
        "left": "p2-left",
        "center": "p2-center",
        "right": "p2-right",
    }

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert state.players["player_1"].member_area == {
        "left": "source-live",
        "center": "p1-right",
        "right": "p1-left",
    }
    assert state.players["player_2"].member_area == {
        "left": "p2-center",
        "center": "p2-right",
        "right": "p2-left",
    }
    assert not state.pending_effects


def test_live_start_no_timing_live_effect_grants_blade_to_other_member():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-no-timing-live-other-blade:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "6" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ開始時】自分のライブ中のライブカードに、"
                "【ライブ開始時】能力も【ライブ成功時】能力も持たないカードがある場合、"
                "ライブ終了時まで、自分のステージにいるこのメンバー以外のメンバー1人は、"
                "【ブレード】【ブレード】を得る。"
            ),
            "effect_type": "triggered",
            "timing": "live_start",
            "trigger": "live_started",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {
                "source_zone": "stage",
                "own_live_has_card_without_live_start_or_success_effects": True,
                "own_stage_member_count_at_least": 2,
            },
            "cost": [],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_blade", "target": "selected", "amount": 2}
            ],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test",
        }
    )
    state = _minimal_effect_state(effect)
    source_member = state.cards["deck-member-1"].card.model_copy(
        update={"card_code": "TEST-SOURCE", "card_id": "TEST-SOURCE"}
    )
    other_member = source_member.model_copy(
        update={"card_code": "TEST-OTHER", "card_id": "TEST-OTHER"}
    )
    state.cards["source-live"] = CardInstance(
        instance_id="source-live",
        owner_id="player_1",
        card=source_member,
    )
    state.cards["other-member"] = CardInstance(
        instance_id="other-member",
        owner_id="player_1",
        card=other_member,
    )
    state.players["player_1"].member_area = {
        "left": "source-live",
        "center": "other-member",
        "right": None,
    }

    legal = generate_legal_actions(state)
    invocation_options = legal[0].options["invocations"][0]
    assert invocation_options["candidate_card_instance_ids"] == ["other-member"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["other-member"],
        },
    )

    assert any(
        modifier.modifier_type == "blade"
        and modifier.amount == 2
        and modifier.duration == "live"
        and modifier.target_card_instance_id == "other-member"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert not state.pending_effects


def test_onplay_branch_choice_uses_branch_conditions_for_waiting_room_lives():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-waiting-live-branches:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "w" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】以下から1つを選ぶ。 "
                "・自分の控え室にカード名が異なるライブカードが3枚以上ある場合、"
                "自分の控え室からライブカードを1枚手札に加える。 "
                "・自分の控え室にグループ名が異なるライブカードが3枚以上ある場合、"
                "自分の控え室からライブカードを2枚手札に加える。"
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
                "branch_ids": ["distinct_name_live", "distinct_group_live"],
                "branch_conditions": {
                    "distinct_name_live": {
                        "waiting_room_live_distinct_name_count_at_least": 3,
                    },
                    "distinct_group_live": {
                        "waiting_room_live_distinct_group_count_at_least": 3,
                    },
                },
                "branch_selection_minimum": {
                    "distinct_name_live": 1,
                    "distinct_group_live": 2,
                },
                "branch_selection_maximum": {
                    "distinct_name_live": 1,
                    "distinct_group_live": 2,
                },
                "branch_choice_filters": {
                    "distinct_name_live": {
                        "choice_type": "card_from_zone",
                        "zone": "waiting_room",
                        "card_type": "live",
                    },
                    "distinct_group_live": {
                        "choice_type": "card_from_zone",
                        "zone": "waiting_room",
                        "card_type": "live",
                    },
                },
            },
            "actions": [
                {
                    "action_type": "return_from_waiting_room",
                    "branch": "distinct_name_live",
                },
                {
                    "action_type": "return_from_waiting_room",
                    "branch": "distinct_group_live",
                },
            ],
            "duration": None,
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    base_live = state_live = CardDefinition(
        card_code="TEST-LIVE",
        card_id="TEST-LIVE",
        name_ja="テストライブ",
        card_type="live",
        score=1,
        required_hearts={"heart01": 1},
    )
    state = _minimal_effect_state(effect)
    for index, name in enumerate(["Live A", "Live B", "Live C"], start=1):
        instance_id = f"same-group-live-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=base_live.model_copy(
                update={
                    "card_code": f"TEST-LIVE-{index}",
                    "card_id": f"TEST-LIVE-{index}",
                    "name_ja": name,
                    "work_keys": ["nijigasaki"],
                }
            ),
        )
        state.players["player_1"].waiting_room.append(instance_id)

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == ["distinct_name_live"]
    with pytest.raises(Exception, match="branch selection is unavailable"):
        _apply_direct(
            state,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_branch": "distinct_group_live",
            },
        )

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "distinct_name_live",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["card_selection_minimum"] == 1
    assert options["card_selection_maximum"] == 1
    assert options["candidate_card_instance_ids"] == [
        "same-group-live-1",
        "same-group-live-2",
        "same-group-live-3",
    ]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["same-group-live-1"],
        },
    )
    assert "same-group-live-1" in state.players["player_1"].hand
    assert not state.pending_effects

    state = _minimal_effect_state(effect)
    for index, work_key in enumerate(
        ["love_live", "love_live_sunshine", "nijigasaki"],
        start=1,
    ):
        instance_id = f"distinct-group-live-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=state_live.model_copy(
                update={
                    "card_code": f"TEST-GROUP-LIVE-{index}",
                    "card_id": f"TEST-GROUP-LIVE-{index}",
                    "name_ja": f"Group Live {index}",
                    "work_keys": [work_key],
                }
            ),
        )
        state.players["player_1"].waiting_room.append(instance_id)

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["available_branch_ids"] == [
        "distinct_name_live",
        "distinct_group_live",
    ]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_branch": "distinct_group_live",
        },
    )
    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["card_selection_minimum"] == 2
    assert options["card_selection_maximum"] == 2
    assert options["candidate_card_instance_ids"] == [
        "distinct-group-live-1",
        "distinct-group-live-2",
        "distinct-group-live-3",
    ]
    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": [
                "distinct-group-live-1",
                "distinct-group-live-2",
            ],
        },
    )
    assert "distinct-group-live-1" in state.players["player_1"].hand
    assert "distinct-group-live-2" in state.players["player_1"].hand
    assert "distinct-group-live-3" in state.players["player_1"].waiting_room
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


def test_multi_player_draw_discard_can_continue_to_stage_member_follow_up():
    state = _minimal_effect_state(_muse_stage_draw_discard_heart_score_effect())
    card = CardDefinition(
        card_code="TEST-CARD",
        card_id="TEST-CARD",
        name_ja="手札カード",
        card_type="member",
    )
    state.cards["p1-old"] = CardInstance(
        instance_id="p1-old",
        owner_id="player_1",
        card=card,
    )
    state.cards["p1-draw"] = CardInstance(
        instance_id="p1-draw",
        owner_id="player_1",
        card=card,
        face_up=False,
    )
    state.cards["p2-old"] = CardInstance(
        instance_id="p2-old",
        owner_id="player_2",
        card=card,
    )
    state.cards["p2-draw"] = CardInstance(
        instance_id="p2-draw",
        owner_id="player_2",
        card=card,
        face_up=False,
    )
    state.players["player_1"].hand = ["p1-old"]
    state.players["player_1"].main_deck = ["p1-draw"]
    state.players["player_2"].hand = ["p2-old"]
    state.players["player_2"].main_deck = ["p2-draw"]
    muse_member = CardDefinition(
        card_code="TEST-MUSE",
        card_id="TEST-MUSE",
        name_ja="高坂穂乃果",
        card_type="member",
        work_keys=["love_live"],
    )
    stage_members = {
        "left": muse_member,
        "center": muse_member.model_copy(update={"name_ja": "南ことり"}),
        "right": muse_member.model_copy(update={"name_ja": "園田海未"}),
    }
    for slot, member in stage_members.items():
        instance_id = f"stage-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=member,
        )
        state.players["player_1"].member_area[slot] = instance_id

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert state.players["player_1"].hand == ["p1-old", "p1-draw"]
    assert state.players["player_2"].hand == ["p2-old", "p2-draw"]
    assert state.pending_choice is not None
    assert state.pending_choice.player_id == "player_1"
    assert state.pending_choice.options["multi_player_choice_type"] == (
        "multi_player_draw_then_discard"
    )
    assert state.pending_choice.options["candidate_card_instance_ids"] == [
        "p1-old",
        "p1-draw",
    ]
    assert state.pending_choice.options["minimum"] == 1

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": ["p1-draw"]},
    )
    assert state.pending_choice.player_id == "player_2"
    assert state.pending_choice.options["candidate_card_instance_ids"] == [
        "p2-old",
        "p2-draw",
    ]

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_ids": ["p2-old"]},
    )
    assert state.pending_choice is None
    assert state.pending_effects[0].resolution_stage == "after_cost"
    assert "p1-draw" in state.players["player_1"].waiting_room
    assert "p2-old" in state.players["player_2"].waiting_room

    options = generate_legal_actions(state)[0].options["invocations"][0]
    assert options["choice_type"] == "member_from_stage"
    assert options["choice_zone"] == "stage"
    assert options["candidate_card_instance_ids"] == [
        "stage-left",
        "stage-center",
        "stage-right",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["stage-center"],
        },
    )

    assert not state.pending_effects
    assert any(
        modifier.modifier_type == "heart"
        and modifier.color_slot == "heart03"
        and modifier.amount == 1
        and modifier.target_card_instance_id == "stage-center"
        for modifier in state.players["player_1"].manual_modifiers
    )
    assert any(
        modifier.modifier_type == "score" and modifier.amount == 1
        for modifier in state.players["player_1"].manual_modifiers
    )


def test_multi_player_draw_discard_finishes_without_follow_up_under_stage_count():
    state = _minimal_effect_state(_muse_stage_draw_discard_heart_score_effect())
    card = CardDefinition(
        card_code="TEST-CARD",
        card_id="TEST-CARD",
        name_ja="手札カード",
        card_type="member",
    )
    for player_id, old_id, draw_id in (
        ("player_1", "p1-old", "p1-draw"),
        ("player_2", "p2-old", "p2-draw"),
    ):
        state.cards[old_id] = CardInstance(
            instance_id=old_id,
            owner_id=player_id,
            card=card,
        )
        state.cards[draw_id] = CardInstance(
            instance_id=draw_id,
            owner_id=player_id,
            card=card,
            face_up=False,
        )
        state.players[player_id].hand = [old_id]
        state.players[player_id].main_deck = [draw_id]
    state.cards["stage-left"] = CardInstance(
        instance_id="stage-left",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-MUSE",
            card_id="TEST-MUSE",
            name_ja="高坂穂乃果",
            card_type="member",
            work_keys=["love_live"],
        ),
    )
    state.players["player_1"].member_area["left"] = "stage-left"

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": ["p1-old"]},
    )
    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_2",
        payload={"selected_card_instance_ids": ["p2-old"]},
    )

    assert state.pending_choice is None
    assert not state.pending_effects
    assert state.players["player_1"].manual_modifiers == []


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


def test_effect_can_deploy_selected_member_from_hand_to_empty_stage():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-hand-deploy:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "a" * 64,
            "effect_index": 1,
            "label_ja": (
                "【登場】【E】【E】支払ってもよい："
                "手札からコスト4以下のメンバーカードを1枚ステージに登場させる。"
            ),
            "effect_type": "triggered",
            "timing": "on_play",
            "trigger": "member_played",
            "execution_mode": "prompt_then_resolve",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {},
            "cost": [],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "hand",
                "card_type": "member",
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
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
    player.hand.append(target)
    state.cards[target].card.cost = 4
    state.cards[target].face_up = False
    player.member_area["right"] = None

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert options["choice_zone"] == "hand"
    assert target in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "accepted": True,
            "selected_card_instance_ids": [target],
            "selected_position_slot": "right",
        },
    )

    assert target not in state.players["player_1"].hand
    assert state.players["player_1"].member_area["right"] == target
    assert state.cards[target].orientation == "wait"
    assert state.cards[target].face_up
    assert state.players["player_1"].member_entered_count_this_turn == 1
    assert "right" in state.players["player_1"].member_areas_entered_this_turn
    assert not state.pending_effects


def test_effect_choice_filters_opponent_member_by_original_blade():
    effect = EffectDefinition.model_validate(
        {
            "effect_id": "test-original-blade:1",
            "card_code": "TEST-MEMBER",
            "text_revision_id": 1,
            "raw_text_hash": "b" * 64,
            "effect_index": 1,
            "label_ja": (
                "【ライブ開始時】相手のステージにいる元々持つ"
                "【ブレード】の数が3つ以下のメンバー1人をウェイトにする。"
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
                "choice_type": "member_from_stage",
                "zone": "stage",
                "target_player": "opponent",
                "card_type": "member",
                "maximum_original_blade": 3,
                "exclude_unit_key": "dollchestra",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "test fixture",
        }
    )
    state = _minimal_effect_state(effect)
    opponent = state.players["player_2"]
    eligible = "opponent-original-blade-3"
    ineligible = "opponent-original-blade-4"
    excluded_unit = "opponent-dollchestra-blade-2"
    base_member = state.cards["deck-member-1"].card
    state.cards[eligible] = CardInstance(
        instance_id=eligible,
        owner_id="player_2",
        card=base_member.model_copy(update={"blade": 3}),
    )
    state.cards[ineligible] = CardInstance(
        instance_id=ineligible,
        owner_id="player_2",
        card=base_member.model_copy(update={"blade": 4}),
    )
    state.cards[excluded_unit] = CardInstance(
        instance_id=excluded_unit,
        owner_id="player_2",
        card=base_member.model_copy(update={"blade": 2, "unit_keys": ["dollchestra"]}),
    )
    opponent.member_area = {"left": eligible, "center": ineligible, "right": excluded_unit}
    opponent.manual_modifiers.append(
        ManualModifier(
            modifier_id="test:blade-minus",
            modifier_type="blade",
            duration="live",
            created_turn=state.turn_number,
            amount=-2,
            target_card_instance_id=ineligible,
        )
    )

    legal = generate_legal_actions(state)
    options = legal[0].options["invocations"][0]
    assert eligible in options["candidate_card_instance_ids"]
    assert ineligible not in options["candidate_card_instance_ids"]
    assert excluded_unit not in options["candidate_card_instance_ids"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": state.pending_effects[0].invocation_id,
            "selected_card_instance_ids": [eligible],
        },
    )

    assert state.cards[eligible].orientation == "wait"
    assert state.cards[ineligible].orientation == "active"
    assert state.cards[excluded_unit].orientation == "active"
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
        first_player_id="player_1",
    )
    return service, result.state.match_id


def test_live_start_yell_count_modifier_reduces_current_yell():
    effect = EffectDefinition(
        effect_id="test-yell-minus:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="y" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】ライブ終了時まで、"
            "エールによって公開される自分のカードの枚数が8枚減る。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_yell_count", "amount": -8}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="エール減少メンバー",
        card_type="member",
        blade=10,
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area = {
        "left": None,
        "center": "source-live",
        "right": None,
    }
    for index in range(10):
        instance_id = f"deck-member-extra-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=source_member.model_copy(
                update={
                    "card_code": f"TEST-DECK-MEMBER-{index}",
                    "card_id": f"TEST-DECK-MEMBER-{index}",
                    "blade": 0,
                }
            ),
            face_up=False,
        )
    state.players["player_1"].main_deck = [
        f"deck-member-extra-{index}" for index in range(10)
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    events: list[GameEvent] = []
    _run_current_yell(state, events)

    assert state.players["player_1"].live_result is not None
    assert state.players["player_1"].live_result.blade_count == 2
    yell_event = next(event for event in events if event.event_type == "yell_completed")
    assert yell_event.data["raw_blade_count"] == 10
    assert yell_event.data["yell_count_modifier"] == -8
    assert len(yell_event.data["revealed_instance_ids"]) == 2


def test_live_start_selected_card_colors_grant_temp_hearts_to_named_member():
    effect = EffectDefinition(
        effect_id="test-kasumi-hearts:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="k" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のデッキの上からカードを4枚公開する。"
            "その中から「中須かすみ」のカードを1枚選ぶ。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_member_name_any": ["中須かすみ"]},
        cost=[],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 4,
            "minimum": 1,
            "maximum": 1,
            "card_type": "member",
            "name_ja_any": ["中須かすみ"],
            "selected_destination": "waiting_room",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": True,
        },
        actions=[
            {
                "action_type": "gain_heart_from_selected_card_colors",
                "target": "selected",
                "value": {"target_stage_member_name_ja": "中須かすみ"},
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    kasumi_stage = CardDefinition(
        card_code="TEST-KASUMI-STAGE",
        card_id="TEST-KASUMI-STAGE",
        name_ja="中須かすみ",
        card_type="member",
    )
    kasumi_deck = kasumi_stage.model_copy(
        update={
            "card_code": "TEST-KASUMI-DECK",
            "card_id": "TEST-KASUMI-DECK",
            "basic_hearts": {"heart02": 2, "heart04": 1},
        }
    )
    other_member = kasumi_stage.model_copy(
        update={
            "card_code": "TEST-OTHER-MEMBER",
            "card_id": "TEST-OTHER-MEMBER",
            "name_ja": "上原歩夢",
            "basic_hearts": {"heart01": 1},
        }
    )
    state.cards["kasumi-stage"] = CardInstance(
        instance_id="kasumi-stage",
        owner_id="player_1",
        card=kasumi_stage,
    )
    state.players["player_1"].member_area = {
        "left": None,
        "center": "kasumi-stage",
        "right": None,
    }
    inspected = ["kasumi-top", "other-top-1", "other-top-2", "other-top-3"]
    for instance_id, card in zip(
        inspected,
        [kasumi_deck, other_member, other_member, other_member],
        strict=True,
    ):
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=card,
            face_up=False,
        )
    state.players["player_1"].main_deck = list(inspected)

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )
    assert state.pending_choice is not None
    assert state.pending_choice.options["candidate_card_instance_ids"] == ["kasumi-top"]

    state = _apply_direct(
        state,
        "resolve_effect_choice",
        player_id="player_1",
        payload={"selected_card_instance_ids": ["kasumi-top"]},
    )

    assert state.pending_choice is None
    assert not state.pending_effects
    assert all(item in state.players["player_1"].waiting_room for item in inspected)
    heart_modifiers = [
        modifier
        for modifier in state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "heart"
    ]
    assert {(modifier.color_slot, modifier.amount) for modifier in heart_modifiers} == {
        ("heart02", 1),
        ("heart04", 1),
    }
    assert all(
        modifier.target_card_instance_id == "kasumi-stage"
        for modifier in heart_modifiers
    )


def test_live_start_reveal_top_matching_member_to_hand_then_position_change():
    effect = EffectDefinition(
        effect_id="test-reveal-cost9-position:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="p" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のデッキの一番上のカードを公開する。"
            "公開したカードがコスト9以下のメンバーカードの場合、"
            "公開したカードを手札に加え、このメンバーはポジションチェンジする。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "reveal_top_matching_to_hand_else_waiting",
                "amount": 1,
                "card_type": "member",
                "value": {"maximum_cost": 9},
            },
            {
                "action_type": "position_change_source",
                "value": {"condition": {"last_revealed_top_matched": True}},
            },
        ],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="ポジションチェンジ元",
        card_type="member",
        cost=3,
    )
    matching_member = source_member.model_copy(
        update={
            "card_code": "TEST-COST9-MEMBER",
            "card_id": "TEST-COST9-MEMBER",
            "name_ja": "公開メンバー",
            "cost": 9,
        }
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area = {
        "left": None,
        "center": "source-live",
        "right": None,
    }
    state.cards["matching-top"] = CardInstance(
        instance_id="matching-top",
        owner_id="player_1",
        card=matching_member,
        face_up=False,
    )
    state.players["player_1"].main_deck = ["matching-top"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    assert "matching-top" in state.players["player_1"].hand
    assert state.cards["matching-top"].face_up is True
    assert state.players["player_1"].member_area["left"] == "source-live"
    assert state.players["player_1"].member_area["center"] is None


def test_live_start_source_attached_member_count_grants_heart05_max_three():
    effect = EffectDefinition(
        effect_id="test-attached-member-heart:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="a" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】ライブ終了時まで、このメンバーの下にある"
            "メンバーカード1枚につき、【heart05】を得る。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "gain_heart",
                "amount_source": "source_attached_member_count",
                "value": {"max": 3},
                "color_slot": "heart05",
            }
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    source_member = CardDefinition(
        card_code="TEST-SOURCE-MEMBER",
        card_id="TEST-SOURCE-MEMBER",
        name_ja="下方参照メンバー",
        card_type="member",
    )
    attached_member = source_member.model_copy(
        update={"card_code": "TEST-ATTACHED-MEMBER", "card_id": "TEST-ATTACHED-MEMBER"}
    )
    attached_energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    state.cards["source-live"].card = source_member
    state.players["player_1"].member_area = {
        "left": None,
        "center": "source-live",
        "right": None,
    }
    attached_ids = [f"attached-member-{index}" for index in range(4)]
    for instance_id in attached_ids:
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=attached_member,
        )
    state.cards["attached-energy"] = CardInstance(
        instance_id="attached-energy",
        owner_id="player_1",
        card=attached_energy,
    )
    state.players["player_1"].member_area_attachments["center"] = [
        *attached_ids,
        "attached-energy",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    heart_modifier = next(
        modifier
        for modifier in state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "heart"
    )
    assert heart_modifier.amount == 3
    assert heart_modifier.color_slot == "heart05"
    assert heart_modifier.target_card_instance_id == "source-live"
    assert heart_modifier.duration == "live"


def test_live_success_aqours_heart05_opponent_no_excess_adds_score():
    effect = EffectDefinition(
        effect_id="test-aqours-no-excess-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="s" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ成功時】自分のステージにいる『Aqours』のメンバーが持つ"
            "ハートに、【heart05】が合計4個以上あり、このターン、相手が"
            "余剰のハートを持たずにライブを成功させていた場合、"
            "このカードのスコアを＋２する。"
        ),
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_heart_at_least": {
                "color_slot": "heart05",
                "count": 4,
                "unit_key": "aqours",
            },
            "opponent_success_excess_heart_count_at_most": 0,
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 2}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    aqours_member = CardDefinition(
        card_code="TEST-AQOURS-MEMBER",
        card_id="TEST-AQOURS-MEMBER",
        name_ja="Aqours member",
        card_type="member",
        unit_keys=["aqours"],
        basic_hearts={"heart05": 2},
    )
    for index, slot in enumerate(["left", "center"], start=1):
        instance_id = f"aqours-member-{index}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=aqours_member,
        )
        state.players["player_1"].member_area[slot] = instance_id
    state.players["player_2"].live_result.requirements_satisfied = True
    state.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {}, "remaining_all_color_hearts": 0}
    ]

    resolved = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    score_modifier = next(
        modifier
        for modifier in resolved.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    )
    assert score_modifier.amount == 2
    assert score_modifier.duration == "live"

    blocked = state.model_copy(deep=True)
    blocked.players["player_2"].live_result.live_allocations = [
        {"remaining_hearts": {"heart05": 1}, "remaining_all_color_hearts": 0}
    ]
    with pytest.raises(Exception, match="opponent_excess_heart_count_too_high"):
        _apply_direct(
            blocked,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )

    not_successful = state.model_copy(deep=True)
    not_successful.players["player_2"].live_result.requirements_satisfied = False
    with pytest.raises(Exception, match="opponent_live_not_successful"):
        _apply_direct(
            not_successful,
            "resolve_effect",
            player_id="player_1",
            payload={"invocation_id": "inv-1"},
        )


def test_live_start_opponent_wait_count_returns_nijigasaki_members_to_deck_top():
    effect = EffectDefinition(
        effect_id="test-nijigasaki-top:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="n" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】相手のステージにいるウェイト状態のメンバーの数まで、"
            "自分の控え室にある『虹ヶ咲』のメンバーカードを選ぶ。"
            "それらを好きな順番でデッキの上に置く。"
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
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "member",
            "work_key": "nijigasaki",
            "minimum": 0,
            "maximum": 3,
            "amount_source": "opponent_stage_wait_member_count",
            "requires_order": True,
        },
        actions=[{"action_type": "move_selected_to_deck_top"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    niji_member = CardDefinition(
        card_code="TEST-NIJI-MEMBER",
        card_id="TEST-NIJI-MEMBER",
        name_ja="虹ヶ咲メンバー",
        card_type="member",
        work_keys=["nijigasaki"],
    )
    other_member = niji_member.model_copy(
        update={
            "card_code": "TEST-OTHER-MEMBER",
            "card_id": "TEST-OTHER-MEMBER",
            "work_keys": ["love_live"],
        }
    )
    opponent_member = CardDefinition(
        card_code="TEST-OPPONENT-MEMBER",
        card_id="TEST-OPPONENT-MEMBER",
        name_ja="相手メンバー",
        card_type="member",
    )
    for instance_id, card in {
        "niji-1": niji_member,
        "niji-2": niji_member,
        "niji-3": niji_member,
        "other-wr": other_member,
    }.items():
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=card,
        )
        state.players["player_1"].waiting_room.append(instance_id)
    for slot in ["left", "center"]:
        instance_id = f"opponent-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_2",
            card=opponent_member,
            orientation="wait",
        )
        state.players["player_2"].member_area[slot] = instance_id

    legal = generate_legal_actions(state)
    invocation_options = legal[0].options["invocations"][0]
    assert invocation_options["card_selection_minimum"] == 0
    assert invocation_options["card_selection_maximum"] == 2
    assert invocation_options["candidate_card_instance_ids"] == [
        "niji-1",
        "niji-2",
        "niji-3",
    ]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["niji-2", "niji-1"],
        },
    )

    assert state.players["player_1"].main_deck[:2] == ["niji-2", "niji-1"]
    assert "niji-2" not in state.players["player_1"].waiting_room
    assert "niji-1" not in state.players["player_1"].waiting_room
    assert "niji-3" in state.players["player_1"].waiting_room
    assert "other-wr" in state.players["player_1"].waiting_room


def test_onplay_baton_non_kachimachi_hasunosora_returns_live():
    effect = EffectDefinition(
        effect_id="test-hasu-baton-return-live:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="b" * 64,
        effect_index=1,
        label_ja=(
            "【登場】「徒町小鈴」以外の『蓮ノ空』のメンバーから"
            "バトンタッチして登場した場合、自分の控え室からライブカードを1枚手札に加える。"
        ),
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_work_key": "hasunosora",
            "replacement_member_name_ja_not": "徒町小鈴",
        },
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    state.pending_effects[0].trigger_data = {
        "used_baton_touch": True,
        "replacement_card_instance_id": "replaced-member",
    }
    replaced_member = CardDefinition(
        card_code="TEST-HASU-MEMBER",
        card_id="TEST-HASU-MEMBER",
        name_ja="村野さやか",
        card_type="member",
        work_keys=["hasunosora"],
    )
    live = CardDefinition(
        card_code="TEST-HASU-LIVE",
        card_id="TEST-HASU-LIVE",
        name_ja="ライブ",
        card_type="live",
    )
    state.cards["replaced-member"] = CardInstance(
        instance_id="replaced-member",
        owner_id="player_1",
        card=replaced_member,
    )
    state.cards["waiting-live"] = CardInstance(
        instance_id="waiting-live",
        owner_id="player_1",
        card=live,
    )
    state.players["player_1"].waiting_room = ["replaced-member", "waiting-live"]

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={
            "invocation_id": "inv-1",
            "selected_card_instance_ids": ["waiting-live"],
        },
    )

    assert "waiting-live" in state.players["player_1"].hand
    assert "waiting-live" not in state.players["player_1"].waiting_room

    forbidden = _minimal_effect_state(effect)
    forbidden.pending_effects[0].trigger_data = {
        "used_baton_touch": True,
        "replacement_card_instance_id": "replaced-member",
    }
    forbidden.cards["replaced-member"] = CardInstance(
        instance_id="replaced-member",
        owner_id="player_1",
        card=replaced_member.model_copy(update={"name_ja": "徒町 小鈴"}),
    )
    forbidden.cards["waiting-live"] = CardInstance(
        instance_id="waiting-live",
        owner_id="player_1",
        card=live,
    )
    forbidden.players["player_1"].waiting_room = ["replaced-member", "waiting-live"]
    with pytest.raises(Exception, match="replacement_member_name_forbidden"):
        _apply_direct(
            forbidden,
            "resolve_effect",
            player_id="player_1",
            payload={
                "invocation_id": "inv-1",
                "selected_card_instance_ids": ["waiting-live"],
            },
        )


def test_live_start_slot_name_condition_ignores_name_spacing_for_score_modifier():
    effect = EffectDefinition(
        effect_id="test-miracreation-score:1",
        card_code="PL!HS-bp2-026",
        text_revision_id=1,
        raw_text_hash="m" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のステージの左に「安養寺姫芽」、中央に"
            "「藤島慈」、右に「大沢瑠璃乃」がいる場合、このカードのスコアを＋２する。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="auto_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_slot_names": {
                "left": "安養寺 姫芽",
                "center": "藤島 慈",
                "right": "大沢 瑠璃乃",
            }
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 2}],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )
    state = _minimal_effect_state(effect)
    for slot, name_ja in {
        "left": "安養寺姫芽",
        "center": "藤島慈",
        "right": "大沢瑠璃乃",
    }.items():
        instance_id = f"stage-{slot}"
        state.cards[instance_id] = CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=f"TEST-{slot}",
                card_id=f"TEST-{slot}",
                name_ja=name_ja,
                card_type="member",
            ),
        )
        state.players["player_1"].member_area[slot] = instance_id

    state = _apply_direct(
        state,
        "resolve_effect",
        player_id="player_1",
        payload={"invocation_id": "inv-1"},
    )

    score_modifier = next(
        modifier
        for modifier in state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    )
    assert score_modifier.amount == 2
    assert score_modifier.duration == "live"


def test_hime_cost_reduction_uses_miracra_stage_members():
    cost_effect = EffectDefinition(
        effect_id="test-hime-cost:1",
        card_code="PL!HS-bp6-006",
        text_revision_id=43,
        raw_text_hash="a" * 64,
        effect_index=1,
        label_ja=(
            "【常時】手札にあるこのメンバーカードのコストは、"
            "自分のステージにいる『みらくらぱーく！』のメンバー1人につき、"
            "2少なくなる。"
        ),
        effect_type="static",
        trigger="static_always",
        timing="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
        actions=[
            {
                "action_type": "reduce_play_cost",
                "amount_source": "own_stage_member_unit_count",
                "multiplier": 2,
                "value": {"unit_key": "miracra_park"},
            }
        ],
    )
    hime = CardDefinition(
        card_code="PL!HS-bp6-006",
        card_id="PL!HS-bp6-006",
        name_ja="安養寺姫芽",
        card_type="member",
        cost=20,
        unit_keys=["miracra_park"],
        effect_ids=[cost_effect.effect_id],
    )
    miracra = CardDefinition(
        card_code="TEST-MIRACRA",
        card_id="TEST-MIRACRA",
        name_ja="みらくらぱーく！テスト",
        card_type="member",
        cost=2,
        unit_keys=["miracra_park"],
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    cards = {
        "hime-hand": CardInstance(
            instance_id="hime-hand",
            owner_id="player_1",
            card=hime,
        ),
        **{
            f"stage-{slot}": CardInstance(
                instance_id=f"stage-{slot}",
                owner_id="player_1",
                card=miracra.model_copy(
                    update={
                        "card_code": f"TEST-MIRACRA-{slot}",
                        "card_id": f"TEST-MIRACRA-{slot}",
                    }
                ),
            )
            for slot in ("left", "center", "right")
        },
        **{
            f"energy-{index}": CardInstance(
                instance_id=f"energy-{index}",
                owner_id="player_1",
                card=energy,
                orientation="active",
            )
            for index in range(14)
        },
    }
    state = MatchState(
        match_id="hime-cost",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                hand=["hime-hand"],
                member_area={
                    "left": "stage-left",
                    "center": "stage-center",
                    "right": "stage-right",
                },
                energy_area=[f"energy-{index}" for index in range(14)],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={cost_effect.effect_id: cost_effect},
    )

    play_action = next(
        action
        for action in generate_legal_actions(state)
        if action.action_type == "play_member"
    )
    placement = next(
        item
        for item in play_action.options["placements"]
        if item["card_instance_id"] == "hime-hand"
        and item["slot"] == "center"
        and not item["use_baton_touch"]
    )
    assert placement["printed_member_cost"] == 20
    assert placement["new_member_cost"] == 14
    assert placement["payment_cost"] == 14

    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": "hime-hand",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": [f"energy-{index}" for index in range(14)],
            },
        ),
    )

    assert result.state.players["player_1"].member_area["center"] == "hime-hand"
    assert sum(
        result.state.cards[f"energy-{index}"].orientation == "wait"
        for index in range(14)
    ) == 14


def test_success_live_music_start_reduces_cost17_muse_member_baton_cost():
    cost_effect = EffectDefinition(
        effect_id="test-music-start-cost:1",
        card_code="PL!-bp6-019",
        text_revision_id=61,
        raw_text_hash="8e55b7ca25975ca9d35b7cc355abc2cf9ba58564bfdda17a0888ad7c5dc32f91",
        effect_index=1,
        label_ja=(
            "【常時】このカードが自分の成功ライブカード置き場にあるかぎり、"
            "元々のコストが17以上の『μ's』のメンバーカードを"
            "自分の手札から登場させるためのコストは2減る。"
            "この効果は重複しない。"
        ),
        effect_type="static",
        trigger="static_always",
        timing="static_always",
        execution_mode="auto_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={"source_zone": "success_live_area"},
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
        actions=[
            {
                "action_type": "reduce_play_cost",
                "amount": 2,
                "value": {
                    "non_stackable_key": "pl_bp6_019_muse_cost17_play_cost",
                    "target_filter": {
                        "card_code_prefixes": ["PL!-"],
                        "card_type": "member",
                        "exclude_unit_key": "a_rise",
                        "minimum_original_cost": 17,
                        "work_key": "love_live",
                    },
                },
            }
        ],
    )
    music_start = CardDefinition(
        card_code="PL!-bp6-019",
        card_id="PL!-bp6-019-L",
        name_ja="Music S.T.A.R.T!!",
        card_type="live",
        score=2,
        work_keys=["love_live"],
        effect_ids=[cost_effect.effect_id],
    )
    maki = CardDefinition(
        card_code="PL!-bp6-006",
        card_id="PL!-bp6-006-R",
        name_ja="西木野真姫",
        card_type="member",
        cost=17,
        work_keys=["love_live"],
        unit_keys=["bibi"],
    )
    cross_title_member = CardDefinition(
        card_code="LL-bp3-001",
        card_id="LL-bp3-001",
        name_ja="園田海未&津島善子&天王寺璃奈",
        card_type="member",
        cost=17,
        work_keys=["love_live"],
    )
    replaced = CardDefinition(
        card_code="TEST-REPLACED",
        card_id="TEST-REPLACED",
        name_ja="交代元",
        card_type="member",
        cost=13,
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    cards = {
        "music-start-1": CardInstance(
            instance_id="music-start-1",
            owner_id="player_1",
            card=music_start,
        ),
        "music-start-2": CardInstance(
            instance_id="music-start-2",
            owner_id="player_1",
            card=music_start.model_copy(update={"card_id": "PL!-bp6-019-L-2"}),
        ),
        "maki-hand": CardInstance(
            instance_id="maki-hand",
            owner_id="player_1",
            card=maki,
        ),
        "cross-title-hand": CardInstance(
            instance_id="cross-title-hand",
            owner_id="player_1",
            card=cross_title_member,
        ),
        "stage-center": CardInstance(
            instance_id="stage-center",
            owner_id="player_1",
            card=replaced,
        ),
        **{
            f"energy-{index}": CardInstance(
                instance_id=f"energy-{index}",
                owner_id="player_1",
                card=energy,
                orientation="active",
            )
            for index in range(2)
        },
    }
    state = MatchState(
        match_id="music-start-cost",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                hand=["maki-hand", "cross-title-hand"],
                member_area={"left": None, "center": "stage-center", "right": None},
                energy_area=["energy-0", "energy-1"],
                success_live_area=["music-start-1", "music-start-2"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions={cost_effect.effect_id: cost_effect},
    )

    play_action = next(
        action
        for action in generate_legal_actions(state)
        if action.action_type == "play_member"
    )
    maki_baton = next(
        item
        for item in play_action.options["placements"]
        if item["card_instance_id"] == "maki-hand"
        and item["slot"] == "center"
        and item["use_baton_touch"]
    )
    assert maki_baton["printed_member_cost"] == 17
    assert maki_baton["new_member_cost"] == 15
    assert maki_baton["replaced_member_cost"] == 13
    assert maki_baton["payment_cost"] == 2
    assert not any(
        item["card_instance_id"] == "cross-title-hand" and item["use_baton_touch"]
        for item in play_action.options["placements"]
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": "maki-hand",
                "slot": "center",
                "use_baton_touch": True,
                "energy_instance_ids": ["energy-0", "energy-1"],
            },
        ),
    )

    assert result.state.players["player_1"].member_area["center"] == "maki-hand"
    assert sum(
        result.state.cards[f"energy-{index}"].orientation == "wait"
        for index in range(2)
    ) == 2


def test_static_play_cost_reducers_cover_hand_success_stage_and_moved_conditions():
    effects = [
        EffectDefinition(
            effect_id="test-ll-hand-count-cost:1",
            card_code="LL-bp2-001",
            text_revision_id=592,
            raw_text_hash="d" * 64,
            effect_index=1,
            label_ja="【常時】手札にあるこのメンバーカードのコストは、このカード以外の自分の手札1枚につき、1少なくなる。",
            effect_type="static",
            trigger="static_always",
            timing="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_zone": "hand"},
            actions=[
                {
                    "action_type": "reduce_play_cost",
                    "amount_source": "own_other_hand_count",
                    "value": {"target_filter": {"card_code": "LL-bp2-001"}},
                }
            ],
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        ),
        EffectDefinition(
            effect_id="test-lily-white-success-cost:1",
            card_code="PL!-pb1-014",
            text_revision_id=429,
            raw_text_hash="e" * 64,
            effect_index=1,
            label_ja="【常時】自分の成功ライブカード置き場に『lily white』のカードがある場合、手札にあるこのメンバーカードのコストは2減る。",
            effect_type="static",
            trigger="static_always",
            timing="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={
                "source_zone": "hand",
                "success_live_unit_count_at_least": {
                    "unit_key": "lily_white",
                    "count": 1,
                },
            },
            actions=[
                {
                    "action_type": "reduce_play_cost",
                    "amount": 2,
                    "value": {"target_filter": {"card_code": "PL!-pb1-014"}},
                }
            ],
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        ),
        EffectDefinition(
            effect_id="test-no-ability-play-cost:2",
            card_code="PL!S-bp5-001",
            text_revision_id=164,
            raw_text_hash="f" * 64,
            effect_index=2,
            label_ja="【常時】能力を持たないメンバーカードを自分の手札から登場させるためのコストは1減る。",
            effect_type="static",
            trigger="static_always",
            timing="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_zone": "stage"},
            actions=[
                {
                    "action_type": "reduce_play_cost",
                    "amount": 1,
                    "value": {
                        "target_filter": {
                            "card_type": "member",
                            "ability_bucket": "none",
                        }
                    },
                }
            ],
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        ),
        EffectDefinition(
            effect_id="test-liella-cost10-play-cost:1",
            card_code="PL!SP-bp5-003",
            text_revision_id=208,
            raw_text_hash="1" * 64,
            effect_index=1,
            label_ja="【常時】コスト10の『Liella!』のメンバーカードを自分の手札から登場させるためのコストは2減る。",
            effect_type="static",
            trigger="static_always",
            timing="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={"source_zone": "stage"},
            actions=[
                {
                    "action_type": "reduce_play_cost",
                    "amount": 2,
                    "value": {
                        "target_filter": {
                            "card_type": "member",
                            "original_cost": 10,
                            "work_key": "love_live_superstar",
                        }
                    },
                }
            ],
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        ),
        EffectDefinition(
            effect_id="test-moved-liella-cost:1",
            card_code="PL!SP-bp5-017",
            text_revision_id=222,
            raw_text_hash="2" * 64,
            effect_index=1,
            label_ja="【常時】自分のステージにいる『Liella!』のメンバーがこのターンにエリアを移動しているかぎり、手札にあるこのメンバーカードのコストは2減る。",
            effect_type="static",
            trigger="static_always",
            timing="static_always",
            execution_mode="auto_resolve",
            frequency_limit="none",
            is_optional=False,
            condition={
                "source_zone": "hand",
                "own_stage_member_moved_this_turn": {
                    "card_type": "member",
                    "work_key": "love_live_superstar",
                },
            },
            actions=[
                {
                    "action_type": "reduce_play_cost",
                    "amount": 2,
                    "value": {"target_filter": {"card_code": "PL!SP-bp5-017"}},
                }
            ],
            simulation_support="test_validated_executable",
            review_status="test_validated",
            source_reference="test",
        ),
    ]
    effect_map = {effect.effect_id: effect for effect in effects}
    cards = {
        "ll-hand": CardInstance(
            instance_id="ll-hand",
            owner_id="player_1",
            card=CardDefinition(
                card_code="LL-bp2-001",
                card_id="LL-bp2-001",
                name_ja="渡辺 曜&鬼塚夏美&大沢瑠璃乃",
                card_type="member",
                cost=20,
                ability_bucket="other",
                effect_ids=["test-ll-hand-count-cost:1"],
            ),
        ),
        "lily-hand": CardInstance(
            instance_id="lily-hand",
            owner_id="player_1",
            card=CardDefinition(
                card_code="PL!-pb1-014",
                card_id="PL!-pb1-014",
                name_ja="星空 凛",
                card_type="member",
                cost=15,
                ability_bucket="other",
                effect_ids=["test-lily-white-success-cost:1"],
            ),
        ),
        "no-ability-hand": CardInstance(
            instance_id="no-ability-hand",
            owner_id="player_1",
            card=CardDefinition(
                card_code="TEST-NO-ABILITY",
                card_id="TEST-NO-ABILITY",
                name_ja="能力なし",
                card_type="member",
                cost=4,
                ability_bucket="none",
            ),
        ),
        "liella-cost10-hand": CardInstance(
            instance_id="liella-cost10-hand",
            owner_id="player_1",
            card=CardDefinition(
                card_code="TEST-LIELLA-10",
                card_id="TEST-LIELLA-10",
                name_ja="Liella! cost10",
                card_type="member",
                cost=10,
                work_keys=["love_live_superstar"],
                ability_bucket="other",
            ),
        ),
        "moved-cost-hand": CardInstance(
            instance_id="moved-cost-hand",
            owner_id="player_1",
            card=CardDefinition(
                card_code="PL!SP-bp5-017",
                card_id="PL!SP-bp5-017",
                name_ja="桜小路きな子",
                card_type="member",
                cost=9,
                work_keys=["love_live_superstar"],
                ability_bucket="other",
                effect_ids=["test-moved-liella-cost:1"],
            ),
        ),
        "stage-no-ability-source": CardInstance(
            instance_id="stage-no-ability-source",
            owner_id="player_1",
            card=CardDefinition(
                card_code="PL!S-bp5-001",
                card_id="PL!S-bp5-001",
                name_ja="高海千歌",
                card_type="member",
                cost=10,
                work_keys=["love_live_sunshine"],
                effect_ids=["test-no-ability-play-cost:2"],
            ),
        ),
        "stage-liella-source": CardInstance(
            instance_id="stage-liella-source",
            owner_id="player_1",
            card=CardDefinition(
                card_code="PL!SP-bp5-003",
                card_id="PL!SP-bp5-003",
                name_ja="嵐 千砂都",
                card_type="member",
                cost=17,
                work_keys=["love_live_superstar"],
                effect_ids=["test-liella-cost10-play-cost:1"],
            ),
        ),
        "success-lily-live": CardInstance(
            instance_id="success-lily-live",
            owner_id="player_1",
            card=CardDefinition(
                card_code="TEST-LILY-LIVE",
                card_id="TEST-LILY-LIVE",
                name_ja="lily white Live",
                card_type="live",
                score=1,
                unit_keys=["lily_white"],
            ),
        ),
        "filler-live-1": CardInstance(
            instance_id="filler-live-1",
            owner_id="player_1",
            card=CardDefinition(
                card_code="TEST-FILLER-LIVE-1",
                card_id="TEST-FILLER-LIVE-1",
                name_ja="フィラー1",
                card_type="live",
            ),
        ),
        "filler-live-2": CardInstance(
            instance_id="filler-live-2",
            owner_id="player_1",
            card=CardDefinition(
                card_code="TEST-FILLER-LIVE-2",
                card_id="TEST-FILLER-LIVE-2",
                name_ja="フィラー2",
                card_type="live",
            ),
        ),
        **{
            f"energy-{index}": CardInstance(
                instance_id=f"energy-{index}",
                owner_id="player_1",
                card=CardDefinition(
                    card_code="TEST-ENERGY",
                    card_id="TEST-ENERGY",
                    name_ja="エネルギー",
                    card_type="energy",
                ),
                orientation="active",
            )
            for index in range(20)
        },
    }
    player = PlayerState(
        player_id="player_1",
        name="Player 1",
        hand=[
            "ll-hand",
            "lily-hand",
            "no-ability-hand",
            "liella-cost10-hand",
            "moved-cost-hand",
            "filler-live-1",
            "filler-live-2",
        ],
        member_area={
            "left": None,
            "center": "stage-no-ability-source",
            "right": "stage-liella-source",
        },
        energy_area=[f"energy-{index}" for index in range(20)],
        success_live_area=["success-lily-live"],
        member_areas_moved_this_turn=["right"],
    )
    state = MatchState(
        match_id="static-cost-reducers",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": player,
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards=cards,
        effect_definitions=effect_map,
    )

    play_action = next(
        action
        for action in generate_legal_actions(state)
        if action.action_type == "play_member"
    )
    costs = {
        item["card_instance_id"]: item["new_member_cost"]
        for item in play_action.options["placements"]
        if item["slot"] == "left" and not item["use_baton_touch"]
    }

    assert costs["ll-hand"] == 14
    assert costs["lily-hand"] == 13
    assert costs["no-ability-hand"] == 3
    assert costs["liella-cost10-hand"] == 8
    assert costs["moved-cost-hand"] == 7


def test_hime_live_success_waits_and_skips_next_active_ready():
    effect = EffectDefinition(
        effect_id="test-hime-live-success:3",
        card_code="PL!HS-bp6-006",
        text_revision_id=43,
        raw_text_hash="a" * 64,
        effect_index=3,
        label_ja="【ライブ成功時】このメンバーをウェイトにし、次のターンのアクティブフェイズにアクティブしない。",
        effect_type="triggered",
        trigger="live_succeeded",
        timing="live_success",
        execution_mode="auto_resolve",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        is_optional=False,
        source_reference="test",
        duration="game",
        frequency_limit="once_per_live",
        actions=[
            {"action_type": "apply_wait_member", "target": "source"},
            {
                "action_type": "set_flag",
                "target": "source",
                "flag": "skip_next_active_phase_ready",
                "value": {"reason": "PL!HS-bp6-006 live success"},
            },
        ],
    )
    hime = CardDefinition(
        card_code="PL!HS-bp6-006",
        card_id="PL!HS-bp6-006",
        name_ja="安養寺姫芽",
        card_type="member",
        effect_ids=[effect.effect_id],
    )
    live = CardDefinition(
        card_code="TEST-LIVE",
        card_id="TEST-LIVE",
        name_ja="ライブ",
        card_type="live",
        score=1,
    )
    state = MatchState(
        match_id="hime-live-success",
        seed=1,
        phase="live_judgment",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area={"left": None, "center": "hime-stage", "right": None},
                success_live_area=["successful-live"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "hime-stage": CardInstance(
                instance_id="hime-stage",
                owner_id="player_1",
                card=hime,
                orientation="active",
            ),
            "successful-live": CardInstance(
                instance_id="successful-live",
                owner_id="player_1",
                card=live,
            ),
        },
        effect_definitions={effect.effect_id: effect},
        success_live_moved_instance_ids={"player_1": ["successful-live"]},
    )
    events: list[GameEvent] = []

    _queue_live_success_effects(state, events)
    _resolve_automatic_effects(state, events)

    assert state.pending_effects == []
    assert state.cards["hime-stage"].orientation == "wait"
    assert any(
        modifier.modifier_type == "flag"
        and modifier.flag == "skip_next_active_phase_ready"
        and modifier.target_card_instance_id == "hime-stage"
        for modifier in state.players["player_1"].manual_modifiers
    )

    state.phase = "first_active"
    ready_result = apply_action(
        state,
        ActionRequest(
            action_type="advance_phase",
            expected_revision=state.revision,
            player_id="player_1",
            payload={},
        ),
    )

    assert ready_result.state.cards["hime-stage"].orientation == "wait"
    assert not ready_result.state.players["player_1"].manual_modifiers
    ready_event = next(
        event for event in ready_result.events if event.event_type == "cards_readied"
    )
    assert ready_event.data["skipped_instance_ids"] == ["hime-stage"]


def test_member_played_by_baton_cannot_baton_touch_again_after_position_change():
    member = CardDefinition(
        card_code="TEST-MEMBER",
        card_id="TEST-MEMBER",
        name_ja="元メンバー",
        card_type="member",
        cost=1,
    )
    first_baton = CardDefinition(
        card_code="TEST-FIRST-BATON",
        card_id="TEST-FIRST-BATON",
        name_ja="一度目バトン",
        card_type="member",
        cost=2,
    )
    second_baton = CardDefinition(
        card_code="TEST-SECOND-BATON",
        card_id="TEST-SECOND-BATON",
        name_ja="二度目バトン",
        card_type="member",
        cost=3,
    )
    energy = CardDefinition(
        card_code="TEST-ENERGY",
        card_id="TEST-ENERGY",
        name_ja="エネルギー",
        card_type="energy",
    )
    state = MatchState(
        match_id="baton-repeat",
        seed=1,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                hand=["first-baton", "second-baton"],
                member_area={"left": None, "center": "old-member", "right": None},
                energy_area=["energy-0", "energy-1", "energy-2"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={
            "old-member": CardInstance(
                instance_id="old-member",
                owner_id="player_1",
                card=member,
            ),
            "first-baton": CardInstance(
                instance_id="first-baton",
                owner_id="player_1",
                card=first_baton,
            ),
            "second-baton": CardInstance(
                instance_id="second-baton",
                owner_id="player_1",
                card=second_baton,
            ),
            **{
                f"energy-{index}": CardInstance(
                    instance_id=f"energy-{index}",
                    owner_id="player_1",
                    card=energy,
                    orientation="active",
                )
                for index in range(3)
            },
        },
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="play_member",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "card_instance_id": "first-baton",
                "slot": "center",
                "use_baton_touch": True,
                "energy_instance_ids": ["energy-0"],
            },
        ),
    )
    state = result.state
    assert state.players["player_1"].member_instance_ids_baton_entered_this_turn == [
        "first-baton"
    ]

    state = apply_action(
        state,
        ActionRequest(
            action_type="manual_adjustment",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "reason": "move Baton-entered member to reproduce repeat Baton",
                "adjustments": [
                    {
                        "adjustment_type": "position_change",
                        "target_player_id": "player_1",
                        "from_slot": "center",
                        "to_slot": "left",
                    }
                ],
            },
        ),
    ).state
    placements = next(
        (
            action.options["placements"]
            for action in generate_legal_actions(state)
            if action.action_type == "play_member"
        ),
        [],
    )
    assert not any(
        item["slot"] == "left" and item["use_baton_touch"] for item in placements
    )

    with pytest.raises(IllegalActionError, match="cannot Baton Touch again"):
        apply_action(
            state,
            ActionRequest(
                action_type="play_member",
                expected_revision=state.revision,
                player_id="player_1",
                payload={
                    "card_instance_id": "second-baton",
                    "slot": "left",
                    "use_baton_touch": True,
                    "energy_instance_ids": ["energy-1"],
                },
            ),
        )


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


def _bulk_waiting_members_to_bottom_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-bulk-waiting-members-bottom:1",
        card_code="TEST-MEMBER",
        text_revision_id=1,
        raw_text_hash="b" * 64,
        effect_index=1,
        label_ja=(
            "【登場】自分と相手はそれぞれ、自身の控え室にあるすべての"
            "メンバーカードをシャッフルし、自身のデッキの下に置く。"
            "これにより自分と相手のカードが合計20枚以上デッキの下に置かれた場合、"
            "自分の控え室からライブカードを1枚手札に加え、"
            "ライブ終了時まで、【ブレード】【ブレード】を得る。"
        ),
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum": 1,
            "maximum": 1,
            "post_action_condition_key": "bulk_moved_waiting_room_member_count",
            "post_action_condition_minimum": 20,
        },
        actions=[
            {
                "action_type": "move_waiting_room_members_to_deck_bottom",
                "target": "both",
            },
            {"action_type": "return_from_waiting_room"},
            {"action_type": "gain_blade", "amount": 2},
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _muse_stage_draw_discard_heart_score_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-muse-draw-discard-heart-score:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="m" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のステージにメンバーが1人以上いる場合、"
            "自分と相手はカードを1枚引き、手札を1枚控え室に置く。"
            "2人以上いる場合、さらに自分のステージにいる『μ's』のメンバー1人は、"
            "ライブ終了時まで、【heart03】を得る。"
            "3人以上おり、かつそれぞれ名前が異なる場合、さらにこのカードのスコアを＋１する。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_member_count_at_least": 1},
        cost=[],
        choice={
            "choice_type": "multi_player_draw_then_discard",
            "zone": "hand",
            "amount": 1,
            "discard_amount": 1,
        },
        follow_up_choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "card_type": "member",
            "work_key": "love_live",
            "minimum": 1,
            "maximum": 1,
            "condition": {"own_stage_member_count_at_least": 2},
        },
        actions=[
            {
                "action_type": "gain_heart",
                "target": "selected",
                "amount": 1,
                "color_slot": "heart03",
                "value": {"condition": {"own_stage_member_count_at_least": 2}},
            },
            {
                "action_type": "modify_score",
                "amount": 1,
                "value": {
                    "condition": {
                        "own_stage_member_distinct_name_count_at_least": 3
                    }
                },
            },
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _all_aqours_draw_top_or_bottom_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-all-aqours-draw-top-bottom:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="o" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】自分のステージにいるメンバーがすべて"
            "『Aqours』の場合、このカードのスコアを＋１し、"
            "カードを1枚引き、手札からカードを1枚デッキの一番上か一番下に置く。"
        ),
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_members_only_work_key": "love_live_sunshine"},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
            "destination_options": ["main_deck_top", "main_deck_bottom"],
        },
        actions=[
            {"action_type": "modify_score", "amount": 1},
            {"action_type": "draw_card", "amount": 1},
            {"action_type": "move_selected_to_deck_top_or_bottom"},
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test fixture",
    )


def _aqours_live_start_branch_effect() -> EffectDefinition:
    return EffectDefinition(
        effect_id="test-aqours-branch:1",
        card_code="TEST-LIVE",
        text_revision_id=1,
        raw_text_hash="n" * 64,
        effect_index=1,
        label_ja=(
            "【ライブ開始時】以下から1つを選ぶ。 "
            "・このカードは「【ライブ成功時】カードを1枚引く。」を得る。 "
            "・ライブ終了時まで、このターンにバトンタッチして登場した"
            "『Aqours』のメンバー1人は【heart02】を得る。 "
            "・自分の成功ライブカード置き場にカードが2枚以上ある場合、"
            "このカードのスコアを＋１する。"
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
            "branch_ids": [
                "grant_success_draw",
                "baton_aqours_heart",
                "success2_score",
            ],
            "branch_selection_minimum": {"baton_aqours_heart": 1},
            "branch_selection_maximum": {"baton_aqours_heart": 1},
            "branch_conditions": {
                "success2_score": {"success_live_count_at_least": 2}
            },
            "branch_choice_filters": {
                "baton_aqours_heart": {
                    "choice_type": "member_from_stage",
                    "zone": "stage",
                    "card_type": "member",
                    "work_key": "love_live_sunshine",
                    "target_player": "self",
                    "baton_entered_this_turn": True,
                }
            },
        },
        actions=[
            {
                "action_type": "grant_live_success_draw",
                "amount": 1,
                "branch": "grant_success_draw",
            },
            {
                "action_type": "gain_heart",
                "target": "selected",
                "amount": 1,
                "color_slot": "heart02",
                "branch": "baton_aqours_heart",
            },
            {
                "action_type": "modify_score",
                "amount": 1,
                "branch": "success2_score",
            },
        ],
        duration="live",
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
