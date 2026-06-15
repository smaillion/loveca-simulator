# Project Guidance / プロジェクト指針 / 项目指引

This file records maintenance rules that should stay stable across releases.

## Branch and Release Flow

### 日本語

- 通常の新機能ブランチは `develop` から作成する。
- `preview` は公開 GitHub Pages preview 用の独立ブランチとして扱う。
- `preview` や preview 専用ブランチから通常の feature branch を切らない。
- 公開 preview を更新する場合のみ、安定した時点の成果を `preview` に同期する。
- 誤って preview 系ブランチから作業を始めた場合は、`develop` ベースの replacement branch を作成するか、必要に応じて history を rewrite して修正する。
- Hosted Online 機能が安定するまでは、VPS が一時的に frontend と backend の両方を提供してよい。
- Hosted Online 機能が安定した後は、正式 frontend 配布を `develop` または `main` の安定 build に切り替え、`VITE_HOSTED_API_BASE_URL` で hosted API に接続する。
- その後、VPS の frontend 静的配信は停止し、backend API のみを担当させる。

### 简体中文

- 常规新功能分支默认从 `develop` 创建。
- `preview` 作为公开 GitHub Pages preview 的独立分支保留。
- 不从 `preview` 或 preview 专用分支继续创建常规 feature branch。
- 只有准备更新公开 preview 时，才把稳定点同步到 `preview`。
- 如果误从 preview 系分支开始开发，应创建 develop-based replacement branch，必要时 rewrite 历史修正。
- Hosted Online 功能稳定前，VPS 可以临时同时提供 frontend 和 backend。
- Hosted Online 功能稳定后，正式 frontend 分发应切换为 `develop` 或 `main` 的稳定构建，并通过 `VITE_HOSTED_API_BASE_URL` 连接 hosted API。
- 此后 VPS 应停止托管前端静态文件，只保留 backend API 职责。

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
