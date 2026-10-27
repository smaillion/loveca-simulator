# AI-DLC Upstream Record

- Repository: https://github.com/awslabs/aidlc-workflows
- Tag: `v2.7.0`
- Commit: `96b11d39028955d4f92375e783525db5275cdfd8`
- Distribution: `dist/codex`
- License: MIT-0, preserved in `LICENSE`

The repository tracks the Codex runtime under `.agents/` and `.codex/` plus
the AI-DLC workspace shell under `aidlc/`. `manifest.json` records hashes for
files that must match the upstream distribution; text line endings are
normalized to LF so verification is stable across platforms.

The following files are intentionally adapted for this project and are not
byte-identical vendor files:

- `AGENTS.md`
- `.codex/config.toml`
- `.gitignore`
- `aidlc/spaces/default/memory/org.md`
- `aidlc/spaces/default/memory/team.md`
- `aidlc/spaces/default/memory/project.md`

For an upgrade, replace the complete `dist/codex/.agents/` and
`dist/codex/.codex/` trees while no AI-DLC workflow is active, copy the workspace
shell additions, reapply the project adaptations, then run:

```powershell
python scripts/aidlc_vendor.py generate --tag vX.Y.Z --commit <40-char-sha>
python scripts/aidlc_vendor.py verify
```

Review the upstream changelog and migration notes before committing. If
`.codex/hooks.json` changed, regenerate and reapprove Codex hook trust before
starting a new session.
