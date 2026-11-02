from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tools.development import core_rule_matrix as matrix


def _row():
    return matrix.Row("bounded", ("7.4.1",), (7,), "basic", "no triggers",
                      ("tests/test_case.py::test_ok",), ())


def _evidence():
    return {"passed": True, "results": [{"node_id": "tests/test_case.py::test_ok", "reported_status": "passed"}]}


def test_catalog_has_scoped_rows_without_counting_contracts_as_rules():
    rows = matrix.catalog()
    assert len(rows) == 5
    assert len(matrix.matrix_nodes(rows)) == 162
    assert sum(len(row.behavior_nodes) for row in rows) == 62
    assert sum(len(row.contract_nodes) for row in rows) == 100
    assert all(row.exclusions and row.pages and row.rule_refs for row in rows)
    assert hashlib.sha256(Path(matrix.PDF_PATH).read_bytes()).hexdigest() == matrix.PDF_SHA256


@pytest.mark.parametrize("fault", ["source", "pdf", "failed", "skipped", "missing", "unknown", "duplicate"])
def test_matrix_never_promotes_invalid_or_changed_evidence(fault):
    evidence = _evidence()
    after, pdf_after = "same", matrix.PDF_SHA256
    if fault == "source":
        after = "different"
    elif fault == "pdf":
        pdf_after = "different"
    elif fault == "failed":
        evidence["passed"] = False
    elif fault == "skipped":
        evidence["results"][0]["reported_status"] = "skipped"
    elif fault == "missing":
        evidence["results"] = []
    elif fault == "unknown":
        evidence["results"].append({"node_id": "tests/test_case.py::test_other", "reported_status": "passed"})
    else:
        evidence["results"].append(dict(evidence["results"][0]))
    result = matrix.build_result((_row(),), evidence, "same", after, matrix.PDF_SHA256, pdf_after)
    assert result["passed"] is False and result["rows"][0]["passed"] is False
    assert result["core_scenario_count"] is None and result["goal_75_complete"] is False


@pytest.mark.parametrize("fault", ["empty", "duplicate_row", "duplicate_node", "missing_scope", "missing_behavior"])
def test_catalog_rejects_ambiguous_or_unscoped_rows(fault):
    row = _row()
    rows = {"empty": (), "duplicate_row": (row, row),
            "duplicate_node": (row, replace(row, row_id="another")),
            "missing_scope": (replace(row, exclusions=""),),
            "missing_behavior": (replace(row, behavior_nodes=()),)}[fault]
    with pytest.raises(ValueError):
        matrix.matrix_nodes(rows)


def _runtime(tmp_path, monkeypatch, fault=None):
    pdf = tmp_path / matrix.PDF_PATH
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"fixed-rules")
    monkeypatch.setattr(matrix, "PDF_SHA256", hashlib.sha256(pdf.read_bytes()).hexdigest())
    monkeypatch.setattr(matrix, "catalog", lambda: (_row(),))
    values = iter(("before", "changed" if fault == "source" else "before"))
    monkeypatch.setattr(matrix, "Workflow", lambda root: SimpleNamespace(fingerprint=lambda: next(values)))
    calls = []

    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["env"].get("PYTEST_ADDOPTS") is None
        assert kwargs["env"].get("PYTEST_PLUGINS") is None
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if fault == "spawn":
            raise OSError("simulated spawn failure")
        if fault == "pdf":
            pdf.write_bytes(b"changed-rules")
        if fault != "missing_report":
            child = '<skipped message="not executed" />' if fault == "skip" else ""
            report = Path(command[command.index("--junitxml") + 1])
            skipped = int(fault == "skip")
            report.write_text(f'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="{skipped}"><testcase classname="tests.test_case" name="test_ok">{child}</testcase></testsuite></testsuites>', encoding="utf-8")
        return SimpleNamespace(returncode=4 if fault == "exit" else 0)

    monkeypatch.setattr(matrix.subprocess, "run", invoke)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_plugin")
    return calls


def test_runner_binds_fresh_command_report_and_exact_nodes(tmp_path, monkeypatch):
    calls = _runtime(tmp_path, monkeypatch)
    output = tmp_path / "logs/new-run"
    result = matrix.run(tmp_path, output)
    assert result["passed"] is True and len(calls) == 1
    assert calls[0][0][3] == "tests/test_case.py::test_ok"
    assert result["core_scenario_count"] is None and result["goal_75_complete"] is False
    assert json.loads((output / "result.json").read_text())["passed"] is True
    invocation = json.loads((output / "invocation.json").read_text())
    assert invocation["source_fingerprint"] == "before"
    assert invocation["expected_nodes"] == ["tests/test_case.py::test_ok"]


@pytest.mark.parametrize("fault", ["timeout", "spawn", "skip", "exit", "missing_report", "source", "pdf"])
def test_runner_saves_failure_without_accepting_partial_reports(tmp_path, monkeypatch, fault):
    calls = _runtime(tmp_path, monkeypatch, fault)
    output = tmp_path / "logs/failed-run"
    result = matrix.run(tmp_path, output)
    assert len(calls) == 1 and result["passed"] is False
    assert json.loads((output / "result.json").read_text())["passed"] is False


@pytest.mark.parametrize("path", ["src/new", "logs", ".tmp", "../outside"])
def test_runner_refuses_source_or_outside_output(tmp_path, monkeypatch, path):
    calls = _runtime(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        matrix.run(tmp_path, tmp_path / path)
    assert not calls


def test_runner_refuses_existing_evidence_directory(tmp_path, monkeypatch):
    calls = _runtime(tmp_path, monkeypatch)
    output = tmp_path / "logs/existing"
    output.mkdir(parents=True)
    marker = output / "result.json"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        matrix.run(tmp_path, output)
    assert marker.read_text() == "preserve" and not calls


def test_runner_rejects_wrong_rule_pdf_before_running(tmp_path, monkeypatch):
    calls = _runtime(tmp_path, monkeypatch)
    (tmp_path / matrix.PDF_PATH).write_bytes(b"wrong")
    with pytest.raises(ValueError, match="PDF hash"):
        matrix.run(tmp_path, tmp_path / "logs/new")
    assert not calls
