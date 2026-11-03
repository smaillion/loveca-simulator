# Ruleset 对局身份与只读 Replay 验证

## 2026-11-04：数据库初始化的事务边界

本地完整检查两次超时后，受控剖析发现卡库和对局库初始化有逐条DDL提交开销。
先复现初始化脚本末尾出错后仍残留表或改写user_version的问题，再将两处初始化放入单个
`BEGIN IMMEDIATE` 事务；连接上下文成功提交、异常回滚。连接建立时原有foreign_keys设置仍在事务外生效。
不改schema SQL、版本号、既有数据或数据库迁移规则；不缓存初始化成功，不跳过已存在库的检查/修复。
不改变journal_mode或synchronous，也不修改RoomRepository及生产数据库。

工程验证覆盖新库/已有库失败回滚、旧版/缺失/非法版本拒绝、重复与并发初始化、锁冲突后重试、
缺失索引重建、约束/结构完整性和单事务轨迹。受控交替10次新建库中，卡库中位数220ms到10ms、
对局库59ms到8ms，全部结构导出相同；局部测量不是全套性能保证。
证据入口 `logs/end-phase-planning-20261102/schema-initialization/`，同源码完整门禁/提交状态以其中最终记录为准。
这属于工程契约，不新增规则场景、reviewed卡或75项完成计数；未上线。

后续更新：等待房间的创建时版本固定与元数据清理已完成，见[后续报告](./room-ruleset-lifecycle-verification.md)。
下文保留本批当时的范围和待办，不代表最新房间状态。

## 本轮范围

从旧 v0.9 工作树只读比对后，选择性接回三个Match字段，不全量合并旧实验。
旧原型仅附加Replay metadata；本轮另补真正的运行校验和只读导出。
固定分支 `codex/continuous-development`，同一Draft PR #54，不合并、不部署。
卡库和技能登记不变：**900/1212（74.26%），312 manual**。

规则来源仍为本地综合规则ver.1.06，Profile `loveca-ja-1.06`，
ruling pack `comprehensive-only-v1`。PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
本批是版本身份和运行安全契约，**不是新增规则矩阵场景、技能适配或人工裁定**。

## 用户可见变化

- 新对局保存规则ID、规则指纹和裁定包版本；省略ID的旧请求仍用当前Profile。
- `POST /api/matches` 提供未知或非当前Profile时，在创建数据前拒绝。
- 不兼容的对局仍可查看和导出，界面有中日只读提示，不再给出可提交操作。
- 直接提交Action也返回409 `ruleset_mismatch`，不能绕过界面继续改变旧对局。
- 不兼容Replay导出保留原始动作、事件和最终快照，**不调用引擎重新执行**。
  `deterministic_replay_verified=false`，不是把保存的快照伪装为计算结果。
- 没有这些字段的旧快照仍省略它们，hash不变；同rule_version可保留旧重放路径，
  但明确为 `legacy_unpinned`、`ruleset_identity_verified=false`，不补写当前身份。

## 真实状态与 SQLite 验证

`tests/test_match_ruleset_binding.py`：22项专项，包含真实MatchService动作和SQLite Replay。
`tests/test_webapp.py` 新增3项API验证并扩展既有room全流程；前端增加1项中日提示测试。

| 场景 | 实际断言 |
|---|---|
| 默认 / 显式当前Profile开局 | 保存相同身份，完成换牌Action后SQL Replay一致 |
| 未知 / 已归档Profile | 写入前拒绝，runtime所有行不变 |
| 当前Profile改为引擎不支持的规则版 | 即使snapshot身份完全吻合，也拒绝开局与重执行 |
| 旧快照缺省字段 | 不补写身份，序列化和hash稳定，保留旧调用 |
| 指纹、ID、rule_version、裁定包不同 | Action不能进入引擎，数据库完整dump不变 |
| 只有部分规则字段 | 不把不完整身份当作legacy，明确只读 |
| 起始 / 最终身份不同 | 不重执行，不标记验证成功 |
| 当前来源PDF hash变化 | 即使版本名相同，也拒绝按新规则执行旧Match |
| CompatibilityFingerprint | 三个规则身份字段分别比较；旧身份不静默升级 |
| 已加入的联机房间 | Host/Guest共享身份，仍只能看到各自手牌 |
| 不兼容的联机房间 | 双方均无可提交Action；409拒绝、只读Replay可下载 |
| SQLite结构 | schema SQL前后完全相同；未引入新列或迁移 |

此前专项组合83项和App组件95项已通过，另补本地只读API和引擎版本边界断言；全量工程证据由协调器保存，不用脚本检查代替人工规则复核。

## 固定 AI 回归

20套牌池，seed12000..12009，显式 `simple_ai_v1_2`，600 action cap。
10/10正式完赛，10/10均在10回合内且双方有成功Live；无blocker、skip或Replay序列化错误。
策略默认仍v1.1，本轮不改变策略或宣称强度提升。

| 局 | 回合 | P1 / P2成功Live |
|---:|---:|---|
| 1 | 3 | 2 / 3 |
| 2 | 6 | 1 / 3 |
| 3 | 5 | 3 / 1 |
| 4 | 6 | 3 / 2 |
| 5 | 9 | 1 / 3 |
| 6 | 4 | 2 / 3 |
| 7 | 9 | 2 / 3 |
| 8 | 5 | 1 / 3 |
| 9 | 7 | 3 / 2 |
| 10 | 6 | 3 / 2 |

原始报告：`logs/continuous-ruleset-binding-ai10-20261026/`，保持ignored，不上传私有日志。
这是运行兼容性回归，不宣称本轮重新逐条人工审计了这10局。

## 本批结束时未完成（历史）

- 等待加入的room目前在Guest加入、创建Match时才固定当前Profile。
  创建到加入期间的Ruleset变化检测另留父任务，不能将版本信息混入decklist，
  也没有复制旧工作树的 `hosted_rooms ALTER TABLE`。
- ≥75核心规则场景、≥20 Live边界及End Phase重复检查继续排队，不计为已通过。
- 完整重叠/继承语义和六张manual登场卡仍保留unresolved reason，未用版本工作提升覆盖率。
- 旧44项和6项dirty文件、ignored报告均未修改或删除；未启用Cloud、睡眠或生产配置变更。
