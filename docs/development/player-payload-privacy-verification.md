# 在线玩家响应：牌库与历史隐私验证

## 问题复现

上一批提交`3be69fb`已确认：从对手视角调用完整MatchPayload时，
`opponent_deck_card_identity_present=True`且`opponent_deck_order_id_present=True`。
只隐藏手牌卡图和pending选项不足以保护牌库；完整技能定义还会暴露未公开卡牌组成，
进行中的完整Replay包含initial/final snapshot和真实seed，能绕过响应层过滤。

## 修正后的可见范围

| 内容 | 在线玩家响应 | 本地可信调试 / 原始Replay |
| --- | --- | --- |
| 双方Main/Energy Deck | 只保留枚数，列表为非真实ID占位，不附卡面与排序映射 | 原始内容保留 |
| 己方手牌/结构化检查 | 当前合法可见卡与真实可操作ID | 保留 |
| 对手手牌/背面Live | 数量及非真实ID占位 | 保留 |
| Stage/附属/Energy/控室/成功Live | 公开内容保留 | 保留 |
| 显式reveal事件 | 保留当时公开的卡片快照，不自动授权当前牌库身份/位置 | 保留 |
| 对手换牌/多人私有选择 | 不输出候选选项 | 保留 |
| 私有检查/排序/抽牌历史 | 隐藏ID/排序和匹配候选数，保留公开数量与公开结果 | 原始事件保留 |
| 未公开卡牌技能定义 | 不输出；已见卡及待处理能力保留 | 完整保存 |
| seed | 返回0占位，不能用于复现 | 真实seed保留 |

这些响应是只读玩家视图，不是可以直接拿来重放或计算权威state hash的完整MatchState。
占位符不是真实卡ID；将它提交为卡牌选择会被引擎拒绝，revision与runtime不变。
引擎、Card Schema、SQLite schema、decklist及Registry均未改变。

## Replay与兼容性

在线完整Replay仅在`phase=complete`或room已expired/关闭时允许下载。
进行中的请求返回409，前端显示带中日说明的禁用下载图标；完赛后恢复下载。
旧规则指纹不匹配但尚未结束的room也不例外，可明确退出关闭后导出。
本地`/api/matches`可信调试路径和repository原始Replay不改变。

这是明确的在线导出行为收紧，不是数据库/保存格式迁移。旧Replay和已存在runtime仍可读取，
新响应过滤不会写回状态。上线前应重建测试房间，浏览器已收到的旧私有信息无法撤回。

## 官方依据

本地官方综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 4.1.2/4.1.2.2：区分公开与非公开区域，区域枚数公开。
- 4.1.5.1：多人从公开区置入非公开区时，对手不能知道自行决定的顺序。
- 4.8.2/4.9.2：双方的Main/Energy Deck均非公开，Main Deck顺序受管理。
- 4.11.2：只能自由查看自己的手牌。
- 4.5.3/4.7.2/4.10.2/4.12.2：Stage、Energy、成功Live与控室公开。
- 5.7.1：查看顶牌只授予被指定玩家相应卡牌的信息。

这些引用用于支持响应边界，不把工程测试当作官方人工裁定认证。

## 真实断言

`tests/test_player_payload_privacy.py`共22项：

1. 两种玩家视角都不包含未知牌库卡名/卡号/技能，牌库仅保留正确数量。
2. 交换隐藏牌身份、顺序及seed，当前可见响应保持相同。
3. 换牌、多人选择及自动/手动检查候选不泄露给另一玩家。
4. 公开控室、Stage、附属、Energy与表面Live正常显示；未分区卡不额外泄露。
5. 明确公开的卡片快照保留，但不能据此读到它后来回到牌库的位置。
6. 原生近江彼方检查后，正序/倒序返回牌库产生不同真实状态，但对手的当前响应与历史相同。
7. 嵌套手动事件及其他玩家AI错误payload不输出隐藏ID/私有诊断，原始事件不变。
8. 四种AI在对手隐藏身份和自己牌库顺序变化后选择相同合法Action。
9. 本地完整视图仍包含双方手牌；指定不同玩家仍分别看到自己的手牌。
10. 真实room创建/加入/GET/Action/SSE/重新GET与关闭后导出通过；SSE只含revision等7字段。
11. 在线进行中Replay拒绝；受控complete端点场景与明确关闭场景均导出未改写原始Replay。
12. 真实repository Action后重执行Replay一致，SQL schema与读取前后state hash不受投影影响。

受控complete fixture只验证端点策略，不用它伪称真实胜负流程。
既有规则身份测试已调整为关闭后下载，并继续核对指纹与原始Replay，不删除旧断言。
前端验证进行中不可点、完赛后链接正确；公开控室/卡面和本地流程保持既有测试。

## AI回归与复现

固定20Deck池10局v1.2：10/10正式完赛且10回合内双方成功Live，最长9回合；
零非法Action、错误skip和Replay差异。5454pass/1review，另4项既有Match Point条款解释待审。
这是引擎未受响应过滤影响的回归，不将其当作完整网络或恶意请求审计。

```powershell
python -m pytest tests/test_player_payload_privacy.py tests/test_activated_inspection.py tests/test_webapp.py tests/test_room_ruleset_binding.py -q
python -m tools.ai_sandbox.ai_rules_acceptance --database data/loveca.sqlite3 --output logs/continuous-deck-privacy-ai10-20261026 --decks 20 --attempts 10 --required-qualified 10 --max-turns 10 --max-actions 500 --policy simple_ai_v1_2
```

完整报告：`logs/continuous-deck-privacy-ai10-20261026/比赛总报告.zh-CN.md`，保持ignored。
登记不变：903/1212（74.50%）、309manual，不晋级reviewed。

## 安全与后续边界

这是玩家响应可见性修正，不是防作弊系统。合作式manual工具仍有调试权限，
显式指定的调试seed仍是调用者已知信息；默认seed由服务端生成，不在玩家响应输出。
生产必须禁用公开debug Match端点。历史公开卡可以被玩家记忆，已缓存信息不能撤回。
需在人工批准发布前，用两个浏览器再核对公开提示、多人选择、刷新和结束后导出。
本轮只更新同一个Draft PR #54，不合并、不部署、不改变生产配置，不动旧dirty工作树。
