import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.development.pytest_evidence import evaluate_junit


NODE = "tests/test_rule.py::test_rule"


def _report(tmp_path, outcomes=(None,), *, name="test_rule", classname="tests.test_rule"):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests=str(len(outcomes)),
                          failures=str(outcomes.count("failure")), errors=str(outcomes.count("error")),
                          skipped=str(outcomes.count("skipped")))
    for outcome in outcomes:
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if outcome:
            ET.SubElement(case, outcome)
    path = tmp_path / "report.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


@pytest.mark.parametrize("outcome,status", [(None, "passed"), ("failure", "failed"),
                                           ("error", "error"), ("skipped", "skipped")])
def test_each_outcome_is_distinct(tmp_path, outcome, status):
    report = _report(tmp_path, (outcome,))
    result = evaluate_junit(report, [NODE], returncode=0)
    assert result["passed"] is (outcome is None)
    assert result["results"] == [{"node_id": NODE, "reported_status": status, "occurrences": 1}]
    assert result["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5, -1])
def test_process_failure_cannot_pass_even_with_green_report(tmp_path, code):
    result = evaluate_junit(_report(tmp_path), [NODE], returncode=code)
    assert not result["passed"] and f"pytest_exit:{code}" in result["issues"]


@pytest.mark.parametrize("outcomes", [(None, None), ("failure", None), (None, "skipped")])
def test_duplicates_never_overwrite_previous_evidence(tmp_path, outcomes):
    result = evaluate_junit(_report(tmp_path, outcomes), [NODE], returncode=0)
    assert not result["passed"]
    assert result["results"][0]["reported_status"] == "duplicate"


@pytest.mark.parametrize("name", ["test_rule[one]", "test_rule_extra", "other"])
def test_missing_exact_node_does_not_match_prefix(tmp_path, name):
    result = evaluate_junit(_report(tmp_path, name=name), [NODE], returncode=0)
    assert not result["passed"] and result["results"][0]["reported_status"] == "not_reported"
    assert result["issues"][0].startswith("unexpected_case:")


@pytest.mark.parametrize("node,classname,name", [
    ("tests/test_rule.py::TestRule::test_rule", "tests.test_rule.TestRule", "test_rule"),
    ("tests/test_rule.py::test_rule[a.b::c]", "tests.test_rule", "test_rule[a.b::c]"),
    ("tests\\test_rule.py::test_rule", "tests.test_rule", "test_rule"),
])
def test_exact_class_parameter_and_windows_path_identity(tmp_path, node, classname, name):
    assert evaluate_junit(_report(tmp_path, classname=classname, name=name), [node], returncode=0)["passed"]


@pytest.mark.parametrize("nodes", [[], [NODE, NODE], [NODE, NODE.replace("/", "\\")],
                                   ["tests/a.b.py::test_x", "tests/a/b.py::test_x"],
                                   ["tests/test_rule.py"], ["../test_rule.py::test_rule"], [None]])
def test_invalid_or_ambiguous_selection_is_rejected(tmp_path, nodes):
    with pytest.raises(ValueError):
        evaluate_junit(_report(tmp_path), nodes, returncode=0)


@pytest.mark.parametrize("content", [None, "", "<broken", "<testsuites/>", "<unrelated/>"])
def test_absent_malformed_or_empty_report_cannot_pass(tmp_path, content):
    path = tmp_path / "report.xml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    result = evaluate_junit(path, [NODE], returncode=0)
    assert not result["passed"] and result["issues"]
    assert result["results"][0]["reported_status"] == "not_reported"


@pytest.mark.parametrize("mutation", ["count", "missing_count", "status", "collection", "suite_error", "duplicate_suite"])
def test_incomplete_or_inconsistent_suite_fails_closed(tmp_path, mutation):
    report = _report(tmp_path)
    tree = ET.parse(report)
    root = tree.getroot()
    suite, case = root.find("testsuite"), root.find("testsuite/testcase")
    if mutation == "count":
        suite.set("skipped", "1")
    elif mutation == "missing_count":
        del suite.attrib["tests"]
    elif mutation == "status":
        case.set("status", "notrun")
    elif mutation == "collection":
        ET.SubElement(suite, "testcase", classname="", name="tests/test_broken.py")
        suite.set("tests", "2")
    elif mutation == "suite_error":
        ET.SubElement(suite, "error")
    else:
        root.append(ET.fromstring(ET.tostring(suite)))
    tree.write(report, encoding="utf-8")
    assert not evaluate_junit(report, [NODE], returncode=0)["passed"]


@pytest.mark.parametrize("marker,status,code", [("", "passed", 0), ("@pytest.mark.skip", "skipped", 0),
                                               ("@pytest.mark.xfail", "skipped", 0)])
def test_real_pytest_reports_are_read_without_promoting_skips(tmp_path, marker, status, code):
    fixture = tmp_path / "test_sample.py"
    fixture.write_text("import pytest\n" + marker + "\ndef test_sample():\n    "
                       + ("assert False" if "xfail" in marker else "assert True") + "\n", encoding="utf-8")
    report = tmp_path / "real.xml"
    run = subprocess.run([sys.executable, "-m", "pytest", "test_sample.py", "-q", "--rootdir", str(tmp_path), "-p", "no:cacheprovider",
                          "-o", "junit_family=xunit2", f"--junitxml={report}"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == code, run.stdout + run.stderr
    result = evaluate_junit(report, ["test_sample.py::test_sample"], returncode=run.returncode)
    assert result["results"][0]["reported_status"] == status
    assert result["passed"] is (status == "passed")


def test_cli_preserves_source_report_and_returns_failure_for_skip(tmp_path):
    report = _report(tmp_path, ("skipped",))
    before = report.read_bytes()
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps([NODE]), encoding="utf-8")
    output = tmp_path / "result.json"
    run = subprocess.run([sys.executable, "-m", "tools.development.pytest_evidence", "--junit", str(report),
                          "--expected", str(expected), "--returncode", "0", "--output", str(output)],
                         cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False
    assert report.read_bytes() == before


@pytest.mark.parametrize("mutation", ["orphan", "rerun", "root_error", "hidden_case", "result_attribute", "wrong_file", "root_count"])
def test_unsupported_report_shapes_do_not_certify_success(tmp_path, mutation):
    report = _report(tmp_path)
    tree = ET.parse(report)
    root = tree.getroot()
    if mutation == "orphan":
        suite = root.find("testsuite")
        case = suite.find("testcase")
        suite.remove(case)
        suite.set("tests", "0")
        root.append(case)
    elif mutation == "rerun":
        ET.SubElement(root.find("testsuite/testcase"), "rerunFailure")
    elif mutation == "root_error":
        ET.SubElement(root, "error")
    elif mutation == "hidden_case":
        suite = root.find("testsuite")
        case = suite.find("testcase")
        suite.remove(case)
        ET.SubElement(suite, "properties").append(case)
    elif mutation == "result_attribute":
        root.find("testsuite/testcase").set("result", "skipped")
    elif mutation == "root_count":
        root.set("errors", "1")
    else:
        root.find("testsuite/testcase").set("file", "tests/different.py")
    tree.write(report, encoding="utf-8")
    assert not evaluate_junit(report, [NODE], returncode=0)["passed"]


@pytest.mark.parametrize("code", [None, True, "0"])
def test_exit_code_is_required_and_not_coerced(tmp_path, code):
    with pytest.raises(ValueError):
        evaluate_junit(_report(tmp_path), [NODE], returncode=code)


def test_cli_refuses_to_overwrite_original_evidence(tmp_path):
    report = _report(tmp_path)
    before = report.read_bytes()
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps([NODE]), encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "tools.development.pytest_evidence", "--junit", str(report),
                          "--expected", str(expected), "--returncode", "0", "--output", str(report)],
                         cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=30)
    assert run.returncode == 2 and report.read_bytes() == before


def test_real_class_and_parameter_instances_match_exact_nodes(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\nclass TestRule:\n    @pytest.mark.parametrize('x', ['a.b::c', 'd'])\n"
        "    def test_rule(self, x):\n        assert x\n", encoding="utf-8")
    report = tmp_path / "real.xml"
    run = subprocess.run([sys.executable, "-m", "pytest", "test_sample.py", "-q", "--rootdir", str(tmp_path),
                          "-p", "no:cacheprovider", f"--junitxml={report}"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    nodes = [f"test_sample.py::TestRule::test_rule[{value}]" for value in ("a.b::c", "d")]
    assert evaluate_junit(report, nodes, returncode=run.returncode)["passed"]


def test_standard_properties_and_output_are_not_outcomes(tmp_path):
    report = _report(tmp_path)
    tree = ET.parse(report)
    case = tree.getroot().find("testsuite/testcase")
    case.set("file", "tests/test_rule.py")
    ET.SubElement(ET.SubElement(case, "properties"), "property", name="example", value="value")
    ET.SubElement(case, "system-out").text = "<skipped/> is output text, not a test outcome"
    tree.write(report, encoding="utf-8")
    assert evaluate_junit(report, [NODE], returncode=0)["passed"]


@pytest.mark.parametrize("single_root", [False, True])
def test_standard_suite_roots_and_distinct_suites(tmp_path, single_root):
    report = _report(tmp_path)
    tree = ET.parse(report)
    root = tree.getroot()
    nodes = [NODE]
    if single_root:
        tree._setroot(root.find("testsuite"))
    else:
        suite = ET.SubElement(root, "testsuite", tests="1", errors="0", failures="0", skipped="0")
        ET.SubElement(suite, "testcase", classname="tests.test_other", name="test_other")
        nodes.append("tests/test_other.py::test_other")
    tree.write(report, encoding="utf-8")
    assert evaluate_junit(report, nodes, returncode=0)["passed"]
