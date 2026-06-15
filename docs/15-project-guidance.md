# Project Guidance / プロジェクト指針 / 项目指引

This file records maintenance rules that should stay stable across releases.

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
