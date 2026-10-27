from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "third_party" / "aidlc-workflows" / "manifest.json"
IMMUTABLE_ROOTS = (
    Path(".agents"),
    Path(".codex"),
    Path("aidlc/spaces/default/memory/phases"),
    Path("aidlc/spaces/default/memory/templates"),
)
IMMUTABLE_FILES = (Path("third_party/aidlc-workflows/LICENSE"),)
ADAPTED_PATHS = (
    Path("AGENTS.md"),
    Path(".codex/config.toml"),
    Path(".gitignore"),
    Path("aidlc/spaces/default/memory/org.md"),
    Path("aidlc/spaces/default/memory/team.md"),
    Path("aidlc/spaces/default/memory/project.md"),
)
IMMUTABLE_EXCLUSIONS = {Path(".codex/config.toml")}
TEXT_SUFFIXES = {".gitkeep", ".json", ".md", ".rules", ".toml", ".ts", ".yaml"}


def sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def immutable_files() -> list[Path]:
    paths: set[Path] = set(IMMUTABLE_FILES)
    for root in IMMUTABLE_ROOTS:
        absolute_root = PROJECT_ROOT / root
        if not absolute_root.exists():
            continue
        for absolute_path in absolute_root.rglob("*"):
            if not absolute_path.is_file():
                continue
            relative_path = absolute_path.relative_to(PROJECT_ROOT)
            if relative_path not in IMMUTABLE_EXCLUSIONS:
                paths.add(relative_path)
    return sorted(paths, key=lambda path: path.as_posix())


def load_manifest() -> dict[str, object]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(f"AI-DLC manifest is missing: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def generate_manifest(tag: str, commit: str) -> None:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise RuntimeError(f"invalid AI-DLC tag: {tag}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError(f"invalid AI-DLC commit: {commit}")

    files = {
        path.as_posix(): sha256(PROJECT_ROOT / path)
        for path in immutable_files()
    }
    payload = {
        "schema_version": 1,
        "upstream": {
            "repository": "https://github.com/awslabs/aidlc-workflows",
            "tag": tag,
            "commit": commit,
            "distribution": "dist/codex",
            "license": "MIT-0",
        },
        "immutable_files": files,
        "project_adapted_paths": [path.as_posix() for path in ADAPTED_PATHS],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated AI-DLC manifest: {len(files)} immutable files")


def verify_manifest() -> list[str]:
    manifest = load_manifest()
    errors: list[str] = []
    expected = manifest.get("immutable_files")
    if not isinstance(expected, dict):
        return ["manifest immutable_files must be an object"]

    expected_paths = {Path(path) for path in expected}
    actual_paths = set(immutable_files())
    for path in sorted(expected_paths - actual_paths, key=lambda item: item.as_posix()):
        errors.append(f"missing vendored file: {path.as_posix()}")
    for path in sorted(actual_paths - expected_paths, key=lambda item: item.as_posix()):
        errors.append(f"untracked vendored file: {path.as_posix()}")

    for path in sorted(expected_paths & actual_paths, key=lambda item: item.as_posix()):
        expected_hash = expected.get(path.as_posix())
        actual_hash = sha256(PROJECT_ROOT / path)
        if expected_hash != actual_hash:
            errors.append(
                f"vendored file changed: {path.as_posix()} "
                f"(expected {expected_hash}, got {actual_hash})"
            )

    for path in ADAPTED_PATHS:
        if not (PROJECT_ROOT / path).is_file():
            errors.append(f"project adaptation is missing: {path.as_posix()}")

    upstream = manifest.get("upstream")
    tag = upstream.get("tag") if isinstance(upstream, dict) else None
    version_path = PROJECT_ROOT / ".codex/tools/aidlc-version.ts"
    if isinstance(tag, str) and version_path.is_file():
        expected_version = tag.removeprefix("v")
        version_text = version_path.read_text(encoding="utf-8")
        if f'AIDLC_VERSION = "{expected_version}"' not in version_text:
            errors.append(
                f"AI-DLC runtime version does not match manifest tag {tag}"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the pinned AI-DLC Codex distribution.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify", help="Verify pinned immutable AI-DLC files.")
    generate = subparsers.add_parser("generate", help="Regenerate hashes after a reviewed upgrade.")
    generate.add_argument("--tag", required=True)
    generate.add_argument("--commit", required=True)
    args = parser.parse_args()

    if args.command == "generate":
        generate_manifest(args.tag, args.commit)
        return 0

    errors = verify_manifest()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    manifest = load_manifest()
    upstream = manifest["upstream"]
    print(
        "AI-DLC vendor verified: "
        f"{upstream['tag']} ({len(manifest['immutable_files'])} immutable files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
