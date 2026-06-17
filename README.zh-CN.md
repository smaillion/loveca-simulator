# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

这是一个面向 Love Live! Series Official Card Game（ラブカ）的本地卡牌数据库、牌组分析与规则验证工具。

项目始终以官方日文资料为唯一权威来源。内部英文标识只用于工程实现，不替代官方日文术语。

## 当前状态

`v0.76` 当前已收录:

- 正式官方 `card_list` 卡牌 importer
- 避免 `＋` / `+` 混用的卡号正规化
- SQLite Schema v2 本地卡牌数据库
- 带本地保存能力的 Deck Builder
- 基于 `decklist.v0` 的 Deck Analyzer
- FastAPI + React SPA 可视化规则验证器
- 可回放的 Action-only GameState
- 925 条 effect registry entry
  - 628 条为 `test_validated_executable`
  - 297 条为 timing prompt / 未支持处理用 `manual_resolution`
- 面向未来低成本 online 同步的 state hash / compatibility metadata 基础
- Hosted Online MVP 房间 API
  - 通过 room code 创建 / 加入房间
  - 使用 HTTP polling 同步状态
  - 服务端复用 Python Rule Engine
  - 临时 room 默认 24 小时过期
- 锁版本权威卡牌 SQLite
  - CI、Docker 和 Pages data export 使用仓库内 `data/loveca.sqlite3`
  - `data/loveca-db-manifest.json` 记录 DB / effect registry 指纹
- GitHub Pages browser preview 用静态 SPA 发布 workflow
  - preview data package 只包含解析后的卡牌 / 技能数据
  - 不打包卡图文件，牌面图片走官方 `image_url`
  - 首次启动时在 browser localStorage 中生成 5 个合法的 `decklist.v0` preview sample deck
  - 支持 decklist.v0 JSON 导入 / 导出

当前开发主线:

- Roadmap 上当前集中在 Phase 5 Effect DSL / 结构化技能执行。
- Phase 1 / 2 / 3 已基本实现，进入维护和改善阶段。
- Phase 4 的 Human-vs-Human 验证器和 Phase 7 的 UI 已提前完成大部分。
- Phase 9 / 10 的低成本 online 验证会和 Phase 5 并行提前推进。
- Simple AI、AI-vs-AI、Monte Carlo 和胜率引擎已降为最低优先级。

当前规则验证器已覆盖:

- 先后攻、起手、调度、初始 Energy
- Member 登场、满位替换、`バトンタッチ`
- Live Set、等量补抽、Live 公开、应援
- Heart 分配、部分特殊 Blade Heart 自动处理
- 成功 Live 移动、下一回合先攻判定、3 张成功 Live 胜负
- 少量技能支持包含手牌 / Energy / Stage Member / Heart 颜色 / 牌堆顶检查的限定结构化 prompt
- 部分双方都需要选择的效果已可通过 multi-player pending choice 顺序处理
- 支持把 Stage Member 目标拆成多个选择组，并对各组选中目标应用相同的临时 modifier
- 支持每个分支使用不同 Stage Member 候选池的技能选择
- 按 registry entry 计算的 `test_validated_executable` 覆盖率已达到 67.89%
- 暂不能自动执行的技能通过 `ManualAdjustmentAction` 补充
- 无法处理的技能可以用调试用 `effect_skipped_due_to_error` 显式记录后跳过

Deck Builder 当前状态:

- 创建、读取、更新、删除本地保存牌组
- 按 `Member` / `Live` / `Energy` 分区显示已组牌组
- 检查 `Member 48` / `Live 12` / `Energy 12` 的构筑数量
- 按作品、组合、Heart 颜色、Blade、Live 所需 Heart、Score、Blade Heart 筛选
- 在卡牌详情弹窗中选择印刷版本并确认卡图
- 通过 dashboard 查看 cost、Heart、score、特殊 Blade Heart 与技能时点统计

当前还没有:

- 全卡技能自动执行
- 面向全量卡池的完整技能提示覆盖
- AI、Monte Carlo、胜率引擎
- 正式在线运营、账户、用户同步和严格防作弊
- GitHub Pages preview 在打包解析后 data package 时，已经可以不依赖 FastAPI 浏览卡库、使用浏览器本地 deck 保存，并执行 MVP deck 分析。对战只有在 `runtime-config.json` 的 `apiBaseUrl` 指向 Hosted FastAPI 时可用。

## 反馈与约战

Bug 报告、规则行为讨论和 online 对战伙伴寻找请前往 [Discord](https://discord.gg/8uYQH7z8)。报告问题时，请尽量附上版本、运行方式是本地 / Hosted / Pages preview、复现步骤、decklist.v0 JSON、Replay JSON 和截图。

## 已知限制

- 这是开发中的 alpha 版本，不是官方数字客户端。当前目标是规则验证和收集 playtest feedback。
- 还没有覆盖全卡技能自动执行。未支持技能可能需要 `ManualAdjustmentAction`、结构化 pending choice，或用调试 skip 继续推进。
- Phase 5 sandbox 中 `illegal_action` 已显著减少，但长局仍会遇到 `mandatory_manual_resolution` 和 `max_actions`。最新详细数字请看 `CHANGELOG.md` 与 `TODO.md`。
- 依赖 FAQ 或个别裁定的效果尚未规格化。
- `data/loveca.sqlite3` 是仓库内锁版本权威卡牌 DB。官方补充包或 parser/schema/effect registry 变化后，由维护者重建并提交新的 DB 与 `data/loveca-db-manifest.json`；普通用户和 CI 不应自行 import 产生不同线上 DB。保存牌组是 `decklist.v0` 用户数据，可以和卡牌数据库分开保留。
- Web/API 测试依赖 `httpx2`。环境缺少该依赖时，`tests/test_catalog_api.py` 和 `tests/test_webapp.py` 会在收集阶段停止。
- Hosted Online MVP 只用于低成本测试反馈。规则判定由 FastAPI 侧 Python engine 执行，但不包含账号、长期保存或严格防作弊。
- GitHub Pages browser preview 主要用于卡库浏览、Deck Builder、decklist.v0 import / export 和 MVP deck 分析。对战只有配置 Hosted API 时可用。

## UI 功能与使用方式

### 首页 / 开始对局

- 右上角语言切换可在简体中文 UI 和日文 UI 之间切换，选择会保存到 browser localStorage。
- 可以选择已保存牌组，或从 Deck Builder 带回当前编辑中的牌组，创建本地规则验证对局。
- 配置了 Hosted API 的环境可以创建 room code，让 host / guest 分别选择牌组后加入同一个 online room。Online match 中己方盘面始终显示在画面下方，Action Dock 只显示当前 room token 可以提交的操作。
- Browser preview 支持查看已打包卡库、使用 5 个合法的初始 `decklist.v0` sample deck、本地保存牌组、decklist.v0 导入 / 导出和 MVP 牌组分析。对战只有在 runtime config 设置了 `apiBaseUrl` 时才会连接 Hosted API。

### 卡牌目录

- 卡牌目录是只读视图。可以用搜索框、卡牌种类、作品和组合 filter 缩小列表。
- 选中卡牌后可以查看卡图、Cost / Blade / Score、Heart、作品 / 组合、官方效果文本、review candidate 和 source observation。
- 图片优先使用本地 cache 的 `/api/card-images/*`，没有本地图片时 fallback 到官方 `image_url`。

### Deck Builder

- 可以创建、读取、覆盖保存、重命名和删除本地保存牌组。
- 支持 decklist.v0 JSON 导入 / 导出，方便在 browser preview 和本地环境之间迁移牌组。
- 已组牌组按 `Member` / `Live` / `Energy` 分区显示，编辑时会检查 `Member 48` / `Live 12` / `Energy 12` 和同名卡上限。
- 卡牌搜索支持按卡名 / 卡号、卡牌种类、作品、组合、Member 基本 Heart / Cost / Blade / Blade Heart、Live 所需 Heart / Score / Blade Heart 筛选。搜索结果可以按卡号、卡名、卡牌种类、Member cost、Blade、Live 所需 Heart、Live score 和当前投入枚数排序。
- 搜索结果中的卡牌可以打开详情 dialog 查看图片和主要 stat，也可以直接用添加按钮投入牌组。
- 右侧分析 dashboard 会自动刷新，展示构筑合法性、枚数问题、Member cost curve、基本 Heart、Live 所需 Heart、Score、特殊 Blade Heart、技能 timing / execution summary。
- 在 Deck Builder 里选择的牌组可以通过“用于对战”回到首页，并作为本地对局或 online room 的 deck source。

### 规则验证器

- Match 画面同屏展示双方舞台、手牌 / 牌库 / 控室等 zone count、Live / Energy / Heart 状态、当前 phase 和 turn number。
- Action Dock 会列出当前可执行 action，可从 UI 发送 Member 登场、Baton Touch、Live Set、调度、Heart 分配和 pending effect 结算等操作。
- 部分技能以结构化 prompt 显示，可在 UI 中处理目标卡选择、choice branch、inspection / reveal 的排序和移动目标。
- 暂不能自动执行的技能可用 `ManualAdjustmentAction` drawer 手动输入卡牌移动、Heart 修正、Live success 修正和备注，继续推进验证。
- Action/Event Log、Live judgment detail、effect activation summary 和卡牌详情 dialog 可用于确认 rule engine 实际处理了什么。
- 本地 match 和 online room match 支持导出 Replay JSON。Browser preview 单独运行时不支持 Replay export。

## 界面预览

启动页：可直接选择已保存牌组并创建对局。

![启动页](docs/images/home-desktop.png)

Deck Builder：右侧筛选选卡，中央查看构筑与分析结果。

![Deck Builder](docs/images/deck-builder-desktop.png)

规则验证器：同屏查看盘面、Action/Event Log 与人工规则调整。

![规则验证器](docs/images/match-actions-desktop.png)

## 卡牌 DB 与 asset 分发方针

长期来看，可以提供包含预构建 SQLite 卡牌数据库、effect registry、manifest 和 checksum 的版本化 asset package，让用户无需每次从官网全量抓取即可直接启动。

但官方效果文本全文、官方 PDF 派生的大量数据和下载后的卡图文件涉及再分发边界。GitHub Pages preview 的公开 asset 应限制为解析后的卡牌数据、解析后的技能数据、manifest、checksum 和项目自有 metadata；卡图文件不随包发布，牌面显示直接使用官方 `image_url`。

公开 preview 从专用 `preview` 分支发布。这个分支会直接提交已审核的 `data/loveca.sqlite3`，GitHub Pages workflow 从这个 SQLite 导出静态 JSON。`develop` 可以继续高频开发，不会触发 Pages 重建；只有准备更新公开 preview 时才同步到 `preview` 分支。

browser preview 的 deck 保存在 localStorage。Deck 主要只保存卡号和数量，5 个合法的初始 `decklist.v0` sample deck 加上普通用户自己的牌组通常只会占用很小空间。需要迁移或分享时，请使用 Deck Builder 的 JSON 导入 / 导出。

如果向 private tester 提供预构建 DB，也应明确 release version、schema version、parser version、card database fingerprint 和 effect registry hash。任何破坏兼容性的版本更新后，都需要重新导入。

## 变更记录

每个版本的详细变更见 [CHANGELOG.md](./CHANGELOG.md)。

## 目录概览

- `TODO.md`: 低优先级待办
- `src/loveca/cards/`: importer、catalog、图片缓存
- `src/loveca/decks/`: 牌组格式、分析器、本地牌组库
- `src/loveca/simulation/`: GameState、Action、runtime、effects
- `src/loveca/webapp.py`: FastAPI 与 SPA 分发
- `web/`: React 规则验证 UI
- `docs/`, `specs/`: 架构文档与规格
- `docs/14-database-migration-and-update-guide.md`: SQLite 重建、增量更新和 runtime 生命周期指引
- `docs/15-project-guidance.md`: changelog 语言等维护指引
- `docs/16-low-cost-online-battle-plan.md`: 低成本网络双人规则验证模式规划
- `docs/17-browser-only-preview-and-pages-release.md`: GitHub Pages browser preview 与静态数据包计划
- `docs/18-hosted-online-smoke-checklist.md`: Hosted Online MVP 合并 / 部署前 smoke checklist

## 本地搭建与开发命令

### 环境要求

- Python `3.11+`
- Node.js `20` / `22` / `24+`
- SQLite 无需额外安装

安装依赖:

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

### 本地启动

1. 初始化卡牌数据库。

```powershell
loveca cards init --database data/loveca.sqlite3
```

版本更新后如果 importer / parser / schema 有变化，请先备份或删除旧的 `data/loveca.sqlite3`，再按本流程重建卡牌数据库。继续使用旧 DB 可能导致卡号、图片、effect registry 或 online compatibility fingerprint 不一致。

2. 从官网抓取卡牌并生成本地规范化产物。

```powershell
loveca cards import-official `
  --output-root data/imports/official `
  --delay 1
```

3. 将规范化产物导入 SQLite。

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-full.md
```

4. 构建前端。

```powershell
cd web
npm run build
cd ..
```

5. 如需牌面图片，先缓存官方图片。

```powershell
loveca cards cache-images `
  --database data/loveca.sqlite3 `
  --cache-dir data/card_images `
  --delay 1
```

6. 启动 Web UI。

```powershell
loveca web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
```

浏览器访问 <http://127.0.0.1:8765>。

如果 `8765` 已被占用，可以改成 `--port 8766`。

### Docker API 服务器

如果要用 Cloudflare Worker gateway、Caddy 和小型 VM 试运行 Hosted Online MVP，可以只把 FastAPI backend 打成 Docker 镜像运行。

前提：

- 仓库内已经提交锁版本 `data/loveca.sqlite3`
- VPS 只保留 `runtime/` 和 `logs/` 为宿主机持久目录
- 如果 GitHub Pages 要连接这个 API，需要把 Pages 地址写入 `LOVECA_ALLOWED_ORIGINS`

本地 build：

```powershell
docker build -t loveca-simulator-api:local .
```

compose 启动：

```powershell
$env:LOVECA_ALLOWED_ORIGINS="https://smaillion.github.io,http://127.0.0.1:8765,http://localhost:8765"
docker compose -f compose.api.yml up -d --build
```

health check：

```powershell
curl http://127.0.0.1:8765/api/health
```

正式低成本部署推荐使用 Cloudflare Worker `workers.dev` 作为稳定 API gateway，VPS 上用 Caddy 暴露由 secret 管理的 origin hostname 的 `/api/*`，并反代到 `127.0.0.1:8765`。

GitHub Actions：

- `.github/workflows/api-image.yml` 会构建 Docker image。
- Pull Request 只做 build 验证。
- `api-image.yml` 在 push 到 `develop` / `preview` 或手动执行时，会推送 GHCR 镜像 `ghcr.io/smaillion/loveca-simulator-api`。
- `.github/workflows/deploy-api.yml` 在 push 到 `develop` 或手动执行时，会构建 / 推送 GHCR image，并通过 SSH 更新 VPS 上的 compose service。
- `.github/workflows/deploy-worker.yml` 在 `develop` / `preview` 的 Worker 相关文件变更或手动执行时，会更新 Cloudflare Worker gateway。
- `.github/workflows/pages-preview.yml` 在 push 到 `preview` 或手动执行时发布 GitHub Pages preview。
- 当前阶段 push 到 `main` 不触发自动 publish / deploy。接近生产的 release promotion 必须由 maintainer 明确手动执行 workflow，或走专门 release 流程。

部署需要的 GitHub Secrets：

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`
- `API_BASE_URL`
- `LOVECA_ALLOWED_ORIGINS`

如果 GitHub Pages 要连接 Hosted API，请在 repository variable `VITE_PUBLIC_API_BASE_URL` 中设置 Cloudflare Worker URL。

### 常用命令

牌组分析:

```powershell
loveca decks analyze `
  --database data/loveca.sqlite3 `
  --deck data/decks/your-deck.json `
  --output text
```

按补充包增量导入:

```powershell
loveca cards import-official `
  --output-root data/imports/official-bp06 `
  --mode incremental-set `
  --card-set BP06 `
  --delay 1
```

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP06 `
  --report logs/import-bp06.md
```

### 测试

Python:

```powershell
python -m pytest
```

AI sandbox 的 20 deck x 20 match 黑盒 smoke 已纳入 pytest。
没有本地正式卡牌数据库的环境会自动 skip。需要单独生成审查报告时:

```powershell
$env:PYTHONPATH="src;."
python -m tools.ai_sandbox.blackbox_playtest `
  --database data/loveca.sqlite3 `
  --output logs/ai_sandbox/manual-run `
  --decks 20 `
  --matches 20 `
  --manual-policy block
```

使用 `--manual-policy skip` 时，未支持的强制技能会记录为
`effect_skipped_due_to_error` 后继续推进。这个能力只用于规则调试，
不是正式技能结算。

Phase 5 的手动技能验证也可以使用 semantic user-agent sandbox。它用 deterministic
sandbox policy 处理普通行动，只在遇到 `manual_resolution` 技能时调用 semantic
provider，检查当前 `ManualAdjustmentAction` 是否足以让类似人工玩家继续游戏。这个结果
只作为可玩性和 schema gap 信号，不计入 registry coverage。未配置真实 provider 时默认
使用 `mock`，只验证报告流程，不会真正解技能。

```powershell
$env:PYTHONPATH="src;."
python -m tools.ai_sandbox.semantic_playtest `
  --database data/loveca.sqlite3 `
  --output logs/semantic_sandbox/manual-run `
  --decks 30 `
  --matches 20 `
  --max-actions 260 `
  --manual-fallback skip
```

使用 OpenAI-compatible provider 时设置:

```powershell
$env:LOVECA_SEMANTIC_AGENT_PROVIDER="openai_compatible"
$env:LOVECA_SEMANTIC_AGENT_MODEL="..."
$env:LOVECA_SEMANTIC_AGENT_API_BASE="..."
$env:LOVECA_SEMANTIC_AGENT_API_KEY="..."
```

前端:

```powershell
cd web
npm run test -- --run
npm run build
```
