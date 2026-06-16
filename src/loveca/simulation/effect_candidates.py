"""Exact-text effect registry candidate discovery.

The candidate generator is deliberately conservative: it only recognizes
source-confirmed Japanese text patterns that the restricted executor already
knows how to resolve.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loveca.db.bootstrap import connect_database
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY, load_effect_registry

SOURCE_REFERENCE = (
    "Official card text; comprehensive rules ver. 1.06 restricted executor pattern"
)


@dataclass(frozen=True)
class EffectCandidate:
    effect_id: str
    card_code: str
    text_revision_id: int
    raw_text_hash: str
    effect_index: int
    label_ja: str
    effect_type: str
    timing: str
    trigger: str
    execution_mode: str
    frequency_limit: str
    is_optional: bool
    condition: dict[str, Any]
    cost: list[dict[str, Any]]
    choice: dict[str, Any] | None
    actions: list[dict[str, Any]]
    duration: str | None
    simulation_support: str
    review_status: str
    source_reference: str
    pattern_id: str
    already_registered: bool = False
    cost_choice: dict[str, Any] | None = None

    def to_registry_entry(self) -> dict[str, Any]:
        payload = self.__dict__.copy()
        payload.pop("pattern_id")
        payload.pop("already_registered")
        return payload


def discover_effect_candidates(
    database_path: Path,
    *,
    registry_path: Path = DEFAULT_EFFECT_REGISTRY,
    include_registered: bool = False,
) -> list[EffectCandidate]:
    registry = load_effect_registry(registry_path)
    registered = {
        (effect.card_code, effect.raw_text_hash, effect.effect_index)
        for effect in registry.effects
    }
    registered_ids = {effect.effect_id for effect in registry.effects}
    emitted_ids: set[str] = set()
    candidates: list[EffectCandidate] = []
    with connect_database(database_path) as connection:
        for row in _effect_text_rows(connection):
            for pattern in _PATTERNS:
                candidate = pattern(row)
                if candidate is None:
                    continue
                identity = (
                    candidate.card_code,
                    candidate.raw_text_hash,
                    candidate.effect_index,
                )
                already_registered = identity in registered
                if (
                    (include_registered or not already_registered)
                    and candidate.effect_id not in emitted_ids
                ):
                    candidates.append(
                        EffectCandidate(
                            **{
                                **candidate.__dict__,
                                "already_registered": already_registered,
                            }
                        )
                    )
                    emitted_ids.add(candidate.effect_id)
            for candidate in _manual_timing_candidates(row):
                identity = (
                    candidate.card_code,
                    candidate.raw_text_hash,
                    candidate.effect_index,
                )
                already_registered = (
                    identity in registered or candidate.effect_id in registered_ids
                )
                if (
                    (include_registered or not already_registered)
                    and candidate.effect_id not in emitted_ids
                ):
                    candidates.append(
                        EffectCandidate(
                            **{
                                **candidate.__dict__,
                                "already_registered": already_registered,
                            }
                        )
                    )
                    emitted_ids.add(candidate.effect_id)
    return sorted(candidates, key=lambda item: (item.card_code, item.effect_index))


def render_candidates_json(candidates: list[EffectCandidate]) -> str:
    import json

    return json.dumps(
        [candidate.__dict__ for candidate in candidates],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _effect_text_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT card.card_code, card.card_type, revision.id AS text_revision_id,
               revision.raw_text_hash, revision.raw_effect_text_ja
        FROM gameplay_cards AS card
        JOIN card_text_revisions AS revision
          ON revision.gameplay_card_id = card.id
        WHERE revision.raw_effect_text_ja IS NOT NULL
          AND length(trim(revision.raw_effect_text_ja)) > 0
        ORDER BY card.card_code, revision.id
        """
    ).fetchall()


def _base(row: sqlite3.Row, *, pattern_id: str, effect_index: int) -> dict[str, Any]:
    return {
        "effect_id": f"{row['card_code']}:{effect_index}",
        "card_code": str(row["card_code"]),
        "text_revision_id": int(row["text_revision_id"]),
        "raw_text_hash": str(row["raw_text_hash"]),
        "effect_index": effect_index,
        "execution_mode": "prompt_then_resolve",
        "simulation_support": "test_validated_executable",
        "review_status": "test_validated",
        "source_reference": SOURCE_REFERENCE,
        "pattern_id": pattern_id,
    }


def _base_with_execution_mode(
    row: sqlite3.Row,
    *,
    pattern_id: str,
    effect_index: int,
    execution_mode: str,
) -> dict[str, Any]:
    payload = _base(row, pattern_id=pattern_id, effect_index=effect_index)
    payload["execution_mode"] = execution_mode
    return payload


def _timing_segments(row: sqlite3.Row) -> list[tuple[int, str]]:
    text = str(row["raw_effect_text_ja"]).strip()
    starts = _timing_effect_starts(text)
    if not starts:
        return [(1, text)]
    segments: list[tuple[int, str]] = []
    for effect_index, (start, _marker) in enumerate(starts, start=1):
        end = starts[effect_index][0] if effect_index < len(starts) else len(text)
        segments.append((effect_index, text[start:end].strip()))
    return segments


def _matching_segment(
    row: sqlite3.Row,
    expected: str,
    *,
    startswith: bool = False,
) -> tuple[int, str] | None:
    for effect_index, label in _timing_segments(row):
        if label == expected or (startswith and label.startswith(expected)):
            return effect_index, expected if startswith else label
    return None


def _onplay_wait_inspect2_reorder(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    prefix = (
        "【登場】このメンバーをウェイトにしてもよい："
        "自分のデッキの上からカードを2枚見る。"
        "その中から好きな枚数を好きな順番でデッキの上に置き、"
        "残りを控え室に置く。"
    )
    if not text.startswith(prefix):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_wait_inspect2_reorder_rest_wr", effect_index=1),
        label_ja=prefix,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[{"action_type": "apply_wait", "target": "source"}],
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
        actions=[
            {"action_type": "inspect_top_cards", "amount": 2},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_inspect2_reorder(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上からカードを2枚見る。"
        "その中から好きな枚数を好きな順番でデッキの上に置き、"
        "残りを控え室に置く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_inspect2_reorder_rest_wr", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
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
        actions=[
            {"action_type": "inspect_top_cards", "amount": 2},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_inspect3_reorder(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上からカードを3枚見る。"
        "その中から好きな枚数を好きな順番でデッキの上に置き、"
        "残りを控え室に置く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_inspect3_reorder_rest_wr", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 3,
            "minimum": 0,
            "maximum": 3,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": False,
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": 3},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _live_success_inspect3_reorder(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    if text == (
        "【ライブ成功時】自分のデッキの上からカードを3枚見る。"
        "それらを好きな順番でデッキの上に置く。"
    ):
        minimum = maximum = 3
        unselected_destination = None
        pattern_id = "live_success_inspect3_reorder_all_top"
    elif text == (
        "【ライブ成功時】自分のデッキの上からカードを3枚見る。"
        "その中から好きな枚数を好きな順番でデッキの上に置き、"
        "残りを控え室に置く。"
    ):
        minimum = 0
        maximum = 3
        unselected_destination = "waiting_room"
        pattern_id = "live_success_inspect3_reorder_rest_wr"
    else:
        return None
    return EffectCandidate(
        **_base(row, pattern_id=pattern_id, effect_index=1),
        label_ja=text,
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 3,
            "minimum": minimum,
            "maximum": maximum,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": unselected_destination,
            "reveal_selected_to_opponent": False,
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": 3},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _live_start_pay_energy_gain_blade(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【ライブ開始時】【E】支払ってもよい：ライブ終了時まで、【ブレード】【ブレード】を得る。": (
            1,
            2,
        ),
        "【ライブ開始時】【E】【E】支払ってもよい：ライブ終了時まで、【ブレード】を得る。": (
            2,
            1,
        ),
        "【ライブ開始時】【E】【E】支払ってもよい：ライブ終了時まで、【ブレード】【ブレード】を得る。": (
            2,
            2,
        ),
        "【ライブ開始時】【E】【E】【E】【E】【E】【E】支払ってもよい：ライブ終了時まで、【ブレード】【ブレード】【ブレード】を得る。": (
            6,
            3,
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, blade) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"live_start_pay{energy}_gain_blade{blade}",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={"source_zone": "stage", "minimum_active_energy": energy},
        cost=[{"action_type": "pay_energy", "amount": energy}],
        choice=None,
        actions=[{"action_type": "gain_blade", "amount": blade}],
        duration="live",
    )


def _live_start_choose_color_gain_heart_per_success_live(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】【heart01】か【heart03】か【heart06】のうち、1つを選ぶ。"
        "ライブ終了時まで、自分の成功ライブカード置き場にあるカード1枚につき、"
        "選んだハートを1つ得る。"
    )
    matched = _matching_segment(row, label, startswith=True)
    if matched is None:
        return None
    effect_index, _ = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_choose_heart_gain_per_success_live",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"success_live_count_at_least": 1},
        cost=[],
        choice={
            "choice_type": "choose_color",
            "color_slots": ["heart01", "heart03", "heart06"],
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "gain_heart", "amount_source": "success_live_count"}],
        duration="live",
    )


def _live_success_draw_then_discard(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【ライブ成功時】カードを1枚引き、手札を1枚控え室に置く。": (1, 1),
        "【ライブ成功時】カードを2枚引き、手札を1枚控え室に置く。": (2, 1),
        "【ライブ成功時】カードを2枚引き、手札を2枚控え室に置く。": (2, 2),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (draw_amount, discard_amount) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"live_success_draw{draw_amount}_discard{discard_amount}",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": discard_amount,
            "maximum": discard_amount,
        },
        actions=[
            {"action_type": "draw_card", "amount": draw_amount},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
    )


def _live_start_draw_then_discard(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【ライブ開始時】カードを1枚引き、手札を1枚控え室に置く。": (1, 1),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (draw_amount, discard_amount) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"live_start_draw{draw_amount}_discard{discard_amount}",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": discard_amount,
            "maximum": discard_amount,
        },
        actions=[
            {"action_type": "draw_card", "amount": draw_amount},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
    )


def _activated_wait_ready_other(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    if text != (
        "【起動】【ターン1回】このメンバーをウェイトにする："
        "自分のステージにいるほかのメンバー1人をアクティブにする。"
    ):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="activated_wait_ready_other_member", effect_index=1),
        label_ja=text,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "card_type": "member",
            "orientation": "wait",
            "exclude_source": True,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "ready_member"}],
        duration=None,
    )


def _onplay_ready_all_self_stage(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分のステージにいるすべてのメンバーをアクティブにする。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_ready_all_self_stage",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_member", "target": "self_stage_all"}],
        duration=None,
    )


def _onplay_success_score_ready_energy(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合、エネルギーを2枚アクティブにする。": (
            6,
            2,
        ),
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が6以上の場合、エネルギーを2枚アクティブにする。": (
            6,
            2,
        ),
    }
    if text not in patterns:
        return None
    score, amount = patterns[text]
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_success_score_ready_energy",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=text,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_score_at_least": score},
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_energy", "amount": amount}],
        duration=None,
    )


def _onplay_success_score_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が３以上の場合、カードを1枚引く。": 3,
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が3以上の場合、カードを1枚引く。": 3,
    }
    if text not in patterns:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_success_score_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=text,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_score_at_least": patterns[text]},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_draw_one(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】カードを1枚引く。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_draw_one",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_dynamic_stage_inspect_keep1_top(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上から、"
        "自分のステージにいるメンバーの数に2を足した数に等しい枚数見る。"
        "その中から1枚をデッキの一番上に置き、残りを控え室に置く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_inspect_stage_count_plus2_keep1_top",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "inspect_top_select",
            "amount_source": "own_stage_member_count_plus_2",
            "minimum": 1,
            "maximum": 1,
            "requires_order": False,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": False,
        },
        actions=[
            {"action_type": "inspect_top_cards"},
            {"action_type": "reorder_deck_top"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_mill3_all_member_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上からカードを3枚控え室に置く。"
        "それらがすべてメンバーカードの場合、カードを1枚引く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_mill3_all_member_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "mill_top_cards", "amount": 3},
            {
                "action_type": "draw_if_milled_all_card_type",
                "card_type": "member",
                "amount": 1,
            },
        ],
        duration=None,
    )


def _onplay_mill5_any_live_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上からカードを5枚控え室に置く。"
        "それらの中にライブカードがある場合、カードを1枚引く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_mill5_any_live_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "mill_top_cards", "amount": 5},
            {
                "action_type": "draw_if_milled_any_card_type",
                "card_type": "live",
                "amount": 1,
            },
        ],
        duration=None,
    )


def _onplay_mill3_all_heart04_gain_heart04(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    color_slot = None
    expected = None
    for candidate in ("heart01", "heart02", "heart03", "heart04", "heart06"):
        prefix = (
            "【登場】自分のデッキの上からカードを3枚控え室に置く。"
            f"それらがすべて【{candidate}】を持つメンバーカードの場合、"
            f"ライブ終了時まで、【{candidate}】を得る。"
        )
        if text.startswith(prefix):
            color_slot = candidate
            expected = prefix
            break
    if color_slot is None or expected is None:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_mill3_all_heart_gain_same_heart",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "mill_top_cards", "amount": 3},
            {
                "action_type": "gain_heart_if_milled_all_have_heart",
                "color_slot": color_slot,
                "amount": 1,
            },
        ],
        duration="live",
    )


def _onplay_wait_opponent_member_cost4(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_wait_opponent_cost4_member", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
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
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _onplay_discard_wait_opponent_members_cost4_up_to2(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【登場】手札を1枚控え室に置いてもよい："
        "相手のステージにいるコスト4以下のメンバーを2人までウェイトにする。"
        "（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）"
    )
    match = _matching_segment(row, expected, startswith=True)
    if match is None:
        return None
    effect_index, label = match
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_discard1_wait_opponent_cost4_members_up_to2",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
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
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": 4,
            "minimum": 0,
            "maximum": 2,
        },
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _dual_onplay_wait_source_wait_opponent_member_cost4(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【登場】/【ライブ開始時】このメンバーをウェイトにしてもよい："
        "相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
        "（ウェイト状態のメンバーが持つ【ブレード】は、"
        "エールで公開する枚数を増やさない。）"
    )
    text = str(row["raw_effect_text_ja"]).strip()
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="dual_onplay_wait_source_wait_opponent_cost4",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": 4,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _dual_livestart_wait_source_wait_opponent_member_cost4(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【登場】/【ライブ開始時】このメンバーをウェイトにしてもよい："
        "相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
        "（ウェイト状態のメンバーが持つ【ブレード】は、"
        "エールで公開する枚数を増やさない。）"
    )
    text = str(row["raw_effect_text_ja"]).strip()
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="dual_livestart_wait_source_wait_opponent_cost4",
            effect_index=2,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=True,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": 4,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _onplay_ready_energy(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】エネルギーを1枚アクティブにする。": 1,
        "【登場】エネルギーを2枚アクティブにする。": 2,
    }
    if text not in patterns:
        return None
    amount = patterns[text]
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_ready_energy",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=text,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_energy", "amount": amount}],
        duration=None,
    )


def _onplay_success_score_place_active_energy(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合、"
        "自分のエネルギーデッキから、エネルギーカードを1枚アクティブ状態で置く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_success_score_place_active_energy",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_score_at_least": 6, "minimum_energy_deck_cards": 1},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "place_energy_from_deck",
                "target": "self",
                "amount": 1,
                "orientation": "active",
            }
        ],
        duration=None,
    )


def _onplay_return_waiting_member_cost4_muse(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の控え室からコスト4以下の『μ's』のメンバーカードを1枚手札に加える。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_return_waiting_member_cost4_muse",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "member",
            "work_key": "love_live",
            "maximum_cost": 4,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_stage_cost13_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分のステージにコスト13以上のメンバーがいる場合、カードを1枚引く。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_stage_cost13_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_stage_member_cost_at_least": 13},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_success_score_return_muse_live(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合、"
        "自分の控え室から『μ's』のライブカードを1枚手札に加える。"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_success_score_return_muse_live",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_score_at_least": 6},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "work_key": "love_live",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_success_count_return_live(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分の成功ライブカード置き場にカードが2枚以上ある場合、"
        "自分の控え室からライブカードを1枚手札に加える。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_success_count2_return_live",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_count_at_least": 2},
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
    )


def _onplay_energy11_return_live(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分のエネルギーが11枚以上ある場合、自分の控え室からライブカードを1枚手札に加える。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_energy11_return_live",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_energy_count_at_least": 11},
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
    )


def _onplay_opponent_active_member_wait(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】相手は、自身のステージにいるアクティブ状態のメンバー1人をウェイトにする。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_opponent_active_member_wait", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "orientation": "active",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _onplay_wait_opponent_member_blade1(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】相手のステージにいる元々持つ【ブレード】の数が1つ以下のメンバー1人をウェイトにする。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_wait_opponent_blade1_member", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_blade": 1,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _onplay_baton_lower_cost_gain_blade2(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    suffix = "のメンバーからバトンタッチして登場した場合、ライブ終了時まで、【ブレード】【ブレード】を得る。"
    if not (text.startswith("【登場】このメンバーよりコストが低い") and suffix in text):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_baton_lower_cost_gain_blade2",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=text,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"replacement_member_cost_less_than_source": True},
        cost=[],
        choice=None,
        actions=[{"action_type": "gain_blade", "amount": 2}],
        duration="live",
    )


def _onplay_draw_then_discard_one(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】カードを1枚引き、手札を1枚控え室に置く。": (1, 1),
        "【登場】カードを2枚引き、手札を1枚控え室に置く。": (2, 1),
        "【登場】カードを2枚引き、手札を2枚控え室に置く。": (2, 2),
    }
    matched = next(
        ((label, values) for label, values in patterns.items() if text.startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, (draw_amount, discard_amount) = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_draw{draw_amount}_then_discard{discard_amount}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": discard_amount,
            "maximum": discard_amount,
        },
        actions=[
            {"action_type": "draw_card", "amount": draw_amount},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
    )


def _onplay_optional_discard_inspect_keep1_any(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを2枚見る。"
            "その中から1枚を手札に加え、残りを控え室に置く。"
        ): 2,
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを3枚見る。"
            "その中から1枚を手札に加え、残りを控え室に置く。"
        ): 3,
    }
    matched = next(
        ((label, amount) for label, amount in patterns.items() if text.startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, amount = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_optional_discard1_inspect{amount}_keep1_any",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
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
            "choice_type": "inspect_top_select",
            "amount": amount,
            "minimum": 1,
            "maximum": 1,
            "requires_order": False,
            "selected_destination": "hand",
            "unselected_destination": "waiting_room",
            "reveal_selected_to_opponent": False,
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_optional_discard_inspect_keep1_filtered(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    patterns: dict[str, tuple[int, str | None, str | None, str | None, str]] = {
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "live", None, None, "live"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "member", None, None, "member"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『μ's』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "member", "love_live", None, "muse_member"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中から『虹ヶ咲』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, "nijigasaki", None, "nijigasaki_card"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中から『lily white』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, None, "lily_white", "lily_white_card"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『みらくらぱーく！』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, None, None, "miracra_park", "miracra_park_card"),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『DOLLCHESTRA』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, None, None, "dollchestra", "dollchestra_card"),
    }
    matched = next(
        ((label, values) for label, values in patterns.items() if str(row["raw_effect_text_ja"]).strip().startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, (amount, card_type, work_key, unit_key, suffix) = matched
    choice: dict[str, Any] = {
        "choice_type": "inspect_top_select",
        "amount": amount,
        "minimum": 0,
        "maximum": 1,
        "requires_order": False,
        "selected_destination": "hand",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": True,
    }
    if card_type:
        choice["card_type"] = card_type
    if work_key:
        choice["work_key"] = work_key
    if unit_key:
        choice["unit_key"] = unit_key
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_optional_discard1_inspect{amount}_keep1_{suffix}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[{"action_type": "discard_from_hand"}],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        choice=choice,
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_inspect_keep_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[int, int, int, str | None, str | None, str]] = {
        (
            "【登場】自分のデッキの上からカードを5枚見る。"
            "その中から『μ's』のライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, 0, 1, "live", "love_live", "muse_live"),
        (
            "【登場】自分のデッキの上からカードを6枚見る。"
            "その中からカードを2枚手札に加え、残りを控え室に置く。"
        ): (6, 2, 2, None, None, "any2"),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if str(row["raw_effect_text_ja"]).strip().startswith(label)
        ),
        None,
    )
    if matched is None:
        return None
    label, (amount, minimum, maximum, card_type, work_key, suffix) = matched
    choice: dict[str, Any] = {
        "choice_type": "inspect_top_select",
        "amount": amount,
        "minimum": minimum,
        "maximum": maximum,
        "requires_order": False,
        "selected_destination": "hand",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": bool(card_type or work_key),
    }
    if card_type:
        choice["card_type"] = card_type
    if work_key:
        choice["work_key"] = work_key
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_inspect{amount}_keep_{suffix}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=choice,
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _inspection_keep_candidate(
    row: sqlite3.Row,
    *,
    pattern_id: str,
    effect_index: int,
    label: str,
    timing: str,
    trigger: str,
    is_optional: bool,
    amount: int,
    minimum: int,
    maximum: int,
    condition: dict[str, Any] | None = None,
    cost: list[dict[str, Any]] | None = None,
    cost_choice: dict[str, Any] | None = None,
    card_type: str | None = None,
    work_key: str | None = None,
    unit_key: str | None = None,
    name_ja_any: list[str] | None = None,
    minimum_cost: int | None = None,
    maximum_cost: int | None = None,
    minimum_score: int | None = None,
    maximum_score: int | None = None,
) -> EffectCandidate:
    choice: dict[str, Any] = {
        "choice_type": "inspect_top_select",
        "amount": amount,
        "minimum": minimum,
        "maximum": maximum,
        "requires_order": False,
        "selected_destination": "hand",
        "unselected_destination": "waiting_room",
        "reveal_selected_to_opponent": True,
    }
    if card_type:
        choice["card_type"] = card_type
    if work_key:
        choice["work_key"] = work_key
    if unit_key:
        choice["unit_key"] = unit_key
    if name_ja_any:
        choice["name_ja_any"] = name_ja_any
    if minimum_cost is not None:
        choice["minimum_cost"] = minimum_cost
    if maximum_cost is not None:
        choice["maximum_cost"] = maximum_cost
    if minimum_score is not None:
        choice["minimum_score"] = minimum_score
    if maximum_score is not None:
        choice["maximum_score"] = maximum_score
    return EffectCandidate(
        **_base(row, pattern_id=pattern_id, effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing=timing,
        trigger=trigger,
        frequency_limit="none" if timing == "on_play" else "once_per_live",
        is_optional=is_optional,
        condition=condition or {},
        cost=cost or [],
        cost_choice=cost_choice,
        choice=choice,
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_inspect_keep_more_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    hand_discard = {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    patterns: dict[str, dict[str, Any]] = {
        (
            "【登場】自分の成功ライブカード置き場にあるカードのスコアの合計が３以上の場合、"
            "自分のデッキの上からカードを5枚見る。"
            "その中から『μ's』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "success_score3_love_live_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "condition": {"success_live_score_at_least": 3},
            "card_type": "member",
            "work_key": "love_live",
        },
        (
            "【登場】自分のデッキの上からカードを2枚見る。"
            "その中から「朝香果林」のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "name_asaka_karin",
            "amount": 2,
            "minimum": 0,
            "maximum": 1,
            "card_type": "member",
            "name_ja_any": ["朝香果林"],
        },
        (
            "【登場】自分のデッキの上からカードを2枚見る。"
            "その中から「近江彼方」のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "name_oumi_kanata",
            "amount": 2,
            "minimum": 0,
            "maximum": 1,
            "card_type": "member",
            "name_ja_any": ["近江彼方"],
        },
        (
            "【登場】自分のデッキの上からカードを2枚見る。"
            "その中から「天王寺璃奈」のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "name_tennoji_rina",
            "amount": 2,
            "minimum": 0,
            "maximum": 1,
            "card_type": "member",
            "name_ja_any": ["天王寺璃奈"],
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『Liella!』のカードを1枚まで公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_liella_card",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "work_key": "love_live_superstar",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "is_optional": True,
        },
        (
            "【登場】自分のデッキの上からカードを2枚見る。"
            "その中から「鐘 嵐珠」のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "name_zhong_lanzhu",
            "amount": 2,
            "minimum": 0,
            "maximum": 1,
            "card_type": "member",
            "name_ja_any": ["鐘 嵐珠"],
        },
        (
            "【登場】自分のデッキの上からカードを5枚見る。"
            "その中から『虹ヶ咲』のライブカードを1枚まで公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "nijigasaki_live",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "card_type": "live",
            "work_key": "nijigasaki",
        },
        (
            "【登場】自分のデッキの上からカードを5枚見る。"
            "その中から『Aqours』のライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "aqours_live",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "card_type": "live",
            "work_key": "love_live_sunshine",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中からメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_member",
            "amount": 4,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "card_type": "member",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを6枚見る。"
            "その中から『Aqours』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_aqours_member",
            "amount": 6,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "love_live_sunshine",
        },
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からコスト9以上の『μ's』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "wait_discard1_cost9_love_live_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [
                {"action_type": "apply_wait", "target": "source"},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "love_live",
            "minimum_cost": 9,
        },
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からコスト9以上の『蓮ノ空』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "wait_discard1_cost9_hasunosora_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [
                {"action_type": "apply_wait", "target": "source"},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "hasunosora",
            "minimum_cost": 9,
        },
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からコスト9以上の『虹ヶ咲』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "wait_discard1_cost9_nijigasaki_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [
                {"action_type": "apply_wait", "target": "source"},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "nijigasaki",
            "minimum_cost": 9,
        },
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からコスト9以上の『Aqours』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "wait_discard1_cost9_aqours_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [
                {"action_type": "apply_wait", "target": "source"},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "love_live_sunshine",
            "minimum_cost": 9,
        },
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からコスト9以上の『Liella!』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "wait_discard1_cost9_liella_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [
                {"action_type": "apply_wait", "target": "source"},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "love_live_superstar",
            "minimum_cost": 9,
        },
        (
            "【登場】自分のデッキの上からカードを3枚見る。"
            "その中からコスト11以上のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "cost11_card",
            "amount": 3,
            "minimum": 0,
            "maximum": 1,
            "minimum_cost": 11,
        },
        (
            "【登場】【E】【E】支払ってもよい："
            "自分のデッキの上からカードを7枚見る。"
            "その中から『Liella!』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "pay2_liella_card",
            "amount": 7,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "work_key": "love_live_superstar",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『Liella!』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_liella_member",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "card_type": "member",
            "work_key": "love_live_superstar",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『CatChu!』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_catchu_card",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "unit_key": "catchu",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『KALEIDOSCORE』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_kaleidoscore_card",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "unit_key": "kaleidoscore",
        },
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『5yncri5e!』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_5yncri5e_card",
            "amount": 5,
            "minimum": 0,
            "maximum": 1,
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "unit_key": "5yncri5e",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        return _inspection_keep_candidate(
            row,
            pattern_id=f"onplay_inspect{values['amount']}_keep_{values['suffix']}",
            effect_index=effect_index,
            label=exact_label,
            timing="on_play",
            trigger="member_played",
            is_optional=bool(values.get("is_optional", False)),
            amount=values["amount"],
            minimum=values["minimum"],
            maximum=values["maximum"],
            condition=values.get("condition"),
            cost=values.get("cost"),
            cost_choice=values.get("cost_choice"),
            card_type=values.get("card_type"),
            work_key=values.get("work_key"),
            unit_key=values.get("unit_key"),
            name_ja_any=values.get("name_ja_any"),
            minimum_cost=values.get("minimum_cost"),
        )
    return None


def _onplay_optional_discard_return_waiting_live(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[
        str,
        tuple[
            str | None,
            str | None,
            str | None,
            int,
            str,
            dict[str, Any],
            str | None,
            str | None,
        ],
    ] = {
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分の控え室から『虹ヶ咲』のライブカードを1枚手札に加える。"
        ): ("live", "nijigasaki", None, 1, "nijigasaki_live", {}, None, None),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分の控え室から『蓮ノ空』のカードを1枚手札に加える。"
        ): (None, "hasunosora", None, 1, "hasunosora_card", {}, None, None),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のステージにほかのメンバーがいる場合、"
            "自分の控え室から『みらくらぱーく！』のカードを1枚手札に加える。"
        ): (
            None,
            None,
            "miracra_park",
            1,
            "other_member_miracra_park_card",
            {"own_stage_member_count_at_least": 2},
            None,
            None,
        ),
        (
            "【登場】手札の『蓮ノ空』のカードを1枚控え室に置いてもよい："
            "自分の控え室からメンバーカードを1枚手札に加える。"
        ): (
            "member",
            None,
            None,
            1,
            "hasunosora_hand_card_return_member",
            {},
            "hasunosora",
            None,
        ),
        (
            "【登場】手札を2枚控え室に置いてもよい："
            "自分の控え室から『Edel Note』のライブカードを1枚手札に加える。"
        ): ("live", None, "edel_note", 2, "edel_note_live", {}, None, None),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if str(row["raw_effect_text_ja"]).strip().startswith(label)
        ),
        None,
    )
    if matched is None:
        return None
    label, (
        card_type,
        work_key,
        unit_key,
        discard_count,
        suffix,
        condition,
        cost_work_key,
        cost_unit_key,
    ) = matched
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "minimum": 1,
        "maximum": 1,
    }
    if card_type:
        choice["card_type"] = card_type
    if work_key:
        choice["work_key"] = work_key
    if unit_key:
        choice["unit_key"] = unit_key
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_optional_discard{discard_count}_return_{suffix}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition=condition,
        cost=[{"action_type": "discard_from_hand"}],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": discard_count,
            "maximum": discard_count,
            **({"work_key": cost_work_key} if cost_work_key else {}),
            **({"unit_key": cost_unit_key} if cost_unit_key else {}),
        },
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_optional_wait_return_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[str, str | None, str]] = {
        "【登場】このメンバーをウェイトにしてもよい：自分の控え室から『μ's』のメンバーカードを1枚手札に加える。（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）": (
            "member",
            "love_live",
            "wait_return_muse_member",
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if str(row["raw_effect_text_ja"]).strip().startswith(label)
        ),
        None,
    )
    if matched is None:
        return None
    label, (card_type, work_key, suffix) = matched
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": card_type,
        "minimum": 1,
        "maximum": 1,
    }
    if work_key:
        choice["work_key"] = work_key
    return EffectCandidate(
        **_base(row, pattern_id=f"onplay_optional_{suffix}", effect_index=1),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_draw_then_deck_bottom(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】カードを1枚引き、手札を1枚デッキの一番下に置く。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, _ = matched
    return EffectCandidate(
        **_base(row, pattern_id="onplay_draw1_then_hand1_deck_bottom", effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card", "amount": 1},
            {"action_type": "move_selected_to_deck_bottom"},
        ],
        duration=None,
    )


def _onplay_return_waiting_to_deck_top(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】自分の控え室からカードを1枚までデッキの一番上に置く。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, _ = matched
    return EffectCandidate(
        **_base(row, pattern_id="onplay_return_waiting_card_up_to1_deck_top", effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "minimum": 0,
            "maximum": 1,
        },
        actions=[{"action_type": "move_selected_to_deck_top"}],
        duration=None,
    )


def _onplay_pay_energy_inspect3_keep1_any(row: sqlite3.Row) -> EffectCandidate | None:
    label = (
        "【登場】【E】支払ってもよい："
        "自分のデッキの上からカードを3枚見る。"
        "その中から1枚を手札に加え、残りを控え室に置く。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, _ = matched
    return EffectCandidate(
        **_base(row, pattern_id="onplay_optional_pay1_inspect3_keep1_any", effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"minimum_active_energy": 1},
        cost=[{"action_type": "pay_energy", "amount": 1}],
        choice={
            "choice_type": "inspect_top_select",
            "amount": 3,
            "minimum": 1,
            "maximum": 1,
            "selected_destination": "hand",
            "unselected_destination": "waiting_room",
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": 3},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_pay_energy_return_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[int, str | None, str | None, str | None, str]] = {
        "【登場】【E】支払ってもよい：自分の控え室から『DOLLCHESTRA』のカードを1枚手札に加える。": (
            1,
            None,
            None,
            "dollchestra",
            "dollchestra_card",
        ),
        "【登場】【E】【E】手札を1枚控え室に置いてもよい：自分の控え室から『蓮ノ空』のカードを1枚手札に加える。": (
            2,
            None,
            "hasunosora",
            None,
            "hasunosora_card",
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if str(row["raw_effect_text_ja"]).strip().startswith(label)
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, card_type, work_key, unit_key, suffix) = matched
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "minimum": 1,
        "maximum": 1,
    }
    if card_type:
        choice["card_type"] = card_type
    if work_key:
        choice["work_key"] = work_key
    if unit_key:
        choice["unit_key"] = unit_key
    has_discard = "手札を1枚控え室に置いてもよい" in label
    cost = [{"action_type": "pay_energy", "amount": energy}]
    cost_choice = None
    if has_discard:
        cost.append({"action_type": "discard_from_hand"})
        cost_choice = {
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        }
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_optional_pay{energy}_return_{suffix}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"minimum_active_energy": energy},
        cost=cost,
        cost_choice=cost_choice,
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_wait_discard_inspect_keep1_any(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        (
            "【登場】このメンバーをウェイトにし、手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを3枚見る。"
            "その中から1枚を手札に加える。残りを控え室に置く。"
        ): 3,
    }
    matched = next(
        (
            (label, amount)
            for label, amount in patterns.items()
            if str(row["raw_effect_text_ja"]).strip().startswith(label)
        ),
        None,
    )
    if matched is None:
        return None
    label, amount = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_optional_wait_discard1_inspect{amount}_keep1_any",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"source_orientation": "active"},
        cost=[
            {"action_type": "apply_wait", "target": "source"},
            {"action_type": "discard_from_hand"},
        ],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        choice={
            "choice_type": "inspect_top_select",
            "amount": amount,
            "minimum": 1,
            "maximum": 1,
            "selected_destination": "hand",
            "unselected_destination": "waiting_room",
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
            {"action_type": "select_to_hand_from_inspected"},
            {"action_type": "move_remaining_cards"},
        ],
        duration=None,
    )


def _onplay_optional_discard_draw_until_hand_size(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】手札を2枚控え室に置いてもよい：自分の手札が5枚になるまでカードを引く。"
    if not str(row["raw_effect_text_ja"]).strip().startswith(label):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_optional_discard2_draw_until_hand5",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[{"action_type": "discard_from_hand"}],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 2,
            "maximum": 2,
        },
        choice=None,
        actions=[{"action_type": "draw_until_hand_size", "target_hand_size": 5}],
        duration=None,
    )


def _onplay_choose_ready_member_or_energy2(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】自分のステージにいるメンバー1人か、エネルギーを2枚アクティブにする。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_choose_ready_member_or_energy2",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "choose_effect_branch",
            "zone": "stage",
            "branch_ids": ["ready_member", "ready_energy"],
            "branch_selection_minimum": {"ready_member": 1},
            "branch_selection_maximum": {"ready_member": 1},
        },
        actions=[
            {"action_type": "ready_member", "branch": "ready_member"},
            {"action_type": "ready_energy", "amount": 2, "branch": "ready_energy"},
        ],
        duration=None,
    )


def _activated_source_to_waiting_return_card(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【起動】このメンバーをステージから控え室に置く：自分の控え室からライブカードを1枚手札に加える。": (
            "live",
            "activated_source_to_wr_return_live",
        ),
        "【起動】このメンバーをステージから控え室に置く：自分の控え室からメンバーカードを1枚手札に加える。": (
            "member",
            "activated_source_to_wr_return_member",
        ),
    }
    matched = next(
        ((label, values) for label, values in patterns.items() if text == label),
        None,
    )
    if matched is None:
        return None
    label, (card_type, pattern_id) = matched
    return EffectCandidate(
        **_base(row, pattern_id=pattern_id, effect_index=1),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="none",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "source_to_waiting_room"}],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": card_type,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _activated_source_to_waiting_return_or_wait(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    patterns: dict[str, tuple[dict[str, Any], list[dict[str, Any]], str]] = {
        "【起動】このメンバーをステージから控え室に置く：自分の控え室から『蓮ノ空』のカードを1枚手札に加える。": (
            {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "work_key": "hasunosora",
                "minimum": 1,
                "maximum": 1,
            },
            [{"action_type": "return_from_waiting_room"}],
            "source_to_wr_return_hasu_card",
        ),
        "【起動】このメンバーをステージから控え室に置く：相手のステージにいるコスト4以下のメンバー1人をウェイトにする。": (
            {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "target_player": "opponent",
                "card_type": "member",
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            [{"action_type": "apply_wait_member"}],
            "source_to_wr_wait_opponent_cost4",
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (choice, actions, suffix) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    return EffectCandidate(
        **_base(row, pattern_id=f"activated_{suffix}", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="none",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "source_to_waiting_room"}],
        choice=choice,
        actions=actions,
        duration=None,
    )


def _activated_pay_energy_draw(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【起動】【ターン1回】【E】【E】：カードを1枚引く。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(row, pattern_id="activated_pay2_draw1", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "pay_energy", "amount": 2}],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _activated_pay_energy_return_live(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【起動】【ターン1回】【E】【E】【E】：自分の控え室からライブカードを1枚手札に加える。"
    matched = _matching_segment(row, expected, startswith=True)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(row, pattern_id="activated_pay3_return_live", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "pay_energy", "amount": 3}],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _activated_pay_energy_return_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[int, str, str | None, int | None, int | None, str]] = {
        "【起動】【ターン1回】【E】【E】：自分の控え室から『Aqours』のライブカードを1枚手札に加える。": (
            2,
            "live",
            "love_live_sunshine",
            None,
            None,
            "pay2_aqours_live",
        ),
        "【起動】【ターン1回】【E】：自分の控え室から4コスト以下の『蓮ノ空』のメンバーカードを1枚手札に加える。": (
            1,
            "member",
            "hasunosora",
            4,
            None,
            "pay1_hasu_member_cost4",
        ),
        "【起動】【ターン1回】【E】【E】【E】：自分の控え室から『蓮ノ空』のライブカードを1枚手札に加える。": (
            3,
            "live",
            "hasunosora",
            None,
            None,
            "pay3_hasu_live",
        ),
        "【起動】【ターン1回】【E】【E】：自分の控え室からスコア3以下の『蓮ノ空』のライブカードを1枚手札に加える。": (
            2,
            "live",
            "hasunosora",
            None,
            3,
            "pay2_hasu_live_score3",
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            for match in [_matching_segment(row, label, startswith=True)]
            if match is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, card_type, work_key, maximum_cost, maximum_score, suffix) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": card_type,
        "minimum": 1,
        "maximum": 1,
    }
    if work_key:
        choice["work_key"] = work_key
    if maximum_cost is not None:
        choice["maximum_cost"] = maximum_cost
    if maximum_score is not None:
        choice["maximum_score"] = maximum_score
    return EffectCandidate(
        **_base(row, pattern_id=f"activated_{suffix}", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "pay_energy", "amount": energy}],
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _activated_pay_discard_return_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[int, int, str, str | None, str, dict[str, Any]]] = {
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から『μ's』のライブカードを1枚手札に加える。この能力は、自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合のみ起動できる。": (
            0,
            2,
            "live",
            "love_live",
            "discard2_success_score6_love_live_live",
            {"success_live_score_at_least": 6},
        ),
        "【起動】【ターン1回】【E】【E】手札を1枚控え室に置く：自分の控え室から『虹ヶ咲』のライブカードを1枚手札に加える。": (
            2,
            1,
            "live",
            "nijigasaki",
            "pay2_discard1_nijigasaki_live",
            {},
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, discard_count, card_type, work_key, suffix, condition) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": card_type,
        "minimum": 1,
        "maximum": 1,
    }
    if work_key:
        choice["work_key"] = work_key
    return EffectCandidate(
        **_base(row, pattern_id=f"activated_{suffix}", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", **condition},
        cost=[
            *([{"action_type": "pay_energy", "amount": energy}] if energy else []),
            {"action_type": "discard_from_hand"},
        ],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": discard_count,
            "maximum": discard_count,
        },
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _activated_wait_return_filtered(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, tuple[str, str | None, str]] = {
        "【起動】【ターン1回】このメンバーをウェイトにする：自分の控え室から『μ's』のライブカードを1枚手札に加える。": (
            "live",
            "love_live",
            "wait_return_muse_live",
        ),
        "【起動】【ターン1回】このメンバーをウェイトにし、手札を1枚控え室に置く：自分の控え室から『虹ヶ咲』のライブカードを1枚手札に加える。": (
            "live",
            "nijigasaki",
            "wait_discard1_return_nijigasaki_live",
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label, startswith=True) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (card_type, work_key, suffix) = matched
    effect_index = _matching_segment(row, label, startswith=True)[0]
    cost = [{"action_type": "apply_wait", "target": "source"}]
    cost_choice = None
    if "手札を1枚控え室に置く" in label:
        cost.append({"action_type": "discard_from_hand"})
        cost_choice = {
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        }
    choice: dict[str, Any] = {
        "choice_type": "card_from_zone",
        "zone": "waiting_room",
        "card_type": card_type,
        "minimum": 1,
        "maximum": 1,
    }
    if work_key:
        choice["work_key"] = work_key
    return EffectCandidate(
        **_base(row, pattern_id=f"activated_{suffix}", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=cost,
        cost_choice=cost_choice,
        choice=choice,
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _activated_pay_energy_mill(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【起動】【ターン1回】【E】【E】：自分のデッキの上からカードを10枚控え室に置く。": (
            2,
            10,
        ),
    }
    matched = next(
        (
            (label, values)
            for label, values in patterns.items()
            if _matching_segment(row, label) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, amount) = matched
    effect_index = _matching_segment(row, label)[0]
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id=f"activated_pay{energy}_mill{amount}",
            effect_index=effect_index,
            execution_mode="prompt_then_resolve",
        ),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[{"action_type": "pay_energy", "amount": energy}],
        choice=None,
        actions=[{"action_type": "mill_top_cards", "amount": amount}],
        duration=None,
    )


def _activated_wait_discard_draw(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【起動】【ターン1回】このメンバーをウェイトにし、手札を1枚控え室に置く：カードを1枚引く。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(row, pattern_id="activated_wait_discard1_draw1", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=[
            {"action_type": "apply_wait", "target": "source"},
            {"action_type": "discard_from_hand"},
        ],
        cost_choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _activated_wait_draw_then_discard(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【起動】【ターン1回】このメンバーをウェイトにする：カードを1枚引き、手札を1枚控え室に置く。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(row, pattern_id="activated_wait_draw1_then_discard1", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
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
    )


def _activated_wait_choose_heart(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【起動】【ターン1回】このメンバーをウェイトにする：【heart01】か【heart03】か【heart06】のうち、1つを選ぶ。ライブ終了時まで、選んだハートを1つ得る。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(row, pattern_id="activated_wait_choose_heart_gain1", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={"source_zone": "stage", "source_orientation": "active"},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={
            "choice_type": "choose_color",
            "color_slots": ["heart01", "heart03", "heart06"],
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "gain_heart", "amount": 1}],
        duration="live",
    )


def _onplay_gain_blade(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】ライブ終了時まで、【ブレード】を得る。": 1,
        "【登場】ライブ終了時まで、【ブレード】【ブレード】を得る。": 2,
        "【登場】ライブ終了時まで、【ブレード】【ブレード】【ブレード】を得る。": 3,
    }
    matched = next(
        ((label, amount) for label, amount in patterns.items() if text.startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, amount = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id=f"onplay_gain_blade{amount}",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "gain_blade", "amount": amount}],
        duration="live",
    )


def _onplay_apply_wait_source(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【登場】このメンバーをウェイトにする。（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）"
    text = str(row["raw_effect_text_ja"]).strip()
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_apply_wait_source",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"source_orientation": "active"},
        cost=[],
        choice=None,
        actions=[{"action_type": "apply_wait", "target": "source"}],
        duration=None,
    )


def _onplay_draw_per_stage_member_then_discard_one(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のステージにいるメンバー1人につき、カードを1枚引く。"
        "その後、手札を1枚控え室に置く。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_draw_per_stage_member_then_discard1",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[
            {"action_type": "draw_card_per_stage_member"},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
    )


def _onplay_reveal_three_opponent_hand_draw_if_no_live(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】相手の手札を、自分は見ないで3枚選び公開する。"
        "これにより公開されたカードの中にライブカードがない場合、カードを1枚引く。"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_reveal3_opponent_hand_draw_if_no_live",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "target_player": "opponent",
            "minimum": 3,
            "maximum": 3,
        },
        actions=[
            {"action_type": "reveal_selected_cards"},
            {
                "action_type": "draw_if_selected_none_card_type",
                "card_type": "live",
                "amount": 1,
            },
        ],
        duration=None,
    )


def _onplay_both_deploy_cost2_waiting_member(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分と相手はそれぞれ、自身の控え室からコスト2以下の"
        "メンバーカードを1枚、メンバーのいないエリアにウェイト状態で"
        "登場させる。（この効果で登場したメンバーのいるエリアには、"
        "このターンにメンバーは登場できない。）"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_both_deploy_cost2_waiting_member",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "multi_player_deploy_waiting_member",
            "zone": "waiting_room",
            "card_type": "member",
            "maximum_cost": 2,
            "minimum": 0,
            "maximum": 1,
        },
        actions=[],
        duration=None,
    )


def _onplay_baton_lower_both_discard_to3_draw3(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】このメンバーよりコストが低いメンバーからバトンタッチして"
        "登場した場合、自分と相手はそれぞれ自身の手札の枚数が3枚になるまで"
        "手札を控え室に置き、その後、自分と相手はそれぞれカードを3枚引く。"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_baton_lower_both_discard_to3_draw3",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"replacement_member_cost_less_than_source": True},
        cost=[],
        choice={
            "choice_type": "multi_player_discard_to_hand_size_then_draw",
            "zone": "hand",
            "target_hand_size": 3,
            "amount": 3,
        },
        actions=[],
        duration=None,
    )


def _onplay_choose_draw_discard_or_wait_opponent_cost2(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】以下から1つを選ぶ。 "
        "・カードを1枚引き、手札を1枚控え室に置く。 "
        "・相手のステージにいるすべてのコスト2以下のメンバーをウェイトにする。"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_choose_draw_discard_or_wait_opponent_cost2",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "choose_effect_branch",
            "zone": "hand",
            "branch_ids": ["draw_discard", "wait_opponent_cost2"],
            "branch_selection_minimum": {"draw_discard": 1},
            "branch_selection_maximum": {"draw_discard": 1},
        },
        actions=[
            {"action_type": "draw_card", "amount": 1, "branch": "draw_discard"},
            {"action_type": "discard_from_hand", "branch": "draw_discard"},
            {
                "action_type": "apply_wait_member",
                "target": "opponent_stage_cost2_all",
                "branch": "wait_opponent_cost2",
            },
        ],
        duration=None,
    )


def _onplay_mill5(row: sqlite3.Row) -> EffectCandidate | None:
    expected_options = {
        "【登場】デッキの上からカードを5枚控え室に置く。": 5,
        "【登場】自分のデッキの上からカードを5枚控え室に置く。": 5,
        "【登場】自分のデッキの上からカードを10枚控え室に置く。": 10,
    }
    matched = next(
        (
            (match, amount)
            for expected, amount in expected_options.items()
            for match in [_matching_segment(row, expected)]
            if match is not None
        ),
        None,
    )
    if matched is None:
        return None
    (effect_index, label), amount = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id=f"onplay_mill{amount}",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[{"action_type": "mill_top_cards", "amount": amount}],
        duration=None,
    )


def _onplay_no_effect_ready_flag(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】このターン、自分と相手のステージにいるメンバーは、効果によってはアクティブにならない。"
    if expected not in text:
        return None
    effect_index = 1 if text.startswith(expected) else 2
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_no_effect_ready_flag",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "set_flag",
                "flag": "members_cannot_be_readied_by_effect",
                "value": True,
            }
        ],
        duration="turn",
    )


def _onplay_success_exists_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の成功ライブカード置き場にカードがある場合、カードを1枚引く。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_success_exists_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"success_live_count_at_least": 1},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_energy_count7_draw(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【登場】自分のエネルギーが7枚以上ある場合、カードを1枚引く。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_energy_count7_draw",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_energy_count_at_least": 7},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_waiting_room10_draw(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の控え室にカードが10枚以上ある場合、カードを1枚引く。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_waiting_room10_draw",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"waiting_room_count_at_least": 10},
        cost=[],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        duration=None,
    )


def _onplay_success_low_score_gain_score(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分の成功ライブカード置き場にカードが1枚以上あり、"
        "かつスコアの合計が１以下の場合、ライブ終了時まで、"
        "「【常時】ライブの合計スコアを＋１する。」を得る。"
    )


def _onplay_return_waiting_member_cost2(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の控え室からコスト2以下のメンバーカードを1枚手札に加える。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_return_waiting_member_cost2",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "member",
            "maximum_cost": 2,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_mill4_any_live_gain_blade2(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のデッキの上からカードを4枚控え室に置く。"
        "それらの中にライブカードがある場合、ライブ終了時まで、"
        "【ブレード】【ブレード】を得る。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_mill4_any_live_gain_blade2",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "mill_top_cards", "amount": 4},
            {"action_type": "gain_blade_if_milled_any_card_type", "card_type": "live", "amount": 2},
        ],
        duration="live",
    )


def _onplay_bibi_two_wait_opponent_cost4(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のステージに名前の異なる『BiBi』のメンバーが2人以上いる場合、"
        "相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_bibi_two_wait_opponent_cost4", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_stage_member_count_at_least": 2},
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
        actions=[{"action_type": "apply_wait_member"}],
        duration=None,
    )


def _onplay_other_member_ready_energy(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分のステージにほかの『スリーズブーケ』のメンバーがいる場合、エネルギーを1枚アクティブにする。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_other_member_ready_energy",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_stage_member_count_at_least": 2},
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_energy", "amount": 1}],
        duration=None,
    )


def _onplay_not_from_hand_draw2_discard2(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】このメンバーが手札以外からステージに登場している場合、カードを2枚引き、手札を2枚控え室に置く。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_not_from_hand_draw2_discard2",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"played_from_zone_not": "hand"},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "hand",
            "minimum": 2,
            "maximum": 2,
        },
        actions=[
            {"action_type": "draw_card", "amount": 2},
            {"action_type": "discard_from_hand"},
        ],
        duration=None,
    )


def _onplay_wait_return_hasu_live_score4(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】このメンバーをウェイトにする。その後、"
        "自分の控え室からスコア４以下の『蓮ノ空』のライブカードを1枚手札に加える。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_wait_return_hasu_live_score4",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "work_key": "hasunosora",
            "maximum_score": 4,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_return_live_score6(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の控え室から、スコア6以上のライブカードを1枚手札に加える。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base(row, pattern_id="onplay_return_live_score6", effect_index=1),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "minimum_score": 6,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_baton_lower_return_hasu_live(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】このメンバーよりコストが低い『スリーズブーケ』のメンバーから"
        "バトンタッチして登場した場合、自分の控え室から『蓮ノ空』のライブカードを1枚手札に加える。"
    )


def _onplay_return_waiting_member_cost2_up_to2(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分の控え室からコスト2以下のメンバーカードを2枚まで手札に加える。"
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_return_waiting_member_cost2_up_to2",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "member",
            "maximum_cost": 2,
            "minimum": 0,
            "maximum": 2,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )


def _onplay_ready_printemps_member_up_to1(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = "【登場】自分のステージにいる『Printemps』のメンバーを1人までアクティブにする。"
    if text != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_ready_printemps_member_up_to1",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "card_type": "member",
            "orientation": "wait",
            "minimum": 0,
            "maximum": 1,
        },
        actions=[{"action_type": "ready_member"}],
        duration=None,
    )


def _onplay_ready_member_up_to1(row: sqlite3.Row) -> EffectCandidate | None:
    expected = "【登場】自分のステージにいるメンバーを1人までアクティブにする。"
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_ready_member_up_to1",
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={},
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "card_type": "member",
            "orientation": "wait",
            "minimum": 0,
            "maximum": 1,
        },
        actions=[{"action_type": "ready_member"}],
        duration=None,
    )


def _live_success_yell_to_hand(row: sqlite3.Row) -> EffectCandidate | None:
    hand_discard = {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    patterns: dict[str, dict[str, Any]] = {
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "『蓮ノ空』のライブカードを1枚手札に加える。 "
            "(必要ハートを確認する時、エールで出た【ALLブレード】は任意の色のハートとして扱う。)"
        ): {
            "suffix": "hasunosora_live",
            "card_type": "live",
            "work_key": "hasunosora",
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "『DOLLCHESTRA』のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "dollchestra_member",
            "card_type": "member",
            "unit_key": "dollchestra",
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "コスト4以下のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "member_cost4",
            "card_type": "member",
            "maximum_cost": 4,
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "コスト4以上9以下の『蓮ノ空』のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "hasunosora_member_cost4_9",
            "card_type": "member",
            "work_key": "hasunosora",
            "minimum_cost": 4,
            "maximum_cost": 9,
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "『虹ヶ咲』のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "nijigasaki_member",
            "card_type": "member",
            "work_key": "nijigasaki",
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "ライブカードを1枚手札に加える。"
        ): {
            "suffix": "live",
            "card_type": "live",
        },
        (
            "【ライブ成功時】エールにより公開された自分のカードの中から、"
            "『Aqours』のライブカードを1枚手札に加える。"
        ): {
            "suffix": "aqours_live",
            "card_type": "live",
            "work_key": "love_live_sunshine",
        },
        (
            "【ライブ成功時】手札を1枚控え室に置いてもよい："
            "エールにより公開された自分のカードの中から、"
            "『μ's』のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "discard1_love_live_member",
            "card_type": "member",
            "work_key": "love_live",
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        choice: dict[str, Any] = {
            "choice_type": "card_from_zone",
            "zone": "resolution_area",
            "minimum": 1,
            "maximum": 1,
        }
        for key in (
            "card_type",
            "work_key",
            "unit_key",
            "minimum_cost",
            "maximum_cost",
        ):
            if values.get(key) is not None:
                choice[key] = values[key]
        return EffectCandidate(
            **_base(
                row,
                pattern_id=f"live_success_yell_to_hand_{values['suffix']}",
                effect_index=effect_index,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="live_success",
            trigger="live_succeeded",
            frequency_limit="once_per_live",
            is_optional=bool(values.get("is_optional", False)),
            condition={},
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=choice,
            actions=[{"action_type": "move_selected_to_hand"}],
            duration=None,
        )
    return None


def _live_start_simple_modifiers(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        (
            "【ライブ開始時】自分のライブカード置き場にカードが2枚以上ある場合、"
            "カードを1枚引く。"
        ): {
            "suffix": "live_area2_draw1",
            "condition": {"live_area_count_at_least": 2},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のライブ中の『μ's』のカードが2枚以上ある場合、"
            "このカードのスコアを＋１する。"
        ): {
            "suffix": "love_live_live_area2_score1",
            "condition": {
                "live_area_work_count_at_least": {"work_key": "love_live", "count": 2}
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分の成功ライブカード置き場にカードが2枚以上ある場合、"
            "このカードのスコアを＋１する。"
        ): {
            "suffix": "success_count2_score1",
            "condition": {"success_live_count_at_least": 2},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のステージにコスト10以上の『蓮ノ空』のメンバーが2人以上いる場合、"
            "このカードのスコアを＋１する。"
        ): {
            "suffix": "hasunosora_cost10_members2_score1",
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "minimum_cost": 10,
                    "count": 2,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】【E】支払ってもよい："
            "自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。"
        ): {
            "suffix": "pay1_place_wait_energy",
            "condition": {"minimum_active_energy": 1, "minimum_energy_deck_cards": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】【E】支払ってもよい："
            "自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。"
        ): {
            "suffix": "pay2_place_wait_energy",
            "condition": {"minimum_active_energy": 2, "minimum_energy_deck_cards": 1},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい：ライブ終了時まで、【heart01】を得る。"
        ): {
            "suffix": "pay1_gain_heart01",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
            "duration": "live",
            "is_optional": True,
            "execution_mode": "prompt_then_resolve",
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、【ブレード】を得る。"
            "これによりライブカードを控え室に置いた場合、さらにカードを1枚引く。"
        ): {
            "suffix": "discard1_gain_blade1_draw_if_live",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_blade", "amount": 1},
                {
                    "action_type": "draw_if_selected_card_type",
                    "card_type": "live",
                    "amount": 1,
                },
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを3枚見る。"
            "その中から好きな枚数を好きな順番でデッキの上に置き、"
            "残りを控え室に置く。"
        ): {
            "suffix": "discard1_inspect3_reorder_rest_wr",
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
                "minimum": 0,
                "maximum": 3,
                "requires_order": True,
                "selected_destination": "main_deck_top_ordered",
                "unselected_destination": "waiting_room",
                "reveal_selected_to_opponent": False,
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 3},
                {"action_type": "reorder_deck_top"},
                {"action_type": "move_remaining_cards"},
            ],
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分のデッキの上からカードを2枚見る。"
            "その中から好きな枚数を好きな順番でデッキの上に置き、"
            "残りを控え室に置く。"
        ): {
            "suffix": "inspect2_reorder_rest_wr",
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 2,
                "minimum": 0,
                "maximum": 2,
                "requires_order": True,
                "selected_destination": "main_deck_top_ordered",
                "unselected_destination": "waiting_room",
                "reveal_selected_to_opponent": False,
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 2},
                {"action_type": "reorder_deck_top"},
                {"action_type": "move_remaining_cards"},
            ],
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "【heart01】か【heart03】か【heart06】のうち、1つを選ぶ。"
            "ライブ終了時まで、選んだハートを1つ得る。"
        ): {
            "suffix": "discard1_choose_muse_heart1",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart03", "heart06"],
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "自分のステージにほかのメンバーがいる場合、好きなハートの色を1つ指定する。"
            "ライブ終了時まで、そのハートを1つ得る。"
        ): {
            "suffix": "discard1_other_member_choose_any_heart1",
            "condition": {"own_stage_member_count_at_least": 2},
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "choose_color",
                "color_slots": [
                    "heart01",
                    "heart02",
                    "heart03",
                    "heart04",
                    "heart05",
                    "heart06",
                ],
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を2枚控え室に置いてもよい："
            "ライブ終了時まで、【ブレード】【ブレード】【ブレード】【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "discard2_gain_blade5",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 2,
                "maximum": 2,
            },
            "actions": [{"action_type": "gain_blade", "amount": 5}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "discard1_gain_blade2",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】『μ's』のメンバー1人をウェイトにしてもよい："
            "ライブ終了時まで、【heart03】【heart03】を得る。"
        ): {
            "suffix": "wait_love_live_member_gain_heart03_2",
            "cost": [{"action_type": "apply_wait_member"}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart03"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分の成功ライブカード置き場にカードがある場合、"
            "【heart01】か【heart03】か【heart06】のうち、1つを選ぶ。"
            "ライブ終了時まで、自分のステージにいる『μ's』のメンバー1人は、"
            "選んだハートを1つ得る。"
        ): {
            "suffix": "success_exists_choose_muse_heart1",
            "condition": {"success_live_count_at_least": 1},
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart03", "heart06"],
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
        },
        (
            "【ライブ開始時】【heart04】か【heart05】か【heart06】のうち、1つを選ぶ。"
            "ライブ終了時まで、自分の成功ライブカード置き場にあるカード1枚につき、"
            "選んだハートを1つ得る。"
        ): {
            "suffix": "choose_heart456_per_success_live",
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart04", "heart05", "heart06"],
            },
            "actions": [
                {"action_type": "gain_heart", "amount_source": "success_live_count"}
            ],
            "duration": "live",
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、自分のステージにいるこのメンバー以外のメンバー1人は、"
            "【heart01】を得る。"
        ): {
            "suffix": "discard1_other_member_gain_heart01",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分のステージにいるメンバーのコストの合計が相手より低い場合、"
            "カードを1枚引く。"
        ): {
            "suffix": "lower_stage_cost_sum_draw1",
            "condition": {"own_stage_cost_sum_less_than_opponent": True},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のステージに『みらくらぱーく！』のメンバーが3人以上いる場合、"
            "このカードのスコアを＋１する。"
        ): {
            "suffix": "miracra_park_stage3_score1",
            "condition": {
                "own_stage_member_unit_count_at_least": {
                    "unit_key": "miracra_park",
                    "count": 3,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のエネルギーが9枚以上ある場合、"
            "このカードのスコアを＋１する。 "
            "(エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)"
        ): {
            "suffix": "energy9_score1",
            "condition": {"own_energy_count_at_least": 9},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のエネルギーが12枚以上ある場合、"
            "このカードのスコアを＋１する。 "
            "(エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)"
        ): {
            "suffix": "energy12_score1",
            "condition": {"own_energy_count_at_least": 12},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】アクティブ状態の自分のエネルギーがある場合、"
            "このカードのスコアを＋１する。"
        ): {
            "suffix": "active_energy_score1",
            "condition": {"minimum_active_energy": 1},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】エネルギーを2枚アクティブにする。"
        ): {
            "suffix": "ready_energy2",
            "choice": {
                "choice_type": "energy_from_area",
                "orientation": "wait",
                "minimum": 0,
                "maximum": 2,
            },
            "actions": [{"action_type": "ready_energy", "amount": 2}],
        },
        (
            "【ライブ開始時】【E】支払ってもよい："
            "自分の控え室にあるメンバーカード2枚を好きな順番でデッキの一番上に置く。"
        ): {
            "suffix": "pay1_waiting_member2_deck_top",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "minimum": 2,
                "maximum": 2,
            },
            "actions": [{"action_type": "move_selected_to_deck_top"}],
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい："
            "ライブ終了時まで、自分のライブ中のカード1枚につき、【ブレード】を得る。"
        ): {
            "suffix": "pay1_gain_blade_per_live_area",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [
                {"action_type": "gain_blade", "amount_source": "live_area_count"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい：ライブ終了時まで、【heart02】を得る。"
        ): {
            "suffix": "pay1_gain_heart02",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい："
            "自分のステージのエリアすべてにメンバーが登場している場合、"
            "ライブ終了時まで、【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "pay1_full_stage_gain_blade2",
            "condition": {"minimum_active_energy": 1, "own_stage_member_count_at_least": 3},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分のデッキの上からカードを3枚控え室に置く。"
            "それらがすべてメンバーカードの場合、ライブ終了時まで、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "mill3_all_member_gain_blade2",
            "actions": [
                {"action_type": "mill_top_cards", "amount": 3},
                {
                    "action_type": "gain_blade_if_milled_all_card_type",
                    "card_type": "member",
                    "amount": 2,
                },
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ成功時】【E】支払ってもよい：カードを1枚引く。"
        ): {
            "suffix": "live_success_pay1_draw1",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "is_optional": True,
        },
        (
            "【ライブ成功時】【E】【E】【E】支払ってもよい：カードを1枚引く。"
        ): {
            "suffix": "live_success_pay3_draw1",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "condition": {"minimum_active_energy": 3},
            "cost": [{"action_type": "pay_energy", "amount": 3}],
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "is_optional": True,
        },
        (
            "【ライブ成功時】【E】【E】【E】【E】【E】【E】支払ってもよい："
            "ライブの合計スコアを＋１する。"
        ): {
            "suffix": "live_success_pay6_score1",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "condition": {"minimum_active_energy": 6},
            "cost": [{"action_type": "pay_energy", "amount": 6}],
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】【E】支払ってもよい："
            "ライブ終了時まで、【heart04】を得る。"
        ): {
            "suffix": "pay2_gain_heart04",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】【E】支払ってもよい："
            "ライブ終了時まで、【heart04】【ブレード】を得る。"
        ): {
            "suffix": "pay2_gain_heart04_blade1",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"},
                {"action_type": "gain_blade", "amount": 1},
            ],
            "duration": "live",
            "is_optional": True,
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = values.get("execution_mode", "prompt_then_resolve")
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"live_start_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing=values.get("timing", "live_start"),
            trigger=values.get("trigger", "live_started"),
            frequency_limit="once_per_live",
            is_optional=bool(values.get("is_optional", False)),
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _live_success_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【ライブ成功時】ライブの合計スコアが相手より高い場合、カードを1枚引く。": {
            "suffix": "higher_score_draw1",
            "condition": {"live_score_relation": "greater_than_opponent"},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分の成功ライブカード置き場に『μ's』のカードがある場合、カードを1枚引く。": {
            "suffix": "success_love_live_draw1",
            "condition": {
                "success_live_work_count_at_least": {"work_key": "love_live", "count": 1}
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のライブカード置き場に『DOLLCHESTRA』のカードがある場合、カードを1枚引く。": {
            "suffix": "live_area_dollchestra_draw1",
            "condition": {
                "live_area_unit_count_at_least": {
                    "unit_key": "dollchestra",
                    "count": 1,
                }
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに、このメンバーよりコストが高いメンバーがいる場合、カードを1枚引く。": {
            "suffix": "higher_cost_stage_member_draw1",
            "condition": {"own_stage_member_cost_greater_than_source": True},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のエネルギーが相手より少ない場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "lower_energy_place_wait_energy",
            "condition": {
                "own_energy_less_than_opponent": True,
                "minimum_energy_deck_cards": 1,
            },
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】相手のエネルギーが自分より多い場合、このカードのスコアを＋１する。": {
            "suffix": "opponent_more_energy_score1",
            "condition": {"own_energy_less_than_opponent": True},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分の手札の枚数が相手より多い場合、このカードのスコアを＋１する。": {
            "suffix": "more_hand_score1",
            "condition": {"own_hand_more_than_opponent": True},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開されている自分のライブカードの枚数が、エールにより公開されている相手のライブカードの枚数より多い場合、このカードのスコアを＋１する。": {
            "suffix": "more_revealed_live_than_opponent_score1",
            "condition": {"yell_revealed_card_type_more_than_opponent": "live"},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中にライブカードがある場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_live_score1",
            "condition": {"yell_revealed_card_type_count_at_least": {"card_type": "live", "count": 1}},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】ライブの合計スコアが相手より高い場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。 (エールで出た【スコア】1つにつき、成功したライブのスコアの合計に1を加算する。)": {
            "suffix": "higher_score_place_wait_energy",
            "condition": {
                "live_score_relation": "greater_than_opponent",
                "minimum_energy_deck_cards": 1,
            },
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分と相手はそれぞれ、自身のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "both_place_wait_energy",
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "both",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに『蓮ノ空』のメンバーがいる場合、カードを1枚引き、手札を1枚控え室に置く。": {
            "suffix": "hasunosora_stage_draw1_discard1",
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 1,
                }
            },
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {"action_type": "discard_from_hand"},
            ],
        },
        "【ライブ成功時】自分のエネルギーが11枚以上ある場合、カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "energy11_draw2_discard1",
            "condition": {"own_energy_count_at_least": 11},
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 2},
                {"action_type": "discard_from_hand"},
            ],
        },
        "【ライブ成功時】自分の手札が6枚以下の場合、自分の控え室からメンバーカードを1枚手札に加える。": {
            "suffix": "hand6_or_less_return_waiting_member",
            "condition": {"own_hand_count_at_most": 6},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = values.get("execution_mode", "prompt_then_resolve")
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"live_success_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="live_success",
            trigger="live_succeeded",
            frequency_limit="once_per_live",
            is_optional=False,
            condition=values.get("condition", {}),
            cost=[],
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _live_start_deep_modifiers(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【ライブ開始時】自分の控え室に『スリーズブーケ』のライブカードが3枚以上ある場合、このカードのスコアを＋１する。": {
            "suffix": "waiting_cerise_live3_score1",
            "condition": {
                "waiting_room_live_unit_count_at_least": {
                    "unit_key": "cerise_bouquet",
                    "count": 3,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに名前とコストが両方ともそれぞれ異なるメンバーが3人以上いる場合、このカードのスコアを＋１する。": {
            "suffix": "stage_distinct_name_cost3_score1",
            "condition": {
                "own_stage_distinct_name_and_cost_member_count_at_least": 3
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージのエリアすべてに『虹ヶ咲』のメンバーがいて、かつそれらのコストの合計が20以上の場合、カードを3枚引き、自分の手札を3枚好きな順番でデッキの上に置く。": {
            "suffix": "nijigasaki_stage_all_cost20_draw3_hand3_top",
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "nijigasaki",
                    "count": 3,
                },
                "own_stage_member_work_cost_sum_at_least": {
                    "work_key": "nijigasaki",
                    "count": 20,
                },
            },
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 3,
                "maximum": 3,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 3},
                {"action_type": "move_selected_to_deck_top"},
            ],
            "duration": None,
        },
        "【ライブ開始時】自分のデッキの上から、自分と相手のステージにいるメンバー1人につき、1枚公開する。それらの中にあるライブカード1枚につき、このカードのスコアを＋１する。その後、これにより公開したカードを控え室に置く。": {
            "suffix": "reveal_top_per_total_stage_live_score",
            "actions": [
                {
                    "action_type": "reveal_top_cards",
                    "amount_source": "total_stage_member_count",
                },
                {
                    "action_type": "modify_score",
                    "amount_source": "revealed_live_count",
                },
            ],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる、このターン中にエリアを移動したすべての『Liella!』のメンバーは、【ブレード】を得る。": {
            "suffix": "moved_liella_stage_blade1",
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {
                        "work_key": "love_live_superstar",
                        "moved_this_turn": True,
                    },
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合、このカードを成功させるための必要ハートを【heart0】減らす。スコアの合計が９以上の場合、さらにこのカードのスコアを＋１する。": {
            "suffix": "success_score6_required_any_minus1_score9_plus1",
            "condition": {"success_live_score_at_least": 6},
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にスコアが１か５のカードがある場合、このカードのスコアを＋１する。それらが両方ある場合、代わりにスコアを＋２する。": {
            "suffix": "success_score_values_1_or_5_bonus",
            "actions": [
                {
                    "action_type": "modify_score",
                    "amount_source": "success_live_score_values_bonus",
                    "value": {"scores": [1, 5]},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にあるカード名が「EMOTION」のカード1枚につき、このカードのスコアを＋２し、成功させるための必要ハートを【heart0】【heart0】【heart0】増やす。": {
            "suffix": "success_emotion_each_score2_required_any_plus3",
            "condition": {
                "success_live_name_count_at_least": {
                    "name_ja": "EMOTION",
                    "count": 1,
                }
            },
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】自分の、ステージと控え室に名前の異なる『Liella!』のメンバーが5人以上いる場合、このカードを使用するためのコストは【heart02】【heart02】【heart03】【heart03】【heart06】【heart06】になる。 (必要ハートを確認する時、エールで出た【ALLブレード】は任意の色のハートとして扱う。)": {
            "suffix": "liella_stage_waiting_distinct5_replace_required_heart02_03_06",
            "condition": {
                "own_stage_waiting_member_work_distinct_name_count_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 5,
                }
            },
            "actions": [
                {
                    "action_type": "replace_required_hearts",
                    "value": {
                        "heart02": 2,
                        "heart03": 2,
                        "heart06": 2,
                    },
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる、このターン中に登場、またはエリアを移動した『5yncri5e!』のメンバー1人につき、このカードを成功させるための必要ハートを【heart0】減らす。": {
            "suffix": "moved_5yncri5e_required_any_minus_each",
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "moved_stage_member_count",
                    "multiplier": -1,
                    "color_slot": "heart0",
                    "value": {"unit_key": "5yncri5e"},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる【heart01】と【heart06】以外の色のハートを持つメンバー1人につき、このカードの必要ハートを【heart0】減らす。": {
            "suffix": "stage_member_non_heart01_06_required_any_minus_each",
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "stage_member_with_heart_excluding_colors_count",
                    "multiplier": -1,
                    "color_slot": "heart0",
                    "value": {"exclude_color_slots": ["heart01", "heart06"]},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のセンターエリアに『μ's』のメンバーがいる場合、そのメンバーが持つ【heart03】2つにつき、このカードの必要ハートを【heart0】減らす。この能力では【heart0】は3つまでしか減らない。": {
            "suffix": "center_muse_heart03_pairs_required_any_minus_max3",
            "condition": {
                "own_stage_slot_member_work": {
                    "slot": "center",
                    "work_key": "love_live",
                }
            },
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに「徒町小鈴」が登場しており、かつ「徒町小鈴」よりコストの大きい「村野さやか」が登場している場合、このカードを成功させるための必要ハートを【heart0】【heart0】【heart0】減らす。": {
            "suffix": "kosuzu_sayaka_cost_relation_required_any_minus3",
            "condition": {
                "own_stage_named_member_cost_greater_than_named": {
                    "lower_name_ja": "徒町小鈴",
                    "higher_name_ja": "村野さやか",
                }
            },
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -3,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに名前の異なる『CatChu!』のメンバーが2人以上いる場合、エネルギーを6枚までアクティブにする。その後、自分のエネルギーがすべてアクティブ状態の場合、このカードのスコアを＋１する。": {
            "suffix": "catchu_distinct2_ready_energy6_all_active_score1",
            "condition": {
                "own_stage_member_unit_distinct_name_count_at_least": {
                    "unit_key": "catchu",
                    "count": 2,
                }
            },
            "choice": {
                "choice_type": "energy_from_area",
                "zone": "energy_area",
                "orientation": "wait",
                "minimum": 0,
                "maximum": 6,
            },
            "actions": [
                {"action_type": "ready_energy"},
                {
                    "action_type": "modify_score",
                    "amount_source": "all_energy_active_bonus",
                },
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる『Aqours』のメンバーが持つハートに、【heart04】が合計10個以上ある場合、このカードのスコアを＋２する。": {
            "suffix": "aqours_stage_heart04_10_score2",
            "condition": {
                "own_stage_heart_at_least": {
                    "unit_key": "aqours",
                    "color_slot": "heart04",
                    "count": 10,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに名前の異なる『KALEIDOSCORE』のメンバーが2人以上いる場合、このカードのスコアを＋１する。": {
            "suffix": "kaleidoscore_stage_distinct2_score1",
            "condition": {
                "own_stage_member_unit_distinct_name_count_at_least": {
                    "unit_key": "kaleidoscore",
                    "count": 2,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる名前の異なる『蓮ノ空』のメンバー1人につき、このカードのスコアを＋２する。": {
            "suffix": "hasunosora_stage_distinct_score2_each",
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 1,
                }
            },
            "actions": [
                {
                    "action_type": "modify_score",
                    "amount_source": "own_stage_member_work_distinct_name_count",
                    "multiplier": 2,
                    "value": {"work_key": "hasunosora"},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる『蓮ノ空』のメンバー1人が元々持つハートをすべて【heart01】にする。": {
            "suffix": "hasunosora_member_replace_base_hearts_heart01",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "hasunosora",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "replace_member_base_hearts",
                    "color_slot": "heart01",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに、このターン中にバトンタッチして登場した『蓮ノ空』のメンバーが2人以上いる場合、このカードを成功させるための必要ハートを【heart05】減らす。": {
            "suffix": "hasunosora_baton_entered2_required_heart05_minus1",
            "condition": {
                "own_baton_entered_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 2,
                }
            },
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -1,
                    "color_slot": "heart05",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに、このターン中にバトンタッチして登場した『蓮ノ空』のメンバーが2人以上いる場合、このカードを成功させるための必要ハートを【heart01】減らす。": {
            "suffix": "hasunosora_baton_entered2_required_heart01_minus1",
            "condition": {
                "own_baton_entered_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 2,
                }
            },
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -1,
                    "color_slot": "heart01",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にあるカード1枚につき、このカードのスコアを＋２し、必要ハートを【heart01】【heart03】【heart06】【heart0】増やす。": {
            "suffix": "success_count_score2_required_heart_plus",
            "actions": [
                {
                    "action_type": "modify_score",
                    "amount_source": "success_live_count",
                    "multiplier": 2,
                },
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_count",
                    "color_slot": "heart01",
                },
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_count",
                    "color_slot": "heart03",
                },
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_count",
                    "color_slot": "heart06",
                },
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_count",
                    "color_slot": "heart0",
                },
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブ中のカードにスコア２以下のライブカードがある場合、このメンバーをアクティブにする。": {
            "suffix": "live_area_score2_ready_source",
            "condition": {"live_area_score_at_most": 2},
            "actions": [{"action_type": "ready_member", "target": "source"}],
        },
        "【ライブ開始時】自分のステージに同じ名前の『虹ヶ咲』のメンバーが2人以上いる場合、このカードを成功させるための必要ハートを【heart0】【heart0】【heart0】減らす。": {
            "suffix": "nijigasaki_same_name2_required_any_minus3",
            "condition": {
                "own_stage_same_name_member_count_at_least": {
                    "work_key": "nijigasaki",
                    "count": 2,
                }
            },
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -3,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】このゲームの1ターン目のライブフェイズの場合、このカードのスコアを＋１し、ライブ終了時まで、自分のステージにいる『虹ヶ咲』のメンバー1人は、【ブレード】を得る。": {
            "suffix": "turn1_score1_choose_nijigasaki_blade1",
            "condition": {"turn_number_exact": 1},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "modify_score", "amount": 1},
                {"action_type": "gain_blade", "amount": 1},
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のセンターエリアに【ブレード】を9つ以上持つ『μ's』のメンバーがいる場合、このカードのスコアを＋２する。": {
            "suffix": "center_muse_blade9_score2",
            "condition": {
                "center_member_blade_at_least": {
                    "work_key": "love_live",
                    "count": 9,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる『μ's』のメンバー1人は、【ブレード】を得る。": {
            "suffix": "choose_muse_member_blade1",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にカードがある場合、【heart01】か【heart03】か【heart06】のうち、1つを選ぶ。ライブ終了時まで、自分のステージにいる『μ's』のメンバー1人は、選んだハートを1つ得る。": {
            "suffix": "success_exists_choose_muse_member_heart1",
            "condition": {"success_live_count_at_least": 1},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live",
                "color_slots": ["heart01", "heart03", "heart06"],
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる『Aqours』のメンバーは【ブレード】を得る。": {
            "suffix": "all_aqours_stage_blade1",
            "condition": {
                "own_stage_member_unit_count_at_least": {
                    "unit_key": "aqours",
                    "count": 1,
                }
            },
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"unit_key": "aqours"},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブカード置き場に「MY舞☆TONIGHT」以外の『Aqours』のライブカードがある場合、ライブ終了時まで、自分のステージのメンバーは【ブレード】を得る。": {
            "suffix": "live_area_other_aqours_live_stage_blade1",
            "condition": {
                "live_area_card_exists": {
                    "card_type": "live",
                    "work_key": "love_live_sunshine",
                    "exclude_name_ja": "MY舞☆TONIGHT",
                }
            },
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブカード置き場にあるこのカード以外の『蓮ノ空』のカード1枚につき、このカードの必要ハートを【heart04】【heart04】減らす。": {
            "suffix": "other_hasu_live_area_required_heart04_minus2_each",
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】手札を2枚控え室に置いてもよい：ライブ終了時まで、自分のステージにいるメンバー1人は、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "discard2_choose_member_blade3",
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 2,
                "maximum": 2,
            },
            "cost": [{"action_type": "discard_from_hand"}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 3}],
            "duration": "live",
            "is_optional": True,
        },
        "【ライブ開始時】手札を1枚控え室に置いてもよい：ライブ終了時まで、自分のステージにいるほかのメンバーは【ブレード】を得る。": {
            "suffix": "discard1_other_stage_members_blade1",
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "cost": [{"action_type": "discard_from_hand"}],
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"exclude_source": True},
                }
            ],
            "duration": "live",
            "is_optional": True,
            "execution_mode": "prompt_then_resolve",
        },
        "【ライブ開始時】相手のステージにウェイト状態のメンバーがいる場合、このカードを成功させるための必要ハートを【heart0】【heart0】減らす。": {
            "suffix": "opponent_wait_member_required_any_minus2",
            "condition": {"opponent_stage_wait_member_count_at_least": 1},
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -2,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にあるカード1枚につき、このカードを成功させるための必要ハートは【heart0】【heart0】少なくなる。": {
            "suffix": "success_count_required_any_minus2",
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount_source": "success_live_count",
                    "multiplier": -2,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージの右サイドエリアに「大沢瑠璃乃」が、左サイドエリアに「安養寺姫芽」が、センターエリアに「藤島 慈」がそれぞれ登場している場合、このカードのスコアを＋２する。": {
            "suffix": "hasu_named_slots_score2",
            "condition": {
                "own_stage_slot_names": {
                    "right": "大沢瑠璃乃",
                    "left": "安養寺姫芽",
                    "center": "藤島 慈",
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】自分の控え室に『蓮ノ空』のメンバーカードが10枚以上ある場合、ライブ終了時まで、自分のステージにいる『蓮ノ空』のメンバー1人は、【heart04】を得る。": {
            "suffix": "waiting_hasu_member10_choose_hasu_heart04",
            "condition": {
                "waiting_room_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 10,
                }
            },
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "hasunosora",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"}
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる『蓮ノ空』のメンバーのコストが合計20以上の場合、デッキの上のカードを2枚見る。その中から1枚を手札に加え、残りをデッキの上に戻す。30以上の場合、さらにこのカードの必要ハートを【heart0】【heart0】減らす。": {
            "suffix": "hasunosora_stage_cost20_inspect2_keep1_top_cost30_required_any_minus2",
            "condition": {
                "own_stage_member_work_cost_sum_at_least": {
                    "work_key": "hasunosora",
                    "count": 20,
                }
            },
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 2,
                "minimum": 1,
                "maximum": 1,
                "requires_order": False,
                "selected_destination": "hand",
                "unselected_destination": "main_deck_top_ordered",
                "reveal_selected_to_opponent": False,
            },
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに『蓮ノ空』のメンバーが3人以上いて、かつ自分の控え室にカード名に「Dream Believers」を含むライブカードがある場合、このカードのスコアを＋１する。": {
            "suffix": "hasunosora_stage3_waiting_dream_believers_score1",
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 3,
                },
                "waiting_room_live_name_contains": "Dream Believers",
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分の、ステージと控え室に名前の異なる『蓮ノ空』のメンバーが6人以上いる場合、このカードの必要ハートは【heart0】【heart0】減る。": {
            "suffix": "hasunosora_stage_waiting_distinct6_required_any_minus2",
            "condition": {
                "own_stage_waiting_member_work_distinct_name_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 6,
                }
            },
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -2,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にカードが2枚以上ある場合、ライブ終了時まで、自分のステージにいるメンバー1人は、【ブレード】【ブレード】を得る。": {
            "suffix": "success_count2_choose_member_blade2",
            "condition": {"success_live_count_at_least": 2},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場にカードが2枚以上ある場合、このカードのスコアを＋５し、必要ハートは【heart02】【heart02】【heart02】【heart03】【heart03】【heart03】【heart06】【heart06】【heart06】【heart0】【heart0】【heart0】になる。": {
            "suffix": "success_count2_score5_replace_required_superstar",
            "condition": {"success_live_count_at_least": 2},
            "actions": [
                {"action_type": "modify_score", "amount": 5},
                {
                    "action_type": "replace_required_hearts",
                    "value": {
                        "heart02": 3,
                        "heart03": 3,
                        "heart06": 3,
                        "heart0": 3,
                    },
                },
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のセンターエリアにいる『Liella!』のメンバーのコストが、相手のセンターエリアにいるメンバーより高い場合、このカードのスコアを＋１する。": {
            "suffix": "center_liella_cost_higher_than_opponent_score1",
            "condition": {
                "center_member_work_cost_greater_than_opponent": {
                    "work_key": "love_live_superstar",
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージの左サイドエリアにいる『Liella!』のメンバーが【heart02】を3つ以上持つ場合、そのメンバーは、ライブ終了時まで、【ブレード】【ブレード】を得る。": {
            "suffix": "left_liella_heart02_3_blade2",
            "condition": {
                "own_stage_slot_member_heart_at_least": {
                    "slot": "left",
                    "work_key": "love_live_superstar",
                    "color_slot": "heart02",
                    "count": 3,
                }
            },
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 2,
                    "value": {
                        "slot": "left",
                        "work_key": "love_live_superstar",
                    },
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに『Aqours』のメンバーと『Saint Snow』のメンバーがいて、かつそれらのメンバーのコストが合計20以上の場合、自分の控え室にある『Aqours』と『Saint Snow』のライブカードを4枚まで好きな順番でデッキの上に置いてもよい。": {
            "suffix": "aqours_saint_snow_cost20_waiting_live_top4",
            "condition": {
                "own_stage_member_unit_keys_present": ["aqours", "saint_snow"],
                "own_stage_member_cost_sum_at_least": 20,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "unit_keys_any": ["aqours", "saint_snow"],
                "minimum": 0,
                "maximum": 4,
            },
            "actions": [{"action_type": "move_selected_to_deck_top"}],
            "is_optional": True,
        },
        "【ライブ開始時】自分のステージにいるメンバーが持つ【ブレード】の合計が10以上の場合、このカードのスコアを＋１する。 (エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)": {
            "suffix": "stage_blade10_score1",
            "condition": {"own_stage_blade_total_at_least": 10},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる『Liella!』のメンバーが持つハートの総数が11以上の場合、このカードのスコアを＋１する。": {
            "suffix": "liella_stage_total_heart11_score1",
            "condition": {
                "own_stage_total_heart_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 11,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいるメンバーが持つハートの中に【heart01】、【heart02】、【heart03】、【heart04】、【heart05】、【heart06】がすべてある場合、このカードのスコアを＋１する。": {
            "suffix": "stage_all_six_heart_colors_score1",
            "condition": {"own_stage_heart_color_variety_at_least": 6},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいる『虹ヶ咲』のメンバーが持つ【heart01】、【heart04】、【heart05】、【heart02】、【heart03】、【heart06】のうち1色につき、このカードのスコアを＋１する。 (エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)": {
            "suffix": "nijigasaki_stage_heart_color_variety_score_each",
            "actions": [
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
            "duration": "live",
        },
        "【ライブ開始時】【heart01】か【heart02】か【heart06】のうち、1つを選ぶ。ライブ終了時まで、自分のステージにいる、このターン中にエリアを移動しているすべてのメンバーは、選んだハートを1つ得る。": {
            "suffix": "choose_heart01_02_06_moved_stage_members_heart1",
            "choice": {
                "choice_type": "choose_color",
                "color_slots": ["heart01", "heart02", "heart06"],
                "minimum": 0,
                "maximum": 0,
            },
            "actions": [
                {
                    "action_type": "gain_heart_to_stage_members",
                    "amount": 1,
                    "value": {"moved_this_turn": True},
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分か相手の成功ライブカード置き場にカードが2枚以上あり、かつ自分のステージに名前の異なるメンバーが3人以上いる場合、このカードのスコアを＋１する。": {
            "suffix": "any_success2_distinct_stage3_score1",
            "condition": {
                "any_success_live_count_at_least": 2,
                "own_stage_distinct_name_and_cost_member_count_at_least": 3,
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブ中のライブカードの必要ハートに含まれる【heart02】の合計が4以上の場合、ライブ終了時まで、【heart02】を得る。": {
            "suffix": "live_required_heart02_4_gain_heart02",
            "condition": {
                "live_area_required_heart_at_least": {
                    "color_slot": "heart02",
                    "count": 4,
                }
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"}
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場かライブ中のライブカードの中に、必要ハートに含まれる【heart01】が4の『虹ヶ咲』のライブカードがある場合、このカードのスコアを＋１する。": {
            "suffix": "nijigasaki_live_or_success_required_heart01_4_score1",
            "condition": {
                "live_or_success_required_heart_at_least": {
                    "work_key": "nijigasaki",
                    "color_slot": "heart01",
                    "count": 4,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分の控え室にカード名の異なる『虹ヶ咲』のライブカードが4枚以上ある場合、このカードのスコアを＋１する。6枚以上ある場合、代わりにスコアを＋２する。": {
            "suffix": "nijigasaki_waiting_distinct_live4_score1_6_score2",
            "condition": {
                "waiting_room_live_work_distinct_name_count_at_least": {
                    "work_key": "nijigasaki",
                    "count": 4,
                }
            },
            "actions": [
                {
                    "action_type": "modify_score",
                    "amount_source": "waiting_room_live_work_distinct_name_threshold_bonus",
                    "value": {
                        "work_key": "nijigasaki",
                        "thresholds": {"4": 1, "6": 2},
                    },
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブカード置き場にあるカードの必要ハートに含まれる【heart05】の合計が4以上の場合、ライブ終了時まで、【heart05】を得る。": {
            "suffix": "live_required_heart05_4_gain_heart05",
            "condition": {
                "live_area_required_heart_at_least": {
                    "color_slot": "heart05",
                    "count": 4,
                }
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"}
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブカード置き場にあるカードの必要ハートに含まれる【heart04】の合計が4以上の場合、ライブ終了時まで、【heart04】を得る。": {
            "suffix": "live_required_heart04_4_gain_heart04",
            "condition": {
                "live_area_required_heart_at_least": {
                    "color_slot": "heart04",
                    "count": 4,
                }
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"}
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場のカードが0枚で、かつ自分のステージにいるメンバーが『lily white』のみの場合、このカードのスコアを＋１する。": {
            "suffix": "success0_only_lily_white_score1",
            "condition": {
                "success_live_count_at_most": 0,
                "own_stage_members_only_unit_key": "lily_white",
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいるメンバーが持つ【ブレード】の合計が10以上の場合、このカードを成功させるための必要ハートは【heart0】【heart0】少なくなる。": {
            "suffix": "stage_blade10_required_any_minus2",
            "condition": {"own_stage_blade_total_at_least": 10},
            "actions": [
                {
                    "action_type": "modify_required_heart",
                    "amount": -2,
                    "color_slot": "heart0",
                }
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のライブ中のカードが3枚以上ある場合、このカードのスコアを＋２する。 (エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)": {
            "suffix": "live_area3_score2",
            "condition": {"live_area_count_at_least": 3},
            "actions": [{"action_type": "modify_score", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージに【heart02】を4つ以上持つメンバーがいる場合、このカードのスコアを＋２し、必要ハートは【heart02】【heart02】【heart02】【heart02】【heart02】になる。": {
            "suffix": "stage_member_heart02_4_score2_replace_heart02_5",
            "condition": {
                "own_stage_member_heart_at_least": {
                    "color_slot": "heart02",
                    "count": 4,
                }
            },
            "actions": [
                {"action_type": "modify_score", "amount": 2},
                {
                    "action_type": "replace_required_hearts",
                    "value": {"heart02": 5},
                },
            ],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージにいるコスト10以上の『蓮ノ空』のメンバー1人は、【ブレード】【ブレード】を得る。": {
            "suffix": "choose_hasu_cost10_blade2",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "hasunosora",
                "minimum_cost": 10,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
        },
        "【ライブ開始時】自分の成功ライブカード置き場のカード枚数が相手より少ない場合、このカードのスコアを＋１する。": {
            "suffix": "success_count_less_than_opponent_score1",
            "condition": {"own_success_live_count_less_than_opponent": True},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = values.get("execution_mode", "auto_resolve")
        if values.get("choice") is not None:
            execution_mode = values.get("execution_mode", "prompt_then_resolve")
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"live_start_deep_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            frequency_limit="once_per_live",
            is_optional=bool(values.get("is_optional", False)),
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _onplay_variable_discard_draw(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】手札を3枚まで控え室に置いてもよい：これにより置いた枚数分カードを引く。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(row, pattern_id="onplay_discard_up_to3_draw_same", effect_index=effect_index),
        label_ja=exact_label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "hand",
            "minimum": 0,
            "maximum": 3,
        },
        actions=[
            {"action_type": "discard_from_hand"},
            {"action_type": "draw_card", "amount_source": "selected_count"},
        ],
        duration=None,
    )


def _activated_more_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    hand_discard = {
        "choice_type": "card_from_zone",
        "zone": "hand",
        "minimum": 1,
        "maximum": 1,
    }
    patterns: dict[str, dict[str, Any]] = {
        "【起動】【ターン1回】【E】：カードを1枚引き、手札を1枚控え室に置く。": {
            "suffix": "pay1_draw1_discard1",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {"action_type": "discard_from_hand"},
            ],
        },
        (
            "【起動】【ターン1回】手札をすべて公開する："
            "自分のステージにほかのメンバーがおり、"
            "かつこれにより公開した手札の中にライブカードがない場合、"
            "自分のデッキの上からカードを5枚見る。"
            "その中からライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "reveal_hand_no_live_inspect5_live",
            "condition": {
                "own_stage_member_count_at_least": 2,
                "own_hand_has_no_card_type": "live",
            },
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 5,
                "minimum": 0,
                "maximum": 1,
                "card_type": "live",
                "selected_destination": "hand",
                "unselected_destination": "waiting_room",
                "reveal_selected_to_opponent": True,
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 5},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ],
        },
        "【起動】このメンバーをウェイトにする：エネルギーを1枚アクティブにする。": {
            "suffix": "wait_source_ready_energy1",
            "condition": {"source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "choice": {
                "choice_type": "energy_from_area",
                "orientation": "wait",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "ready_energy", "amount": 1}],
        },
        "【起動】【ターン1回】【E】【E】：自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "pay2_place_wait_energy",
            "condition": {"minimum_active_energy": 2, "minimum_energy_deck_cards": 1},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
        },
        "【起動】【ターン1回】【E】このメンバーをウェイトにする：自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "pay1_wait_source_place_wait_energy",
            "condition": {
                "minimum_active_energy": 1,
                "minimum_energy_deck_cards": 1,
                "source_orientation": "active",
            },
            "cost": [
                {"action_type": "pay_energy", "amount": 1},
                {"action_type": "apply_wait", "target": "source"},
            ],
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
        },
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から『虹ヶ咲』のメンバーカードを1枚手札に加える。": {
            "suffix": "discard2_return_nijigasaki_member",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                **hand_discard,
                "minimum": 2,
                "maximum": 2,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から『虹ヶ咲』のライブカードを1枚手札に加える。": {
            "suffix": "discard2_return_nijigasaki_live",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                **hand_discard,
                "minimum": 2,
                "maximum": 2,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
        "【起動】【ターン1回】【E】【E】手札を1枚控え室に置く：自分の控え室から『Liella!』のライブカードを1枚手札に加える。": {
            "suffix": "pay2_discard1_return_liella_live",
            "condition": {"minimum_active_energy": 2},
            "cost": [
                {"action_type": "pay_energy", "amount": 2},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "love_live_superstar",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        return EffectCandidate(
            **_base(
                row,
                pattern_id=f"activated_{values['suffix']}",
                effect_index=effect_index,
            ),
            label_ja=exact_label,
            effect_type="activated",
            timing="activated_main",
            trigger="player_activation",
            frequency_limit="once_per_turn" if "【ターン1回】" in exact_label else "none",
            is_optional=False,
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=None,
        )
    return None


def _static_modifier_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【常時】自分か相手のステージにコスト13以上のメンバーがいる場合、 【ブレード】【ブレード】 を得る。": {
            "suffix": "any_stage_cost13_blade2",
            "condition": {"any_stage_member_cost_at_least": 13},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】自分のステージにいるメンバーがちょうど2人であるかぎり、【heart05】【ブレード】を得る。": {
            "suffix": "own_stage_exact2_heart05_blade1",
            "condition": {"own_stage_member_count_exact": 2},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"},
                {"action_type": "gain_blade", "amount": 1},
            ],
        },
        "【常時】自分と相手の成功ライブカード置き場にカードが合計4枚以上あるかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "total_success4_blade2",
            "condition": {"total_success_live_count_at_least": 4},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】相手の成功ライブカード置き場にあるカードのスコアの合計が６以上であるかぎり、ライブの合計スコアを＋１する。": {
            "suffix": "opponent_success_score6_score1",
            "condition": {"opponent_success_live_score_at_least": 6},
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】【センター】ライブの合計スコアを＋１する。": {
            "suffix": "center_score1",
            "condition": {"source_slot": "center"},
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】自分の成功ライブカード置き場にあるカードのスコアの合計が６以上であるかぎり、【heart03】【heart03】を得る。": {
            "suffix": "success_score6_heart03_2",
            "condition": {"success_live_score_at_least": 6},
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart03"}
            ],
        },
        "【常時】このメンバーがウェイト状態であるかぎり、【heart05】を得る。": {
            "suffix": "source_wait_heart05",
            "condition": {"source_orientation": "wait"},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"}
            ],
        },
        "【常時】相手のステージにウェイト状態のメンバーが2人以上いるかぎり、【heart06】を得る。": {
            "suffix": "opponent_wait2_heart06",
            "condition": {"opponent_stage_wait_member_count_at_least": 2},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
            ],
        },
        "【常時】自分の成功ライブカード置き場に『Printemps』のカードがあるかぎり、【heart03】を得る。": {
            "suffix": "success_printemps_heart03",
            "condition": {
                "success_live_unit_count_at_least": {"unit_key": "printemps", "count": 1}
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
        },
        "【常時】自分の成功ライブカード置き場に『lily white』のカードがあるかぎり、【heart01】を得る。": {
            "suffix": "success_lily_white_heart01",
            "condition": {
                "success_live_unit_count_at_least": {"unit_key": "lily_white", "count": 1}
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
        },
        "【常時】自分の成功ライブカード置き場に『BiBi』のカードがあるかぎり、【heart06】を得る。": {
            "suffix": "success_bibi_heart06",
            "condition": {
                "success_live_unit_count_at_least": {"unit_key": "bibi", "count": 1}
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
            ],
        },
        "【常時】自分の成功ライブカード置き場にあるカード1枚につき、【ブレード】を得る。": {
            "suffix": "blade_per_success_live",
            "actions": [
                {"action_type": "gain_blade", "amount_source": "success_live_count"}
            ],
        },
        "【常時】自分のステージに、このメンバーよりコストの大きいメンバーがいる場合、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "higher_cost_stage_member_blade3",
            "condition": {"own_stage_member_cost_greater_than_source": True},
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】自分のステージにほかのメンバーがいないかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "alone_blade2",
            "condition": {"own_stage_member_count_exact": 1},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】自分のステージにほかのメンバーがいないかぎり、【ブレード】【ブレード】【ブレード】を失う。": {
            "suffix": "alone_blade_minus3",
            "condition": {"own_stage_member_count_exact": 1},
            "actions": [{"action_type": "gain_blade", "amount": -3}],
        },
        "【常時】自分のステージに「大沢瑠璃乃」がいるかぎり、【heart01】【heart01】を得る。": {
            "suffix": "stage_name_osawa_rurino_heart01_2",
            "condition": {"own_stage_member_name_any": ["大沢瑠璃乃"]},
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart01"}
            ],
        },
        "【常時】自分のステージに「藤島 慈」がいるかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "stage_name_fujishima_megumi_blade2",
            "condition": {"own_stage_member_name_any": ["藤島 慈"]},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】自分のステージに「日野下花帆」か「徒町小鈴」か「安養寺姫芽」がいるかぎり、【heart04】を得る。": {
            "suffix": "stage_name_kaho_kozue_hime_heart04",
            "condition": {
                "own_stage_member_name_any": ["日野下花帆", "徒町小鈴", "安養寺姫芽"]
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"}
            ],
        },
        "【常時】自分のステージに「村野さやか」か「百生吟子」か「安養寺姫芽」がいるかぎり、【ブレード】を得る。": {
            "suffix": "stage_name_sayaka_ginko_hime_blade1",
            "condition": {
                "own_stage_member_name_any": ["村野さやか", "百生吟子", "安養寺姫芽"]
            },
            "actions": [{"action_type": "gain_blade", "amount": 1}],
        },
        "【常時】自分と相手のステージにメンバーが合計6人いるかぎり、【heart02】【heart05】を得る。": {
            "suffix": "total_stage6_heart02_heart05",
            "condition": {"total_stage_member_count_at_least": 6},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"},
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"},
            ],
        },
        "【常時】自分と相手のステージにメンバーが合計6人いるかぎり、【heart02】【heart04】を得る。": {
            "suffix": "total_stage6_heart02_heart04",
            "condition": {"total_stage_member_count_at_least": 6},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"},
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"},
            ],
        },
        "【常時】自分と相手のステージにメンバーが合計6人いるかぎり、【heart02】【heart03】を得る。": {
            "suffix": "total_stage6_heart02_heart03",
            "condition": {"total_stage_member_count_at_least": 6},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"},
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"},
            ],
        },
        "【常時】自分と相手のエネルギーの合計が15枚以上あるかぎり、【heart02】【heart02】を得る。": {
            "suffix": "total_energy15_heart02_2",
            "condition": {"total_energy_count_at_least": 15},
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart02"}
            ],
        },
        "【常時】相手のエネルギーが自分より多い場合、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "opponent_more_energy_blade3",
            "condition": {"own_energy_less_than_opponent": True},
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】自分と相手の成功ライブカード置き場にカードが合計3枚以上ある場合、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "total_success3_blade3",
            "condition": {"total_success_live_count_at_least": 3},
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】自分のライブ中のライブカードが2枚以上あるかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "live_area2_blade2",
            "condition": {"live_area_count_at_least": 2},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】自分の成功ライブカード置き場のカードが0枚で、かつ相手の成功ライブカード置き場にカードが1枚以上ある場合、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "behind_success_blade3",
            "condition": {
                "success_live_count_at_most": 0,
                "opponent_success_live_count_at_least": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】ステージのセンターエリアにいる場合、【ブレード】【ブレード】【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "center_blade5",
            "condition": {"source_slot": "center"},
            "actions": [{"action_type": "gain_blade", "amount": 5}],
        },
        "【常時】【センター】【ブレード】【ブレード】を得る。": {
            "suffix": "center_blade2",
            "condition": {"source_slot": "center"},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】【センター】【ブレード】【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "center_blade4",
            "condition": {"source_slot": "center"},
            "actions": [{"action_type": "gain_blade", "amount": 4}],
        },
        "【常時】自分のエネルギーが10枚以上あるかぎり、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "energy10_blade3",
            "condition": {"own_energy_count_at_least": 10},
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】自分のエネルギーが10枚以上あるかぎり、【heart06】【heart06】を得る。": {
            "suffix": "energy10_heart06_2",
            "condition": {"own_energy_count_at_least": 10},
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart06"}
            ],
        },
        "【常時】自分のエネルギーが12枚以上ある場合、ライブの合計スコアを＋１する。": {
            "suffix": "energy12_score1",
            "condition": {"own_energy_count_at_least": 12},
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】自分のエネルギーがちょうど8枚あるかぎり、ライブの合計スコアを＋１する。": {
            "suffix": "energy8_score1",
            "condition": {"own_energy_count_exact": 8},
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】自分のエネルギーが相手より多いかぎり、【heart06】を得る。": {
            "suffix": "own_more_energy_heart06",
            "condition": {"own_energy_more_than_opponent": True},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
            ],
        },
        "【常時】自分のステージにコスト13以上のメンバーがいるかぎり、【heart03】を得る。": {
            "suffix": "own_stage_cost13_heart03",
            "condition": {"own_stage_member_cost_at_least": 13},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
        },
        "【常時】自分のステージにいるメンバーのコストの合計が相手より低いかぎり、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "lower_stage_cost_sum_blade3",
            "condition": {"own_stage_cost_sum_less_than_opponent": True},
            "actions": [{"action_type": "gain_blade", "amount": 3}],
        },
        "【常時】【左サイド】【heart02】【heart02】【heart02】を得る。": {
            "suffix": "left_heart02_3",
            "condition": {"source_slot": "left"},
            "actions": [
                {"action_type": "gain_heart", "amount": 3, "color_slot": "heart02"}
            ],
        },
        "【常時】【センター】【heart03】【heart03】【heart03】を得る。": {
            "suffix": "center_heart03_3",
            "condition": {"source_slot": "center"},
            "actions": [
                {"action_type": "gain_heart", "amount": 3, "color_slot": "heart03"}
            ],
        },
        "【常時】【右サイド】【heart05】【heart05】【heart05】を得る。": {
            "suffix": "right_heart05_3",
            "condition": {"source_slot": "right"},
            "actions": [
                {"action_type": "gain_heart", "amount": 3, "color_slot": "heart05"}
            ],
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"static_{values['suffix']}",
                effect_index=effect_index,
                execution_mode="auto_resolve",
            ),
            label_ja=exact_label,
            effect_type="static",
            timing="static_always",
            trigger="static_always",
            frequency_limit="none",
            is_optional=False,
            condition=values.get("condition", {}),
            cost=[],
            choice=None,
            actions=values["actions"],
            duration="game",
        )
    return None
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_baton_lower_return_hasu_live",
            effect_index=1,
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_cost_less_than_source": True,
        },
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "work_key": "hasunosora",
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
    )
    if text != expected:
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_success_low_score_gain_score",
            effect_index=1,
            execution_mode="auto_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={
            "success_live_count_at_least": 1,
            "success_live_score_at_most": 1,
        },
        cost=[],
        choice=None,
        actions=[{"action_type": "modify_score", "amount": 1}],
        duration="live",
    )


def _live_start_left_liella_heart02_blade(row: sqlite3.Row) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】自分のステージの左サイドエリアにいる『Liella!』のメンバーが"
        "【heart02】を3つ以上持つ場合、そのメンバーは、ライブ終了時まで、"
        "【ブレード】【ブレード】を得る。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="live_start_deep_left_liella_heart02_3_blade2",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_stage_slot_member_heart_at_least": {
                "slot": "left",
                "work_key": "love_live_superstar",
                "color_slot": "heart02",
                "count": 3,
            }
        },
        cost=[],
        choice=None,
        actions=[
            {
                "action_type": "gain_blade_to_stage_members",
                "amount": 2,
                "value": {
                    "slot": "left",
                    "work_key": "love_live_superstar",
                },
            }
        ],
        duration="live",
    )


def _live_start_named_superstar_members_gain_heart_and_blade(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる「澁谷かのん」1人は"
        "【heart05】【ブレード】を、「唐 可可」1人は【heart01】【ブレード】を得る。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="live_start_deep_named_superstar_members_gain_heart_blade",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
    )


def _live_start_grouped_superstar_members_gain_blade(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる、"
        "「澁谷かのん」「ウィーン・マルガレーテ」「鬼塚冬毬」のうちのメンバー1人と、"
        "これにより選んだメンバー以外の『Liella!』のメンバー1人は、【ブレード】を得る。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_grouped_superstar_named_and_other_liella_blade",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
    )


def _live_start_nijigasaki_ready_history_score(row: sqlite3.Row) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】このターン、自分の『虹ヶ咲』のカードの効果によって"
        "ウェイト状態の自分のエネルギーをアクティブにしていた場合、"
        "このカードのスコアを＋１する。さらに、自分の『虹ヶ咲』のカードの効果によって"
        "自分のステージにいるウェイト状態のメンバーもアクティブにしていた場合、"
        "代わりにスコアを＋２する。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="live_start_deep_nijigasaki_effect_ready_history_score",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
      )


def _live_start_yell_blade_heart_replacement(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        (
            "【ライブ開始時】ライブ終了時まで、エールによって公開される自分のカードが持つ"
            "[桃ブレード]、[赤ブレード]、[黄ブレード]、[緑ブレード]、"
            "[紫ブレード]、【ALLブレード】は、すべて[青ブレード]になる。"
        ): {
            "suffix": "replace_yell_blade_hearts_heart05",
            "color_slot": "heart05",
        },
        (
            "【ライブ開始時】ライブ終了時まで、エールによって公開される自分のカードが持つ"
            "[桃ブレード]、[赤ブレード]、[黄ブレード]、[緑ブレード]、"
            "[青ブレード]、【ALLブレード】は、すべて[紫ブレード]になる。"
        ): {
            "suffix": "replace_yell_blade_hearts_heart06",
            "color_slot": "heart06",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"live_start_deep_{values['suffix']}",
                effect_index=effect_index,
                execution_mode="auto_resolve",
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="live_start",
            trigger="live_started",
            frequency_limit="once_per_live",
            is_optional=False,
            condition={},
            cost=[],
            choice=None,
            actions=[
                {
                    "action_type": "replace_yell_blade_hearts",
                    "color_slot": values["color_slot"],
                    "value": {"include_all_color": True},
                }
            ],
            duration="live",
        )
    return None


def _live_start_pay2_or_discard2(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【ライブ開始時】【E】【E】支払わないかぎり、自分の手札を2枚控え室に置く。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_pay2_or_discard2",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
    )


_PATTERNS = (
    _onplay_wait_inspect2_reorder,
    _onplay_inspect2_reorder,
    _onplay_inspect3_reorder,
    _live_success_inspect3_reorder,
    _live_start_pay_energy_gain_blade,
    _live_start_choose_color_gain_heart_per_success_live,
    _live_success_draw_then_discard,
    _live_start_draw_then_discard,
    _activated_wait_ready_other,
    _onplay_ready_all_self_stage,
    _onplay_success_score_ready_energy,
    _onplay_success_score_draw,
    _onplay_draw_one,
    _onplay_dynamic_stage_inspect_keep1_top,
    _onplay_mill3_all_member_draw,
    _onplay_mill5_any_live_draw,
    _onplay_mill3_all_heart04_gain_heart04,
    _onplay_wait_opponent_member_cost4,
    _onplay_discard_wait_opponent_members_cost4_up_to2,
    _dual_onplay_wait_source_wait_opponent_member_cost4,
    _dual_livestart_wait_source_wait_opponent_member_cost4,
    _onplay_ready_energy,
    _onplay_success_score_place_active_energy,
    _onplay_return_waiting_member_cost4_muse,
    _onplay_stage_cost13_draw,
    _onplay_success_score_return_muse_live,
    _onplay_success_count_return_live,
    _onplay_energy11_return_live,
    _onplay_opponent_active_member_wait,
    _onplay_wait_opponent_member_blade1,
    _onplay_baton_lower_cost_gain_blade2,
    _onplay_draw_then_discard_one,
    _onplay_optional_discard_inspect_keep1_any,
    _onplay_optional_discard_inspect_keep1_filtered,
    _onplay_inspect_keep_filtered,
    _onplay_inspect_keep_more_filtered,
    _onplay_optional_discard_return_waiting_live,
    _onplay_optional_wait_return_filtered,
    _onplay_draw_then_deck_bottom,
    _onplay_return_waiting_to_deck_top,
    _onplay_pay_energy_inspect3_keep1_any,
    _onplay_pay_energy_return_filtered,
    _onplay_wait_discard_inspect_keep1_any,
    _onplay_optional_discard_draw_until_hand_size,
    _onplay_choose_ready_member_or_energy2,
    _activated_source_to_waiting_return_card,
    _activated_source_to_waiting_return_or_wait,
    _activated_pay_energy_draw,
    _activated_pay_energy_return_live,
    _activated_pay_energy_return_filtered,
    _activated_pay_discard_return_filtered,
    _activated_wait_return_filtered,
    _activated_pay_energy_mill,
    _activated_wait_discard_draw,
    _activated_wait_draw_then_discard,
    _activated_wait_choose_heart,
    _onplay_gain_blade,
    _onplay_apply_wait_source,
    _onplay_draw_per_stage_member_then_discard_one,
    _onplay_reveal_three_opponent_hand_draw_if_no_live,
    _onplay_both_deploy_cost2_waiting_member,
    _onplay_baton_lower_both_discard_to3_draw3,
    _onplay_choose_draw_discard_or_wait_opponent_cost2,
    _onplay_mill5,
    _onplay_no_effect_ready_flag,
    _onplay_success_exists_draw,
    _onplay_energy_count7_draw,
    _onplay_waiting_room10_draw,
    _onplay_success_low_score_gain_score,
    _onplay_return_waiting_member_cost2,
    _onplay_mill4_any_live_gain_blade2,
    _onplay_bibi_two_wait_opponent_cost4,
    _onplay_other_member_ready_energy,
    _onplay_not_from_hand_draw2_discard2,
    _onplay_wait_return_hasu_live_score4,
    _onplay_return_live_score6,
    _onplay_baton_lower_return_hasu_live,
    _onplay_return_waiting_member_cost2_up_to2,
    _onplay_ready_printemps_member_up_to1,
    _onplay_ready_member_up_to1,
    _live_success_yell_to_hand,
    _live_start_simple_modifiers,
    _live_success_simple_effects,
    _live_start_nijigasaki_ready_history_score,
    _live_start_named_superstar_members_gain_heart_and_blade,
    _live_start_grouped_superstar_members_gain_blade,
    _live_start_yell_blade_heart_replacement,
    _live_start_left_liella_heart02_blade,
    _live_start_pay2_or_discard2,
    _live_start_deep_modifiers,
    _onplay_variable_discard_draw,
    _activated_more_simple_effects,
    _static_modifier_effects,
)


_MANUAL_TIMING_MARKERS = {
    "【登場】": ("triggered", "on_play", "member_played", "none"),
    "【起動】": ("activated", "activated_main", "player_activation", "none"),
    "【ライブ開始時】": ("triggered", "live_start", "live_started", "once_per_live"),
    "【ライブ成功時】": ("triggered", "live_success", "live_succeeded", "once_per_live"),
    "【自動】": ("triggered", "auto_triggered_event", "auto_triggered_event", "none"),
    "【常時】": ("static", "static_always", "static_always", "none"),
    "【バトンタッチ時】": (
        "triggered",
        "baton_touch",
        "baton_touch_performed",
        "none",
    ),
}

_TIMING_BOUNDARY_PREFIXES = tuple(_MANUAL_TIMING_MARKERS)
_TIMING_BOUNDARY_PREVIOUS = {"", " ", "\n", "\r", "\t", "/", "。"}


def _manual_timing_candidates(row: sqlite3.Row) -> list[EffectCandidate]:
    """Return conservative manual candidates for real timing-tagged effects.

    Official card text also uses bracketed tokens for icons such as 【ブレード】
    and for quoted abilities. A timing marker is treated as a new effect only
    when it appears at the beginning of the text or after a clear separator.
    """

    text = str(row["raw_effect_text_ja"]).strip()
    starts = _timing_effect_starts(text)
    if not starts:
        return []
    candidates: list[EffectCandidate] = []
    for effect_index, (start, marker) in enumerate(starts, start=1):
        end = starts[effect_index][0] if effect_index < len(starts) else len(text)
        label_ja = text[start:end].strip()
        if _is_empty_timing_alias(label_ja):
            continue
        effect_type, timing, trigger, frequency_limit = _MANUAL_TIMING_MARKERS[marker]
        if marker == "【起動】" and "【ターン1回】" in label_ja:
            frequency_limit = "once_per_turn"
        base = _base(
            row,
            pattern_id="manual_timing_fallback",
            effect_index=effect_index,
        )
        base.update(
            {
                "execution_mode": "manual_resolution",
                "simulation_support": "manual_resolution",
                "review_status": "parsed_draft",
                "source_reference": (
                    "Official card text; timing-only manual fallback pending "
                    "structured effect modeling"
                ),
            }
        )
        candidates.append(
            EffectCandidate(
                **base,
                label_ja=label_ja,
                effect_type=effect_type,
                timing=timing,
                trigger=trigger,
                frequency_limit=frequency_limit,
                is_optional=_looks_optional(label_ja),
                condition=_manual_condition(marker),
                cost=[],
                choice=None,
                actions=[{"action_type": "manual_resolution"}],
                duration=_manual_duration(timing, label_ja),
            )
        )
    return candidates


def _timing_effect_starts(text: str) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    for index, char in enumerate(text):
        if char != "【":
            continue
        marker = next(
            (
                candidate
                for candidate in _TIMING_BOUNDARY_PREFIXES
                if text.startswith(candidate, index)
            ),
            None,
        )
        if marker is None:
            continue
        previous = "" if index == 0 else text[index - 1]
        if previous not in _TIMING_BOUNDARY_PREVIOUS:
            continue
        starts.append((index, marker))
    return sorted(starts)


def _is_empty_timing_alias(label_ja: str) -> bool:
    compact = label_ja.replace(" ", "")
    return compact in {"【登場】/", "/【登場】"}


def _looks_optional(label_ja: str) -> bool:
    return "てもよい" in label_ja or "1枚まで" in label_ja or "選んでもよい" in label_ja


def _manual_condition(marker: str) -> dict[str, Any]:
    if marker == "【起動】":
        return {"source_zone": "stage"}
    return {}


def _manual_duration(timing: str, label_ja: str) -> str | None:
    if "ライブ終了時まで" in label_ja or timing in {"live_start", "live_success"}:
        return "live"
    if "ターン終了時まで" in label_ja:
        return "turn"
    return None
