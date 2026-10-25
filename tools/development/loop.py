"""Coordinate a recurring Codex worker without spawning branches or model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class WorkflowError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def command(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=90,
    )
    if check and result.returncode:
        raise WorkflowError(f"{' '.join(args[:3])}: {result.stderr.strip()}")
    return result.stdout.strip()


def validate(policy: dict[str, Any], queue: dict[str, Any]) -> None:
    if policy.get("schema_version") != 1 or queue.get("schema_version") != 1:
        raise WorkflowError("unknown development workflow schema")
    branch = policy.get("branch", "")
    if not branch.startswith("codex/") or branch in policy["protected_branches"]:
        raise WorkflowError("development branch must be an unprotected codex branch")
    if policy.get("allow_merge") or policy.get("allow_deploy"):
        raise WorkflowError("remote merge and deployment require separate user approval")
    if policy.get("active_environment", "local") not in {"local", "cloud"}:
        raise WorkflowError("unknown active development environment")
    if "pull_request" in policy and (
        type(policy["pull_request"]) is not int or policy["pull_request"] < 1
    ):
        raise WorkflowError("pull_request must identify the existing review PR")
    if "checkpoint" in policy and policy["checkpoint"] != "automation/cloud-checkpoint.json":
        raise WorkflowError("checkpoint must use the fixed version-controlled path")
    for key in ("runtime_relative", "workspace_relative"):
        path = Path(policy[key])
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != ".tmp":
            raise WorkflowError(f"{key} must stay below the repository .tmp directory")
    if not 1 <= policy["cycle_minutes"] < policy["lease_minutes"] <= 240:
        raise WorkflowError("cycle must be shorter than the bounded lease")
    tasks = queue.get("tasks", [])
    by_id = {task["id"]: task for task in tasks}
    if len(tasks) != len(by_id):
        raise WorkflowError("duplicate task id")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id not in by_id or task_id in visiting:
            raise WorkflowError("missing dependency or dependency cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        task = by_id[task_id]
        if task.get("status") not in {"queued", "done", "blocked"}:
            raise WorkflowError(f"invalid initial task status: {task_id}")
        if not task.get("acceptance") or not task.get("required_profiles"):
            raise WorkflowError(f"task needs acceptance criteria and gates: {task_id}")
        if set(task["required_profiles"]) - set(policy["profiles"]):
            raise WorkflowError(f"unknown gate profile: {task_id}")
        for dependency in task.get("depends_on", []):
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)


class Workflow:
    def __init__(self, root: Path, *, environment: str = "local"):
        self.root = root.resolve()
        if environment not in {"local", "cloud"}:
            raise WorkflowError("unknown development environment")
        self.environment = environment
        self.policy = read_json(self.root / "automation/policy.json")
        self.queue = read_json(self.root / "automation/queue.json")
        validate(self.policy, self.queue)
        common = Path(command(self.root, "git", "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = self.root / common
        self.main = common.resolve().parent
        self.runtime = self.main / self.policy["runtime_relative"]
        self.state_path = self.runtime / "state.json"

    def load(self) -> dict[str, Any]:
        if self.state_path.exists():
            return read_json(self.state_path)
        state = {"schema_version": 1, "paused": False, "lease": None, "tasks": {}}
        if self.environment == "cloud" and self.policy.get("checkpoint"):
            checkpoint = read_json(self.root / self.policy["checkpoint"])
            expected_keys = {
                "schema_version", "branch", "base_ref", "pull_request", "source_head",
                "generated_at", "task_states",
            }
            if (
                not isinstance(checkpoint, dict) or set(checkpoint) != expected_keys
                or checkpoint["schema_version"] != 1
            ):
                raise WorkflowError("invalid portable checkpoint schema")
            if any(checkpoint[key] != self.policy.get(key) for key in (
                "branch", "base_ref", "pull_request"
            )):
                raise WorkflowError("checkpoint belongs to another branch or PR")
            head = checkpoint["source_head"]
            if not isinstance(head, str) or len(head) != 40 or any(
                char not in "0123456789abcdef" for char in head
            ):
                raise WorkflowError("invalid checkpoint source commit")
            command(self.root, "git", "merge-base", "--is-ancestor", head, "HEAD")
            statuses = checkpoint["task_states"]
            if not isinstance(statuses, dict):
                raise WorkflowError("invalid checkpoint task states")
            for task_id, status in statuses.items():
                self.task(task_id)
                if not isinstance(status, str) or status not in {
                    "queued", "in_progress", "done", "blocked"
                }:
                    raise WorkflowError("invalid checkpoint task status")
                state["tasks"][task_id] = {"status": status, "restored_from_checkpoint": True}
            # Progress is portable; leases and publishing evidence deliberately are not.
            state["restored_from"] = head
        return state

    def assert_writer(self) -> None:
        active = self.policy.get("active_environment", "local")
        if active != self.environment:
            raise WorkflowError(f"writer is {active}; {self.environment} is preflight-only")

    def checkpoint(self, token: str) -> dict[str, Any]:
        self.assert_writer()
        self.assert_workspace()
        state = self.load()
        self.lease(state, token)
        if not self.policy.get("checkpoint"):
            raise WorkflowError("portable checkpoint is not configured")
        statuses = {}
        for task in self.queue["tasks"]:
            status = state["tasks"].get(task["id"], {}).get("status", task["status"])
            if not isinstance(status, str) or status not in {
                "queued", "in_progress", "done", "blocked"
            }:
                raise WorkflowError("invalid task status; checkpoint not exported")
            statuses[task["id"]] = status
        result = {
            "schema_version": 1,
            "branch": self.policy["branch"],
            "base_ref": self.policy["base_ref"],
            "pull_request": self.policy.get("pull_request"),
            "source_head": command(self.root, "git", "rev-parse", "HEAD"),
            "generated_at": now_utc().isoformat(),
            "task_states": statuses,
        }
        write_json(self.root / self.policy["checkpoint"], result)
        return result

    @contextmanager
    def transaction(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        # SQLite releases this OS-backed lock even if a worker is terminated.
        with closing(
            sqlite3.connect(self.runtime / "coordination.sqlite3", timeout=0.5)
        ) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise WorkflowError("state is locked by another writer") from exc
            try:
                state = self.load()
                yield state
                write_json(self.state_path, state)
                connection.commit()
            finally:
                connection.rollback()

    def assert_workspace(self, *, require_base: bool = True) -> None:
        actual = command(self.root, "git", "symbolic-ref", "--short", "HEAD")
        if actual != self.policy["branch"]:
            raise WorkflowError(f"wrong branch: {actual}; reuse {self.policy['branch']}")
        expected = self.main if self.environment == "cloud" else (
            self.main / self.policy["workspace_relative"]
        ).resolve()
        if self.root != expected:
            raise WorkflowError(f"wrong worktree: use {expected}")
        if require_base:
            command(
                self.root, "git", "merge-base", "--is-ancestor", self.policy["base_ref"], "HEAD"
            )

    def task(self, task_id: str) -> dict[str, Any]:
        for task in self.queue["tasks"]:
            if task["id"] == task_id:
                return task
        raise WorkflowError(f"unknown task: {task_id}")

    def next_task(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("paused"):
            return None
        statuses = {
            task["id"]: state["tasks"].get(task["id"], {}).get("status", task["status"])
            for task in self.queue["tasks"]
        }
        eligible = [
            task
            for task in self.queue["tasks"]
            if statuses[task["id"]] in {"queued", "in_progress"}
            and all(statuses.get(dep) == "done" for dep in task.get("depends_on", []))
        ]
        return min(eligible, key=lambda task: (task["priority"], task["id"]), default=None)

    def lease(self, state: dict[str, Any], token: str) -> dict[str, Any]:
        lease = state.get("lease")
        if not lease or lease["token"] != token:
            raise WorkflowError("lease does not belong to this worker")
        if datetime.fromisoformat(lease["expires_at"]) <= now_utc():
            raise WorkflowError("lease expired; claim again before editing")
        return lease

    def claim(self, owner: str, task_id: str | None = None) -> dict[str, Any]:
        # Take the lease before updating a branch after develop advances.
        self.assert_writer()
        self.assert_workspace(require_base=False)
        with self.transaction() as state:
            if state.get("paused"):
                raise WorkflowError("workflow is paused")
            old = state.get("lease")
            if old and datetime.fromisoformat(old["expires_at"]) > now_utc():
                raise WorkflowError(f"worker already active: {old['owner']}")
            task = self.task(task_id) if task_id else self.next_task(state)
            if task is None:
                raise WorkflowError(
                    "no actionable task; triage the queue without creating a branch"
                )
            status = state["tasks"].get(task["id"], {}).get("status", task["status"])
            if status not in {"queued", "in_progress"} or not all(
                state["tasks"].get(dep, {}).get("status", self.task(dep)["status"]) == "done"
                for dep in task.get("depends_on", [])
            ):
                raise WorkflowError("task is blocked, complete, or has unfinished dependencies")
            token = uuid.uuid4().hex
            state["lease"] = {
                "token": token,
                "owner": owner,
                "task_id": task["id"],
                "started_at": now_utc().isoformat(),
                "expires_at": (
                    now_utc() + timedelta(minutes=self.policy["lease_minutes"])
                ).isoformat(),
            }
            progress = state["tasks"].setdefault(task["id"], {})
            progress["status"] = "in_progress"
            return {"lease": state["lease"], "task": task, "recovered_expired_lease": bool(old)}

    def renew(self, token: str) -> None:
        self.assert_writer()
        with self.transaction() as state:
            lease = self.lease(state, token)
            lease["expires_at"] = (
                now_utc() + timedelta(minutes=self.policy["lease_minutes"])
            ).isoformat()

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        paths = set(command(self.root, "git", "ls-files", "-z").split("\0"))
        paths.update(
            command(self.root, "git", "ls-files", "--others", "--exclude-standard", "-z").split(
                "\0"
            )
        )
        for name in sorted(paths - {""}):
            path = self.root / name
            digest.update(name.encode("utf-8") + b"\0")
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8"))
            elif path.is_file():
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"missing")
        return digest.hexdigest()

    def check(self, token: str, profiles: list[str], timeout: int = 1800) -> dict[str, Any]:
        self.assert_writer()
        self.assert_workspace()
        lease = self.lease(self.load(), token)
        if not profiles or set(profiles) - set(self.policy["profiles"]):
            raise WorkflowError("unknown gate profile")
        self.renew(token)
        with self.transaction() as state:
            self.lease(state, token)
            state["last_check"] = {
                "task_id": lease["task_id"],
                "passed": False,
                "status": "running",
                "created_at": now_utc().isoformat(),
            }
        run_dir = self.runtime / "runs" / f"{now_utc():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        run_dir.mkdir(parents=True)
        temporary = run_dir / "temp"
        temporary.mkdir()
        environment = dict(
            os.environ, PYTHONPATH=str(self.root / "src"), TEMP=str(temporary), TMP=str(temporary)
        )
        before = self.fingerprint()
        checks = []
        for profile in dict.fromkeys(profiles):
            for configured in self.policy["profiles"][profile]:
                args = [part.replace("{run_dir}", str(run_dir)) for part in configured]
                args = resolve_command(args, environment)
                log_path = run_dir / f"{len(checks) + 1:02}-{profile}.log"
                started = time.monotonic()
                self.renew(token)
                with log_path.open("w", encoding="utf-8") as log:
                    try:
                        process = subprocess.Popen(
                            args,
                            cwd=self.root,
                            env=environment,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                            if os.name == "nt"
                            else 0,
                            start_new_session=os.name != "nt",
                        )
                        try:
                            while process.poll() is None:
                                if time.monotonic() - started > timeout:
                                    stop_process(process)
                                    break
                                self.renew(token)
                                time.sleep(1)
                        finally:
                            if process.poll() is None:
                                stop_process(process)
                        code = process.returncode
                    except OSError as exc:
                        log.write(str(exc))
                        code = 127
                checks.append(
                    {
                        "profile": profile,
                        "command": configured,
                        "exit_code": code,
                        "seconds": round(time.monotonic() - started, 2),
                        "log": str(log_path),
                    }
                )
                print(
                    f"{profile}: {'PASS' if code == 0 else 'FAIL'} ({checks[-1]['seconds']}s)",
                    flush=True,
                )
                if code:
                    break
            if checks[-1]["exit_code"]:
                break
        passed = all(check["exit_code"] == 0 for check in checks) and before == self.fingerprint()
        cleanup_warnings = []
        if passed:
            for name in ("pytest", "temp"):
                generated = run_dir / name
                if generated.exists():
                    try:
                        remove_generated_directory(generated, run_dir)
                    except OSError as exc:
                        cleanup_warnings.append(str(exc))
        result = {
            "task_id": lease["task_id"],
            "source_fingerprint": before,
            "profiles": sorted({check["profile"] for check in checks}),
            "passed": passed,
            "checks": checks,
            "cleanup_warnings": cleanup_warnings,
            "created_at": now_utc().isoformat(),
        }
        write_json(run_dir / "result.json", result)
        with self.transaction() as state:
            self.lease(state, token)
            state["last_check"] = dict(result, report=str(run_dir / "result.json"))
            progress = state["tasks"][lease["task_id"]]
            progress["consecutive_gate_failures"] = (
                0 if passed else progress.get("consecutive_gate_failures", 0) + 1
            )
        return result

    def verify_evidence(self, state: dict[str, Any], task_id: str) -> dict[str, Any]:
        check = state.get("last_check", {})
        required = set(self.task(task_id)["required_profiles"])
        if (
            not check.get("passed")
            or check.get("task_id") != task_id
            or required - set(check.get("profiles", []))
            or check.get("source_fingerprint") != self.fingerprint()
        ):
            raise WorkflowError(
                "passing gates for the current source and required profiles are missing"
            )
        return check

    def complete(self, token: str, outcome: str, note: str) -> None:
        self.assert_writer()
        self.assert_workspace()
        with self.transaction() as state:
            lease = self.lease(state, token)
            progress = state["tasks"][lease["task_id"]]
            if outcome == "done":
                evidence = self.verify_evidence(state, lease["task_id"])
                progress["evidence"] = evidence["report"]
                state["publish_task_id"] = lease["task_id"]
            progress.update(status=outcome, note=note, updated_at=now_utc().isoformat())
            state["lease"] = None

    def publish(self) -> dict[str, str]:
        self.assert_writer()
        self.assert_workspace()
        with self.transaction() as state:
            if state.get("paused") or state.get("lease"):
                raise WorkflowError("release the worker lease before publishing")
            task_id = state.get("publish_task_id")
            if not task_id:
                raise WorkflowError("no completed checkpoint to publish")
            self.verify_evidence(state, task_id)
            if command(self.root, "git", "status", "--porcelain"):
                raise WorkflowError("commit the validated checkpoint before publishing")
            if not self.policy["allow_push"] or not self.policy["allow_draft_pr"]:
                raise WorkflowError("publishing is disabled")
            branch = self.policy["branch"]
            pinned_pull = self.policy.get("pull_request")
            if pinned_pull:
                pull = json.loads(command(
                    self.root, "gh", "pr", "view", str(pinned_pull), "--json",
                    "state,isDraft,headRefName,baseRefName,url",
                ))
                if (
                    pull.get("state") != "OPEN" or not pull.get("isDraft")
                    or pull.get("headRefName") != branch
                    or pull.get("baseRefName") != self.policy["base_branch"]
                ):
                    raise WorkflowError("pinned PR changed or closed; wait for maintainer")
                pulls = [dict(pull, number=pinned_pull)]
            else:
                pulls = None
            command(self.root, "git", "push", "-u", "origin", branch)
            pulls = pulls if pulls is not None else json.loads(
                command(
                    self.root,
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--head",
                    branch,
                    "--base",
                    self.policy["base_branch"],
                    "--json",
                    "number,url,isDraft",
                )
            )
            body = self.runtime / "pull-request.md"
            body.write_text(self.pr_body(state), encoding="utf-8")
            if len(pulls) > 1:
                raise WorkflowError("multiple PRs found; reconcile before publishing")
            if pulls:
                pull = pulls[0]
                command(
                    self.root, "gh", "pr", "edit", str(pull["number"]), "--body-file", str(body)
                )
                url = pull["url"]
            else:
                url = command(
                    self.root,
                    "gh",
                    "pr",
                    "create",
                    "--draft",
                    "--base",
                    self.policy["base_branch"],
                    "--head",
                    branch,
                    "--title",
                    "持续开发：卡库同步、规则可靠性与自动验证",
                    "--body-file",
                    str(body),
                )
            state["published"] = {
                "head": command(self.root, "git", "rev-parse", "HEAD"),
                "url": url,
                "at": now_utc().isoformat(),
            }
            return state["published"]

    def pr_body(self, state: dict[str, Any]) -> str:
        lines = [
            "将持续迭代集中在单一 develop-based 分支，自动验证后更新同一个 PR。",
            "",
            "## 本批成果",
            "",
        ]
        for task in self.queue["tasks"]:
            progress = state["tasks"].get(task["id"], {})
            if progress.get("status") == "done":
                lines.append(f"- {task['title']}：{progress.get('note', '')}")
        lines.extend(["", "## 验证", ""])
        for check in state.get("last_check", {}).get("checks", []):
            lines.append(f"- {check['profile']}: {'PASS' if check['exit_code'] == 0 else 'FAIL'}")
        lines.extend(["", "当前 PR 为人工审查入口；合并与部署需维护者明确批准。", ""])
        return "\n".join(lines)


def resolve_command(args: list[str], environment: dict[str, str]) -> list[str]:
    if args[0] == "python":
        return [sys.executable, *args[1:]]
    if args[0] != "npm":
        return args
    node = environment.get("LOVECA_NODE") or shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise WorkflowError("Node/npm missing; use a supported Node 24 runtime")
    npm_path = Path(npm).resolve()
    npm_cli = npm_path.parent / "node_modules/npm/bin/npm-cli.js"
    environment["PATH"] = str(Path(node).parent) + os.pathsep + environment.get("PATH", "")
    return [node, str(npm_cli), *args[1:]] if npm_cli.exists() else [npm, *args[1:]]


def stop_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=30)


def remove_generated_directory(path: Path, run_dir: Path) -> None:
    root = run_dir.resolve()
    if path.is_symlink() or path.resolve().parent != root:
        raise WorkflowError("generated test directory escaped its run")

    def retry_readonly(function, name, error):
        target = Path(name)
        if not isinstance(error, PermissionError) or not target.resolve().is_relative_to(root):
            raise error
        os.chmod(target, target.stat().st_mode | stat.S_IWUSR)
        function(name)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry_readonly)
    else:
        shutil.rmtree(path, onerror=lambda fn, name, info: retry_readonly(fn, name, info[1]))


def inventory(root: Path, base_ref: str, active_branch: str) -> dict[str, Any]:
    records = []
    for block in command(root, "git", "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" not in fields:
            continue
        path = Path(fields["worktree"])
        record: dict[str, Any] = {
            "path": str(path),
            "head": fields.get("HEAD"),
            "branch": fields.get("branch", "detached").removeprefix("refs/heads/"),
        }
        try:
            changes = command(path, "git", "status", "--porcelain")
            behind, ahead = map(
                int,
                command(
                    path, "git", "rev-list", "--left-right", "--count", f"{base_ref}...HEAD"
                ).split(),
            )
            record.update(changes=changes.splitlines(), behind=behind, ahead=ahead)
            record["disposition"] = (
                "active"
                if record["branch"] == active_branch
                else "preserve_dirty"
                if changes
                else "merged_history"
                if ahead == 0
                else "review_unique"
            )
        except (WorkflowError, OSError) as exc:
            record.update(disposition="unreadable_preserve", error=str(exc))
        records.append(record)
    branches = []
    refs = command(
        root, "git", "for-each-ref", "--format=%(refname:short)", "refs/heads"
    ).splitlines()
    for ref in refs:
        behind, ahead = map(
            int,
            command(
                root, "git", "rev-list", "--left-right", "--count", f"{base_ref}...{ref}"
            ).split(),
        )
        branches.append(
            {
                "branch": ref,
                "ahead": ahead,
                "behind": behind,
                "worktree": next((r["path"] for r in records if r["branch"] == ref), None),
            }
        )
    return {
        "generated_at": now_utc().isoformat(),
        "base_ref": base_ref,
        "worktrees": records,
        "branches": branches,
    }


def inventory_markdown(result: dict[str, Any]) -> str:
    labels = {
        "active": "唯一活跃主线",
        "preserve_dirty": "未提交成果，必须保留",
        "merged_history": "已合并历史，报告核对后归档",
        "review_unique": "有独有提交，待对比迁移",
        "unreadable_preserve": "未能读取，保留并重试",
    }
    lines = [
        "# 分支与工作树清单",
        "",
        f"生成时间（UTC）：{result['generated_at']}。基线：`{result['base_ref']}`。",
        f"本地分支 {len(result['branches'])} 个；工作树 {len(result['worktrees'])} 个。",
        "",
        "## 工作树",
        "",
        "| 分支 | 领先 / 落后 develop | 未提交文件 | 处理方式 | 路径 |",
        "|---|---:|---:|---|---|",
    ]
    for tree in result["worktrees"]:
        lines.append(
            f"| `{tree['branch']}` | {tree.get('ahead', '?')} / {tree.get('behind', '?')} "
            f"| {len(tree.get('changes', [])) if 'changes' in tree else '?'} "
            f"| {labels[tree['disposition']]} | `{tree['path']}` |"
        )
    lines.extend(
        [
            "",
            "## 分支",
            "",
            "| 分支 | 领先 / 落后 develop | 被工作树使用 |",
            "|---|---:|---|",
        ]
    )
    for branch in result["branches"]:
        lines.append(
            f"| `{branch['branch']}` | {branch['ahead']} / {branch['behind']} "
            f"| {'是' if branch['worktree'] else '否'} |"
        )
    lines.extend(
        [
            "",
            "`ahead=0` 仅说明提交已包含在 develop；"
            "不代表工作树中的未提交文件或 ignored 报告可以删除。",
            "dirty、独有提交与无法读取的工作树全部保留。"
            "常规自动任务只使用 continuous-development。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--environment", choices=["local", "cloud"],
        default=os.environ.get("LOVECA_DEVELOPMENT_ENV", "local"),
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("validate", "status", "next", "doctor", "pause", "resume", "publish"):
        commands.add_parser(name)
    inv = commands.add_parser("inventory")
    inv.add_argument("--output", type=Path)
    inv.add_argument("--markdown", type=Path)
    claim = commands.add_parser("claim")
    claim.add_argument("--owner", required=True)
    claim.add_argument("--task")
    for name in ("renew", "release", "complete", "check", "checkpoint"):
        sub = commands.add_parser(name)
        sub.add_argument("--lease", required=True)
        if name == "complete":
            sub.add_argument("--outcome", choices=["done", "blocked"], required=True)
            sub.add_argument("--note", required=True)
        if name == "check":
            sub.add_argument("--profiles", nargs="+", required=True)
            sub.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    try:
        workflow = Workflow(args.root, environment=args.environment)
        operation = args.operation
        result: Any = {"ok": True}
        if operation == "doctor":
            workflow.assert_workspace()
            workflow.load()
            result = {
                "ok": True,
                "workspace": str(workflow.root),
                "runtime": str(workflow.runtime),
                "branch": workflow.policy["branch"],
                "environment": workflow.environment,
                "write_enabled": workflow.environment == workflow.policy.get(
                    "active_environment", "local"
                ),
            }
        elif operation == "inventory":
            result = inventory(
                workflow.root, workflow.policy["base_ref"], workflow.policy["branch"]
            )
            if args.output:
                write_json(args.output, result)
            if args.markdown:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                args.markdown.write_text(inventory_markdown(result), encoding="utf-8")
        elif operation == "status":
            state = workflow.load()
            result = dict(state, next_task=workflow.next_task(state))
        elif operation == "next":
            result = workflow.next_task(workflow.load())
        elif operation in {"pause", "resume"}:
            workflow.assert_writer()
            with workflow.transaction() as state:
                state["paused"] = operation == "pause"
                result = {"paused": state["paused"]}
        elif operation == "claim":
            result = workflow.claim(args.owner, args.task)
        elif operation == "renew":
            workflow.renew(args.lease)
        elif operation == "release":
            workflow.assert_writer()
            with workflow.transaction() as state:
                workflow.lease(state, args.lease)
                state["lease"] = None
        elif operation == "checkpoint":
            result = workflow.checkpoint(args.lease)
        elif operation == "complete":
            workflow.complete(args.lease, args.outcome, args.note)
        elif operation == "check":
            result = workflow.check(args.lease, args.profiles, args.timeout)
            if not result["passed"]:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
        elif operation == "publish":
            result = workflow.publish()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkflowError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
