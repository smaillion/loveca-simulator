#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
mode="${1:-install}"
if [[ "$mode" != install && "$mode" != --check ]]; then
  printf 'Usage: bash scripts/codex-cloud-setup.sh [--check]\n' >&2
  exit 2
fi

# The environment supplies runtimes; do not download executables or credentials.
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python >=3.11 required (3.12 recommended)"'
node -e 'if (Number(process.versions.node.split(".")[0]) !== 24) throw new Error("Node 24 required")'
command -v git >/dev/null
command -v gh >/dev/null
npm --version

if [[ "$mode" == install ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[dev]'
  npm --prefix web ci
fi

export PYTHONPATH="$repo/src"
export LOVECA_DEVELOPMENT_ENV=cloud
export TEMP="$repo/.tmp/cloud-temp"
export TMP="$TEMP"
mkdir -p "$TEMP"
python="$repo/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  printf 'Run the install step first; .venv is missing.\n' >&2
  exit 1
fi
"$python" -m tools.development.loop validate
"$python" -m tools.development.loop doctor
"$python" scripts/aidlc_vendor.py verify
"$python" scripts/card-db-manifest.py verify
"$python" -m tools.ai_sandbox.effect_registry_integrity \
  --database data/loveca.sqlite3 --strict --output logs/cloud-setup-registry
printf 'Preflight complete. This does not activate the cloud writer or schedule tasks.\n'
