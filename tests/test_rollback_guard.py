from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from loveca.deploy.rollback_guard import RollbackGuardError, check_deploy_rollback


def test_rollback_guard_allows_fast_forward_target(tmp_path: Path):
    repo = _git_repo(tmp_path)
    deployed_sha = _commit(repo, "deployed")
    target_sha = _commit(repo, "target")

    result = check_deploy_rollback(
        {"deployment": {"git_sha": deployed_sha}},
        target_sha=target_sha,
        repository=repo,
    )

    assert result.status == "fast-forward"
    assert result.deployed_sha == deployed_sha
    assert result.target_sha == target_sha


def test_rollback_guard_rejects_non_fast_forward_target(tmp_path: Path):
    repo = _git_repo(tmp_path)
    deployed_sha = _commit(repo, "deployed")
    _git(repo, "checkout", "--detach", "HEAD~1")
    target_sha = _commit(repo, "rollback-target")

    with pytest.raises(RollbackGuardError, match="refusing non-fast-forward deploy"):
        check_deploy_rollback(
            {"deployment": {"git_sha": deployed_sha}},
            target_sha=target_sha,
            repository=repo,
        )


def test_rollback_guard_allows_explicit_non_fast_forward_override(tmp_path: Path):
    repo = _git_repo(tmp_path)
    deployed_sha = _commit(repo, "deployed")
    _git(repo, "checkout", "--detach", "HEAD~1")
    target_sha = _commit(repo, "rollback-target")

    result = check_deploy_rollback(
        {"deployment": {"git_sha": deployed_sha}},
        target_sha=target_sha,
        repository=repo,
        allow_non_fast_forward=True,
    )

    assert result.status == "override-non-fast-forward"


def test_rollback_guard_bootstraps_when_current_health_has_no_sha(tmp_path: Path):
    repo = _git_repo(tmp_path)
    target_sha = _commit(repo, "target")

    result = check_deploy_rollback({}, target_sha=target_sha, repository=repo)

    assert result.status == "unverified-current"
    assert result.deployed_sha is None


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "base")
    return repo


def _commit(repo: Path, label: str) -> str:
    marker = repo / f"{label}.txt"
    marker.write_text(label, encoding="utf-8")
    _git(repo, "add", marker.name)
    _git(repo, "commit", "-m", label)
    return _git(repo, "rev-parse", "HEAD")


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()
