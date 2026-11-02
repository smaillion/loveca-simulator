"""Fail-closed reading of pytest JUnit evidence, not rule-conformance approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


_CHILDREN = {
    "testsuites": {"testsuite"},
    "testsuite": {"testsuite", "testcase", "properties", "system-out", "system-err"},
    "testcase": {"failure", "error", "skipped", "properties", "system-out", "system-err"},
    "properties": {"property"},
    **{name: set() for name in ("property", "failure", "error", "skipped", "system-out", "system-err")},
}


def _expected_keys(nodes: list[str]) -> dict[tuple[str, str], str]:
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("expected nodes must be a nonempty list")
    keys = {}
    for node in nodes:
        if not isinstance(node, str):
            raise ValueError("expected nodes must be strings")
        prefix, bracket, parameter = node.partition("[")
        parts = prefix.replace("\\", "/").split("::")
        path = parts[0]
        if (len(parts) < 2 or not path.endswith(".py") or path.startswith("/")
                or ":" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(not part for part in parts[1:]) or (bracket and not parameter.endswith("]"))):
            raise ValueError(f"expected a relative, exact pytest node: {node}")
        key = (".".join([path[:-3].replace("/", "."), *parts[1:-1]]),
               parts[-1] + bracket + parameter)
        if key in keys:
            raise ValueError(f"duplicate or ambiguous JUnit identity: {node}")
        keys[key] = node
    return keys


def evaluate_junit(report: Path, expected_nodes: list[str], *, returncode: int) -> dict:
    """Require exact instances and a successful process; never expand test prefixes.

    The caller must bind the report and exit code to the same execution/source.
    This reader cannot establish freshness, rule semantics, or human review.
    """
    keys = _expected_keys(expected_nodes)
    if type(returncode) is not int:
        raise ValueError("a recorded integer pytest return code is required")
    issues = [] if returncode == 0 else [f"pytest_exit:{returncode}"]
    matches = {key: [] for key in keys}
    digest = None
    try:
        raw = report.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        issues.append(f"unreadable_report:{type(exc).__name__}")
    else:
        if root.tag not in {"testsuites", "testsuite"}:
            issues.append("unsupported_root")
        suites = list(root.iter("testsuite"))
        if not suites:
            issues.append("missing_test_suite")
        for parent in root.iter():
            allowed = _CHILDREN.get(parent.tag)
            if allowed is None or any(child.tag not in allowed for child in parent):
                issues.append(f"unsupported_child:{parent.tag}")
        count_elements = suites + ([root] if root.tag == "testsuites" else [])
        for suite in count_elements:
            cases = list(suite.iter("testcase"))
            observed = {"tests": len(cases), "failures": sum(c.find("failure") is not None for c in cases),
                        "errors": sum(c.find("error") is not None for c in cases),
                        "skipped": sum(c.find("skipped") is not None for c in cases)}
            for name, count in observed.items():
                if suite.tag == "testsuites" and suite.get(name) is None:
                    continue
                if suite.get(name) != str(count):
                    issues.append(f"suite_count_mismatch:{name}")
            if any(suite.find(tag) is not None for tag in ("failure", "error", "skipped")):
                issues.append("suite_level_outcome")
        for case in root.iter("testcase"):
            key = (case.get("classname", ""), case.get("name", ""))
            if key not in matches:
                issues.append(f"unexpected_case:{key[0]}::{key[1]}")
                continue
            if set(case.attrib) - {"classname", "name", "time", "file", "line", "assertions", "status"}:
                issues.append(f"unsupported_case_attributes:{keys[key]}")
            if case.get("file") and case.get("file").replace("\\", "/") != keys[key].replace("\\", "/").split("::")[0]:
                issues.append(f"conflicting_file_identity:{keys[key]}")
            status = "passed"
            if case.get("status", "run") != "run":
                status = "not_reported"
            elif case.find("error") is not None:
                status = "error"
            elif case.find("failure") is not None:
                status = "failed"
            elif case.find("skipped") is not None:
                status = "skipped"
            matches[key].append(status)
    results = []
    for key, node in keys.items():
        statuses = matches[key]
        status = "not_reported" if not statuses else "duplicate" if len(statuses) != 1 else statuses[0]
        results.append({"node_id": node, "reported_status": status, "occurrences": len(statuses)})
    passed = not issues and all(item["reported_status"] == "passed" for item in results)
    return {"passed": passed, "pytest_returncode": returncode, "report_sha256": digest,
            "issues": issues, "results": results,
            "scope": "pytest evidence only; freshness, source binding and rule acceptance are caller responsibilities"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True, help="JSON list of exact collected pytest node IDs")
    parser.add_argument("--returncode", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {args.junit.resolve(), args.expected.resolve()}:
        parser.error("output must not overwrite input evidence")
    nodes = json.loads(args.expected.read_text(encoding="utf-8"))
    if not isinstance(nodes, list):
        parser.error("expected JSON must be a list")
    try:
        result = evaluate_junit(args.junit, nodes, returncode=args.returncode)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
