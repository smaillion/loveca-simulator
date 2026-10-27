# 桜坂しずく：其他虹咲成员与cost15边界

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PR/PL!N-PR-036-PR.png" width="160" alt="桜坂しずく PL!N-PR-036">

## 精确支持范围

`PL!N-PR-036:1`，revision1225，官方效果文本hash：
`efcae675449686825bdddf0b5f7a013d74837a06441dfa296f1677bed2d04ab4`。
只按完整日文段匹配，不依卡名或前缀批量登记。

> 【ライブ開始時】ライブ終了時まで、自分のステージにいるほかの『虹ヶ咲』のメンバー1人は【heart03】を得る。そのメンバーのコストが15以上の場合、さらに【heart03】を得る。

原登记只有强制manual占位。本批先复现原生Live开始暂停，再验证受限候选，
补齐来源对象、Replay、AI和UI边界后才将这一段915→916/1212（75.58%），297→296manual。
`PL!S-bp2-005:1`等未确认文义仍人工；未提升`reviewed_executable`。

## 规则依据

固定本地综合规则ver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
已查看PDF相关全文和第4页原版排版，不重新抓取官网或猜测FAQ。

- `2.6.1`：此处读取Member卡牌信息cost，不把登场支付减费后的数值当成cost。
- `9.6.3.1`、`9.6.3.1.3`：有目标必须选1；完全无目标时不选、不影响来源，不因不可选择而卡死。
- `4.1.4`：成员区内移动不是新对象；离场再回场属于新对象，不单靠instance ID判断“其他”。
- `9.7.7`、`9.6.2.4.2`：来源离场不取消原待机能力的处理义务。
- `11.5.2`、`8.4.11`：自己的Live开始触发，Live期限修正按既有清理机制结束。本批不宣称修复其他End Phase循环问题。

## 实际状态验证

| 场景 | 期望与实际断言 |
|---|---|
| 其他己方虹咲cost14 | 目标获得1颗Heart03 |
| cost15/16 | 目标获得2颗Heart03 |
| 原来源、异作品、手牌、附属卡、对方成员 | 不能选择，非法请求状态不变 |
| 没有其他合法目标 | 显式选0后结束，记录未适用理由，不给来源加Heart |
| 待机后目标cost14→15/15→14 | 结算时重新读取卡牌信息 |
| cost15但登场支付被减到5 | 仍获得2颗；支付成本不是卡牌信息cost |
| 来源仅移动到其他成员区 | 仍是原对象，不可自选 |
| 来源离场后同ID回场 | 是新对象，可以作为“其他虹咲”选择，实际仅cost2故获得1颗 |
| 来源离场不回场 | 待机继续；没有其他目标时明确完成 |
| 目标在结算前离场 | 不回退来源、不保留过期选择 |
| 目标获得修正后离场并回场 | 清除修正，新对象不继承 |
| Live结束 | 修正清理 |

新增独立受限`selection_policy`及单条Heart数量计算，不放宽旧指定姓名Blade策略。
单条modifier避免同色两次operation产生重复ID。旧manual快照仍人工，不静默升级旧Replay。

45项专项通过，连同旧姓名/分组技能与图文回归共142项。
包含真实原生Action和SQLite Replay、四种AI、隐藏手牌身份替换不影响选择、
双视角响应及两方控制。前端新增正常选择、零目标、同ID回场三个实际交互契约，217项通过。
图文180项全部通过：142状态/边界、38登记契约，新增3场景携带`rule_reference_ids`。
自动断言不等同人类裁判全卡审查。

## 冻结30局诊断

沿用相同30套合法牌组和seed18000–18029，`simple_ai_v1_2/block`，最多500动作。
不更换成更容易的牌组，不当作30×300发布门禁。

| 指标 | 本批前 | 最终本批 |
|---|---:|---:|
| 正式完赛 |7|7|
| 明确人工技能停止 |23|23|
| 非法动作 / runtime异常 / Replay错误 / 错误skip |0/0/0/0|0/0/0/0|
| 可执行待机完成 |132/134|142/146|
| 保留在其他人工阻塞后的可执行待机 |2|4|

本段在seed18009/18013/18018共入队9次，其中2个在`PL!N-sd2-026:1`人工阻塞后待机，
不能把入队9次写成全部结算。三局推进至第3/6/3回合后分别遇到其他未支持技能，
正式完赛数没有增加，未达beta发布门禁。

首轮诊断还在seed18007暴露了内部临时选择对象没有`selection_policy`的回归。
修复为兼容缺省属性并新增2项adapter回归后，重跑全部30局，最终异常为0；
失败探索报告仍保留，不作为通过证据。

## 证据与复现

```powershell
python -m pytest tests/test_other_nijigasaki_heart.py tests/test_named_live_blade.py tests/test_named_live_groups.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --database data/loveca.sqlite3 --output logs/other-nijigasaki-heart-final-20261026/verification
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --output logs/other-nijigasaki-heart-final-20261026/final-frozen-30 --deck-directory logs/continuous-manual-focus-30-bound-20261026/decks --decks 30 --matches 30 --manual-policy block --policy simple_ai_v1_2 --seed-base 18000 --max-actions 500
```

诊断provenance与30局摘要的源码指纹逐一一致；完整top40在同目录`gaps/`的中日文报告。
最终工程门禁另绑定全仓库源码，包含全量后端、前端/TS/build、control、strict registry和manifest/pre-push。
不改Card或runtime SQLite schema，不改变默认AI v1.1，不读取GPT认证，不调用付费API。
同一Draft PR54，旧44/6 dirty与ignored成果保留；不合并、不部署。

下一有限切片：`PL!S-cl1-002:1`从Yell公开Aqours卡中选最多3张排序入底；
先核对公开历史与清理时点，不将整个Resolution Area等同Yell。
