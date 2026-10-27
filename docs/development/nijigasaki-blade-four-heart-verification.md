# Fire Bird：有效Blade至少4的虹咲目标

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-026-P.png" width="160" alt="Fire Bird PL!N-sd2-026">

## 精确支持范围

`PL!N-sd2-026:1`，revision958，官方日文全文hash：
`8b847fb338647ea95bba010ac586cf3e5880289f44ee9a5a0de0c4119ffa0ebb`。

> 【ライブ開始時】自分のステージにいる【ブレード】を4つ以上持つ『虹ヶ咲』のメンバー1人は、ライブ終了時まで、【heart02】【heart02】を得る。

只匹配完整段落，不按卡名或“4 Blade”前缀批量登记。
从原manual占位新增受限`public_nijigasaki_blade_four_heart`策略：
必须选择一名当前有效Blade至少4的己方虹咲Stage顶层Member；完全无候补时明确选择0。
只给所选对象两颗Heart02，不能回退来源Live，不影响其他成员。
本段917→918/1212（75.74%），295→294manual；未提升`reviewed_executable`。

## PDF规则核对

固定本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
阅读第2/3/10/11页相关完整条文，查看第11页原版排版，不重新抓取官网或猜测FAQ。

- `2.8.1`、`2.8.2`：读取Member的Blade信息，不把Blade Heart或玩家级额外应援数量当成该Member的Blade。
- `9.9.1.1`、`9.9.1.4`、`9.9.1.5`：按现有共享引擎读取基础/已支持信息替换和有效加减修正；不是仅看卡面印刷Blade。
- `9.6.3.1`、`9.6.3.1.3`：有候补必须选1；完全无候补时目标效果不适用，记录理由后结束待机。
- `9.7.3`：同一玩家可决定待机处理顺序，因此其他能力改变Blade后，应重新生成当前候补。
- `11.5.2`、`8.4.11`、`9.9.2`：Live期限清理，目标离场后同ID回来不继承已经给予的修正。

审计发现旧通用`minimum_blade`候补过滤只包含基础信息与目标临时修正，没有常时Blade。
本批仅新policy改用现有`_effective_member_blade`共享规则视图，包含已支持常时修正。
旧policy/旧快照保留原过滤，防止静默改变旧Replay；专项明确比较两条路径。
这不表示复杂continuous/replacement语义已经全部支持，也没有登记任何新replacement技能。
无法确认的常时依赖、继承能力和FAQ仍保留manual。

## 真实状态断言

55项专项通过，连同旧指定姓名Blade和另一虹咲Heart回归共148项通过。

| 场景 | 期望与实际断言 |
|---|---|
| Blade3/4/5，Active与Wait | 3不选；4/5可选，状态不改变目标资格 |
| 基础3+临时1、基础3+常时1、基础2+临时1+常时1 | 当前4，均可选择 |
| 基础5-临时2、基础5-常时2、基础4-临时2+常时1 | 当前不足4，不可选择 |
| 玩家级Blade应援+20 | 不充当成员自身Blade，不让基础3通过 |
| 已支持的基础Blade信息替换 | 按共享引擎当前值判断，不按旧印刷值 |
| 非虹咲/对方/附属/手牌/Live/未知ID/重复/多选/有候补选0 | 原子拒绝，输入hash不变 |
| 无候补 | 明确结束，记录`no_legal_stage_member_at_resolution`，来源不获得Heart |
| 两名合法候补 | 必须显式选其中一名，仅所选对象获得两颗Heart02 |
| 原生待机能力先给Blade3+1或Blade4-1 | 另一待机的候补实时变为可选或不可选 |
| 待机后其他原生人工能力移走目标 | 不可继续选择；回到Stage的新对象可在此时被重新选择 |
| Heart给予后离场回场 | 新对象不继承旧修正 |
| Live结束 | Heart期限修正清理 |
| 第二玩家控制 | 只选择第二玩家自己的合法目标 |
| 四AI、有/无候补、隐藏手牌身份替换 | 只执行当前LegalAction，选择一致，不泄露对方手牌 |
| 新自动与旧manual SQLite Replay | 确定性重放及最终状态hash一致 |

3项前端实际交互覆盖无候补、单候补、多候补，服务器决定候补，UI不重复计算Blade。
双语图文187项全部通过：149状态/边界、38登记契约；新增4项附规则条款。
这些自动断言不替代完整人工裁判审核。

## 冻结30局诊断

原30套合法技能密集牌组、seed18000–18029、`simple_ai_v1_2/block`、最多500动作不变。

| 指标 | 前批 | 本批 |
|---|---:|---:|
| 正式完赛 |8|9|
| 明确mandatory manual停止 |22|21|
| 可执行待机完成 |150/154|158/160|
| 其他manual后保留的可执行待机 |4|2|
| 非法动作/runtime/Replay/错误skip |0/0/0/0|0/0/0/0|

原seed18009/18018各有一次本段强制manual，均停在第3回合。
本批本段两次入队、无manual/错误skip；18009推进至第5回合另一manual，
18018第6回合正式结束，但败方成功Live为0，不能冒充双方均完成Live的验收。
整体尚未达到v0.9发布门禁；不能把98.75%的可执行待机完成率写成全技能100%。

provenance与30局摘要逐一一致，诊断源码指纹：
`2112d434606f7dfff4eba842211345cc36ec67949b6a59b7cdf7f56f44fcd44e`。
剩余manual共89次入队、65次可选辞退、23个强制待机（21局，可同局多个），完整top40保存在`gaps/`。

## 复现与下一项

```powershell
python -m pytest tests/test_nijigasaki_blade_four_heart.py tests/test_named_live_blade.py tests/test_other_nijigasaki_heart.py -q
python -m tools.ai_sandbox.effect_verification_report --database data/loveca.sqlite3 --output logs/nijigasaki-blade-four-final-20261026/verification
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --output logs/nijigasaki-blade-four-final-20261026/final-frozen-30 --deck-directory logs/continuous-manual-focus-30-bound-20261026/decks --decks 30 --matches 30 --manual-policy block --policy simple_ai_v1_2 --seed-base 18000 --max-actions 500
```

最终control/registry/backend/web及manifest/pre-push证据由协调器绑定源码保存。
后续只读审计定位到既有`PL!S-bp3-025:1`登记仍用`minimum_blade=6`及通用`modify_score`，
而官方正文是先选一名Aqours、再判断Blade，且只改来源Live分数。
本批没有改动这一旧登记，也不能用本批55项测试为其背书。
已将其真实复现与精确校正排为下一最高优先级，先于新增覆盖；旧Replay不可静默重写。
之后再审计`PL!-pb2-041:2`成功Live区lily white两张时仅来源Live score+1，
区分unit/work并保留第一段manual，不批量晋级其他复杂技能。
默认AI仍v1.1，不改Card/SQLite schema，不读取GPT认证或调用付费模型API。
同一Draft PR54，不合并部署；旧44/6 dirty、ignored报告和未确认语义保留。
