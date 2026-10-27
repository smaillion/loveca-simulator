import copy
import json
from pathlib import Path

import pytest
from test_multi_keep_inspection_audit import CODE, _state
from test_nijigasaki_inspection import _play, _resolve

from loveca.simulation.effects import load_effect_registry
from loveca.simulation.engine import apply_action
from tools.ai_sandbox.blackbox_playtest import build_decks, summarize_deck
from tools.ai_sandbox.effect_gap_report import (
    build_effect_gap_report,
    load_actual_trigger_counts,
    write_gap_outputs,
)
from tools.ai_sandbox.effect_observations import (
    diagnostic_source_fingerprint,
    load_observations,
    merge_observations,
    observe_effects,
)


def _event(kind, invocation="i1", effect="A:1", **private):
    return {
        "event_type": kind,
        "data": {"invocation_id": invocation, "effect_id": effect, **private},
    }


def test_actual_triggers_are_not_decisions_declines_skips_or_deck_frequency():
    events = [
        _event("effect_triggered"),
        _event("effect_triggered"),
        _event("ai_action_selected"),
        _event("effect_declined"),
        _event("effect_skipped_due_to_error", "i2"),
        _event("effect_triggered", "i3"),
    ]
    assert observe_effects(events, [{"effect_id": "A:1", "invocation_id": "i3"}]) == {
        "A:1": {"triggered": 2, "optional_declined": 1, "error_skipped": 1, "manual_blocked": 1}
    }


def test_observation_does_not_mutate_or_export_hidden_information():
    events = [_event("effect_triggered", private_hand=["SECRET-A"], token="SECRET-TOKEN")]
    before = copy.deepcopy(events)
    first = observe_effects(events)
    changed = copy.deepcopy(events)
    changed[0]["data"]["private_hand"] = ["DIFFERENT-HIDDEN-CARD"]
    assert observe_effects(changed) == first and events == before
    assert "SECRET" not in json.dumps(first)


def test_current_native_optional_manual_decline_is_observed_not_lost():
    state = _state()
    played = apply_action(state, _play(state))
    declined = apply_action(played.state, _resolve(played.state, accepted=False))
    observed = observe_effects(
        [event.model_dump(mode="json") for event in [*played.events, *declined.events]]
    )
    assert observed[CODE + ":1"] == {
        "triggered": 1,
        "optional_declined": 1,
        "error_skipped": 0,
        "manual_blocked": 0,
    }


def test_event_trace_and_summary_loading_preserve_separate_metrics(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {"actions": [{"events": [_event("effect_triggered"), _event("effect_declined")]}]}
        )
        + "\n",
        encoding="utf-8",
    )
    counts = load_observations([trace])
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps({"match_summaries": [{"effect_observations": counts}]}), encoding="utf-8"
    )
    assert load_observations([summary]) == counts
    assert merge_observations([counts, counts])["A:1"]["triggered"] == 2
    with pytest.raises(ValueError, match="duplicate"):
        load_observations([trace, trace])


def test_legacy_skip_input_remains_compatible_but_is_not_trigger_evidence(tmp_path):
    legacy = tmp_path / "old.json"
    legacy.write_text(json.dumps({"skipped_effects": {CODE + ":1": 7}}), encoding="utf-8")
    assert load_actual_trigger_counts([legacy]) == {CODE + ":1": 7}
    with pytest.raises(ValueError, match="legacy"):
        load_observations([legacy])
    report = build_effect_gap_report(
        effect_observations={}, legacy_skip_counts=load_actual_trigger_counts([legacy]), top=500
    )
    group = next(g for g in report["top_manual_patterns"] if CODE + ":1" in g["sample_effect_ids"])
    assert group["actual_trigger_count"] == 0 and group["legacy_skip_count"] == 7


def test_gap_filters_current_manual_and_sorts_by_real_trigger_counts(tmp_path):
    report = build_effect_gap_report(
        effect_observations={
            CODE + ":1": {
                "triggered": 2,
                "optional_declined": 1,
                "error_skipped": 0,
                "manual_blocked": 1,
            },
            "PL!HS-bp6-014:1": {"triggered": 999},
        },
        top=40,
    )
    registry = load_effect_registry()
    assert report["manual_resolution"] == sum(
        e.simulation_support == "manual_resolution" for e in registry.effects
    )
    assert report["test_validated_executable"] == sum(
        e.simulation_support == "test_validated_executable" for e in registry.effects
    )
    assert report["actual_trigger_samples"] == 2
    assert report["top_manual_patterns"][0]["sample_effect_ids"] == [CODE + ":1"]
    assert report["top_manual_patterns"][0]["optional_decline_count"] == 1
    write_gap_outputs(tmp_path, report)
    text = (tmp_path / "effect-gap-report.zh-CN.md").read_text(encoding="utf-8")
    assert "可选辞退" in text and "printed_heart_icon_scope" in text


@pytest.mark.parametrize("value", (-1, True, "1"))
def test_malformed_metrics_are_rejected(value):
    with pytest.raises(ValueError):
        merge_observations([{"A:1": {"triggered": value}}])


def test_manual_focused_decks_are_deterministic_legal_and_enriched():
    database = Path("data/loveca.sqlite3")
    normal = build_decks(database, 30)
    focused = build_decks(database, 30, manual_focus=True)
    assert normal == build_decks(database, 30)
    assert focused == build_decks(database, 30, manual_focus=True)
    manual_codes = {
        e.card_code
        for e in load_effect_registry().effects
        if e.simulation_support == "manual_resolution"
    }

    def count(decks):
        return sum(
            entry.quantity
            for deck in decks
            for entry in deck.main_deck
            if entry.card_code in manual_codes
        )

    assert count(focused) > count(normal)
    assert len(focused) == 30
    for deck in focused:
        assert summarize_deck(database, deck).members == 48


def test_diagnostic_fingerprint_excludes_private_files_and_docs_but_binds_code(tmp_path):
    (tmp_path / "src").mkdir()
    code = tmp_path / "src" / "engine.py"
    code.write_text("version = 1\n", encoding="utf-8")
    for relative in (
        "data/loveca.sqlite3",
        "data/loveca-db-manifest.json",
        "data_sources/effect-registry.v0.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    before = diagnostic_source_fingerprint(tmp_path)
    (tmp_path / "private.txt").write_text("DO-NOT-EXPORT", encoding="utf-8")
    assert diagnostic_source_fingerprint(tmp_path) == before
    code.write_text("version = 2\n", encoding="utf-8")
    assert diagnostic_source_fingerprint(tmp_path) != before


def test_incomplete_events_and_unknown_metrics_fail_closed():
    with pytest.raises(ValueError):
        observe_effects([{"event_type": "effect_declined", "data": {"invocation_id": "unknown"}}])
    with pytest.raises(ValueError):
        observe_effects([_event("effect_triggered", invocation={"not": "an-id"})])
    with pytest.raises(ValueError):
        build_effect_gap_report(effect_observations={"A:1": {"decision_count": 9}})
