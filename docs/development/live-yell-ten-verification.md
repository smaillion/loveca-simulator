# 僕たちはひとつの光：成功Live条件与Yell加十

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL02/PL!-pb2-039-L.png" width="160" alt="僕たちはひとつの光 PL!-pb2-039">

## 修正范围

仅`PL!-pb2-039:1`，revision1018，原始整段hash
`c64c225ab648e5389537066b41874ad2905e24eb668f1a651fde9bd7b45780f9`。
第二段「按不同姓名μs成员加分」仍为manual；不是整卡已完全支持。

官方日文第一段：

> 【ライブ開始時】自分の成功ライブカード置き場に『μ's』のカードが2枚以上ある場合、ライブ終了時まで、エールによって公開される自分のカードの枚数が10枚増える。

此前只有时点占位登记，成功区0张也会要求人工处理。
原30局中seed18026/18029共出现3个该段人工待机，均在第1回合17个动作后停下。
先以原生advance动作复现失败，再添加精确段匹配；不靠名称或前缀猜测其他卡。

## 规则依据与处理

固定本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
已查看PDF第8页及9.6/9.7条款；未重新抓取官网或猜测FAQ。

- `8.3.8–8.3.11`：Live开始及自动效果检查先于Blade合计与Yell公开。
- `9.6.2.4.2`、`9.7.3`：正文效果在自动能力结算时处理。这里用operation条件检查当时成功区，而非把正文条件提前当作诱发过滤。
- `8.4.11`：Live期限修正消灭。沿用现有期限处理，本批不宣称修复旧End Phase重复检查的其他问题。

| 局面 | 期望和实际断言 |
|---|---|
| 成功区0/1张μs | 正常进入Yell，不加十、不人工暂停 |
| 成功区2张μs | Yell公开数量+10，Member Blade不变 |
| 成功区2张其他作品 | 不追加 |
| 同作品在手牌、控室、当前Live或对手成功区 | 不作为己方成功区数量 |
| 另一个有序效果先移入/移出成功区 | 按结算时当前区域重新检查，两个方向均有断言 |
| Active Blade1 | 真实公开11张，不是把Stage成员Blade改成11 |
| 成员Wait | 基础公开0，效果仍追加10 |
| 短牌库 | 刷新控室后继续公开，已Yell牌不会重复使用 |
| Live结束 | 数量修正清理，Stage Blade仍1 |

## 自动验证

28项专项，另有12项统计回归及1项图文回归，共41项通过。
包括原生触发/Yell、双方控制、四种AI、隐藏手牌替换不影响决策、双视角响应、
过期revision原子拒绝、新自动与旧人工snapshot的真实SQLite Replay。
图文报告177项全部通过，其中139状态/边界、38登记契约；新增4项有实际公开张数断言及`rule_reference_ids`。
这是自动测试证据，不是人类裁判完整审核；未提升`reviewed_executable`。

登记914→915/1212（75.50%），298→297 manual。旧Replay沿用snapshot，
无engine/Card/SQLite schema修改；只更新一个登记段及对应manifest，其他段内容不改。

## 同池AI诊断

冻结上一轮30套合法牌组，seed18000–18029，`simple_ai_v1_2`、`block`、500动作上限。
不是重新生成更容易的测试池，也不是30×300发布门禁。

| 指标 | 修正前 | 修正后 |
|---|---:|---:|
| 正式完赛 |6|7|
| 明确强制人工停止 |24|23|
| 非法动作 / runtime异常 / Replay错误 / 错误skip |0/0/0/0|0/0/0/0|
| 可执行待机完成 |125/127|132/134|
| 可执行待机保留在人工blocker后 |2|2|

seed18026从第1回合阻塞推进到第5回合正式结束（102动作），本段入队4次、不再人工阻塞。
但成功Live为0:3，**不符合历史验收要求的双方至少成功一次**，不能包装为该验收通过。
seed18029本段入队1次、不再人工阻塞；第2回合停在另一张卡`PL!N-bp7-020:1`。
其余manual边界继续如实报告，不静默跳过。

## 复现入口

```powershell
python -m pytest tests/test_live_yell_ten.py tests/test_effect_observations.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --database data/loveca.sqlite3 --output logs/yell-ten-audit-20261026/verification
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --output logs/yell-ten-audit-20261026/final-frozen-30 --deck-directory logs/continuous-manual-focus-30-bound-20261026/decks --decks 30 --matches 30 --manual-policy block --policy simple_ai_v1_2 --seed-base 18000 --max-actions 500
```

诊断`provenance.json`和每局摘要携带同一源码指纹；牌组、seed、策略可复核。
报告与旧ignored成果均保留。产品默认AI仍v1.1，不调用付费API，不读取GPT认证。
最终协调器门禁另绑定全仓库源码；同Draft PR54，不合并、不部署。

下一项优先审计`PL!N-PR-036:1`另一虹咲成员按cost追加Heart；不凭频次批量晋级，
`PL!S-bp2-005:1`仍待文义及专用执行器确认。
