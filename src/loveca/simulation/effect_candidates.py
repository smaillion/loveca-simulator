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
    follow_up_choice: dict[str, Any] | None = None

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
    amount = 3
    condition: dict[str, Any] = {}
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
    elif text == (
        "【ライブ成功時】このターン、自分が余剰ハートを1つ以上持っている場合、"
        "自分のデッキの上からカードを2枚見る。"
        "その中から好きな枚数を好きな順番でデッキの上に置き、"
        "残りを控え室に置く。"
    ):
        amount = 2
        minimum = 0
        maximum = 2
        unselected_destination = "waiting_room"
        condition = {"own_excess_heart_count_at_least": 1}
        pattern_id = "live_success_excess_heart_inspect2_reorder_rest_wr"
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
        condition=condition,
        cost=[],
        choice={
            "choice_type": "inspect_top_select",
            "amount": amount,
            "minimum": minimum,
            "maximum": maximum,
            "requires_order": True,
            "selected_destination": "main_deck_top_ordered",
            "unselected_destination": unselected_destination,
            "reveal_selected_to_opponent": False,
        },
        actions=[
            {"action_type": "inspect_top_cards", "amount": amount},
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
    for candidate in ("heart01", "heart02", "heart03", "heart04", "heart05", "heart06"):
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


def _wait_opponent_member_by_cost(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【登場】相手のステージにいるコスト2以下のメンバー1人をウェイトにする。": {
            "pattern_id": "onplay_wait_opponent_cost2_member",
            "timing": "on_play",
            "trigger": "member_played",
            "frequency_limit": "none",
            "condition": {},
            "maximum_cost": 2,
            "minimum": 1,
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
            "duration": None,
        },
        "【ライブ開始時】相手のステージにいるコスト9以下のメンバー1人をウェイトにする。": {
            "pattern_id": "live_start_wait_opponent_cost9_member",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {},
            "maximum_cost": 9,
            "minimum": 1,
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにコスト10以上のメンバーがいる場合、相手のステージにいるコスト4以下のメンバー1人をウェイトにする。": {
            "pattern_id": "live_start_stage_cost10_wait_opponent_cost4_member",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {"own_stage_member_cost_at_least": 10},
            "maximum_cost": 4,
            "minimum": 1,
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
            "duration": "live",
        },
        "【ライブ開始時】カードを1枚引く。相手のステージにいるコスト9以下のメンバーを1人までウェイトにする。": {
            "pattern_id": "live_start_draw1_wait_opponent_cost9_member_up_to1",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {},
            "maximum_cost": 9,
            "minimum": 0,
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {"action_type": "apply_wait_member", "target": "selected"},
            ],
            "duration": "live",
        },
        "【ライブ開始時】自分のステージにいるメンバーが持つハートが合計5つ以上ある場合、相手のステージにいるコスト2以下のメンバー1人をウェイトにする。": {
            "pattern_id": "live_start_stage_total_heart5_wait_opponent_cost2_member",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {"own_stage_total_heart_at_least": {"count": 5}},
            "maximum_cost": 2,
            "minimum": 1,
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
            "duration": "live",
        },
    }
    config = None
    effect_index = 0
    label = ""
    for expected, pattern_config in patterns.items():
        match = _matching_segment(row, expected)
        if match is not None:
            effect_index, label = match
            config = pattern_config
            break
    if config is None:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id=str(config["pattern_id"]),
            effect_index=effect_index,
        ),
        label_ja=label,
        effect_type="triggered",
        timing=str(config["timing"]),
        trigger=str(config["trigger"]),
        frequency_limit=str(config["frequency_limit"]),
        is_optional=False,
        condition=dict(config["condition"]),
        cost=[],
        choice={
            "choice_type": "member_from_stage",
            "zone": "stage",
            "target_player": "opponent",
            "card_type": "member",
            "maximum_cost": int(config["maximum_cost"]),
            "minimum": int(config["minimum"]),
            "maximum": 1,
        },
        actions=list(config["actions"]),
        duration=config["duration"],
    )


def _dual_onplay_wait_opponent_member_patterns(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns: dict[str, dict[str, Any]] = {
        "【登場】/【ライブ開始時】相手のステージにいるコスト9以下のメンバー1人をウェイトにする。": {
            "pattern_id": "onplay_wait_opponent_cost9_member",
            "condition": {},
            "choice": {"maximum_cost": 9},
        },
        (
            "【登場】/【ライブ開始時】自分のステージにコスト10以上のメンバーがいる場合、"
            "相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
        ): {
            "pattern_id": "onplay_stage_cost10_wait_opponent_cost4_member",
            "condition": {"own_stage_member_cost_at_least": 10},
            "choice": {"maximum_cost": 4},
        },
        (
            "【登場】/【ライブ開始時】相手のステージにいる元々持つ【ブレード】の数が3つ以下の"
            "『DOLLCHESTRA』以外のメンバー1人をウェイトにする。"
        ): {
            "pattern_id": "onplay_wait_opponent_original_blade3_non_dollchestra_member",
            "condition": {},
            "choice": {"maximum_original_blade": 3, "exclude_unit_key": "dollchestra"},
        },
    }
    for expected, config in patterns.items():
        if not text.startswith(expected):
            continue
        return _wait_opponent_member_candidate(
            row,
            expected,
            pattern_id=str(config["pattern_id"]),
            effect_index=1,
            timing="on_play",
            trigger="member_played",
            frequency_limit="none",
            condition=dict(config["condition"]),
            choice_filter=dict(config["choice"]),
            duration=None,
        )
    return None


def _live_start_wait_opponent_original_blade_patterns(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【ライブ開始時】相手のステージにいる元々持つ【ブレード】の数が3つ以下の"
        "『DOLLCHESTRA』以外のメンバー1人をウェイトにする。"
    )
    match = _matching_segment(row, expected)
    if match is None:
        return None
    effect_index, label = match
    return _wait_opponent_member_candidate(
        row,
        label,
        pattern_id="live_start_wait_opponent_original_blade3_non_dollchestra_member",
        effect_index=effect_index,
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        condition={},
        choice_filter={"maximum_original_blade": 3, "exclude_unit_key": "dollchestra"},
        duration="live",
    )


def _wait_opponent_member_candidate(
    row: sqlite3.Row,
    label: str,
    *,
    pattern_id: str,
    effect_index: int,
    timing: str,
    trigger: str,
    frequency_limit: str,
    condition: dict[str, Any],
    choice_filter: dict[str, Any],
    duration: str | None,
) -> EffectCandidate:
    choice = {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "target_player": "opponent",
        "card_type": "member",
        "minimum": 1,
        "maximum": 1,
    }
    choice.update(choice_filter)
    return EffectCandidate(
        **_base(row, pattern_id=pattern_id, effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing=timing,
        trigger=trigger,
        frequency_limit=frequency_limit,
        is_optional=False,
        condition=condition,
        cost=[],
        choice=choice,
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        duration=duration,
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


def _source_wait_opponent_member_patterns(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    raw_patterns: dict[str, dict[str, Any]] = {
        (
            "【登場】/【ライブ開始時】このメンバーをウェイトにしてもよい："
            "自分のステージにいるメンバーが『BiBi』のみの場合、"
            "相手のステージにいる元々持つ【ブレード】の数が3つ以下のメンバー1人をウェイトにする。"
        ): {
            "pattern_id": "onplay_wait_source_bibi_only_wait_opponent_original_blade3",
            "effect_index": 1,
            "timing": "on_play",
            "trigger": "member_played",
            "frequency_limit": "none",
            "condition": {"source_orientation": "active", "own_stage_members_only_unit_key": "bibi"},
            "choice": {"maximum_original_blade": 3},
            "duration": None,
        },
        (
            "【登場】/【ライブ開始時】このメンバーをウェイトにしてもよい："
            "相手のステージにいる元々持つ【ブレード】の数がちょうど4つのメンバー1人をウェイトにする。"
            "（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）"
        ): {
            "pattern_id": "onplay_wait_source_wait_opponent_original_blade4",
            "effect_index": 1,
            "timing": "on_play",
            "trigger": "member_played",
            "frequency_limit": "none",
            "condition": {"source_orientation": "active"},
            "choice": {"minimum_original_blade": 4, "maximum_original_blade": 4},
            "duration": None,
        },
    }
    for expected, config in raw_patterns.items():
        if text.startswith(expected):
            return _source_wait_opponent_member_candidate(
                row,
                expected,
                pattern_id=str(config["pattern_id"]),
                effect_index=int(config["effect_index"]),
                timing=str(config["timing"]),
                trigger=str(config["trigger"]),
                frequency_limit=str(config["frequency_limit"]),
                condition=dict(config["condition"]),
                choice_filter=dict(config["choice"]),
                duration=config["duration"],
            )
    segment_patterns: dict[str, dict[str, Any]] = {
        "【登場】このメンバーをウェイトにしてもよい：相手のステージにいるコスト9以下のメンバー1人をウェイトにする。": {
            "pattern_id": "onplay_wait_source_wait_opponent_cost9_member",
            "timing": "on_play",
            "trigger": "member_played",
            "frequency_limit": "none",
            "condition": {"source_orientation": "active"},
            "choice": {"maximum_cost": 9},
            "duration": None,
        },
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "自分のステージにいるメンバーが『BiBi』のみの場合、"
            "相手のステージにいる元々持つ【ブレード】の数が3つ以下のメンバー1人をウェイトにする。"
        ): {
            "pattern_id": "live_start_wait_source_bibi_only_wait_opponent_original_blade3",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {
                "source_zone": "stage",
                "source_orientation": "active",
                "own_stage_members_only_unit_key": "bibi",
            },
            "choice": {"maximum_original_blade": 3},
            "duration": "live",
        },
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "相手のステージにいる元々持つ【ブレード】の数がちょうど4つのメンバー1人をウェイトにする。"
            "（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）"
        ): {
            "pattern_id": "live_start_wait_source_wait_opponent_original_blade4",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "condition": {"source_zone": "stage", "source_orientation": "active"},
            "choice": {"minimum_original_blade": 4, "maximum_original_blade": 4},
            "duration": "live",
        },
    }
    for expected, config in segment_patterns.items():
        match = _matching_segment(row, expected)
        if match is None:
            continue
        effect_index, label = match
        return _source_wait_opponent_member_candidate(
            row,
            label,
            pattern_id=str(config["pattern_id"]),
            effect_index=effect_index,
            timing=str(config["timing"]),
            trigger=str(config["trigger"]),
            frequency_limit=str(config["frequency_limit"]),
            condition=dict(config["condition"]),
            choice_filter=dict(config["choice"]),
            duration=config["duration"],
        )
    return None


def _source_wait_opponent_member_live_start_patterns(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    segment_patterns: dict[str, dict[str, Any]] = {
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "自分のステージにいるメンバーが『BiBi』のみの場合、"
            "相手のステージにいる元々持つ【ブレード】の数が3つ以下のメンバー1人をウェイトにする。"
        ): {
            "pattern_id": "live_start_wait_source_bibi_only_wait_opponent_original_blade3",
            "condition": {
                "source_zone": "stage",
                "source_orientation": "active",
                "own_stage_members_only_unit_key": "bibi",
            },
            "choice": {"maximum_original_blade": 3},
        },
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "相手のステージにいる元々持つ【ブレード】の数がちょうど4つのメンバー1人をウェイトにする。"
            "（ウェイト状態のメンバーが持つ【ブレード】は、エールで公開する枚数を増やさない。）"
        ): {
            "pattern_id": "live_start_wait_source_wait_opponent_original_blade4",
            "condition": {"source_zone": "stage", "source_orientation": "active"},
            "choice": {"minimum_original_blade": 4, "maximum_original_blade": 4},
        },
    }
    for expected, config in segment_patterns.items():
        match = _matching_segment(row, expected)
        if match is None:
            continue
        effect_index, label = match
        return _source_wait_opponent_member_candidate(
            row,
            label,
            pattern_id=str(config["pattern_id"]),
            effect_index=effect_index,
            timing="live_start",
            trigger="live_started",
            frequency_limit="once_per_live",
            condition=dict(config["condition"]),
            choice_filter=dict(config["choice"]),
            duration="live",
        )
    return None


def _source_wait_opponent_member_candidate(
    row: sqlite3.Row,
    label: str,
    *,
    pattern_id: str,
    effect_index: int,
    timing: str,
    trigger: str,
    frequency_limit: str,
    condition: dict[str, Any],
    choice_filter: dict[str, Any],
    duration: str | None,
) -> EffectCandidate:
    choice = {
        "choice_type": "member_from_stage",
        "zone": "stage",
        "target_player": "opponent",
        "card_type": "member",
        "minimum": 1,
        "maximum": 1,
    }
    choice.update(choice_filter)
    return EffectCandidate(
        **_base(row, pattern_id=pattern_id, effect_index=effect_index),
        label_ja=label,
        effect_type="triggered",
        timing=timing,
        trigger=trigger,
        frequency_limit=frequency_limit,
        is_optional=True,
        condition=condition,
        cost=[{"action_type": "apply_wait", "target": "source"}],
        choice=choice,
        actions=[{"action_type": "apply_wait_member", "target": "selected"}],
        duration=duration,
    )


def _onplay_ready_energy(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【登場】エネルギーを1枚アクティブにする。": {
            "amount": 1,
            "condition": {},
            "suffix": "ready_energy",
        },
        "【登場】エネルギーを2枚アクティブにする。": {
            "amount": 2,
            "condition": {},
            "suffix": "ready_energy",
        },
        "【登場】【右サイド】エネルギーを2枚アクティブにする。": {
            "amount": 2,
            "condition": {"source_slot": "right"},
            "suffix": "right_side_ready_energy",
        },
        "【登場】自分のステージにほかの『虹ヶ咲』のメンバーがいる場合、エネルギーを1枚アクティブにする。": {
            "amount": 1,
            "condition": {
                "own_stage_member_work_count_at_least": {
                    "work_key": "nijigasaki",
                    "count": 2,
                }
            },
            "suffix": "other_nijigasaki_ready_energy",
        },
    }
    matched = next(
        (
            (label, values, match)
            for label, values in patterns.items()
            if (match := _matching_segment(row, label, startswith=True)) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, values, (effect_index, matched_label) = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id=f"onplay_{values['suffix']}",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=matched_label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition=values["condition"],
        cost=[],
        choice=None,
        actions=[{"action_type": "ready_energy", "amount": values["amount"]}],
        duration=None,
    )


def _onplay_named_stage_ready_energy_return_hasu_live(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】自分のステージに「大沢瑠璃乃」か「百生吟子」か「徒町小鈴」がいる場合、"
        "エネルギーを1枚アクティブにし、自分の控え室から『蓮ノ空』のライブカードを1枚手札に加える。"
    )
    if not text.startswith(expected):
        return None
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_named_stage_ready_energy_return_hasu_live",
            effect_index=1,
            execution_mode="prompt_then_resolve",
        ),
        label_ja=expected,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={"own_stage_member_name_any": ["大沢瑠璃乃", "百生吟子", "徒町小鈴"]},
        cost=[],
        choice={
            "choice_type": "post_action_card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "work_key": "hasunosora",
            "minimum": 0,
            "maximum": 1,
        },
        actions=[
            {"action_type": "ready_energy", "target": "auto", "amount": 1},
            {"action_type": "return_from_waiting_room"},
        ],
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


def _onplay_return_baton_replaced_member(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【登場】バトンタッチして登場した場合、このバトンタッチで控え室に置かれた『Liella!』のメンバーカードを1枚手札に加える。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="onplay_baton_return_replaced_liella_member",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
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


def _onplay_named_baton_draw_then_discard(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    patterns = {
        "【登場】「中須かすみ」からバトンタッチして登場した場合、カードを2枚引き、手札を1枚控え室に置く。": (
            "nakasu_kasumi",
            "中須かすみ",
            2,
            1,
        ),
        "【登場】「優木せつ菜」からバトンタッチして登場した場合、カードを2枚引き、手札を2枚控え室に置く。": (
            "yuki_setsuna",
            "優木せつ菜",
            2,
            2,
        ),
        "【登場】「エマ・ヴェルデ」からバトンタッチして登場した場合、カードを2枚引き、手札を2枚控え室に置く。": (
            "emma_verde",
            "エマ・ヴェルデ",
            2,
            2,
        ),
        "【登場】「三船栞子」からバトンタッチして登場した場合、カードを2枚引き、手札を1枚控え室に置く。": (
            "mifune_shioriko",
            "三船栞子",
            2,
            1,
        ),
    }
    matched = next(
        ((label, values) for label, values in patterns.items() if text.startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, (suffix, name_ja, draw_amount, discard_amount) = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id=f"onplay_named_baton_{suffix}_draw{draw_amount}_discard{discard_amount}",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=False,
        condition={
            "requires_baton_touch": True,
            "replacement_member_name_ja": name_ja,
        },
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
    patterns: dict[
        str,
        tuple[int, str | None, str | None, str | None, str, dict[str, Any]],
    ] = {
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "live", None, None, "live", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中からメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "member", None, None, "member", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『μ's』のメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, "member", "love_live", None, "muse_member", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中から『虹ヶ咲』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, "nijigasaki", None, "nijigasaki_card", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中から『lily white』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, None, "lily_white", "lily_white_card", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『みらくらぱーく！』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, None, None, "miracra_park", "miracra_park_card", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『DOLLCHESTRA』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (5, None, None, "dollchestra", "dollchestra_card", {}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中からハートに【heart04】を2個以上持つメンバーカードか、"
            "必要ハートに【heart04】を2以上含むライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, None, None, "heart04_2_member_or_live", {"heart_color_slot": "heart04", "minimum_heart_count": 2}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中からハートに【heart02】を2個以上持つメンバーカードか、"
            "必要ハートに【heart02】を2以上含むライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, None, None, "heart02_2_member_or_live", {"heart_color_slot": "heart02", "minimum_heart_count": 2}),
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを4枚見る。"
            "その中からハートに【heart05】を2個以上持つメンバーカードか、"
            "必要ハートに【heart05】を2以上含むライブカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): (4, None, None, None, "heart05_2_member_or_live", {"heart_color_slot": "heart05", "minimum_heart_count": 2}),
    }
    matched = next(
        ((label, values) for label, values in patterns.items() if str(row["raw_effect_text_ja"]).strip().startswith(label)),
        None,
    )
    if matched is None:
        return None
    label, (amount, card_type, work_key, unit_key, suffix, choice_filters) = matched
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
    choice.update(choice_filters)
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
        "【登場】【E】【E】支払ってもよい：自分の控え室から『Liella!』のメンバーカードを1枚手札に加える。": (
            2,
            "member",
            "love_live_superstar",
            None,
            "liella_member",
        ),
    }
    matched = next(
        (
            (label, values, match)
            for label, values in patterns.items()
            if (match := _matching_segment(row, label, startswith=True)) is not None
        ),
        None,
    )
    if matched is None:
        return None
    label, (energy, card_type, work_key, unit_key, suffix), (
        effect_index,
        exact_label,
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
            effect_index=effect_index,
        ),
        label_ja=exact_label,
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


def _onplay_pay_energy_draw(row: sqlite3.Row) -> EffectCandidate | None:
    label = (
        "【登場】【E】【E】支払ってもよい："
        "ステージの左サイドエリアに登場しているなら、カードを2枚引く。"
    )
    matched = _matching_segment(row, label, startswith=True)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_optional_pay2_left_side_draw2",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"minimum_active_energy": 2, "source_slot": "left"},
        cost=[{"action_type": "pay_energy", "amount": 2}],
        choice=None,
        actions=[{"action_type": "draw_card", "amount": 2}],
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
        "【起動】このメンバーをステージから控え室に置く：自分の控え室から『μ's』のライブカードを1枚手札に加える。自分の成功ライブカード置き場にあるカードのスコアの合計が９以上の場合、エネルギーを2枚アクティブにする。": (
            {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "love_live",
                "minimum": 1,
                "maximum": 1,
            },
            [
                {"action_type": "return_from_waiting_room"},
                {
                    "action_type": "ready_energy",
                    "target": "auto",
                    "amount": 2,
                    "value": {"condition": {"success_live_score_at_least": 9}},
                },
            ],
            "source_to_wr_return_muse_live_success9_ready_energy2",
        ),
        "【起動】このメンバーをステージから控え室に置く：自分の控え室から『Liella!』のカードを1枚手札に加える。": (
            {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "work_key": "love_live_superstar",
                "minimum": 1,
                "maximum": 1,
            },
            [{"action_type": "return_from_waiting_room"}],
            "source_to_wr_return_liella_card",
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
    patterns: dict[
        str,
        tuple[int, int, str, str | None, str, dict[str, Any], dict[str, Any]],
    ] = {
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から『μ's』のライブカードを1枚手札に加える。この能力は、自分の成功ライブカード置き場にあるカードのスコアの合計が６以上の場合のみ起動できる。": (
            0,
            2,
            "live",
            "love_live",
            "discard2_success_score6_love_live_live",
            {"success_live_score_at_least": 6},
            {},
        ),
        "【起動】【ターン1回】【E】【E】手札を1枚控え室に置く：自分の控え室から『虹ヶ咲』のライブカードを1枚手札に加える。": (
            2,
            1,
            "live",
            "nijigasaki",
            "pay2_discard1_nijigasaki_live",
            {},
            {},
        ),
        "【起動】【ターン1回】【E】【E】手札を1枚控え室に置く：自分の控え室から『Aqours』のライブカードを1枚手札に加える。": (
            2,
            1,
            "live",
            "love_live_sunshine",
            "pay2_discard1_aqours_live",
            {},
            {},
        ),
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から【スコア】を持つ『Aqours』のライブカードを1枚手札に加える。": (
            0,
            2,
            "live",
            "love_live_sunshine",
            "discard2_aqours_score_live",
            {},
            {"minimum_score": 1},
        ),
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から必要ハートに【heart03】を3以上含むライブカードを1枚手札に加える。": (
            0,
            2,
            "live",
            None,
            "discard2_return_live_required_heart03_3",
            {},
            {"required_heart_color_slot": "heart03", "minimum_required_heart": 3},
        ),
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から必要ハートに【heart01】を3以上含むライブカードを1枚手札に加える。": (
            0,
            2,
            "live",
            None,
            "discard2_return_live_required_heart01_3",
            {},
            {"required_heart_color_slot": "heart01", "minimum_required_heart": 3},
        ),
        "【起動】【ターン1回】手札を2枚控え室に置く：自分の控え室から必要ハートに【heart06】を3以上含むライブカードを1枚手札に加える。": (
            0,
            2,
            "live",
            None,
            "discard2_return_live_required_heart06_3",
            {},
            {"required_heart_color_slot": "heart06", "minimum_required_heart": 3},
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
    label, (
        energy,
        discard_count,
        card_type,
        work_key,
        suffix,
        condition,
        choice_filters,
    ) = matched
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
    choice.update(choice_filters)
    return EffectCandidate(
        **_base(row, pattern_id=f"activated_{suffix}", effect_index=effect_index),
        label_ja=label,
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        frequency_limit="once_per_turn",
        is_optional=False,
        condition={
            "source_zone": "stage",
            **({"minimum_active_energy": energy} if energy else {}),
            **condition,
        },
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


def _activated_deploy_waiting_member_to_empty_stage(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        (
            "【起動】【ターン1回】【E】【E】：自分の控え室からコスト2以下の"
            "メンバーカードを1枚、メンバーのいないエリアに登場させる。"
        ): {
            "suffix": "pay2_deploy_waiting_member_cost2",
            "energy": 2,
            "maximum_cost": 2,
            "work_key": None,
        },
        (
            "【起動】【ターン1回】【E】【E】【E】【E】：自分の控え室から"
            "コスト4以下の『蓮ノ空』のメンバーカードを1枚、"
            "メンバーのいないエリアに登場させる。"
        ): {
            "suffix": "pay4_deploy_waiting_hasu_member_cost4",
            "energy": 4,
            "maximum_cost": 4,
            "work_key": "hasunosora",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        choice = {
            "choice_type": "deploy_member_from_waiting_room",
            "zone": "waiting_room",
            "card_type": "member",
            "maximum_cost": values["maximum_cost"],
            "minimum": 1,
            "maximum": 1,
        }
        if values["work_key"] is not None:
            choice["work_key"] = values["work_key"]
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"activated_{values['suffix']}",
                effect_index=effect_index,
                execution_mode="prompt_then_resolve",
            ),
            label_ja=exact_label,
            effect_type="activated",
            timing="activated_main",
            trigger="player_activation",
            frequency_limit="once_per_turn",
            is_optional=False,
            condition={
                "source_zone": "stage",
                "minimum_active_energy": values["energy"],
            },
            cost=[{"action_type": "pay_energy", "amount": values["energy"]}],
            choice=choice,
            actions=[{"action_type": "deploy_selected_to_empty_stage"}],
            duration=None,
        )
    return None


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


def _onplay_choose_mill3_or_wait_opponent_cost2(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【登場】以下から1つを選ぶ。 "
        "・自分のデッキの上からカードを3枚控え室に置く。 "
        "・相手のステージにいるコスト2以下のメンバー1人をウェイトにする。"
    )
    matched = _matching_segment(row, expected)
    if matched is None:
        return None
    effect_index, label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_choose_mill3_or_wait_opponent_cost2",
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
        actions=[
            {"action_type": "mill_top_cards", "amount": 3, "branch": "mill3"},
            {
                "action_type": "apply_wait_member",
                "target": "selected",
                "branch": "wait_opponent_cost2",
            },
        ],
        duration=None,
    )


def _onplay_pay1_choose_wait_opponent_cost4_or_draw1(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【登場】/【ライブ開始時】【E】支払ってもよい：以下から1つを選ぶ。 "
        "・相手のステージにいるコスト4以下のメンバー1人をウェイトにする。 "
        "・カードを1枚引く。"
    )
    text = str(row["raw_effect_text_ja"]).strip()
    if not text.startswith(label):
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_pay1_choose_wait_opponent_cost4_or_draw1",
            effect_index=1,
        ),
        label_ja=label,
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        frequency_limit="none",
        is_optional=True,
        condition={"minimum_active_energy": 1},
        cost=[{"action_type": "pay_energy", "amount": 1}],
        choice={
            "choice_type": "choose_effect_branch",
            "branch_ids": ["wait_opponent_cost4", "draw1"],
            "branch_selection_minimum": {"wait_opponent_cost4": 1},
            "branch_selection_maximum": {"wait_opponent_cost4": 1},
            "branch_choice_filters": {
                "wait_opponent_cost4": {
                    "choice_type": "member_from_stage",
                    "zone": "stage",
                    "target_player": "opponent",
                    "card_type": "member",
                    "maximum_cost": 4,
                }
            },
        },
        actions=[
            {
                "action_type": "apply_wait_member",
                "target": "selected",
                "branch": "wait_opponent_cost4",
            },
            {"action_type": "draw_card", "amount": 1, "branch": "draw1"},
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


def _onplay_choose_waiting_live_by_distinct_name_or_group(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    expected = (
        "【登場】以下から1つを選ぶ。 "
        "・自分の控え室にカード名が異なるライブカードが3枚以上ある場合、"
        "自分の控え室からライブカードを1枚手札に加える。 "
        "・自分の控え室にグループ名が異なるライブカードが3枚以上ある場合、"
        "自分の控え室からライブカードを2枚手札に加える。"
    )
    if str(row["raw_effect_text_ja"]).strip() != expected:
        return None
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_choose_waiting_live_distinct_name_or_group",
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
        actions=[
            {
                "action_type": "return_from_waiting_room",
                "branch": "distinct_name_live",
            },
            {
                "action_type": "return_from_waiting_room",
                "branch": "distinct_group_live",
            },
        ],
        duration=None,
    )


def _onplay_baton_lower_return_hasu_live(row: sqlite3.Row) -> EffectCandidate | None:
    text = str(row["raw_effect_text_ja"]).strip()
    expected = (
        "【登場】このメンバーよりコストが低い『スリーズブーケ』のメンバーから"
        "バトンタッチして登場した場合、自分の控え室から『蓮ノ空』のライブカードを1枚手札に加える。"
    )
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


def _onplay_more_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【登場】自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "place_wait_energy",
            "condition": {"minimum_energy_deck_cards": 1},
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
        "【登場】ライブ終了時まで、「【常時】ライブの合計スコアを＋１する。」を得る。": {
            "suffix": "gain_live_score1",
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【登場】【センター】ライブ終了時まで、【ブレード】【ブレード】を得る。": {
            "suffix": "center_gain_blade2",
            "condition": {"source_slot": "center"},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【登場】自分のステージにほかの『5yncri5e!』のメンバーがいる場合、カードを1枚引く。": {
            "suffix": "other_5yncri5e_draw1",
            "condition": {
                "own_stage_member_unit_count_at_least": {
                    "unit_key": "5yncri5e",
                    "count": 2,
                }
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【登場】【左サイド】カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "left_side_draw2_discard1",
            "condition": {"source_slot": "left"},
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
        "【登場】自分の控え室にあるカード1枚をデッキの一番上に置いてもよい。": {
            "suffix": "optional_waiting_card_to_deck_top",
            "is_optional": True,
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_deck_top"}],
        },
        "【登場】手札のライブカードを1枚控え室に置いてもよい：カードを3枚引く。": {
            "suffix": "optional_discard1_live_draw3",
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "card_type": "live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "draw_card", "amount": 3}],
        },
        "【登場】自分のエネルギー6枚につき、カードを1枚引く。": {
            "suffix": "draw_per_energy6",
            "actions": [
                {
                    "action_type": "draw_card",
                    "amount_source": "own_energy_count_divided_by",
                    "value": {"divisor": 6},
                }
            ],
            "execution_mode": "auto_resolve",
        },
        "【登場】控え室から登場している場合、カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "from_waiting_draw2_discard1",
            "condition": {"played_from_zone": "waiting_room"},
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
        "【登場】カードを2枚引く。その後、控え室から登場している場合、ライブ終了時まで、【ブレード】【ブレード】【ブレード】を得る。": {
            "suffix": "draw2_from_waiting_gain_blade3",
            "actions": [
                {"action_type": "draw_card", "amount": 2},
                {
                    "action_type": "gain_blade",
                    "amount": 3,
                    "value": {"condition": {"played_from_zone": "waiting_room"}},
                },
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【登場】このターン、自分のステージにいるほかのメンバーがエリアを移動している場合、カードを1枚引く。": {
            "suffix": "other_stage_member_moved_this_turn_draw1",
            "condition": {"own_stage_other_member_moved_this_turn": True},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【登場】このメンバーをウェイトにしてもよい：自分のステージにいる『Printemps』のメンバー1人につき、エネルギーを1枚アクティブにする。": {
            "suffix": "wait_source_ready_energy_per_printemps_member",
            "is_optional": True,
            "condition": {"source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "actions": [
                {
                    "action_type": "ready_energy",
                    "target": "auto",
                    "amount_source": "own_stage_member_unit_count",
                    "value": {"unit_key": "printemps"},
                }
            ],
        },
        "【登場】自分のステージにいるこのメンバー以外の【heart06】を持つメンバー1人は、ライブ終了時まで、【heart06】を得る。": {
            "suffix": "other_heart06_member_gain_heart06",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "heart_color_slot": "heart06",
                "minimum_heart_count": 1,
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "gain_heart",
                    "target": "selected",
                    "amount": 1,
                    "color_slot": "heart06",
                }
            ],
            "duration": "live",
        },
        (
            "【登場】自分のステージにいるメンバーが『Liella!』のみで、"
            "かつ自分のエネルギーが7枚以上ある場合、"
            "自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。"
        ): {
            "suffix": "liella_only_energy7_place_wait_energy",
            "condition": {
                "own_stage_members_only_work_key": "love_live_superstar",
                "own_energy_count_at_least": 7,
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
        (
            "【登場】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを2枚控え室に置く。"
            "その後、自分の控え室からメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "optional_discard1_mill2_return_member",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "mill_top_cards", "amount": 2},
                {"action_type": "return_from_waiting_room"},
            ],
            "is_optional": True,
        },
        (
            "【登場】【E】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを3枚控え室に置く。"
            "その後、自分の控え室から『スリーズブーケ』のライブカードを1枚手札に加える。"
        ): {
            "suffix": "optional_pay1_discard1_mill3_return_cerise_bouquet_live",
            "condition": {"minimum_active_energy": 1},
            "cost": [
                {"action_type": "pay_energy", "amount": 1},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "unit_key": "cerise_bouquet",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "mill_top_cards", "amount": 3},
                {"action_type": "return_from_waiting_room"},
            ],
            "is_optional": True,
        },
        "【登場】【E】【E】支払ってもよい：手札からコスト4以下の「上原歩夢」のメンバーカードを1枚ステージに登場させる。": {
            "suffix": "optional_pay2_deploy_hand_uehara_ayumu_member_cost4",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "hand",
                "card_type": "member",
                "name_ja_any": ["上原歩夢"],
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
            "is_optional": True,
        },
        "【登場】【E】【E】支払ってもよい：手札からコスト4以下の「桜坂しずく」のメンバーカードを1枚ステージに登場させる。": {
            "suffix": "optional_pay2_deploy_hand_osaka_shizuku_member_cost4",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "hand",
                "card_type": "member",
                "name_ja_any": ["桜坂しずく"],
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
            "is_optional": True,
        },
        "【登場】【E】【E】支払ってもよい：手札からコスト4以下の「宮下 愛」のメンバーカードを1枚ステージに登場させる。": {
            "suffix": "optional_pay2_deploy_hand_miyashita_ai_member_cost4",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "hand",
                "card_type": "member",
                "name_ja_any": ["宮下 愛"],
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
            "is_optional": True,
        },
        "【登場】【E】【E】支払ってもよい：手札からコスト4以下の「ミア・テイラー」のメンバーカードを1枚ステージに登場させる。": {
            "suffix": "optional_pay2_deploy_hand_mia_taylor_member_cost4",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "choice": {
                "choice_type": "deploy_member_from_waiting_room",
                "zone": "hand",
                "card_type": "member",
                "name_ja_any": ["ミア・テイラー"],
                "maximum_cost": 4,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "deploy_selected_to_empty_stage"}],
            "is_optional": True,
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
                pattern_id=f"onplay_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=values.get("execution_mode", "prompt_then_resolve"),
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="on_play",
            trigger="member_played",
            frequency_limit="none",
            is_optional=bool(values.get("is_optional", False)),
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


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
            "【ライブ開始時】【センター】自分のライブカード置き場に『µ's』のカードがある場合、"
            "ライブ終了時まで、自分のステージにいるすべての『μ's』のメンバーは【ブレード】を得る。"
        ): {
            "suffix": "center_live_area_muse_stage_muse_blade1",
            "condition": {
                "source_slot": "center",
                "live_area_work_count_at_least": {"work_key": "love_live", "count": 1},
            },
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"work_key": "love_live"},
                }
            ],
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
            "【ライブ開始時】【E】【E】支払ってもよい："
            "自分のステージに『虹ヶ咲』のメンバーがいる場合、"
            "このカードのスコアを＋１する。"
            " (エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)"
        ): {
            "suffix": "pay2_nijigasaki_stage_score1",
            "condition": {
                "minimum_active_energy": 2,
                "own_stage_member_work_count_at_least": {
                    "work_key": "nijigasaki",
                    "count": 1,
                },
            },
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        "【ライブ開始時】自分の控え室に『μ's』のカードが25枚以上ある場合、ライブ終了時まで、「【常時】ライブの合計スコアを＋１する。」を得る。": {
            "suffix": "waiting_love_live_card25_score1",
            "condition": {
                "waiting_room_work_count_at_least": {
                    "work_key": "love_live",
                    "count": 25,
                }
            },
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
        "【ライブ開始時】ライブ終了時まで、自分の手札2枚につき、【ブレード】を得る。": {
            "suffix": "hand_count_per2_blade",
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "own_hand_count_divided_by",
                    "value": {"divisor": 2},
                }
            ],
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
            "【ライブ開始時】自分の成功ライブカード置き場にカードがある場合、"
            "手札を1枚控え室に置いてもよい。"
            "そうした場合、自分の控え室から『μ's』のライブカードを1枚手札に加える。"
        ): {
            "suffix": "success_exists_discard1_return_muse_live",
            "condition": {"success_live_count_at_least": 1},
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "love_live",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "自分のデッキの上からカードを3枚控え室に置く。"
            "その後、自分の控え室から『A-RISE』のメンバーカードを1枚手札に加える。"
        ): {
            "suffix": "discard1_mill3_return_a_rise_member",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "unit_key": "a_rise",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "mill_top_cards", "amount": 3},
                {"action_type": "return_from_waiting_room"},
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
            "【ライブ開始時】自分のデッキの上からカードを1枚見る。"
            "そのカードを控え室に置いてもよい。"
        ): {
            "suffix": "inspect1_optional_send_to_waiting",
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 1,
                "minimum": 0,
                "maximum": 1,
                "requires_order": True,
                "selected_destination": "waiting_room",
                "unselected_destination": "main_deck_top_ordered",
                "reveal_selected_to_opponent": False,
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 1},
                {"action_type": "reorder_deck_top"},
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
            "【ライブ開始時】手札のライブカードを1枚控え室に置いてもよい："
            "好きなハートの色を1つ指定する。"
            "ライブ終了時まで、そのハートを1つ得る。"
        ): {
            "suffix": "discard1_live_choose_any_heart1",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "card_type": "live",
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
            "【ライブ開始時】手札を2枚まで控え室に置いてもよい："
            "ライブ終了時まで、これによって控え室に置いたカード1枚につき、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "discard_up_to2_blade2_each",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 0,
                "maximum": 2,
            },
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "selected_count",
                    "multiplier": 2,
                }
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札の「渡辺 曜」と「鬼塚夏美」と「大沢瑠璃乃」を、"
            "好きな枚数控え室に置いてもよい：ライブ終了時まで、"
            "これによって控え室に置いた枚数1枚につき、【ブレード】を得る。"
            " （手札のこのカードもこの効果で控え室に置ける。）"
        ): {
            "suffix": "discard_named_you_natsumi_rurino_blade_each",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "name_ja_any": ["渡辺 曜", "鬼塚夏美", "大沢瑠璃乃"],
                "minimum": 0,
                "maximum": 3,
            },
            "actions": [{"action_type": "gain_blade", "amount_source": "selected_count"}],
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
            "【ライブ開始時】手札の『蓮ノ空』のメンバーカードを3枚まで控え室に置いてもよい："
            "ライブ終了時まで、自分のステージのメンバー1人は、"
            "これにより控え室に置いたカード1枚につき、【ブレード】を得る。"
        ): {
            "suffix": "discard_hasu_members_up_to3_member_blade_each",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "card_type": "member",
                "work_key": "hasunosora",
                "minimum": 0,
                "maximum": 3,
            },
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "gain_blade",
                    "target": "selected",
                    "amount_source": "selected_count",
                }
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、自分の成功ライブカード置き場にあるカード1枚につき、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "discard1_gain_blade2_per_success_live",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "success_live_count",
                    "multiplier": 2,
                }
            ],
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
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、自分のステージにいる『みらくらぱーく！』のメンバー1人は、"
            "【heart01】を得る。"
        ): {
            "suffix": "discard1_miracra_park_member_gain_heart01",
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
                "unit_key": "miracra_park",
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
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、自分のステージにいる『蓮ノ空』のメンバー1人は、"
            "【heart05】を得る。"
        ): {
            "suffix": "discard1_hasunosora_member_gain_heart05",
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
                "work_key": "hasunosora",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"}
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を2枚控え室に置いてもよい："
            "自分のステージにいるこのメンバー以外のウェイト状態のメンバー1人をアクティブにする。"
            "そうした場合、ライブ終了時まで、これによりアクティブにしたメンバーと、"
            "このメンバーは、それぞれ【heart04】を得る。"
        ): {
            "suffix": "discard2_ready_other_wait_member_source_and_selected_heart04",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 2,
                "maximum": 2,
            },
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "orientation": "wait",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "ready_member", "target": "selected"},
                {
                    "action_type": "gain_heart",
                    "target": "selected",
                    "amount": 1,
                    "color_slot": "heart04",
                },
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart04"},
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい：ライブ終了時まで、"
            "自分のステージにいるこのメンバー以外の『蓮ノ空』のメンバー1人は、"
            "【heart01】【ブレード】を得る。"
        ): {
            "suffix": "pay1_other_hasunosora_member_gain_heart01_blade1",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "hasunosora",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "gain_heart",
                    "target": "selected",
                    "amount": 1,
                    "color_slot": "heart01",
                },
                {"action_type": "gain_blade", "target": "selected", "amount": 1},
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】【E】支払ってもよい："
            "ライブ終了時まで、このメンバーが元々持つハートはすべて【heart04】になる。"
        ): {
            "suffix": "pay2_replace_source_base_hearts_heart04",
            "condition": {"minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "actions": [
                {
                    "action_type": "replace_member_base_hearts",
                    "color_slot": "heart04",
                }
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】【E】支払ってもよい：ライブ終了時まで、"
            "自分のステージにいるほかの『虹ヶ咲』のメンバーは【ブレード】を得る。"
        ): {
            "suffix": "pay1_other_nijigasaki_members_gain_blade1",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"work_key": "nijigasaki", "exclude_source": True},
                }
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分のエネルギーが7枚以上ある場合、"
            "ライブ終了時まで、このメンバーと自分のステージにいるほかの"
            "『Liella!』のメンバー1人は、【ブレード】を得る。"
        ): {
            "suffix": "energy7_source_and_other_liella_member_gain_blade1",
            "condition": {"own_energy_count_at_least": 7},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live_superstar",
                "exclude_source": True,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_blade", "amount": 1},
                {"action_type": "gain_blade", "target": "selected", "amount": 1},
            ],
            "duration": "live",
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
            "【ライブ開始時】自分のステージにいるメンバーのコストの合計が相手より低い場合、"
            "カードを2枚引き、自分の手札を1枚デッキの一番上に置く。"
        ): {
            "suffix": "lower_stage_cost_sum_draw2_hand1_top",
            "condition": {"own_stage_cost_sum_less_than_opponent": True},
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 2},
                {"action_type": "move_selected_to_deck_top"},
            ],
        },
        (
            "【ライブ開始時】カードを1枚引いてもよい。"
            "そうした場合、手札2枚を好きな順番でデッキの上に置く。"
        ): {
            "suffix": "optional_draw1_hand2_top",
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 2,
                "maximum": 2,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {"action_type": "move_selected_to_deck_top"},
            ],
            "is_optional": True,
        },
        (
            "【ライブ開始時】自分のステージにエネルギーカードが下にあるメンバーがいる場合、"
            "ライブ終了時まで、【heart01】を得る。"
        ): {
            "suffix": "stage_attached_energy_member_gain_heart01",
            "condition": {"own_stage_has_attached_energy_member": True},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】自分のステージにいるメンバーが持つハートの中に"
            "【heart01】、【heart02】、【heart03】、【heart04】、"
            "【heart05】、【heart06】がすべてある場合、ライブ終了時まで、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "stage_all_heart_colors_gain_blade2",
            "condition": {
                "own_stage_heart_colors_present": [
                    "heart01",
                    "heart02",
                    "heart03",
                    "heart04",
                    "heart05",
                    "heart06",
                ]
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】相手のステージにいるすべてのメンバーのそれぞれのコストより"
            "コストが高いメンバーが自分のステージにいる場合、ライブ終了時まで、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "own_member_higher_than_all_opponent_cost_gain_blade2",
            "condition": {"own_stage_member_cost_higher_than_all_opponent": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】ライブ終了時まで、自分のステージにいる、"
            "このターン中にエリアを移動したメンバーは【ブレード】を得る。"
        ): {
            "suffix": "moved_stage_members_blade1",
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"moved_this_turn": True},
                }
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】【左サイド】このターン、このメンバーがエリアを移動している場合、"
            "ライブ終了時まで、【ブレード】【ブレード】を得る。"
            "（この能力は左サイドエリアにいる場合のみ発動する。）"
        ): {
            "suffix": "left_source_moved_this_turn_blade2",
            "condition": {"source_slot": "left", "source_moved_this_turn": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】【右サイド】このターン、このメンバーがエリアを移動している場合、"
            "ライブ終了時まで、【ブレード】【ブレード】を得る。"
            "（この能力は右サイドエリアにいる場合のみ発動する。）"
        ): {
            "suffix": "right_source_moved_this_turn_blade2",
            "condition": {"source_slot": "right", "source_moved_this_turn": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        (
            "【ライブ開始時】【センター】自分のステージにいるすべての『Liella!』のメンバーと、"
            "自分のすべてのエネルギーをアクティブにする。"
        ): {
            "suffix": "center_ready_all_liella_members_and_energy",
            "condition": {
                "source_slot": "center",
                "own_stage_members_only_work_key": "love_live_superstar",
            },
            "actions": [
                {"action_type": "ready_member", "target": "self_stage_all"},
                {"action_type": "ready_energy", "target": "auto", "amount": 99},
            ],
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
            "【ライブ開始時】自分のデッキの上からカードを4枚控え室に置く。"
            "それらがすべて『蓮ノ空』のカードの場合、ライブ終了時まで、"
            "【ブレード】を得る。"
        ): {
            "suffix": "mill4_all_hasunosora_gain_blade1",
            "actions": [
                {"action_type": "mill_top_cards", "amount": 4},
                {
                    "action_type": "gain_blade",
                    "amount": 1,
                    "value": {"condition": {"milled_all_work_key": "hasunosora"}},
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
        (
            "【ライブ開始時】【E】支払ってもよい："
            "好きなハートの色を1つ指定する。"
            "ライブ終了時まで、そのハートを1つ得る。"
        ): {
            "suffix": "pay1_choose_any_heart1",
            "condition": {"minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
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
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_heart", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】手札を1枚控え室に置いてもよい："
            "ライブ終了時まで、【ブレード】を得る。"
        ): {
            "suffix": "discard1_gain_blade1",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "gain_blade", "amount": 1}],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "ライブ終了時まで、自分のセンターエリアにいる『μ's』のメンバーは、"
            "【ブレード】【ブレード】を得る。"
        ): {
            "suffix": "wait_source_center_muse_blade2",
            "condition": {"source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 2,
                    "value": {"slot": "center", "work_key": "love_live"},
                }
            ],
            "duration": "live",
            "is_optional": True,
        },
        (
            "【ライブ開始時】このメンバーをウェイトにしてもよい："
            "ライブ終了時まで、自分のセンターエリアにいる『μ's』のメンバーは、"
            "【ブレード】を得る。"
        ): {
            "suffix": "wait_source_center_muse_blade1",
            "condition": {"source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "actions": [
                {
                    "action_type": "gain_blade_to_stage_members",
                    "amount": 1,
                    "value": {"slot": "center", "work_key": "love_live"},
                }
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
        "【ライブ成功時】【E】【E】【E】支払ってもよい：カードを1枚引く。": {
            "suffix": "optional_pay3_draw1",
            "is_optional": True,
            "condition": {"minimum_active_energy": 3},
            "cost": [{"action_type": "pay_energy", "amount": 3}],
            "actions": [{"action_type": "draw_card", "amount": 1}],
        },
        "【ライブ成功時】自分の成功ライブカード置き場に『μ's』のカードがある場合、カードを1枚引く。": {
            "suffix": "success_love_live_draw1",
            "condition": {
                "success_live_work_count_at_least": {"work_key": "love_live", "count": 1}
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】カードを1枚引く。自分の成功ライブカード置き場に『μ's』のカードがある場合、さらにカードを1枚引く。": {
            "suffix": "draw1_success_love_live_extra_draw1",
            "actions": [
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
        "【ライブ成功時】自分のステージにいるメンバーが持つハートの総数が、相手のステージにいるメンバーが持つハートの総数より多い場合、このカードのスコアを＋１する。": {
            "suffix": "stage_total_heart_more_than_opponent_score1",
            "condition": {"own_stage_total_heart_more_than_opponent": True},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】このターン、自分が余剰ハートを持たない場合、このカードのスコアを＋１する。": {
            "suffix": "no_excess_heart_score1",
            "condition": {"own_excess_heart_count_at_most": 0},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージにいるウェイト状態のメンバー1人につき、このカードのスコアを＋１する。": {
            "suffix": "wait_stage_member_count_score",
            "actions": [
                {
                    "action_type": "modify_score",
                    "amount_source": "own_wait_stage_member_count",
                }
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに、元々持つハートの数より多い数のハートを持つメンバーがいる場合、カードを1枚引く。": {
            "suffix": "extra_heart_stage_member_draw1",
            "condition": {
                "own_stage_member_more_than_original_heart_count_at_least": {
                    "count": 1
                }
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分が余剰ハートに【heart01】を1つ以上持つ場合、カードを1枚引く。": {
            "suffix": "excess_heart01_draw1",
            "condition": {
                "own_excess_heart_color_count_at_least": {
                    "color_slot": "heart01",
                    "count": 1,
                }
            },
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に、ブレードハートを持たない『μ's』のメンバーカードがある場合、カードを1枚引き、手札を1枚控え室に置く。": {
            "suffix": "revealed_muse_member_without_blade_heart_draw1_discard1",
            "condition": {
                "own_yell_revealed_member_without_blade_heart_count_at_least": {
                    "work_key": "love_live",
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
        "【ライブ成功時】エールにより公開された自分のカードの中にライブカードが2枚以上あるか、自分のステージにいるメンバーが持つハートの中に【heart01】、【heart04】、【heart05】、【heart02】、【heart03】、【heart06】のうち合計5種類以上あるか、このターンに自分のステージにいるメンバーがエリアを移動している場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_live2_or_stage_heart_variety5_or_member_moved_score1",
            "condition": {
                "live_success_any_revealed_live2_stage_heart_variety5_or_member_moved": True
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のデッキの一番上のカードを公開し、手札に加える。それがブレードハートを持たないメンバーカードの場合、ライブの合計スコアを＋１する。": {
            "suffix": "reveal_top_to_hand_non_blade_member_score1",
            "actions": [
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
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】このターン、エールにより公開された自分のカードの中にブレードハートを持たないカードが0枚の場合か、または自分が余剰ハートを2つ以上持っている場合、このカードのスコアは４になる。": {
            "suffix": "no_yell_blade_heartless_or_excess2_replace_score4",
            "condition": {"own_yell_no_blade_heartless_or_excess_heart_count_at_least": 2},
            "actions": [{"action_type": "replace_score", "amount": 4}],
            "duration": "game",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分か相手の成功ライブカード置き場にカードが2枚以上ある場合、エールにより公開された自分のカードの中から、メンバーカードを2枚まで手札に加える。": {
            "suffix": "any_success2_yell_revealed_member_up_to2_to_hand",
            "condition": {"any_success_live_count_at_least": 2},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "card_type": "member",
                "minimum": 0,
                "maximum": 2,
            },
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】手札を1枚控え室に置いてもよい：エールにより公開された自分のカードの中から、コスト2以下のメンバーカードか、スコア２以下のライブカードを1枚手札に加える。": {
            "suffix": "discard1_yell_revealed_cost2_member_or_score2_live_to_hand",
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
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
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】自分が余剰ハートを3つ以上持っている場合、それらをすべて失い、このカードのスコアを＋１する。": {
            "suffix": "clear_excess_heart3_score1",
            "condition": {"own_excess_heart_count_at_least": 3},
            "actions": [
                {"action_type": "clear_excess_hearts"},
                {"action_type": "modify_score", "amount": 1},
            ],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】ライブ終了時まで、相手は余剰ハートをすべて失う。これにより相手が余剰ハートを2つ以上失っている場合、このカードのスコアを＋１する。": {
            "suffix": "clear_opponent_excess_heart2_score1",
            "actions": [
                {"action_type": "clear_excess_hearts", "target": "opponent"},
                {
                    "action_type": "modify_score",
                    "amount": 1,
                    "value": {
                        "condition": {
                            "last_cleared_excess_heart_count_at_least": 2
                        }
                    },
                },
            ],
            "duration": "live",
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
        "【ライブ成功時】エールにより公開された自分のカードの中にライブカードが1枚以上あるとき、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "revealed_live1_place_wait_energy",
            "condition": {
                "yell_revealed_card_type_count_at_least": {
                    "card_type": "live",
                    "count": 1,
                },
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
        "【ライブ成功時】相手は、エネルギーデッキからエネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "opponent_place_wait_energy",
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "opponent",
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
        "【ライブ成功時】このターン、自分のデッキがリフレッシュしていた場合、このカードのスコアを＋２する。": {
            "suffix": "deck_refreshed_this_turn_score2",
            "condition": {"own_deck_refreshed_this_turn": True},
            "actions": [{"action_type": "modify_score", "amount": 2}],
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
        "【ライブ成功時】エールにより公開された自分のカードの枚数が、相手がエールによって公開したカードの枚数より少ない場合、カードを1枚引く。": {
            "suffix": "fewer_yell_revealed_cards_than_opponent_draw1",
            "condition": {"yell_revealed_card_count_less_than_opponent": True},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中にライブカードがある場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_live_score1",
            "condition": {"yell_revealed_card_type_count_at_least": {"card_type": "live", "count": 1}},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に【ALLブレード】を持つカードが1枚以上ある場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_all_blade_score1",
            "condition": {
                "own_yell_revealed_special_blade_heart_count_at_least": {
                    "effect_type": "all_color",
                    "count": 1,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】【センター】エールにより公開された自分のカードの中に、【スコア】を持つ『Aqours』のライブカードがある場合、ライブの合計スコアを＋１する。": {
            "suffix": "center_revealed_aqours_score_live_score1",
            "condition": {
                "source_slot": "center",
                "own_yell_revealed_special_blade_heart_count_at_least": {
                    "effect_type": "score",
                    "card_type": "live",
                    "work_key": "love_live_sunshine",
                    "count": 1,
                },
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分か相手の成功ライブカード置き場にカードが2枚以上あり、かつエールにより公開された自分のカードの中に【スコア】を持つライブカードが1枚以上ある場合、このカードのスコアを＋２する。": {
            "suffix": "any_success2_revealed_score_live_score2",
            "condition": {
                "any_success_live_count_at_least": 2,
                "own_yell_revealed_special_blade_heart_count_at_least": {
                    "effect_type": "score",
                    "card_type": "live",
                    "count": 1,
                },
            },
            "actions": [{"action_type": "modify_score", "amount": 2}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに「澁谷かのん」と「唐 可可」がいる場合、カードを1枚引く。 (必要ハートを確認する時、エールで出た【ALLブレード】は任意の色のハートとして扱う。)": {
            "suffix": "stage_kanon_keke_draw1",
            "condition": {"own_stage_member_names_present": ["澁谷かのん", "唐 可可"]},
            "actions": [{"action_type": "draw_card", "amount": 1}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に名前が異なる『Liella!』のメンバーカードが5枚以上ある場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_distinct_liella_member5_score1",
            "condition": {
                "own_yell_revealed_member_distinct_name_count_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 5,
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分の『虹ヶ咲』のメンバーカードが持つハートの中に【heart01】、【heart02】、【heart03】、【heart04】、【heart05】、【heart06】がある場合、このカードのスコアを＋１する。": {
            "suffix": "revealed_nijigasaki_member_all_heart_colors_score1",
            "condition": {
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
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に『蓮ノ空』のメンバーカードが10枚以上ある場合、このカードのスコアを＋１する。 (エールをすべて行った後、エールで出た【ドロー】1つにつき、カードを1枚引く。)": {
            "suffix": "revealed_hasu_member10_score1",
            "condition": {
                "own_yell_revealed_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 10,
                }
            },
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
        "【ライブ成功時】ライブの合計スコアが相手より高く、かつ自分のステージに『蓮ノ空』のメンバーがいる場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。 (必要ハートを確認する時、エールで出た【ALLブレード】は任意の色のハートとして扱う。)": {
            "suffix": "higher_score_hasu_stage_place_wait_energy",
            "condition": {
                "live_score_relation": "greater_than_opponent",
                "own_stage_member_work_count_at_least": {
                    "work_key": "hasunosora",
                    "count": 1,
                },
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
        "【ライブ成功時】自分と相手のライブの合計スコアが同じ場合、エールにより公開された自分のカードの中から、コスト9以上のメンバーカードを1枚手札に加える。": {
            "suffix": "equal_score_yell_revealed_member_cost9_to_hand",
            "condition": {"live_score_relation": "equal_to_opponent"},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "card_type": "member",
                "minimum_cost": 9,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】ライブの合計スコアが相手より高い場合、エールにより公開された自分のカードの中から、『虹ヶ咲』のカードを1枚手札に加える。 (必要ハートを確認する時、エールで出た【ALLブレード】は任意の色のハートとして扱う。)": {
            "suffix": "higher_score_yell_revealed_nijigasaki_to_hand",
            "condition": {"live_score_relation": "greater_than_opponent"},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】このターン、自分が余剰ハートに【heart04】を1つ以上持っており、かつ自分のステージに『虹ヶ咲』のメンバーがいる場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "excess_heart04_nijigasaki_stage_place_wait_energy",
            "condition": {
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
        (
            "【ライブ成功時】自分のデッキの上からカードを4枚見る。"
            "その中からハートに【heart04】を2つ以上持つメンバーカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "inspect4_member_heart04_2_keep1",
            "is_optional": True,
            "choice": {
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
            },
            "actions": [
                {"action_type": "inspect_top_cards", "amount": 4},
                {"action_type": "select_to_hand_from_inspected"},
                {"action_type": "move_remaining_cards"},
            ],
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
        "【ライブ成功時】エールにより公開された自分のカードの中から、カードを1枚デッキの一番上に置いてもよい。": {
            "suffix": "optional_yell_revealed_card_to_deck_top",
            "is_optional": True,
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_deck_top"}],
        },
        "【ライブ成功時】エールにより公開された自分のカードの中から、ライブカードを1枚までデッキの一番下に置く。": {
            "suffix": "yell_revealed_live_up_to1_to_deck_bottom",
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "card_type": "live",
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_deck_bottom"}],
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に『Liella!』のカードが7枚以上ある場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "revealed_liella_card7_place_wait_energy",
            "condition": {
                "own_yell_revealed_work_count_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 7,
                },
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
        "【ライブ成功時】自分のステージに「澁谷かのん」、「ウィーン・マルガレーテ」、「鬼塚冬毬」のうち、名前の異なるメンバーが2人以上いる場合、エールにより公開された自分のカードの中から、カードを1枚手札に加える。": {
            "suffix": "stage_kanon_margarete_tomari_distinct2_yell_card_to_hand",
            "condition": {
                "own_stage_member_names_any_distinct_count_at_least": {
                    "name_ja_any": ["澁谷かのん", "ウィーン・マルガレーテ", "鬼塚冬毬"],
                    "count": 2,
                }
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】エールにより公開された自分のカードの中に、名前が異なる『Liella!』のメンバーカードが3枚以上ある場合、エールにより公開された自分のカードの中から『Liella!』のライブカードを1枚手札に加える。": {
            "suffix": "revealed_distinct_liella_member3_liella_live_to_hand",
            "condition": {
                "own_yell_revealed_member_distinct_name_count_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 3,
                }
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "resolution_area",
                "card_type": "live",
                "work_key": "love_live_superstar",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "move_selected_to_hand"}],
        },
        "【ライブ成功時】自分のステージのセンターエリアにいる『Liella!』のメンバーが、このターン中に移動している場合、このカードのスコアを＋１する。": {
            "suffix": "center_liella_moved_this_turn_score1",
            "condition": {
                "own_stage_slot_member_moved_this_turn": {
                    "slot": "center",
                    "work_key": "love_live_superstar",
                }
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】カードを1枚引く。このターン、このメンバーがエリアを移動している場合、さらにカードを1枚引く。": {
            "suffix": "draw1_source_moved_extra_draw1",
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {
                    "action_type": "draw_card",
                    "amount": 1,
                    "value": {"condition": {"source_moved_this_turn": True}},
                },
            ],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分が余剰ハートを1つ以上持っている場合、カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "excess_heart1_draw2_discard1",
            "condition": {"own_excess_heart_count_at_least": 1},
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
        "【ライブ成功時】自分が余剰ハートを持たない場合、ライブの合計スコアを＋１する。自分が余剰ハートを2つ以上持つ場合、ライブの合計スコアを－１する。この効果ではライブの合計スコアは０未満にはならない。": {
            "suffix": "no_excess_score1_excess2_score_minus1",
            "actions": [
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
            "duration": "live",
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】ライブの合計スコアが相手より高い場合、自分のエネルギーデッキから、このメンバーの下にあるエネルギーカードの枚数に1を足した枚数のエネルギーカードをウェイト状態で置く。": {
            "suffix": "source_attached_energy_plus1_place_wait_energy",
            "condition": {
                "live_score_relation": "greater_than_opponent",
                "minimum_energy_deck_cards": 1,
            },
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "amount_source": "source_attached_energy_count_plus",
                    "value": {"add": 1},
                    "target": "self",
                    "orientation": "wait",
                }
            ],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに『スリーズブーケ』のメンバーがいる場合、自分のデッキの上からカードを4枚控え室に置いてもよい。": {
            "suffix": "cerise_stage_optional_mill4",
            "is_optional": True,
            "condition": {
                "own_stage_member_unit_count_at_least": {
                    "unit_key": "cerise_bouquet",
                    "count": 1,
                }
            },
            "actions": [{"action_type": "mill_top_cards", "amount": 4}],
        },
        "【ライブ成功時】自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置いてもよい。そうした場合、相手はカードを1枚引く。": {
            "suffix": "optional_place_wait_energy_opponent_draw1",
            "is_optional": True,
            "condition": {"minimum_energy_deck_cards": 1},
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                },
                {"action_type": "draw_card", "target": "opponent", "amount": 1},
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
        "【ライブ成功時】このカードのスコアが３の場合、自分の控え室にある『虹ヶ咲』のカードを1枚手札に加える。": {
            "suffix": "source_score3_return_nijigasaki_card",
            "condition": {"source_score_exact": 3},
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "work_key": "nijigasaki",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
        "【ライブ成功時】自分のステージにこのメンバー以外のメンバーがいる場合、このメンバーをウェイトにする。": {
            "suffix": "other_stage_member_wait_source",
            "condition": {
                "source_orientation": "active",
                "own_stage_member_count_at_least": 2,
            },
            "actions": [{"action_type": "apply_wait"}],
            "execution_mode": "auto_resolve",
        },
        "【ライブ成功時】自分のステージに名前の異なる『BiBi』のメンバーが2人以上いる場合、自分の控え室から『BiBi』のメンバーカードを1枚手札に加える。": {
            "suffix": "bibi_distinct2_return_bibi_member",
            "condition": {
                "own_stage_member_unit_distinct_name_count_at_least": {
                    "unit_key": "bibi",
                    "count": 2,
                }
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "member",
                "unit_key": "bibi",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
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
            is_optional=bool(values.get("is_optional", False)),
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _live_start_deep_modifiers(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【ライブ開始時】このメンバーが持つ【ブレード】の数が8つ以上の場合、カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "source_blade8_draw2_discard1",
            "condition": {"source_blade_at_least": 8},
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
        "【ライブ開始時】このターン、自分のステージにメンバーが2回以上登場している場合、ライブ終了時まで、「【常時】ライブの合計スコアを＋１する。」を得る。": {
            "suffix": "member_entered2_score1",
            "condition": {"own_member_entered_count_this_turn_at_least": 2},
            "actions": [{"action_type": "modify_score", "amount": 1}],
            "duration": "live",
        },
        "【ライブ開始時】ライブ終了時まで、自分のステージのセンターエリアにいる『Liella!』のメンバーが元々持つ【ブレード】の数は3つになる。": {
            "suffix": "center_liella_base_blade3",
            "actions": [
                {
                    "action_type": "replace_member_base_blade",
                    "amount": 3,
                    "value": {
                        "slot": "center",
                        "work_key": "love_live_superstar",
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
        "【ライブ開始時】自分のステージにいる『Aqours』のメンバーが持つハートに、【heart02】が合計6個以上ある場合、このカードの【ライブ成功時】能力を無効にする。": {
            "suffix": "aqours_stage_heart02_6_disable_source_live_success",
            "condition": {
                "own_stage_heart_at_least": {
                    "unit_key": "aqours",
                    "color_slot": "heart02",
                    "count": 6,
                }
            },
            "actions": [{"action_type": "disable_source_live_success_effects"}],
            "duration": "live",
        },
        "【ライブ開始時】【センター】自分のステージの右サイドエリアと左サイドエリアにいるメンバーのコストが同じ場合、相手のステージにいる元々持つ【ブレード】の数が3つ以下のすべてのメンバーをウェイトにする。": {
            "suffix": "center_side_cost_equal_wait_opponent_original_blade3",
            "condition": {
                "source_slot": "center",
                "own_side_stage_member_costs_equal": True,
            },
            "actions": [
                {
                    "action_type": "apply_wait_member",
                    "target": "opponent_stage_original_blade_at_most",
                    "amount": 3,
                }
            ],
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
        "【ライブ開始時】自分のステージに、このターン中にバトンタッチして登場した『蓮ノ空』のメンバーが2人以上いる場合、このカードを成功させるための必要ハートを【heart04】減らす。": {
            "suffix": "hasunosora_baton_entered2_required_heart04_minus1",
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
                    "color_slot": "heart04",
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
        "【ライブ開始時】自分のステージに、元々持つハートの数より多い数のハートを持つ『みらくらぱーく！』のメンバーが1人以上いる場合、カードを1枚引く。2人以上いる場合、さらにこのカードの必要ハートを【heart0】【heart0】減らす。": {
            "suffix": "miracra_park_extra_heart_count_draw_required_any_minus2",
            "condition": {
                "own_stage_member_more_than_original_heart_count_at_least": {
                    "unit_key": "miracra_park",
                    "count": 1,
                }
            },
            "actions": [
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
        "【ライブ開始時】自分のステージにいる『Aqours』のメンバー1人を選ぶ。そのメンバーが持つ【ブレード】が6つ以上の場合、このカードのスコアを＋１する。": {
            "suffix": "choose_aqours_member_blade6_score1",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "love_live_sunshine",
                "minimum_blade": 6,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
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
        "【ライブ開始時】自分と相手の成功ライブカード置き場にあるカードの枚数が同じ場合、ライブ終了時まで、【heart02】【heart02】を得る。": {
            "suffix": "success_count_equal_opponent_heart02_2",
            "condition": {"own_success_live_count_equals_opponent": True},
            "actions": [
                {"action_type": "gain_heart", "amount": 2, "color_slot": "heart02"}
            ],
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
        (
            "【起動】【ターン1回】このメンバーをウェイトにする："
            "ライブ終了時まで、自分のステージにいる『みらくらぱーく！』のメンバー1人は、"
            "【ブレード】を得る。"
        ): {
            "suffix": "wait_source_miracra_park_member_gain_blade1",
            "condition": {"source_orientation": "active"},
            "cost": [{"action_type": "apply_wait", "target": "source"}],
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "unit_key": "miracra_park",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "gain_blade", "target": "selected", "amount": 1}
            ],
            "duration": "live",
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
        (
            "【起動】【ターン1回】【E】【E】手札を1枚控え室に置く："
            "自分のデッキの上からカードを5枚見る。"
            "その中から『Liella!』のカードを1枚公開して手札に加えてもよい。"
            "残りを控え室に置く。"
        ): {
            "suffix": "pay2_discard1_inspect5_liella_card_keep1",
            "condition": {"minimum_active_energy": 2},
            "cost": [
                {"action_type": "pay_energy", "amount": 2},
                {"action_type": "discard_from_hand"},
            ],
            "cost_choice": hand_discard,
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 5,
                "minimum": 0,
                "maximum": 1,
                "work_key": "love_live_superstar",
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
        "【起動】このメンバーをステージから控え室に置く：自分のエネルギーが6枚以上ある場合、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "source_to_waiting_energy6_place_wait_energy",
            "condition": {
                "own_energy_count_at_least": 6,
                "minimum_energy_deck_cards": 1,
            },
            "cost": [{"action_type": "source_to_waiting_room"}],
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
        (
            "【起動】【ターン1回】このメンバー以外の『虹ヶ咲』のメンバー1人をウェイトにする："
            "カードを1枚引く。"
        ): {
            "suffix": "wait_other_nijigasaki_member_draw1",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "work_key": "nijigasaki",
                "exclude_source": True,
                "orientation": "active",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {"action_type": "apply_wait_member", "target": "selected"},
                {"action_type": "draw_card", "amount": 1},
            ],
        },
        "【起動】【ターン1回】手札を1枚控え室に置く：エネルギー1枚か『虹ヶ咲』のメンバー1人をアクティブにする。": {
            "suffix": "discard1_ready_energy1_or_nijigasaki_member",
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "choice": {
                "choice_type": "choose_effect_branch",
                "zone": "stage",
                "branch_ids": ["ready_energy", "ready_member"],
                "branch_selection_minimum": {"ready_member": 1},
                "branch_selection_maximum": {"ready_member": 1},
                "branch_choice_filters": {
                    "ready_member": {
                        "choice_type": "member_from_stage",
                        "zone": "stage",
                        "card_type": "member",
                        "work_key": "nijigasaki",
                        "orientation": "wait",
                    }
                },
            },
            "actions": [
                {
                    "action_type": "ready_energy",
                    "target": "auto",
                    "amount": 1,
                    "branch": "ready_energy",
                },
                {"action_type": "ready_member", "branch": "ready_member"},
            ],
        },
        "【起動】【ターン1回】手札を1枚控え室に置く：このターン、自分のステージに『虹ヶ咲』のメンバーが登場している場合、エネルギーを2枚アクティブにする。": {
            "suffix": "discard1_if_nijigasaki_entered_ready_energy2",
            "condition": {"own_stage_member_work_entered_this_turn": "nijigasaki"},
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": hand_discard,
            "actions": [
                {"action_type": "ready_energy", "target": "auto", "amount": 2}
            ],
        },
        "【起動】【ターン1回】デッキの上からカードを3枚控え室に置く：ライブ終了時まで、これにより控え室に置いた『Liella!』のメンバーカード1枚につき、【ブレード】を得る。": {
            "suffix": "mill3_blade_per_milled_liella_member",
            "cost": [{"action_type": "mill_top_cards", "amount": 3}],
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "milled_member_work_count",
                    "value": {"work_key": "love_live_superstar"},
                }
            ],
            "duration": "live",
        },
        "【起動】【ターン1回】このメンバーをウェイトにするか、手札を1枚控え室に置く：エネルギーを1枚アクティブにする。": {
            "suffix": "wait_source_or_discard1_ready_energy1",
            "choice": {
                "choice_type": "choose_effect_branch",
                "zone": "hand",
                "branch_ids": ["wait_source", "discard_hand"],
                "branch_selection_minimum": {"discard_hand": 1},
                "branch_selection_maximum": {"discard_hand": 1},
                "branch_conditions": {
                    "wait_source": {"source_orientation": "active"}
                },
            },
            "actions": [
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
            duration=values.get("duration"),
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
        "【常時】自分のステージにコストがそれぞれ異なるメンバーが3人以上いるかぎり、【heart05】【ブレード】を得る。": {
            "suffix": "own_stage_distinct_cost3_heart05_blade1",
            "condition": {"own_stage_distinct_cost_member_count_at_least": 3},
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
        "【常時】自分の成功ライブカード置き場にあるカードのスコアの合計が相手より高いかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "success_score_higher_than_opponent_blade2",
            "condition": {"success_live_score_more_than_opponent": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】【センター】自分のステージの右サイドエリアと左サイドエリアに、元々持つ【ブレード】の数が2つのメンバーがいるかぎり、ライブの合計スコアを＋１する。": {
            "suffix": "center_side_original_blade2_score1",
            "condition": {
                "source_slot": "center",
                "own_side_stage_member_original_blade_exact": 2,
            },
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】自分と相手のステージの中で、このメンバーがほかのすべてのメンバーより多くのハートを持つかぎり、ライブの合計スコアを＋１する。": {
            "suffix": "source_most_stage_hearts_score1",
            "condition": {"source_has_most_stage_hearts": True},
            "actions": [{"action_type": "modify_score", "amount": 1}],
        },
        "【常時】自分のステージにいるメンバーのうち、センターエリアにいるメンバーが最も大きいコストを持つ場合、【heart03】を得る。": {
            "suffix": "center_highest_cost_heart03",
            "condition": {"own_center_member_highest_cost": True},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
        },
        "【常時】自分のライブカード置き場に必要ハートの合計が8以上の『Liella!』のライブカードがあるかぎり、【heart03】を得る。": {
            "suffix": "liella_live_required_heart8_heart03",
            "condition": {
                "live_area_work_required_heart_total_at_least": {
                    "work_key": "love_live_superstar",
                    "count": 8,
                }
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
        },
        "【常時】このメンバーがウェイト状態であるかぎり、【heart05】を得る。": {
            "suffix": "source_wait_heart05",
            "condition": {"source_orientation": "wait"},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart05"}
            ],
        },
        "【常時】このメンバーの正面のエリアにいる相手のメンバーのコストが、このメンバーのコストより高いかぎり、【heart01】を得る。": {
            "suffix": "opposing_member_higher_cost_heart01",
            "condition": {"opposing_member_cost_greater_than_source": True},
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart01"}
            ],
        },
        "【常時】このターンにこのメンバーが移動していないかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "source_not_moved_this_turn_blade2",
            "condition": {"source_not_moved_this_turn": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
        "【常時】このメンバーの下にエネルギーカードが2枚以上置かれているかぎり、ライブの合計スコアを＋１する。 (メンバーがステージから離れたとき、下に置かれているエネルギーカードはエネルギーデッキに戻す。)": {
            "suffix": "attached_energy2_score1",
            "condition": {"source_attached_energy_count_at_least": 2},
            "actions": [{"action_type": "modify_score", "amount": 1}],
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
        "【常時】相手の成功ライブカード置き場にあるカードの枚数が自分より多いかぎり、その差に等しい数の【ブレード】を得る。": {
            "suffix": "blade_per_opponent_success_lead",
            "condition": {"own_success_live_count_less_than_opponent": True},
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "opponent_success_live_count_difference",
                }
            ],
        },
        "【常時】自分のステージにいるほかの『みらくらぱーく！』のメンバー1人につき、【ブレード】を得る。": {
            "suffix": "blade_per_other_miracra_park_member",
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "own_stage_member_unit_count",
                    "value": {"unit_key": "miracra_park", "exclude_source": True},
                }
            ],
        },
        "【常時】自分のステージにいるコスト4以上の『スリーズブーケ』以外のメンバー1人につき、【ブレード】【ブレード】を得る。": {
            "suffix": "blade2_per_cost4_non_cerise_bouquet_member",
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "own_stage_member_filter_count",
                    "multiplier": 2,
                    "value": {
                        "minimum_cost": 4,
                        "exclude_unit_key": "cerise_bouquet",
                    },
                }
            ],
        },
        "【常時】自分のステージにこのメンバー以外の『Edel Note』のメンバーがいるかぎり、【ブレード】【ブレード】を得る。": {
            "suffix": "other_edel_note_member_blade2",
            "condition": {
                "own_stage_other_member_unit_count_at_least": {
                    "unit_key": "edel_note",
                    "count": 1,
                }
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
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
        "【常時】自分のステージにメンバーがちょうど2人おり、かつ相手のステージにメンバーが3人以上いるかぎり、【heart06】を得る。": {
            "suffix": "own_stage2_opponent_stage3_heart06",
            "condition": {
                "own_stage_member_count_exact": 2,
                "opponent_stage_member_count_at_least": 3,
            },
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
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
        "【常時】相手の余剰ハートが2つ以上あるかぎり、自分のライブの合計スコアを＋１する。": {
            "suffix": "opponent_excess_heart2_score1",
            "condition": {"opponent_excess_heart_count_at_least": 2},
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


def _static_segment_center_heart03_3(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【常時】【センター】【heart03】【heart03】【heart03】を得る。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="static_center_heart03_3",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="static",
        timing="static_always",
        trigger="static_always",
        frequency_limit="none",
        is_optional=False,
        condition={"source_slot": "center"},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "gain_heart", "amount": 3, "color_slot": "heart03"}
        ],
        duration="game",
    )


def _static_segment_right_heart05_3(row: sqlite3.Row) -> EffectCandidate | None:
    label = "【常時】【右サイド】【heart05】【heart05】【heart05】を得る。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="static_right_heart05_3",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="static",
        timing="static_always",
        trigger="static_always",
        frequency_limit="none",
        is_optional=False,
        condition={"source_slot": "right"},
        cost=[],
        choice=None,
        actions=[
            {"action_type": "gain_heart", "amount": 3, "color_slot": "heart05"}
        ],
        duration="game",
    )


def _static_segment_stage_fujishima_blade2(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = "【常時】自分のステージに「藤島 慈」がいるかぎり、【ブレード】【ブレード】を得る。"
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id="static_stage_name_fujishima_megumi_blade2",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="static",
        timing="static_always",
        trigger="static_always",
        frequency_limit="none",
        is_optional=False,
        condition={"own_stage_member_name_any": ["藤島 慈"]},
        cost=[],
        choice=None,
        actions=[{"action_type": "gain_blade", "amount": 2}],
        duration="game",
    )


def _static_opponent_wait_count_modifiers(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【常時】相手のステージにいるウェイト状態のメンバー1人につき、【ブレード】を得る。": {
            "suffix": "blade_per_opponent_wait_member",
            "actions": [
                {
                    "action_type": "gain_blade",
                    "amount_source": "opponent_stage_wait_member_count",
                }
            ],
        },
        "【常時】相手のステージにいるウェイト状態のメンバー1人につき、【heart06】を得る。": {
            "suffix": "heart06_per_opponent_wait_member",
            "actions": [
                {
                    "action_type": "gain_heart",
                    "amount_source": "opponent_stage_wait_member_count",
                    "color_slot": "heart06",
                }
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
            condition={},
            cost=[],
            choice=None,
            actions=values["actions"],
            duration="game",
        )
    return None


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


def _live_start_grouped_edel_note_blade_and_heart06(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】ライブ終了時まで、自分のステージにいる『Edel Note』のメンバー1人は、"
        "【ブレード】【ブレード】を得て、そのメンバーとは名前の異なる『Edel Note』のメンバー1人は、"
        "【heart06】【heart06】を得る。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_grouped_edel_note_blade2_and_other_name_heart06_2",
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
                    "group_id": "blade_member",
                    "label_ja": "【ブレード】を得る『Edel Note』のメンバー",
                    "zone": "stage",
                    "card_type": "member",
                    "unit_key": "edel_note",
                    "minimum": 1,
                    "maximum": 1,
                },
                {
                    "group_id": "heart_member",
                    "label_ja": "【heart06】を得る名前の異なる『Edel Note』のメンバー",
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
    )


def _live_success_stage2_return_score3_live(row: sqlite3.Row) -> EffectCandidate | None:
    label = (
        "【ライブ成功時】自分のステージにメンバーが2人以上いる場合、"
        "自分の控え室からスコア３以下のライブカードを1枚手札に加える。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_success_stage2_return_score3_live",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_success",
        trigger="live_succeeded",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={"own_stage_member_count_at_least": 2},
        cost=[],
        choice={
            "choice_type": "card_from_zone",
            "zone": "waiting_room",
            "card_type": "live",
            "maximum_score": 3,
            "minimum": 1,
            "maximum": 1,
        },
        actions=[{"action_type": "return_from_waiting_room"}],
        duration=None,
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


def _live_start_choose_color_replace_source_base_hearts(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    patterns: dict[str, tuple[str, list[str]]] = {
        "【ライブ開始時】【heart01】か【heart03】か【heart04】のうち1つを選ぶ。ライブ終了時まで、このメンバーが元々持つハートは選んだハートになる。": (
            "heart01_03_04",
            ["heart01", "heart03", "heart04"],
        ),
        "【ライブ開始時】【heart02】か【heart05】か【heart06】のうち1つを選ぶ。ライブ終了時まで、このメンバーが元々持つハートは選んだハートになる。": (
            "heart02_05_06",
            ["heart02", "heart05", "heart06"],
        ),
        "【ライブ開始時】【heart03】か【heart04】か【heart05】のうち1つを選ぶ。ライブ終了時まで、このメンバーが元々持つハートは選んだハートになる。": (
            "heart03_04_05",
            ["heart03", "heart04", "heart05"],
        ),
        "【ライブ開始時】【heart01】か【heart02】か【heart06】のうち1つを選ぶ。ライブ終了時まで、このメンバーが元々持つハートは選んだハートになる。": (
            "heart01_02_06",
            ["heart01", "heart02", "heart06"],
        ),
    }
    for label, (suffix, color_slots) in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        return EffectCandidate(
            **_base(
                row,
                pattern_id=f"live_start_choose_{suffix}_replace_source_base_hearts",
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
                "choice_type": "choose_color",
                "color_slots": color_slots,
                "minimum": 1,
                "maximum": 1,
            },
            actions=[{"action_type": "replace_member_base_hearts"}],
            duration="live",
        )
    return None


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


def _live_start_choose_aqours_blade2_or_wait_opponent_cost4(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】自分のステージのセンターエリアにコスト9以上の"
        "『Aqours』のメンバーがいる場合、以下から1つを選ぶ。 "
        "・ライブ終了時まで、自分のステージにいるメンバー1人は、"
        "【ブレード】【ブレード】を得る。 "
        "・相手のステージにいるコスト4以下のメンバー1人をウェイトにする。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_choose_aqours_center9_blade2_or_wait_opponent_cost4",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        frequency_limit="once_per_live",
        is_optional=False,
        condition={
            "own_center_member_work_cost_at_least": {
                "work_key": "love_live_sunshine",
                "count": 9,
            }
        },
        cost=[],
        choice={
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
        actions=[
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
        duration="live",
    )


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


def _live_start_muse_stage_draw_discard_heart_score(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】自分のステージにメンバーが1人以上いる場合、"
        "自分と相手はカードを1枚引き、手札を1枚控え室に置く。"
        "2人以上いる場合、さらに自分のステージにいる『μ's』のメンバー1人は、"
        "ライブ終了時まで、【heart03】を得る。"
        "3人以上おり、かつそれぞれ名前が異なる場合、さらにこのカードのスコアを＋１する。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_muse_stage_draw_discard_heart03_score",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
    )


def _live_start_all_aqours_score_draw_hand_top_or_bottom(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】自分のステージにいるメンバーがすべて"
        "『Aqours』の場合、このカードのスコアを＋１し、"
        "カードを1枚引き、手札からカードを1枚デッキの一番上か一番下に置く。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="live_start_all_aqours_score_draw_hand_top_or_bottom",
            effect_index=effect_index,
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
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
    )


def _live_start_choose_grant_success_draw_or_baton_aqours_heart_or_success2_score(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【ライブ開始時】以下から1つを選ぶ。 "
        "・このカードは「【ライブ成功時】カードを1枚引く。」を得る。 "
        "・ライブ終了時まで、このターンにバトンタッチして登場した"
        "『Aqours』のメンバー1人は【heart02】を得る。 "
        "・自分の成功ライブカード置き場にカードが2枚以上ある場合、"
        "このカードのスコアを＋１する。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id=(
                "live_start_choose_grant_success_draw_or_baton_aqours_heart_"
                "or_success2_score"
            ),
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
    )


def _onplay_shuffle_waiting_members_bottom_return_live_blade2(
    row: sqlite3.Row,
) -> EffectCandidate | None:
    label = (
        "【登場】自分と相手はそれぞれ、自身の控え室にあるすべての"
        "メンバーカードをシャッフルし、自身のデッキの下に置く。"
        "これにより自分と相手のカードが合計20枚以上デッキの下に置かれた場合、"
        "自分の控え室からライブカードを1枚手札に加え、"
        "ライブ終了時まで、【ブレード】【ブレード】を得る。"
    )
    matched = _matching_segment(row, label)
    if matched is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base(
            row,
            pattern_id="onplay_shuffle_waiting_members_bottom_return_live_blade2",
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
    )


def _source_position_change_simple(row: sqlite3.Row) -> EffectCandidate | None:
    patterns = {
        "【登場】このメンバーをポジションチェンジしてもよい。(このメンバーを今いるエリア以外のエリアに移動させる。そのエリアにメンバーがいる場合、そのメンバーはこのメンバーがいたエリアに移動させる。)": {
            "suffix": "onplay_optional_source_position_change",
            "timing": "on_play",
            "trigger": "member_played",
            "frequency_limit": "none",
            "is_optional": True,
            "condition": {},
            "choice": {},
        },
        "【ライブ開始時】このメンバーをポジションチェンジしてもよい。(このメンバーを今いるエリア以外のエリアに移動させる。そのエリアにメンバーがいる場合、そのメンバーはこのメンバーがいたエリアに移動させる。)": {
            "suffix": "live_start_optional_source_position_change",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "is_optional": True,
            "condition": {},
            "choice": {},
        },
        "【ライブ開始時】自分のステージに【ブレード】を5つ以上持つ『μ's』のメンバーがいない場合、このメンバーはセンターエリア以外にポジションチェンジする。(このメンバーを今いるエリア以外のエリアに移動させる。そのエリアにメンバーがいる場合、そのメンバーはこのメンバーがいたエリアに移動させる。)": {
            "suffix": "live_start_no_muse_blade5_position_change_non_center",
            "timing": "live_start",
            "trigger": "live_started",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": {
                "own_stage_member_work_blade_count_at_most": {
                    "work_key": "love_live",
                    "minimum_blade": 5,
                    "count": 0,
                }
            },
            "choice": {"excluded_position_slots": ["center"]},
        },
        "【起動】【ターン1回】【E】【E】：このメンバーをポジションチェンジする。": {
            "suffix": "activated_pay2_source_position_change",
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "frequency_limit": "once_per_turn",
            "is_optional": False,
            "condition": {"source_zone": "stage", "minimum_active_energy": 2},
            "cost": [{"action_type": "pay_energy", "amount": 2}],
            "choice": {},
        },
        "【起動】【ターン1回】【E】：このメンバーがいるエリアとは別の自分のエリア1つを選ぶ。このメンバーをそのエリアに移動する。選んだエリアにメンバーがいる場合、そのメンバーは、このメンバーがいたエリアに移動させる。": {
            "suffix": "activated_pay1_source_position_change",
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "frequency_limit": "once_per_turn",
            "is_optional": False,
            "condition": {"source_zone": "stage", "minimum_active_energy": 1},
            "cost": [{"action_type": "pay_energy", "amount": 1}],
            "choice": {},
        },
        "【起動】【ターン1回】デッキの上からカードを3枚控え室に置く：このメンバーはポジションチェンジする。(このメンバーを今いるエリア以外のエリアに移動させる。そのエリアにメンバーがいる場合、そのメンバーはこのメンバーがいたエリアに移動させる。)": {
            "suffix": "activated_mill3_source_position_change",
            "effect_type": "activated",
            "timing": "activated_main",
            "trigger": "player_activation",
            "frequency_limit": "once_per_turn",
            "is_optional": False,
            "condition": {"source_zone": "stage"},
            "cost": [{"action_type": "mill_top_cards", "amount": 3}],
            "choice": {},
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
                pattern_id=values["suffix"],
                effect_index=effect_index,
                execution_mode="prompt_then_resolve",
            ),
            label_ja=exact_label,
            effect_type=values.get("effect_type", "triggered"),
            timing=values["timing"],
            trigger=values["trigger"],
            frequency_limit=values["frequency_limit"],
            is_optional=values["is_optional"],
            condition=values["condition"],
            cost=values.get("cost", []),
            choice={
                "choice_type": "position_change_source",
                "minimum": 1,
                "maximum": 1,
                **values["choice"],
            },
            actions=[{"action_type": "position_change_source"}],
            duration=None,
        )
    return None


def _auto_own_member_played_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【自動】【ターン1回】自分のステージにコスト10のメンバーが登場したとき、カードを1枚引く。": {
            "suffix": "cost10_member_draw1",
            "frequency_limit": "once_per_turn",
            "condition": {"trigger_member_cost_exact": 10},
            "actions": [{"action_type": "draw_card", "amount": 1}],
        },
        "【自動】【ターン1回】自分のステージにこのメンバー以外のコスト11のメンバーが登場したとき、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "other_cost11_member_place_wait_energy",
            "frequency_limit": "once_per_turn",
            "condition": {
                "trigger_member_not_source": True,
                "trigger_member_cost_exact": 11,
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
        },
        "【自動】【ターン1回】自分のステージに『Edel Note』のメンバーが登場したとき、相手は、自身のステージにいるアクティブ状態のメンバー1人をウェイトにする。": {
            "suffix": "edel_note_member_wait_opponent_active_member",
            "frequency_limit": "once_per_turn",
            "condition": {"trigger_member_unit_key": "edel_note"},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "target_player": "opponent",
                "card_type": "member",
                "orientation": "active",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
        },
        "【自動】【センター】【ターン2回】自分のステージに『蓮ノ空』のメンバーが登場するたび、ライブ終了時まで、【ブレード】【ブレード】を得る。": {
            "suffix": "center_hasu_member_blade2",
            "frequency_limit": "twice_per_turn",
            "condition": {
                "source_slot": "center",
                "trigger_member_work_key": "hasunosora",
            },
            "actions": [{"action_type": "gain_blade", "amount": 2}],
            "duration": "live",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = "prompt_then_resolve" if values.get("choice") else "auto_resolve"
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"auto_own_member_played_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="auto_triggered_event",
            trigger="own_member_played",
            frequency_limit=values["frequency_limit"],
            is_optional=False,
            condition=values.get("condition", {}),
            cost=[],
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _auto_moved_source_gain_modifier(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、ライブ終了時まで、【ブレード】を得る。": {
            "suffix": "blade1",
            "actions": [{"action_type": "gain_blade", "amount": 1}],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、ライブ終了時まで、【ブレード】を得る。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "blade1_opponent_effect",
            "actions": [{"action_type": "gain_blade", "amount": 1}],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、ライブ終了時まで、【heart02】を得る。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "heart02",
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"}
            ],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、ライブ終了時まで、【heart03】を得る。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "heart03",
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart03"}
            ],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、ライブ終了時まで、【heart06】を得る。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "heart06",
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
            ],
        },
        "【自動】このメンバーが登場か、エリアを移動するたび、ライブ終了時まで、【ブレード】【ブレード】を得る。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "entered_or_moved_blade2",
            "trigger": "own_member_played|member_moved",
            "frequency_limit": "none",
            "condition": {"trigger_member_is_source": True},
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        },
    }
    matched = None
    values = None
    for label, candidate_values in patterns.items():
        maybe = _matching_segment(row, label)
        if maybe is not None:
            matched = maybe
            values = candidate_values
            break
    if matched is None or values is None:
        return None
    effect_index, exact_label = matched
    return EffectCandidate(
        **_base_with_execution_mode(
            row,
            pattern_id=f"auto_moved_source_gain_{values['suffix']}",
            effect_index=effect_index,
            execution_mode="auto_resolve",
        ),
        label_ja=exact_label,
        effect_type="triggered",
        timing="auto_triggered_event",
        trigger=values.get("trigger", "member_moved"),
        frequency_limit=values.get("frequency_limit", "once_per_turn"),
        is_optional=False,
        condition={"source_zone": "stage", **values.get("condition", {})},
        cost=[],
        choice=None,
        actions=values["actions"],
        duration="live",
    )


def _auto_moved_source_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【自動】このメンバーがエリアを移動するたび、カードを1枚引く。 (対戦相手のカードの効果でも発動する。)": {
            "suffix": "draw1",
            "frequency_limit": "none",
            "actions": [{"action_type": "draw_card", "amount": 1}],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。": {
            "suffix": "place_wait_energy",
            "frequency_limit": "once_per_turn",
            "condition": {"minimum_energy_deck_cards": 1},
            "actions": [
                {
                    "action_type": "place_energy_from_deck",
                    "target": "self",
                    "amount": 1,
                    "orientation": "wait",
                }
            ],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、エネルギーを2枚アクティブにする。": {
            "suffix": "ready_energy2",
            "frequency_limit": "once_per_turn",
            "actions": [
                {"action_type": "ready_energy", "target": "auto", "amount": 2}
            ],
        },
        "【自動】【ターン1回】このメンバーがエリアを移動したとき、自分の控え室から、スコア3以下の『Liella!』のライブカードを1枚手札に加える。": {
            "suffix": "return_liella_live_score3",
            "frequency_limit": "once_per_turn",
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "work_key": "love_live_superstar",
                "maximum_score": 3,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
        "【自動】このメンバーがエリアを移動したとき、相手のステージにいる元々持つ【ブレード】の数が2つ以下のメンバー1人をウェイトにする。": {
            "suffix": "wait_opponent_original_blade2",
            "frequency_limit": "none",
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "target_player": "opponent",
                "card_type": "member",
                "maximum_blade": 2,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
        },
        "【自動】このメンバーが登場か、エリアを移動したとき、相手のステージにいる元々持つ【ブレード】の数が3つ以下のメンバー1人をウェイトにする。": {
            "suffix": "entered_or_moved_wait_opponent_original_blade3",
            "trigger": "own_member_played|member_moved",
            "frequency_limit": "none",
            "condition": {"trigger_member_is_source": True},
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "target_player": "opponent",
                "card_type": "member",
                "maximum_blade": 3,
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "apply_wait_member", "target": "selected"}],
        },
        "【自動】【ターン1回】自分のカードの効果によって、このメンバーがエリアを移動するか自分のエネルギー置き場にエネルギーが置かれたとき、カードを1枚引き、ライブ終了時まで、【heart02】を得る。": {
            "suffix": "moved_or_energy_by_effect_draw1_heart02",
            "trigger": "member_moved|energy_placed_by_effect",
            "frequency_limit": "once_per_turn",
            "actions": [
                {"action_type": "draw_card", "amount": 1},
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart02"},
            ],
            "duration": "live",
        },
        "【自動】カードの効果によって自分のエネルギー置き場にエネルギーカードが置かれるたび、ライブ終了時まで、【heart06】を得る。(相手のカードの効果でも発動する。)": {
            "suffix": "energy_by_effect_heart06",
            "trigger": "energy_placed_by_effect",
            "frequency_limit": "none",
            "actions": [
                {"action_type": "gain_heart", "amount": 1, "color_slot": "heart06"}
            ],
            "duration": "live",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = "prompt_then_resolve" if values.get("choice") else "auto_resolve"
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"auto_moved_source_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="auto_triggered_event",
            trigger=values.get("trigger", "member_moved"),
            frequency_limit=values["frequency_limit"],
            is_optional=False,
            condition={"source_zone": "stage", **values.get("condition", {})},
            cost=[],
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


def _auto_stage_to_waiting_simple_effects(row: sqlite3.Row) -> EffectCandidate | None:
    patterns: dict[str, dict[str, Any]] = {
        "【自動】このメンバーがステージから控え室に置かれたとき、メンバー1人をアクティブにしてもよい。": {
            "suffix": "ready_member_up_to1",
            "frequency_limit": "none",
            "is_optional": True,
            "choice": {
                "choice_type": "member_from_stage",
                "zone": "stage",
                "card_type": "member",
                "orientation": "wait",
                "minimum": 0,
                "maximum": 1,
            },
            "actions": [{"action_type": "ready_member"}],
        },
        (
            "【自動】このメンバーがステージから控え室に置かれたとき、"
            "自分のデッキの上からカードを5枚見る。その中からメンバーカードを1枚公開して"
            "手札に加えてもよい。残りを控え室に置く。"
        ): {
            "suffix": "inspect5_member_keep1",
            "frequency_limit": "none",
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 5,
                "card_type": "member",
                "minimum": 0,
                "maximum": 1,
                "requires_order": False,
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
        (
            "【自動】このメンバーがステージから控え室に置かれたとき、"
            "自分のデッキの上からカードを5枚見る。その中からライブカードを1枚公開して"
            "手札に加えてもよい。残りを控え室に置く。"
        ): {
            "suffix": "inspect5_live_keep1",
            "frequency_limit": "none",
            "choice": {
                "choice_type": "inspect_top_select",
                "amount": 5,
                "card_type": "live",
                "minimum": 0,
                "maximum": 1,
                "requires_order": False,
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
        "【自動】このメンバーがステージから控え室に置かれたとき、カードを2枚引き、手札を1枚控え室に置く。": {
            "suffix": "draw2_discard1",
            "frequency_limit": "none",
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
        "【自動】このメンバーがステージから控え室に置かれたとき、カードを2枚引き、手札を2枚控え室に置く。": {
            "suffix": "draw2_discard2",
            "frequency_limit": "none",
            "choice": {
                "choice_type": "post_action_card_from_zone",
                "zone": "hand",
                "minimum": 2,
                "maximum": 2,
            },
            "actions": [
                {"action_type": "draw_card", "amount": 2},
                {"action_type": "discard_from_hand"},
            ],
        },
        (
            "【自動】このメンバーがステージから控え室に置かれたとき、"
            "手札を1枚控え室に置いてもよい。そうした場合、"
            "自分の控え室から『Aqours』のライブカードを1枚手札に加える。"
        ): {
            "suffix": "optional_discard1_return_aqours_live",
            "frequency_limit": "none",
            "is_optional": True,
            "cost": [{"action_type": "discard_from_hand"}],
            "cost_choice": {
                "choice_type": "card_from_zone",
                "zone": "hand",
                "minimum": 1,
                "maximum": 1,
            },
            "choice": {
                "choice_type": "card_from_zone",
                "zone": "waiting_room",
                "card_type": "live",
                "unit_key": "aqours",
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [{"action_type": "return_from_waiting_room"}],
        },
        (
            "【自動】このメンバーがステージから控え室に置かれたとき、"
            "手札を1枚控え室に置いてもよい。そうした場合、ライブ終了時まで、"
            "自分のステージにいるメンバー1人は、【heart05】【ブレード】を得る。"
        ): {
            "suffix": "optional_discard1_stage_member_heart05_blade1",
            "frequency_limit": "none",
            "is_optional": True,
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
                "minimum": 1,
                "maximum": 1,
            },
            "actions": [
                {
                    "action_type": "gain_heart",
                    "target": "selected",
                    "amount": 1,
                    "color_slot": "heart05",
                },
                {"action_type": "gain_blade", "target": "selected", "amount": 1},
            ],
            "duration": "live",
        },
    }
    for label, values in patterns.items():
        matched = _matching_segment(row, label)
        if matched is None:
            continue
        effect_index, exact_label = matched
        execution_mode = (
            values.get("execution_mode")
            or "prompt_then_resolve"
            if values.get("choice") or values.get("cost") or values.get("is_optional")
            else "auto_resolve"
        )
        return EffectCandidate(
            **_base_with_execution_mode(
                row,
                pattern_id=f"auto_stage_to_waiting_{values['suffix']}",
                effect_index=effect_index,
                execution_mode=execution_mode,
            ),
            label_ja=exact_label,
            effect_type="triggered",
            timing="auto_triggered_event",
            trigger="member_left_stage_to_waiting_room",
            frequency_limit=values["frequency_limit"],
            is_optional=values.get("is_optional", False),
            condition=values.get("condition", {}),
            cost=values.get("cost", []),
            cost_choice=values.get("cost_choice"),
            choice=values.get("choice"),
            actions=values["actions"],
            duration=values.get("duration"),
        )
    return None


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
    _wait_opponent_member_by_cost,
    _dual_onplay_wait_opponent_member_patterns,
    _live_start_wait_opponent_original_blade_patterns,
    _onplay_discard_wait_opponent_members_cost4_up_to2,
    _dual_onplay_wait_source_wait_opponent_member_cost4,
    _dual_livestart_wait_source_wait_opponent_member_cost4,
    _source_wait_opponent_member_patterns,
    _source_wait_opponent_member_live_start_patterns,
    _onplay_ready_energy,
    _onplay_named_stage_ready_energy_return_hasu_live,
    _onplay_success_score_place_active_energy,
    _onplay_return_waiting_member_cost4_muse,
    _onplay_stage_cost13_draw,
    _onplay_success_score_return_muse_live,
    _onplay_success_count_return_live,
    _onplay_energy11_return_live,
    _onplay_opponent_active_member_wait,
    _onplay_wait_opponent_member_blade1,
    _onplay_baton_lower_cost_gain_blade2,
    _onplay_return_baton_replaced_member,
    _onplay_draw_then_discard_one,
    _onplay_named_baton_draw_then_discard,
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
    _onplay_pay_energy_draw,
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
    _activated_deploy_waiting_member_to_empty_stage,
    _onplay_baton_lower_both_discard_to3_draw3,
    _onplay_choose_draw_discard_or_wait_opponent_cost2,
    _onplay_choose_mill3_or_wait_opponent_cost2,
    _onplay_pay1_choose_wait_opponent_cost4_or_draw1,
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
    _onplay_choose_waiting_live_by_distinct_name_or_group,
    _onplay_baton_lower_return_hasu_live,
    _onplay_shuffle_waiting_members_bottom_return_live_blade2,
    _onplay_return_waiting_member_cost2_up_to2,
    _onplay_ready_printemps_member_up_to1,
    _onplay_ready_member_up_to1,
    _onplay_more_simple_effects,
    _live_success_yell_to_hand,
    _live_start_simple_modifiers,
    _live_success_simple_effects,
    _live_success_stage2_return_score3_live,
    _live_start_nijigasaki_ready_history_score,
    _live_start_named_superstar_members_gain_heart_and_blade,
    _live_start_grouped_superstar_members_gain_blade,
    _live_start_grouped_edel_note_blade_and_heart06,
    _live_start_choose_color_replace_source_base_hearts,
    _live_start_yell_blade_heart_replacement,
    _live_start_choose_aqours_blade2_or_wait_opponent_cost4,
    _live_start_left_liella_heart02_blade,
    _live_start_pay2_or_discard2,
    _live_start_muse_stage_draw_discard_heart_score,
    _live_start_all_aqours_score_draw_hand_top_or_bottom,
    _live_start_choose_grant_success_draw_or_baton_aqours_heart_or_success2_score,
    _source_position_change_simple,
    _auto_own_member_played_simple_effects,
    _auto_moved_source_gain_modifier,
    _auto_moved_source_simple_effects,
    _auto_stage_to_waiting_simple_effects,
    _live_start_deep_modifiers,
    _onplay_variable_discard_draw,
    _activated_more_simple_effects,
    _static_segment_center_heart03_3,
    _static_segment_right_heart05_3,
    _static_segment_stage_fujishima_blade2,
    _static_opponent_wait_count_modifiers,
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
