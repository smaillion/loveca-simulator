"""Run a bounded, source-bound rules matrix; never infer the 75-scenario goal."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from tools.development.loop import Workflow
from tools.development.pytest_evidence import evaluate_junit


PDF_PATH = "raw_doc/LoveLiveTCG_cr_1.06_260428.pdf"
PDF_SHA256 = "c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485"
PLAYERS = ("player_1", "player_2")
POLICIES = ("simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2")


@dataclass(frozen=True)
class Row:
    row_id: str
    rule_refs: tuple[str, ...]
    pages: tuple[int, ...]
    scope: str
    exclusions: str
    behavior_nodes: tuple[str, ...]
    contract_nodes: tuple[str, ...]


def _nodes(file: str, function: str, parameters) -> tuple[str, ...]:
    return tuple(f"tests/{file}.py::{function}[{parameter}]" for parameter in parameters)


def catalog() -> tuple[Row, ...]:
    mulligan = "test_mulligan_boundary"
    normal = "test_normal_phase_boundary"
    live = "test_match_engine"
    next_turn = "test_next_first_player_boundary"
    baton = "test_baton_payment_boundary"
    ai = [f"{policy}-{player}" for policy in POLICIES for player in PLAYERS]
    return (
        Row("opening-exchange", ("6.2.1.5", "6.2.1.6", "6.2.1.7"), (6,),
            "Both seats, 0-6 exchanges; draw before return/shuffle; Energy after both players.",
            "Not random first-selector quality, deck construction or card abilities.",
            _nodes(mulligan, "test_native_mulligan_draws_before_return_and_waits_for_both_players",
                   [f"{n}-{p}" for n in range(7) for p in PLAYERS]),
            _nodes(mulligan, "test_invalid_mulligan_preserves_sql_actions_events_and_state",
                   [f"{kind}-{p}" for kind in ("duplicate", "deck", "opponent", "wrong_player", "stale", "repeat") for p in PLAYERS])
            + _nodes(mulligan, "test_four_ai_mulligans_ignore_unseen_cards_and_execute_sql", ai)),
        Row("normal-basic", ("7.1.2", "7.3.3", "7.4.1", "7.5.2", "7.6.2", "5.6.1"), (6, 7),
            "Both normal phases: owner readiness, top Energy and one top draw; persisted reload.",
            "No abilities, attachments, depletion, prevention, phase-start triggers or full check timings.",
            _nodes(normal, "test_native_setup_reaches_both_normal_main_phases_in_order", PLAYERS)
            + _nodes(normal, "test_basic_normal_phases_ready_only_owner_then_add_top_energy_and_draw",
                     [f"{orientation}-{n}-{p}" for orientation in ("active", "wait") for n in (0, 1, 3) for p in PLAYERS]),
            _nodes(normal, "test_normal_phase_invalid_action_preserves_sql_state_and_history",
                   [f"{kind}-{step}-{p}" for kind in ("wrong_player", "stale") for step in range(3) for p in PLAYERS])
            + _nodes(normal, "test_four_ai_advance_both_normal_phases_without_hidden_card_influence", ai)),
        Row("live-set-base", ("8.2.2", "8.2.4", "5.6.1"), (6, 7),
            "Both seats set 0-3 cards, draw the same count, preserve exact zones and private projections.",
            "Not all Live-start triggers, depletion interactions or complete games.",
            _nodes(live, "test_live_set_exact_zones_draw_order_privacy_and_sql_replay",
                   [f"{n}-{p}" for n in range(4) for p in PLAYERS]),
            _nodes(live, "test_live_set_rejects_invalid_selection_without_sql_mutation",
                   [f"{kind}-{p}" for kind in ("four", "duplicate", "deck", "opponent") for p in PLAYERS])
            + _nodes(live, "test_live_set_four_ai_policies_choose_valid_private_hand_action", ai)),
        Row("next-first-placement", ("8.4.13",), (8,),
            "Six non-match-point outcomes, both seats; actual placement drives next first player; pending selection waits.",
            "Not 8.4.7.1 ambiguity, natural match-point tie reachability or the end-phase loop.",
            _nodes(next_turn, "test_next_turn_roles_follow_actual_live_placement_sql",
                   [f"{scores}-moved_roles{i}-{p}" for i, scores in enumerate(("None-None", "2-None", "None-2", "2-2", "3-2", "2-3")) for p in PLAYERS])
            + _nodes(next_turn, "test_next_turn_waits_for_success_live_selection", PLAYERS),
            _nodes(next_turn, "test_rejected_next_turn_command_preserves_sql",
                   [f"{kind}-{p}" for kind in ("stale", "repeat") for p in PLAYERS])
            + _nodes(next_turn, "test_four_ai_policies_start_new_first_players_turn", ai)),
        Row("baton-basic-payment", ("7.7.2.2", "9.6.2.1.2", "9.6.2.1.2.1", "9.6.2.3.1", "9.6.2.3.2", "9.6.2.3.2.1", "9.6.2.4.1", "5.9.1", "9.4.2"), (6, 7, 9, 10),
            "Both seats, positive/zero cost difference, Active/Wait outgoing Member; exact payment, zones and SQL Replay.",
            "Constructed no-ability cards; no attachments, cost modifiers, partial-payment ordering, departure triggers or complete games.",
            _nodes(baton, "test_baton_cost_difference_exact_zones_energy_and_sql",
                   [f"{orientation}-{cost}-{p}" for orientation in ("active", "wait") for cost in (5, 3, 2) for p in PLAYERS]),
            _nodes(baton, "test_baton_invalid_payment_is_atomic_in_sql",
                   [f"{kind}-{p}" for kind in ("short", "excess", "duplicate", "wait", "opponent_energy", "deck_energy", "zero_cost", "empty_area", "entered", "wrong_player", "stale", "repeat") for p in PLAYERS])
            + _nodes(baton, "test_four_ai_baton_payment_ignores_hidden_cards_and_replays", ai)),
    )


def matrix_nodes(rows: tuple[Row, ...]) -> list[str]:
    if not rows or len({row.row_id for row in rows}) != len(rows):
        raise ValueError("matrix requires unique rows")
    nodes = []
    for row in rows:
        if not all((row.row_id, row.rule_refs, row.pages, row.scope, row.exclusions, row.behavior_nodes)):
            raise ValueError("matrix row needs source, scope, exclusions and behavioral evidence")
        nodes.extend(row.behavior_nodes + row.contract_nodes)
    if len(set(nodes)) != len(nodes):
        raise ValueError("test instances must not be counted in multiple rows or classes")
    return nodes


def build_result(rows, evidence, before, after, pdf_before, pdf_after):
    nodes = matrix_nodes(rows)
    source_valid = bool(before) and before == after and pdf_before == pdf_after == PDF_SHA256
    outcomes = {item["node_id"]: item["reported_status"] for item in evidence["results"]}
    complete = len(outcomes) == len(evidence["results"]) and set(outcomes) == set(nodes)
    passed = source_valid and complete and evidence["passed"] and all(value == "passed" for value in outcomes.values())
    result_rows = []
    for row in rows:
        result_rows.append({"id": row.row_id, "rule_refs": row.rule_refs, "pages": row.pages,
                            "scope": row.scope, "exclusions": row.exclusions,
                            "behavior_instances": len(row.behavior_nodes), "contract_instances": len(row.contract_nodes),
                            "passed": bool(passed), "behavior_nodes": row.behavior_nodes, "contract_nodes": row.contract_nodes})
    return {"passed": bool(passed), "source_unchanged": source_valid, "source_before": before, "source_after": after,
            "rule_source": {"path": PDF_PATH, "version": "1.06 (2026-04-28)", "sha256_before": pdf_before, "sha256_after": pdf_after},
            "rows": result_rows, "pytest_evidence": evidence,
            "behavior_instances": sum(len(row.behavior_nodes) for row in rows),
            "contract_instances": sum(len(row.contract_nodes) for row in rows),
            "core_scenario_count": None, "goal_75_complete": False,
            "scope": "Bounded evidence links only; rows and parameter instances are not new official rulings or additive core-scene counts."}


def run(root: Path, output: Path, *, timeout: int = 600) -> dict:
    root, output = root.resolve(), output.resolve()
    if not any(output.is_relative_to(root / folder) and output != root / folder for folder in ("logs", ".tmp")):
        raise ValueError("output must be a fresh child directory under workspace logs or .tmp")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    rows = catalog()
    nodes = matrix_nodes(rows)
    pdf = root / PDF_PATH
    pdf_before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if pdf_before != PDF_SHA256:
        raise ValueError("fixed rule PDF hash mismatch")
    before = Workflow(root).fingerprint()
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "pytest", *nodes, "--rootdir", str(root), "-q", "-p", "no:cacheprovider",
               "--basetemp", str(output / "pytest"), "--junitxml", str(output / "junit.xml")]
    (output / "invocation.json").write_text(json.dumps({"command": command, "source_fingerprint": before, "expected_nodes": nodes}, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    failure = None
    with (output / "pytest.log").open("w", encoding="utf-8") as log:
        try:
            rc = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False).returncode
        except (subprocess.TimeoutExpired, OSError) as exc:
            failure, rc = type(exc).__name__, -1
    evidence = evaluate_junit(output / "junit.xml", nodes, returncode=rc)
    after = Workflow(root).fingerprint()
    pdf_after = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else None
    result = build_result(rows, evidence, before, after, pdf_before, pdf_after)
    result["execution_error"] = failure
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=600, type=int)
    args = parser.parse_args()
    result = run(Path.cwd(), args.output, timeout=args.timeout)
    print(json.dumps({"passed": result["passed"], "rows": len(result["rows"]), "core_scenario_count": None}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
