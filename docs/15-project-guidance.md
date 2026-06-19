# Project Guidance / プロジェクト指針 / 项目指引

This file records maintenance rules that should stay stable across releases.

## Branch and Release Flow

### 日本語

- 通常の新機能ブランチは `develop` から作成する。
- hotfix ブランチも、緊急でない限り `develop` から作成する。
- `develop` は通常の統合ブランチであり、Hosted Online の検証と低コスト online smoke の主な対象とする。
- `preview` は公開 GitHub Pages preview 用の独立ブランチとして扱う。
- `preview` や preview 専用ブランチから通常の feature branch を切らない。
- 公開 preview を更新する場合のみ、安定した時点の成果を `preview` に同期する。
- `main` は手動で昇格する安定 snapshot ブランチとして扱う。
- 現段階では `main` への push で自動 publish / deploy しない。production 相当の公開は maintainer が明示的に workflow を手動実行するか、専用の release 手順で行う。
- 誤って preview 系ブランチから作業を始めた場合は、`develop` ベースの replacement branch を作成するか、必要に応じて history を rewrite して修正する。
- Hosted Online は GitHub Pages frontend、Cloudflare Worker API gateway、Caddy HTTPS origin、localhost FastAPI を基本構成とする。
- 正式 frontend 配布は、当面は `develop` の安定 build または maintainer が手動昇格した `main` snapshot から行い、`runtime-config.json` の `apiBaseUrl` で Worker URL に接続する。
- VPS は frontend 静的配信を担当せず、backend API origin のみを担当させる。

### 简体中文

- 常规新功能分支默认从 `develop` 创建。
- hotfix 分支除非特别紧急，也默认从 `develop` 创建。
- `develop` 是常规集成分支，也是 Hosted Online 验证和低成本 online smoke 的主要目标。
- `preview` 作为公开 GitHub Pages preview 的独立分支保留。
- 不从 `preview` 或 preview 专用分支继续创建常规 feature branch。
- 只有准备更新公开 preview 时，才把稳定点同步到 `preview`。
- `main` 作为手动晋升的稳定 snapshot 分支维护。
- 当前阶段 `main` push 不触发自动 publish / deploy。接近生产的公开发布必须由 maintainer 明确手动执行 workflow，或走专门的 release 流程。
- 如果误从 preview 系分支开始开发，应创建 develop-based replacement branch，必要时 rewrite 历史修正。
- Hosted Online 采用 GitHub Pages frontend、Cloudflare Worker API gateway、Caddy HTTPS origin、localhost FastAPI 作为基本结构。
- 正式 frontend 分发现阶段来自 `develop` 稳定构建，或 maintainer 手动晋升后的 `main` snapshot，并通过 `runtime-config.json` 的 `apiBaseUrl` 连接 Worker URL。
- VPS 不托管前端静态文件，只保留 backend API origin 职责。

## Changelog Language

### 日本語

- `CHANGELOG.md` は日本語と簡体中文の二言語で記述する。
- 英語のみの release note は追加しない。
- 各 release section では日本語を先に書き、その直後に `中文:` として簡体中文の説明を置く。
- 公式カード名、公式ルール用語、カード効果ラベルは、可能な限り公式日本語表記を保持する。
- コマンド名、file path、enum、API field、内部識別子は翻訳せず、そのまま記述する。

### 简体中文

- `CHANGELOG.md` 必须使用日文和简体中文双语维护。
- 不新增只有英文的 release note。
- 每个版本段落先写日文，再在 `中文:` 下写对应的简体中文说明。
- 官方卡名、官方规则术语和卡牌效果标签应尽量保留官方日文表记。
- 命令名、文件路径、enum、API 字段和内部标识不翻译，保持代码中的原样。

## Local Pre-Push Checks

### 日本語

- 通常の push 前には `powershell -ExecutionPolicy Bypass -File ./scripts/pre-push-check.ps1` を実行する。
- DB、effect registry、manifest、fingerprint 算出ロジックに関係する変更がある場合、この script は `python scripts/card-db-manifest.py verify` を実行する。
- 純粋な frontend / CSS / document 変更では card DB manifest check は不要なので、この script は明示的に skip する。
- `data/loveca.sqlite3` または `data_sources/effect-registry.v0.json` を変更した場合は、必要に応じて `python scripts/card-db-manifest.py generate` で `data/loveca-db-manifest.json` を更新してから push する。
- GitHub Pages preview の build は frontend 配布物用に manifest を生成してよいが、API image / API deploy は locked manifest verification を通す。

### 简体中文

- 常规 push 前运行 `powershell -ExecutionPolicy Bypass -File ./scripts/pre-push-check.ps1`。
- 如果改动涉及 DB、effect registry、manifest 或 fingerprint 计算逻辑，该脚本会执行 `python scripts/card-db-manifest.py verify`。
- 纯前端 / CSS / 文档改动不需要 card DB manifest 检查，脚本会明确跳过。
- 如果修改了 `data/loveca.sqlite3` 或 `data_sources/effect-registry.v0.json`，应视情况先运行 `python scripts/card-db-manifest.py generate` 更新 `data/loveca-db-manifest.json` 再 push。
- GitHub Pages preview 构建可以为前端发布产物生成 manifest；API image / API deploy 必须继续通过 locked manifest verification。

## Documentation Language

### 日本語

- `README.md` は日本語を主文とする。
- `README.zh-CN.md` は簡体中文の利用者向け README とする。
- `docs/` と `specs/` の既存英語設計文書は、必要がない限り英語のまま維持する。
- ユーザー向け操作説明や release note は、日本語または簡体中文で書くことを優先する。

### 简体中文

- `README.md` 以日文为主文。
- `README.zh-CN.md` 面向简体中文用户。
- `docs/` 和 `specs/` 中既有的英文设计文档，除非有明确需要，继续保持英文。
- 面向用户的操作说明和 release note 优先使用日文或简体中文。
