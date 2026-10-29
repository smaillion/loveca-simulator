from collections import Counter
from contextlib import closing
from pathlib import Path

import pytest

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.engine import _normalized_card_name
from test_printemps_ready_history_boundary import _advance, _repo, _replay, _resolve
from test_q246_named_cost_union_boundary import PROBE
from test_q246_paid_color_union_probe import _probe

NAMES = ("南 ことり", "黒澤ダイヤ", "徒町小鈴")


def _inventory():
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        rows = db.execute("SELECT card_code, canonical_name_ja FROM gameplay_cards ORDER BY card_code").fetchall()
        cards = []
        for row in rows:
            normalized = _normalized_card_name(row["canonical_name_ja"])
            if any(_normalized_card_name(name) in normalized for name in NAMES):
                cards.append(_load_definition(db, row["card_code"], None, {}, {}))
        return cards


def test_actual_named_inventory_preserves_blade_and_basic_color_distinction():
    cards = _inventory()
    by_code = {card.card_code: card for card in cards}
    assert "LL-bp6-001" in by_code
    card = by_code["PL!-bp6-003"]
    assert card.blade_heart_color_slot == "heart03"
    assert card.basic_hearts == {"heart01": 1, "heart03": 3, "heart06": 1}
    with_blade = [card for card in cards if card.blade_heart_color_slot]
    blade_only = [card for card in with_blade if card.blade_heart_color_slot not in card.basic_hearts]
    print("inventory", len(cards), "blade", len(with_blade), "blade_only", len(blade_only))
    assert any(card.card_code == "PL!-bp3-012" and card.blade_heart_color_slot == "heart03"
               and card.basic_hearts == {} for card in blade_only)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("code,expected", [
    ("PL!-bp6-003", {"heart01": 1, "heart03": 1, "heart06": 1}),
    ("PL!-bp3-012", {}),
])
def test_real_named_card_basic_only_probe_sql(tmp_path, owner, code, expected):
    state = _probe(owner)
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        card = _load_definition(db, code, None, {}, {})
    state.cards["audit-hand-0"].card = card
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
        selected_card_instance_ids=["audit-hand-0"]))
    colors = Counter(m.color_slot for m in result.state.players[owner].manual_modifiers
                     if m.value == {"policy": "paid_basic_color_union_v1"})
    assert colors == expected
    assert "audit-hand-0" in result.state.players[owner].waiting_room
    _replay(repo, result.state)
