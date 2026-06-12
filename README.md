# Love Live! Series Official Card Game Analysis & Simulation Platform

面向 Love Live! Series Official Card Game（ラブカ）的本地卡牌数据、牌组分析与对战规则验证平台。

项目以官方日文资料为唯一权威来源。英文内部名称仅作为稳定的工程标识，不替代官方日文术语。当前导入和卡图数据只用于本地研究与规则验证，不作为公开卡牌数据集发布。

## 当前开发状态

### 已完成

#### 卡牌数据库

* SQLite Schema v2 与 schema version 检查。
* `Gameplay Card` 与 `Card Printing` 分离：
  * `card_code` 表示规则卡身份。
  * `card_id` 表示完整印刷版本。
* Member、Live、Energy 类型属性边界。
* Heart 颜色、Blade、Blade Heart、特殊 Blade Heart 和 Live 所需 Heart。
* 日文技能文本修订、来源观测、Work、Unit 和 Card Set 关系。
* 30 张跨产品官方卡牌审查样本的离线、幂等导入。
* 本地官方卡图缓存与 SHA-256 manifest。

#### Deck Analyzer MVP

* `decklist.v0.json` 牌组格式。
* 主牌组、Live 与 Energy 数量检查。
* 同一 `card_code` 最多 4 张。
* 未知卡牌、错误区域卡型和 `preferred_printing_id` 一致性检查。
* Member cost curve、Heart 分布、Blade、Live score 和特殊 Blade Heart 汇总。
* text 与 JSON 两种输出格式。

#### 可视化规则验证器

* React、TypeScript、Vite SPA。
* FastAPI 本地权威服务。
* 独立 runtime SQLite：
  * `matches`
  * `match_actions`
  * `match_events`
  * `match_snapshots`
* 可序列化 `GameState`、Action-only 状态变化和 `expected_revision` 并发检查。
* Action、Events 与最新 Snapshot 在同一事务中提交。
* 使用 seed 和有序 Actions 进行确定性 Replay。
* 双方公开信息的本地规则调试模式。
* 中文操作界面，同时显示官方日文阶段名、卡名和技能原文。
* 已支持的首轮流程：
  * 创建对局与确定先后攻
  * 起手 6 张与双方调度
  * 初始 Energy 3 张
  * Active、Energy、Draw 和 Main 阶段
  * 基础 Energy 支付与 Member 登场
  * Live Set 与 Live 公开
  * 应援（エール）
  * Blade 合计与应援翻牌
  * 成员 Heart、应援 Heart 和任意色 Heart 计算
  * 逐张 Live 所需 Heart 分配
  * 特殊 Blade Heart 的 `ALLn`、`ドローn` 和 `スコアn`
  * Live 基础分、特殊加分、总分与首次胜负判定
  * 成功 Live 选择
* 中央 Live 区显示判定基准、Heart 消费、缺口、分数构成与结果。
* 不支持的卡牌语义技能可通过 replay-safe `ManualAdjustmentAction` 处理。
* 卡图缺失时使用文字卡面降级，不由 UI 自动联网。

### 当前边界

* 对局在第一次 Live 胜负判定完成后停止。
* 当前目标是人工验证规则模型，不是胜率估算或自动对战。
* Member 只能进入空的左、中、右 Member Area。
* 卡牌语义技能不会根据日文原文自动执行。
* 规则基线为本地审查的综合规则 `ver. 1.06`（2026-04-28）。
* 当前卡牌库只包含 30 张跨产品审查样本，不是全量官方卡表。

### 尚未实现

* 多回合对局循环。
* 成功 Live 达到 3 张时的正式胜利或同时达成时的平局。
* 根据 Live 判定结果变更下一回合先攻玩家。
* Member 替换、叠放与 Baton 等完整 Main 阶段规则。
* 完整卡牌技能触发、Effect DSL 与可执行效果审查流程。
* Simple AI、AI vs AI、Monte Carlo 与胜率引擎。
* WebSocket、账户、在线多人和服务器部署。
* 全量官方卡牌导入。

## 环境要求

* Python 3.11 或更高版本。
* Node.js 20、22 或 24 以上版本。
* Node.js 21 不在 Vite 和 Vitest 支持的 engine 范围内。

安装 Python 项目和开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

## 本地卡牌数据库

初始化 SQLite Schema v2：

```powershell
loveca cards init --database data/loveca.sqlite3
```

导入已审查的 30 张本地样本：

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data_samples/normalized/cards-cross-product-sample.json `
  --normalization data_sources/card-entity-normalization.json
```

该导入命令完全离线，不会访问官方网站，也不会运行 importer spike。

## Deck Analyzer MVP

使用本地 SQLite 卡牌库分析示例牌组：

```powershell
loveca decks analyze `
  --database data/loveca.sqlite3 `
  --deck examples/decks/sample-deck.json `
  --output text
```

使用 `--output json` 可获得供 UI 或自动化测试消费的结构化结果。Deck Entry 引用 `card_code`；可选的 `preferred_printing_id` 仅用于选择展示印刷版本，不改变规则合法性。

## 可视化规则验证器

安装前端依赖并构建 SPA：

```powershell
cd web
npm install
npm run build
cd ..
```

可选：将数据库中记录的官方 HTTPS 卡图缓存到本地：

```powershell
loveca cards cache-images `
  --database data/loveca.sqlite3 `
  --cache-dir data/card_images `
  --delay 1
```

启动 FastAPI 与构建后的 SPA：

```powershell
loveca web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
```

浏览器打开 <http://127.0.0.1:8765>。

卡牌数据库和对局 runtime 数据库彼此独立。`data/`、本地 SQLite、卡图缓存和浏览器测试截图均不提交 Git。

## 验证状态

当前验证基线：

* 49 个 Python/pytest 测试通过。
* Vitest 前端组件测试通过。
* TypeScript 与 Vite production build 通过。
* Playwright 通过完整首轮流程、桌面布局、移动布局和卡图降级验证。
* `npm audit` 未报告已知依赖漏洞。

运行 Python 测试：

```powershell
python -m pytest
```

运行前端测试与构建：

```powershell
cd web
npm run test
npm run build
```

运行 Playwright 测试前，需先在 `127.0.0.1:8765` 启动本地服务：

```powershell
cd web
npm run test:e2e
```

## 主要目录

* `src/loveca/cards/`：卡牌数据库、导入和本地卡图缓存。
* `src/loveca/decks/`：牌组格式、合法性校验和分析。
* `src/loveca/simulation/`：GameState、Actions、规则引擎、runtime SQLite 和 Replay。
* `src/loveca/webapp.py`：FastAPI 接口和 SPA 静态文件服务。
* `web/`：React 规则验证器。
* `tests/`：离线 Python 测试。
* `data_samples/`：本地官方数据审查样本与 importer spike 报告。
* `data_sources/`：官方来源 manifest、术语和规范化审查资料。
* `raw_doc/`：本地保存的官方规则审查资料，不作为公开数据集发布。
* `docs/`：长期维护的架构与领域文档。
* `specs/`：Spec-Driven Development 规格。

## 文档

* [项目愿景](docs/00-project-vision.md)
* [来源与数据政策](docs/01-source-policy.md)
* [领域术语表](docs/02-domain-glossary.md)
* [概念数据模型](docs/03-data-model-notes.md)
* [规则模型](docs/04-rule-model-notes.md)
* [开发路线图](docs/05-development-roadmap.md)
* [架构总览](docs/06-architecture-overview.md)
* [扩展路线图](docs/07-roadmap-expanded.md)
* [AI 与模拟说明](docs/08-ai-and-simulation-notes.md)
* [Replay 与在线就绪性](docs/09-replay-and-online-readiness.md)
* [效果建模与分类](docs/10-effect-modeling-and-taxonomy.md)
* [卡牌数据 ERD](docs/12-card-data-erd.md)

## 规格

* [规格索引](specs/README.md)
* [Rule Engine](specs/002-rule-engine.spec.md)
* [GameState and Actions](specs/003-gamestate-and-actions.spec.md)
* [Action System](specs/005-action-system.spec.md)
* [Controller and Legal Actions](specs/012-controller-and-legal-actions.spec.md)
* [Terminology Normalization](specs/016-terminology-normalization.spec.md)
* [Public Release and Export Policy](specs/017-public-release-and-export-policy.spec.md)
* [Card Data Storage](specs/018-card-data-storage.spec.md)
