# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

这是一个面向 Love Live! Series Official Card Game（ラブカ）的本地卡牌数据库、牌组分析与规则验证工具。

项目始终以官方日文资料为唯一权威来源。内部英文标识只用于工程实现，不替代官方日文术语。

## 当前状态

补齐 `PL!HS-pb1-009:1` 花帆中心观察者：已触发后因普通替换离场，仍处理能力并计次数，
但不把本次自身 Blade 加成给控室或重新登场的同一卡牌。旧 Replay 不变，非重叠对象追踪仍待审计。
[中文状态 / 限制 / AI 验证](./docs/development/overlap-source-modifier-verification.md)。

新建对局修正 `PL!N-pb1-012` 鐘嵐珠普通替换离场后漏补 Wait Energy 的问题，
包含重叠整理返还附属 Energy 后再补入的边界；无牌可补时明确显示结果。旧 Replay 与登记率不变。
[中文状态 / AI / UI 验证报告](./docs/development/overlap-energy-observer-verification.md)。

新建对局可选择多个待机技能的结算顺序，统一 AP / NAP 优先级并禁止打断已开始的多步处理。
旧 Replay 不变；这不代表完整规则调度已经完成，技能登记率不变。
[中文顺序 / 状态 / AI 验证报告](./docs/development/pending-effect-order-verification.md)。

新建对局修正 `PL!N-pb1-005` 宮下愛被 cost10 Member 普通替换时漏抽1的问题；
Baton 中先作为费用离场的对照不抽。旧 Replay 保留原行为，复杂重叠仍待审计。
[中文状态与兼容性报告](./docs/development/overlap-entry-observer-verification.md)。

受控效果登場底座已支持按条件筛选非公开手牌时明确选零张：费用不退回，旧快照与公开必选目标不变。
这是未登记的底座能力，不代表六张待审卡已经自动适配；复杂重叠仍未完成。
[中文截图与状态验证](./docs/development/private-hand-choice-verification.md)。

修复 `PL!SP-bp5-111:2` / `PL!SP-pb2-010:1` 将 Energy 返回牌库后无法读取保存状态的问题。
旧坏快照不自动改写：返回明确错误，停止前端重试并提示新建对局，不提升技能登记率。
[中文状态 / API / Replay 验证报告](./docs/development/energy-return-replay-verification.md)。

持续开发统一使用 `codex/continuous-development` 和固定工作树，自动接续任务、验证并更新
同一个 Draft PR。入口见[持续开发指南](./docs/21-continuous-development.md)与
[执行流程](./automation/WORKFLOW.md)；合并和部署仍需维护者确认。

已准备 [Codex Cloud 交接入口](./docs/development/codex-cloud-handoff.md)：提供 Linux 初始化、
可移植任务检查点和单写者预检。当前仍由本机执行，云端切换、定时接续及同一 PR 更新待实测；
不复制认证信息，也不迁移或部署生产对战服务。

已从旧工作树迁移综合规则 ver.1.06 的只读 Profile 与 49 条规则引用；未审核 FAQ 不生效。
对局 / Replay 接入和规则矩阵仍在后续队列，来源校验不代表 v0.9 规则门禁完成。
详见[迁移范围与限制](./docs/22-ruleset-source-profile-migration.md)。

Deck Builder 详情中主动选择的卡面不会再被后台数据更新重置；打开其他卡牌时重新初始化印刷版。

API Play 测试工具已隔离对手背面卡与他方私有选择，区分 mock / 真实模型，默认不保存输入样本。
这属于测试底座改进，不计入技能可执行覆盖率。

新增 `PL!-bp5-003:2` 起动能力的结构化处理：根据实际弃牌决定查看 4 张选 2 张，或回收
控室 Live。待查看卡不向对手画面 / AI 暴露，费用选择与后续选择之间会重置 UI。
[中文验证记录](./docs/development/cost-result-branch-verification.md)

`PL!-PR-015` / `PL!SP-PR-020` 仅在确实从较低费用 Member Baton 入场时显示手动技能提示。
两张卡仍为手动处理，暂不把不完整的区域 / 朝向选择登记为自动支持。
[中文审计报告](./docs/development/baton-hand-deploy-audit.md)
已逐项复核 10 条旧效果登场：6 条明确空区域的技能改为 Active 登场并支持位置选择；
4 条不限定空区域的虹咲技能退回手动处理，等待合法替换区域底座。旧 Replay 朝向不变。
[本轮验证及限制](./docs/development/empty-effect-deployment-verification.md)。登记率不代表规则正确率。

新建对局的本回合登场区域限制现按 Member 卡的当前位置判断：Position / Formation Change 后，
限制不会错误地留在旧区域；本回合从 Stage 外放入下方的 Member 卡也会随组追踪。
旧 Replay 保留原行为；本轮不提升技能登记率。[验证记录](./docs/development/member-entry-area-history-verification.md)

修正 `PL!-bp6-003:2` 从下方移到空区域时额外触发登場能力、增加次数的问题。新技能快照区分
Area 内转移与外部登場，旧 Replay 保留原结果；结算面板显示中文 / 日文说明。
[状态验证及后续缺口](./docs/development/attachment-promotion-verification.md)，不增加虚假覆盖率。

修正 `PL!-pb1-018:1` 双方控室登場漏触发能力的问题：双方先选卡与空区域，再同时 Wait 登場，
父技能结束后处理触发效果。补齐多人选卡 / 区域 UI，保留旧 Replay 结果。
[中文状态验证报告](./docs/development/multi-player-entry-verification.md)，本轮不增加登记率。

已有 Member 区域的效果登場已增加受控执行底座，但复杂重叠触发和私有手牌选择仍未完成；
两张 PR 卡及四张虹咲卡继续手动处理，不增加登记率。
[本轮验证范围与新发现的 Replay 缺口](./docs/development/occupied-deployment-foundation.md)已记录。

`develop`（下一版 `v0.9`）当前已收录:

- 基于官方 `card_list` JSON API 的正式卡牌 importer
- 避免 `＋` / `+` 混用的卡号正规化
- SQLite Schema v2 本地卡牌数据库
- 带本地保存能力的 Deck Builder
- 基于 `decklist.v0` 的 Deck Analyzer
- FastAPI + React SPA 可视化规则验证器
- 可回放的 Action-only GameState
- 包含 2026-10-24 发售的 `CLLS01`，以及 `PBLL02` / `BP07` / `NSD02` 的锁版本卡牌数据库
  - 1,977 条 Gameplay Card / 2,700 个印刷版本 / 1,246 条文本修订 / 24 个 Card Set
  - importer 优先使用官方 products API，不会把尚未公开卡表的未来商品或 unit filter 误当成卡包
- 1,212 条 effect registry entry
  - 899 条（74.17%）为 `test_validated_executable`
  - 313 条为 timing prompt / 未支持处理用 `manual_resolution`
  - 新卡包中发现的未支持技能也会显式登记为 manual，避免静默跳过
- 面向未来低成本 online 同步的 state hash / compatibility metadata 基础
- Hosted Online MVP 房间 API
  - 通过 room code 创建 / 加入房间
  - 使用 HTTP polling 同步状态
  - 服务端复用 Python Rule Engine
  - 临时 room 默认 24 小时过期
  - server 预计每天 JST 04:00 自动重启并整理 runtime cache
- 锁版本权威卡牌 SQLite
  - CI、Docker 和 Pages data export 使用仓库内 `data/loveca.sqlite3`
  - `data/loveca-db-manifest.json` 记录 DB / effect registry 指纹
- GitHub Pages browser preview 用静态 SPA 发布 workflow
  - preview data package 只包含解析后的卡牌 / 技能数据
  - 不打包卡图文件，牌面图片走官方 `image_url`
  - 首次启动时在 browser localStorage 中生成 5 个合法的 `decklist.v0` preview sample deck
  - 支持 decklist.v0 JSON 导入 / 导出

当前开发主线:

- Roadmap 当前让 Phase 5 进入维护，同时推进 Phase 6 官方规则符合性与结构化技能准确度。
- Phase 1 / 2 / 3 已基本实现，进入维护和改善阶段。
- Phase 4 的 Human-vs-Human 验证器和 Phase 7 的 UI 已提前完成大部分。
- Phase 9 / 10 的低成本 online 验证会和 Phase 5 并行提前推进。
- Simple AI v1.1 已可在 local / Hosted FastAPI 中使用，会基于 Rule Engine 的评估值对 Member、Live 和结构化技能进行 deterministic 评分；旧 Replay 仍保留 v0 / v1 policy。MCTS、Monte Carlo、学习型 AI 和胜率引擎不在本轮范围。

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
- 按 registry entry 计算的 `test_validated_executable` 覆盖率为 74.17%（899 / 1,212）。未适配新技能和审计发现不准确的旧登场效果均明确标为 manual，不靠错误登记维持数字
- `PBSP02` 相关技能 74 条中 63 条已结构化，新补充包覆盖率确认达到 85.14%
- 追加结构化支持 μ's / Aqours / Saint Snow / Nijigasaki / Hasunosora / Edel Note 的部分控室回收、Energy ready、牌堆顶检查、应援公开条件和带手牌成本的 Live 开始时效果
- static Heart / Blade 等常时效果现在只会在 operation 侧条件满足时计入
- `PBSP02` 集中 block sandbox 为 `30 decks x 20 matches` 中 19 局完走，`mandatory_manual_resolution = 0`，剩余 1 局为 `max_actions:match_point_players_have_no_live_in_hand`
- Phase 5 broad black-box sandbox 已在 `30 decks x 100 matches` block mode 中达到 `100/100` 完走，blocker 为 0
- 最新 skill-dense Simple AI regression 为 `30 decks x 100 matches` 100/100 完赛，blocker / silent skip / Replay error 均为 0
- 之前问题卡 targeted sandbox 中的 `PL!S-bp6-001:1` / `PL!S-pb1-001:1` 已完成结构化；剩余 313 条未支持技能通过 gap report 记录原因
- 已结构化 `LL-bp5-002:1`：Stage 上存在 3 名不同组合的 Member 时，中心 Member 获得持续到本次 Live 结束的任意色 Heart
- 2026-10 全量同步后，基于官方综合规则 ver.1.06 的 AI 逐 Action 审计为 20/20 完赛，13/20 满足“10 回合内且双方至少各成功一次 Live”；共 13,539 条检查，Replay error / effect-error skip 均为 0
- 最新 30 deck / 50 match black-box run 中 executable effect 为 314/314、skipped effect 为 0、Replay error 为 0；34 局完赛，剩余 16 局因 Live 获取或长局策略达到 action cap，作为 AI 策略问题而非非法规则操作追踪
- Live 判定另有 9 个固定边界门禁，分别审计 Live 成功、本轮胜者、Match Point 时的成功 Live 移动资格及最终胜负
- 触发时条件满足的 pending effect 如果在同一时点中被其他效果改变条件导致失效，会记录明确的 `effect_not_activatable` event 并继续推进
- 公开并加入手牌的效果会在对手侧履历中保留公开卡名，方便联机复盘
- 现在提供 60 个日文 / 中文人类可读技能验证场景，其中 21 个会实际验证 GameState 状态变化
- Simple AI v1.1 / v1 的 200 局镜像 benchmark 为 200/200 完赛、v1.1 积分率 54%、平均 8.38 回合、P95 14 回合、单次决策 P95 6.975 ms、illegal action / Replay error 均为 0；19 次未支持技能均显式记录为 skip，没有静默处理，55% 强度目标尚未达到
- 使用 `amount_source=selected_count` 的效果已支持按选中张数抽牌
- `PL!HS-bp6-006` 已结构化支持手牌中 cost reduction、非みらくらぱーく！Baton replacement 限制、Live 成功时 Wait + 下一 Active Phase 不转 Active
- `PL!HS-bp6-014:1` 等从手牌发动的效果，在没有目标 Stage Member 时也会处理成本和抽牌，只把目标 modifier 空结算
- 两段式技能会在进入后续选择时记录 `effect_choice_started` event，方便 UI、Replay 和 sandbox report 确认当前是在等待技能后续选择
- local / Hosted FastAPI 可以把 Player 2 设为 `simple_ai` 创建对电脑战。AI 只从 LegalAction 中选择，并在 event / replay 中记录选择理由
- Simple AI 验收已使用 20 套牌完成 Human-vs-AI 20 局 + AI-vs-AI 20 局，结果为 `40/40` 完整结束、blocker 0、Replay error 0
- 电脑无法安全处理操作或达到连续 action 上限时，会把来源卡、技能时点等信息作为 `ai_blocked` event 写入 runtime 与 Replay，UI 可引导到当前可处理操作
- 暂不能自动执行的技能通过 `ManualAdjustmentAction` 补充
- 无法处理的技能可以用调试用 `effect_skipped_due_to_error` 显式记录后跳过

Deck Builder 当前状态:

- 创建、读取、更新、删除本地保存牌组
- 画面内折叠式 manual 可说明搜索、加入牌组、构筑条件、分析、保存、分享和进入对战的流程
- 按 `Member` / `Live` / `Energy` 分区显示已组牌组
- 检查 `Member 48` / `Live 12` / `Energy 12` 的构筑数量
- 按作品、组合、Heart 颜色、Blade、Live 所需 Heart、Score、Blade Heart 筛选
- 在卡牌详情弹窗中选择印刷版本并确认卡图
- 通过 dashboard 查看 cost、Heart、score、特殊 Blade Heart 与技能时点统计

当前还没有:

- 全卡技能自动执行
- 面向全量卡池的完整技能提示覆盖
- 强 AI、Monte Carlo、胜率引擎
- Simple AI 当前是优先保证合法性和流程推进的 deterministic policy，不保证对战强度或最优操作
- 正式在线运营、账户、用户同步和严格防作弊
- GitHub Pages preview 在打包解析后 data package 时，已经可以不依赖 FastAPI 浏览卡库、使用浏览器本地 deck 保存，并执行 MVP deck 分析。对战只有在 `runtime-config.json` 的 `apiBaseUrl` 指向 Hosted FastAPI 时可用。

## 反馈与约战

Bug 报告、规则行为讨论和 online 对战伙伴寻找请前往 [Discord](https://discord.gg/8uYQH7z8)。报告问题时，请尽量附上版本、运行方式是本地 / Hosted / Pages preview、复现步骤、decklist.v0 JSON、Replay JSON 和截图。

## 已知限制

- 这是开发中的 alpha 版本，不是官方数字客户端。当前目标是规则验证和收集 playtest feedback。
- 还没有覆盖全卡技能自动执行。未支持技能可能需要 `ManualAdjustmentAction`、结构化 pending choice，或用调试 skip 继续推进。
- 当前明确保留 313 条 `manual_resolution`；未在测试池触发或语义复杂的技能仍需人工处理，最新分类见 `docs/13-effect-semantics-audit.md` 与 `TODO.md`。
- `BP07` 的 `無2` 特殊 Blade Heart 无法仅凭综合规则 ver.1.06 确定语义，因此不会猜测实现，当前保持未支持状态。
- 依赖 FAQ 或个别裁定的效果尚未规格化。
- `data/loveca.sqlite3` 是仓库内锁版本权威卡牌 DB。官方补充包或 parser/schema/effect registry 变化后，由维护者重建并提交新的 DB 与 `data/loveca-db-manifest.json`；普通用户和 CI 不应自行 import 产生不同线上 DB。保存牌组是 `decklist.v0` 用户数据，可以和卡牌数据库分开保留。
- Web/API 测试依赖 `httpx2`。环境缺少该依赖时，`tests/test_catalog_api.py` 和 `tests/test_webapp.py` 会在收集阶段停止。
- Hosted Online MVP 只用于低成本测试反馈。规则判定由 FastAPI 侧 Python engine 执行，但不包含账号、长期保存或严格防作弊。
- Hosted API 的 runtime DB 是临时数据。默认只保留最近 25 局 match history 和每局最近的少量 snapshot，并在每天 JST 04:00 自动重启时执行 cleanup。如果 online room 被中断，请重新创建房间。
- 公开 Hosted API 不显示全局 match history。单人模拟 match 会依靠创建浏览器 localStorage 中保存的 access token 恢复。管理员 runtime 查看 / cleanup API 需要 `LOVECA_ADMIN_KEY`。
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
- 画面顶部的“Deck Builder 使用说明”会说明搜索、加入牌组、构筑条件、分析、保存、分享和进入对战的流程。
- 支持 decklist.v0 JSON 导入 / 导出，方便在 browser preview 和本地环境之间迁移牌组。
- 已组牌组按 `Member` / `Live` / `Energy` 分区显示，编辑时会检查 `Member 48` / `Live 12` / `Energy 12` 和同名卡上限。
- 卡牌搜索支持按卡名 / 卡号、卡牌种类、作品、组合、Member 基本 Heart / Cost / Blade / Blade Heart、Live 所需 Heart / Score / Blade Heart 筛选。搜索结果可以按卡号、卡名、卡牌种类、Member cost、Blade、Live 所需 Heart、Live score 和当前投入枚数排序。
- 搜索结果中的卡牌可以打开详情 dialog 查看图片和主要 stat，也可以直接用添加按钮投入牌组。
- 右侧分析 dashboard 会自动刷新，展示构筑合法性、枚数问题、Member cost curve、基本 Heart、Live 所需 Heart、Score、特殊 Blade Heart、技能 timing / execution summary。
- 分享 UUID 只会把当前牌组临时上传到 server；别人用 UUID 下载后才会写入自己的本地保存列表。普通保存牌组仍然保存在各自浏览器或本地环境中。
- 在 Deck Builder 里选择的牌组可以通过“用于对战”回到首页，并作为本地对局或 online room 的 deck source。

### 规则验证器

- Match 画面同屏展示双方舞台、手牌 / 牌库 / 控室等 zone count、Live / Energy / Heart 状态、当前 phase 和 turn number。
- 手机端会放大显示己方手牌卡面；Member 登场通过卡牌下方的登场候选按钮、区域选择和确认按钮提交。点击卡牌本体仍用于查看详情。成功 Live 进度、Live 判定和对手区域可通过弹窗查看。
- Live 判定弹窗内可以直接继续下一步。开始下一回合时会关闭弹窗，不再停留在无意义的结束画面。
- 初始调度使用和 Member 登场相同风格的卡牌选择 + 确认操作，减少误触。
- Action Dock 会列出当前可执行 action，可从 UI 发送 Member 登场、Baton Touch、Live Set、调度、Heart 分配和 pending effect 结算等操作。
- 部分技能以结构化 prompt 显示，可在 UI 中处理目标卡选择、choice branch、inspection / reveal 的排序和移动目标。
- 暂不能自动执行的技能可用 `ManualAdjustmentAction` drawer 手动输入卡牌移动、Heart 修正、Live success 修正和备注，继续推进验证。
- Action/Event Log、Live judgment detail、effect activation summary 和卡牌详情 dialog 可用于确认 rule engine 实际处理了什么。
- 本地 match 和 online room match 支持导出 Replay JSON。Browser preview 单独运行时不支持 Replay export。

## 界面预览

PC 启动页：可直接选择已保存牌组并创建对局。

![PC 启动页](docs/images/home-desktop.png)

PC Deck Builder：右侧筛选选卡，中央查看构筑与分析结果。

![PC Deck Builder](docs/images/deck-builder-desktop.png)

PC 规则验证器：同屏查看盘面、Action/Event Log 与人工规则调整。

![PC 规则验证器](docs/images/match-actions-desktop.png)

手机 Deck Builder：卡牌搜索使用弹窗，竖屏下也能查看筛选条件并加入牌组。

![手机 Deck Builder](docs/images/deck-builder-mobile.png)

手机规则验证器：以己方盘面和手牌为中心，登场确认和手动调整入口保持小型化。

![手机规则验证器](docs/images/match-actions-mobile.png)

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
- `docs/19-ai-rule-conformance-and-strategy-audit.md`: AI 对战与官方规则符合性审计基准
- `docs/20-ai-dlc-development-workflow.md`: AI-DLC 开发、审批和 vendor 更新流程

## 本地搭建与开发命令

### 环境要求

- Python `3.11+`
- Node.js `20` / `22` / `24+`
- Bun（仅使用 AI-DLC workflow 的开发者需要）
- SQLite 无需额外安装

安装依赖:

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

需要使用 AI-DLC 时：

```powershell
npm install -g bun
python scripts/aidlc_vendor.py verify
bun .codex/tools/aidlc-utility.ts doctor
```

在新的 Codex 会话中检查 `.codex/hooks.json` 并确认 hook trust，然后使用
`$aidlc compose "改动内容"` 开始。完整流程见
`docs/20-ai-dlc-development-workflow.md`。

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
  --output-root data/imports/official-bp07-nsd02 `
  --mode incremental-set `
  --card-set BP07 `
  --card-set NSD02 `
  --delay 1
```

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP07 `
  --card-set NSD02 `
  --report logs/import-bp07-nsd02.md
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

如果希望让两个 semantic agent 连普通行动也一起选择，可以使用 `--two-agent`。
该模式会用 `pypdf` 抽取 `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，并且只把当前操作玩家
能看到的非公开信息放进 provider context。未配置真实 provider 时，`mock` 不会选择普通行动，
只会通过 deterministic fallback 验证流程和报告格式。

```powershell
$env:PYTHONPATH="src;."
$env:LOVECA_SEMANTIC_AGENT_PROVIDER="openai_compatible"
$env:LOVECA_SEMANTIC_AGENT_MODEL="..."
$env:LOVECA_SEMANTIC_AGENT_API_BASE="..."
$env:LOVECA_SEMANTIC_AGENT_API_KEY="..."
python -m tools.ai_sandbox.semantic_playtest `
  --database data/loveca.sqlite3 `
  --output logs/semantic_sandbox/two-agent-large `
  --decks 30 `
  --matches 100 `
  --max-actions 360 `
  --manual-fallback skip `
  --two-agent `
  --play-fallback deterministic
```

如果想用更接近人工审查的形式确认单个 effect，可以生成 effect verification report。
它会输出日文主报告、中文报告和 JSON summary，并把本地卡库中能查到的官方图片 URL
嵌入 Markdown。当前固定验证本分支重点修正的 `PL!HS-bp6-014` 手牌发动、
`PL!HS-bp6-006` 登场 cost / Live 成功时处理、`PL!HS-bp2-026` score modifier、
Baton Touch 二次登场阻止，以及 `PL!HS-sd1-005` 同名 Baton 条件。

```powershell
$env:PYTHONPATH="src;."
python -m tools.ai_sandbox.effect_verification_report `
  --output logs/effect_verification/manual-run
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
