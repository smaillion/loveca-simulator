from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_aidlc_vendor_manifest_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/aidlc_vendor.py", "verify"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_aidlc_project_adaptation_preserves_repository_contracts():
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    config = (PROJECT_ROOT / ".codex/config.toml").read_text(encoding="utf-8")
    org_rules = (
        PROJECT_ROOT / "aidlc/spaces/default/memory/org.md"
    ).read_text(encoding="utf-8")
    project_rules = (
        PROJECT_ROOT / "aidlc/spaces/default/memory/project.md"
    ).read_text(encoding="utf-8")

    assert "feature and hotfix branches start from `develop`" in agents
    assert "Never merge a remote pull request" in agents
    assert "model_provider" not in config
    assert "base and merge target are `develop`" in org_rules
    assert "official Japanese comprehensive rules" in project_rules
