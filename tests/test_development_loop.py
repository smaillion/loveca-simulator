from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from tools.development.loop import (
    Workflow,
    WorkflowError,
    inventory,
    now_utc,
    remove_generated_directory,
    validate,
    write_json,
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def workflow(tmp_path: Path) -> Workflow:
    git(tmp_path, "init", "-b", "develop")
    git(tmp_path, "config", "user.email", "workflow-test@example.invalid")
    git(tmp_path, "config", "user.name", "Workflow Test")
    (tmp_path / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
    git(tmp_path, "add", ".gitignore")
    git(tmp_path, "commit", "-m", "initial")
    target = tmp_path / ".tmp/continuous-development"
    target.parent.mkdir()
    git(tmp_path, "worktree", "add", "-b", "codex/continuous-development", str(target))
    policy = {
        "schema_version": 1,
        "base_ref": "develop",
        "base_branch": "develop",
        "branch": "codex/continuous-development",
        "workspace_relative": ".tmp/continuous-development",
        "runtime_relative": ".tmp/development-loop",
        "lease_minutes": 120,
        "cycle_minutes": 45,
        "retry_limit": 3,
        "allow_merge": False,
        "allow_deploy": False,
        "allow_push": True,
        "allow_draft_pr": True,
        "protected_branches": ["develop", "main", "preview", "test"],
        "profiles": {"control": [["python", "-c", "print('gate passed')"]]},
    }
    queue = {
        "schema_version": 1,
        "tasks": [
            {
                "id": "first",
                "priority": 1,
                "status": "queued",
                "title": "First",
                "depends_on": [],
                "required_profiles": ["control"],
                "acceptance": ["pass"],
            },
            {
                "id": "second",
                "priority": 0,
                "status": "queued",
                "title": "Second",
                "depends_on": ["first"],
                "required_profiles": ["control"],
                "acceptance": ["pass"],
            },
        ],
    }
    write_json(target / "automation/policy.json", policy)
    write_json(target / "automation/queue.json", queue)
    git(target, "add", "automation")
    git(target, "commit", "-m", "workflow fixture")
    return Workflow(target)


def test_queue_rejects_cycles_and_automatic_merge(workflow):
    workflow.queue["tasks"][0]["depends_on"] = ["second"]
    with pytest.raises(WorkflowError, match="cycle"):
        validate(workflow.policy, workflow.queue)
    workflow.queue["tasks"][0]["depends_on"] = []
    workflow.policy["allow_merge"] = True
    with pytest.raises(WorkflowError, match="separate user approval"):
        validate(workflow.policy, workflow.queue)


def test_runtime_cannot_escape_repository(workflow):
    workflow.policy["runtime_relative"] = ".tmp/../../escape"
    with pytest.raises(WorkflowError, match="below"):
        validate(workflow.policy, workflow.queue)


def test_single_writer_persists_across_instances(workflow):
    claimed = workflow.claim("worker-one")
    assert claimed["task"]["id"] == "first"
    reloaded = Workflow(workflow.root)
    with pytest.raises(WorkflowError, match="already active"):
        reloaded.claim("worker-two")
    with pytest.raises(WorkflowError, match="does not belong"):
        reloaded.renew("incorrect-token")
    assert reloaded.load()["lease"]["token"] == claimed["lease"]["token"]


def test_expired_worker_can_resume_same_task(workflow):
    old = workflow.claim("old-worker")["lease"]["token"]
    with workflow.transaction() as state:
        state["lease"]["expires_at"] = (now_utc() - timedelta(seconds=1)).isoformat()
    resumed = workflow.claim("new-worker")
    assert resumed["recovered_expired_lease"]
    assert resumed["lease"]["token"] != old
    with pytest.raises(WorkflowError):
        workflow.complete(old, "blocked", "old worker must not modify progress")


def test_paused_loop_refuses_claim(workflow):
    with workflow.transaction() as state:
        state["paused"] = True
    assert workflow.next_task(workflow.load()) is None
    with pytest.raises(WorkflowError, match="paused"):
        workflow.claim("worker")


def test_gate_evidence_is_bound_to_source_and_required_profiles(workflow):
    token = workflow.claim("worker")["lease"]["token"]
    report = workflow.check(token, ["control"])
    assert report["passed"]
    assert Path(workflow.load()["last_check"]["report"]).is_file()
    (workflow.root / "new_source.py").write_text("changed = True\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="current source"):
        workflow.complete(token, "done", "should fail")
    assert workflow.load()["tasks"]["first"]["status"] == "in_progress"
    assert workflow.check(token, ["control"])["passed"]
    workflow.complete(token, "done", "verified after code change")
    reloaded = Workflow(workflow.root)
    assert reloaded.load()["lease"] is None
    assert reloaded.next_task(reloaded.load())["id"] == "second"


def test_failed_gate_cannot_complete_or_publish(workflow):
    workflow.policy["profiles"]["control"] = [["python", "-c", "raise SystemExit(3)"]]
    token = workflow.claim("worker")["lease"]["token"]
    result = workflow.check(token, ["control"])
    assert not result["passed"]
    assert result["checks"][0]["exit_code"] == 3
    assert workflow.load()["tasks"]["first"]["consecutive_gate_failures"] == 1
    with pytest.raises(WorkflowError, match="passing gates"):
        workflow.complete(token, "done", "bad checkpoint")
    with pytest.raises(WorkflowError, match="release"):
        workflow.publish()


def test_publish_requires_a_clean_validated_checkpoint(workflow):
    token = workflow.claim("worker")["lease"]["token"]
    (workflow.root / "new.py").write_text("value = 1\n", encoding="utf-8")
    workflow.check(token, ["control"])
    workflow.complete(token, "done", "validated")
    with pytest.raises(WorkflowError, match="commit the validated checkpoint"):
        workflow.publish()


def test_state_lock_never_silently_breaks_another_writer(workflow):
    with workflow.transaction():
        with pytest.raises(WorkflowError, match="state is locked"):
            workflow.claim("second-worker")


def test_wrong_branch_refuses_editing(workflow):
    git(workflow.root, "checkout", "-b", "codex/unrelated")
    with pytest.raises(WorkflowError, match="wrong branch"):
        workflow.claim("worker")


def test_upstream_advance_can_be_synchronized_under_a_lease(workflow):
    (workflow.main / "upstream.txt").write_text("new develop work\n", encoding="utf-8")
    git(workflow.main, "add", "upstream.txt")
    git(workflow.main, "commit", "-m", "advance develop")
    with pytest.raises(WorkflowError, match="merge-base"):
        workflow.assert_workspace()
    token = workflow.claim("sync-worker")["lease"]["token"]
    with pytest.raises(WorkflowError, match="merge-base"):
        workflow.check(token, ["control"])
    git(workflow.root, "merge", "--no-edit", "develop")
    workflow.assert_workspace()
    assert workflow.check(token, ["control"])["passed"]


def test_inventory_preserves_dirty_and_unique_work(workflow):
    (workflow.root / "user-work.txt").write_text("keep me", encoding="utf-8")
    result = inventory(workflow.root, "develop", "codex/other-active")
    current = next(
        item for item in result["worktrees"] if item["branch"] == "codex/continuous-development"
    )
    assert current["disposition"] == "preserve_dirty"
    assert current["ahead"] == 1
    assert "?? user-work.txt" in current["changes"]
    assert (workflow.root / "user-work.txt").read_text(encoding="utf-8") == "keep me"


def test_publish_reuses_existing_pr_and_never_merges(workflow, monkeypatch):
    token = workflow.claim("worker")["lease"]["token"]
    workflow.check(token, ["control"])
    workflow.complete(token, "done", "tested")
    from tools.development import loop

    real_command = loop.command
    calls = []

    def fake_command(cwd, *args, **kwargs):
        calls.append(args)
        if args[:2] == ("git", "push"):
            return ""
        if args[:3] == ("gh", "pr", "list"):
            return json.dumps(
                [{"number": 54, "url": "https://example.invalid/pull/54", "isDraft": True}]
            )
        if args[:3] == ("gh", "pr", "edit"):
            return ""
        return real_command(cwd, *args, **kwargs)

    monkeypatch.setattr(loop, "command", fake_command)
    assert workflow.publish()["url"].endswith("/54")
    assert any(call[:3] == ("gh", "pr", "edit") for call in calls)
    assert not any("merge" in call or "--force" in call or "create" in call for call in calls)


def test_gate_timeout_records_failure(workflow):
    workflow.policy["profiles"]["control"] = [["python", "-c", "import time; time.sleep(30)"]]
    token = workflow.claim("worker")["lease"]["token"]
    assert not workflow.check(token, ["control"], timeout=1)["passed"]


def test_killed_coordinator_releases_operating_system_lock(workflow):
    from tools.development import loop

    environment = dict(os.environ, PYTHONPATH=str(Path(loop.__file__).parents[2]))
    worker_code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from tools.development.loop import Workflow\n"
        "with Workflow(Path(sys.argv[1])).transaction():\n"
        " print('locked', flush=True)\n"
        " time.sleep(60)\n"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(workflow.root)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert worker.stdout.readline().strip() == "locked"
        with pytest.raises(WorkflowError, match="locked"):
            with workflow.transaction():
                pass
    finally:
        worker.terminate()
        worker.communicate(timeout=10)
    assert workflow.claim("recovered")["task"]["id"] == "first"


def test_incomplete_gate_profiles_do_not_satisfy_task(workflow):
    workflow.policy["profiles"]["other"] = [["python", "-c", "print('pass')"]]
    workflow.queue["tasks"][0]["required_profiles"].append("other")
    token = workflow.claim("worker")["lease"]["token"]
    assert workflow.check(token, ["control"])["passed"]
    with pytest.raises(WorkflowError, match="required profiles"):
        workflow.complete(token, "done", "missing a required gate")


def test_interrupted_gate_invalidates_older_success(workflow, monkeypatch):
    from tools.development import loop

    token = workflow.claim("worker")["lease"]["token"]
    assert workflow.check(token, ["control"])["passed"]

    def interrupted(*args):
        raise WorkflowError("runtime unavailable")

    monkeypatch.setattr(loop, "resolve_command", interrupted)
    with pytest.raises(WorkflowError, match="runtime unavailable"):
        workflow.check(token, ["control"])
    assert workflow.load()["last_check"]["status"] == "running"
    with pytest.raises(WorkflowError, match="passing gates"):
        workflow.complete(token, "done", "old success must not mask an interrupted check")


def test_cleanup_handles_readonly_git_objects_and_refuses_escape(tmp_path):
    run_dir = tmp_path / "run"
    generated = run_dir / "pytest"
    objects = generated / ".git/objects/00"
    objects.mkdir(parents=True)
    git_object = objects / "test-object"
    git_object.write_text("temporary test fixture", encoding="utf-8")
    git_object.chmod(stat.S_IREAD)
    remove_generated_directory(generated, run_dir)
    assert not generated.exists()
    outside = tmp_path / "user-data"
    outside.mkdir()
    with pytest.raises(WorkflowError, match="escaped"):
        remove_generated_directory(outside, run_dir)
    assert outside.exists()
