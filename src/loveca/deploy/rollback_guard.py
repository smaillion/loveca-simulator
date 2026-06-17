"""Deployment rollback guard utilities."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RollbackGuardError(RuntimeError):
    """Raised when a deployment should not proceed."""


@dataclass(frozen=True)
class RollbackGuardResult:
    status: str
    deployed_sha: str | None
    target_sha: str
    message: str


def deployed_git_sha(health_payload: dict[str, Any]) -> str | None:
    deployment = health_payload.get("deployment")
    if not isinstance(deployment, dict):
        return None
    value = deployment.get("git_sha")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value == "unknown":
        return None
    return value


def check_deploy_rollback(
    health_payload: dict[str, Any],
    *,
    target_sha: str,
    repository: Path = Path("."),
    allow_non_fast_forward: bool = False,
) -> RollbackGuardResult:
    deployed_sha = deployed_git_sha(health_payload)
    target_sha = target_sha.strip()
    if not target_sha:
        raise RollbackGuardError("target sha is required")
    if deployed_sha is None:
        return RollbackGuardResult(
            status="unverified-current",
            deployed_sha=None,
            target_sha=target_sha,
            message=(
                "current deployment does not expose deployment.git_sha; "
                "allowing this deploy as rollback-guard bootstrap"
            ),
        )
    if deployed_sha == target_sha:
        return RollbackGuardResult(
            status="same-sha",
            deployed_sha=deployed_sha,
            target_sha=target_sha,
            message="target sha is already deployed",
        )
    if _is_ancestor(deployed_sha, target_sha, repository=repository):
        return RollbackGuardResult(
            status="fast-forward",
            deployed_sha=deployed_sha,
            target_sha=target_sha,
            message="target sha is a descendant of the current deployed sha",
        )
    message = (
        "refusing non-fast-forward deploy: current deployed sha "
        f"{deployed_sha} is not an ancestor of target sha {target_sha}"
    )
    if allow_non_fast_forward:
        return RollbackGuardResult(
            status="override-non-fast-forward",
            deployed_sha=deployed_sha,
            target_sha=target_sha,
            message=message + "; manual override accepted",
        )
    raise RollbackGuardError(message)


def fetch_health(origin_base_url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    base_url = origin_base_url.rstrip("/")
    if not base_url:
        raise RollbackGuardError("origin base URL is required")
    request = urllib.request.Request(
        f"{base_url}/api/health",
        headers={"Accept": "application/json", "User-Agent": "loveca-rollback-guard"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RollbackGuardError(f"failed to fetch current deployment health: {exc}") from exc
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RollbackGuardError("current deployment health is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RollbackGuardError("current deployment health must be a JSON object")
    return decoded


def _is_ancestor(deployed_sha: str, target_sha: str, *, repository: Path) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", deployed_sha, target_sha],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    details = completed.stderr.strip() or completed.stdout.strip()
    raise RollbackGuardError(f"failed to compare git ancestry: {details}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block accidental non-fast-forward API deploys.")
    parser.add_argument("--origin-base-url", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--allow-non-fast-forward", action="store_true")
    args = parser.parse_args(argv)

    try:
        health = fetch_health(args.origin_base_url)
        result = check_deploy_rollback(
            health,
            target_sha=args.target_sha,
            repository=args.repository,
            allow_non_fast_forward=args.allow_non_fast_forward,
        )
    except RollbackGuardError as exc:
        print(f"rollback guard failed: {exc}", file=sys.stderr)
        return 1
    print(f"rollback guard: {result.status}: {result.message}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
