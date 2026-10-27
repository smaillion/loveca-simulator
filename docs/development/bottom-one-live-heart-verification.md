# 津島善子：牌库底一张与原来源红Heart

2026-10-27，仅固定分支`codex/continuous-development`本地实现；不推送、不新建PR、不合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-015-N.png" alt="津島善子 PL!S-bp7-015" width="220">

## 精确绑定与依据

- `PL!S-bp7-015:1`，津島善子，cost5、Blade2、原Heart04/05各一；revision860。
- 原文hash：`4de00b242755d4712ed8afbb6b6d5a27047c8f4cdbfd76101d0f1f1b7343cbf0`。
- 完整日文：`【ライブ開始時】自分のデッキの下からカードを1枚控え室に置く。それがライブカードの場合、ライブ終了時まで、【heart02】を得る。`
- generator同时核对卡号、全文、revision和hash，不作模糊前缀绑定。
- 原冻结池seed18027有真实mandatory manual。专项以旧manual snapshot重现原生Live开始仍待机、未移动底牌，再对新定义断言真实区域及Heart变化。
- 固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。4.8.2/4.8.3确认牌库非公开且按单张移动，10.2.2.1/10.2.3为空库刷新，10.2.2.2的查看前补库不适用本次移动。4.1.4/9.7.7区分离场新对象与已待机能力，8.4.11为Live期清理。
- [官方Q&A](https://llofficial-cardgame.com/question/searchresults/)的公开API实际读取282条：`https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published`。响应SHA256 `b05d8f59209cbfc508e20095c8c2e0a1f558365a403f8b53922995949811ca0a`，原始响应及官方卡图在本轮logs。未检出本卡专属记录不代表FAQ不存在；本实现按固定通则推导，不冒充专属人工裁定。

## 实现边界

新增受限operation `gain_source_heart_if_bottom_card_live`和来源policy `original_live_start_bottom_source`。
仅允许无费用、无选择、强制Live开始、每Live一次、先`mill_bottom_cards(1)`再固定原来源Heart02+1、期限Live的序列。

1. 牌库非空时直接从底部置入控室；已有控室不提前混入牌库。空库且有控室时正常刷新后取底牌；两处都空则按可能范围移零张。
2. 移动使牌库为空时，条件前正常刷新。判断仍引用本次实际移动的Card，不检查刷新后的当前底牌、旧控室其他Live或牌库顶牌。
3. 只看卡种Live，不用Member的Heart/Blade Heart代替。只给原来源，不给其他Stage Member或全局加心。
4. 来源待机后离场仍执行底牌移动，但不给新区域对象加心；同ID返回不继承。Stage内换位仍为原对象，来源Wait不取消能力。
5. 新补正带自身policy标记，来源离场清理，Live结束清理。专门红测试复现旧空`stage_departure_policy`下的新补正遗留，再限定修正；旧无标记modifier仍按旧快照行为。
6. 旧`mill_bottom_cards`操作、旧manual定义和无来源policy序列不改。Card/SQL schema、默认AI及人工reviewed未改，不扩展为任意“それ”引用框架。

registry结构化diff只有本段；923/1212（76.16%）、289manual，只是程序可执行登记，不是完整人工审查覆盖率。

## 验收

- `tests/test_bottom_one_live_heart.py`共60项：全文绑定、Member/Live/构造Energy、空库/恰一张/已有控室/刷新顺序、原移动对象、AP/NAP、Wait、无Live及来源不在场不触发、原子拒绝和Live期限。
- 原生Live开始加测试CONTROL干涉，覆盖来源离场/返回/换位及新旧离场policy的六种SQL组合；另有新自动、旧manual和旧普通mill三种SQL Replay。CONTROL只是测试构造，不是生产记录或正式卡能力。
- 四AI v0/v1/v1.1/v1.2分别做真实Live开始与待机选择；隐藏卡名/卡号/Heart替换不改变选择，不改输入。双方完整响应保留公开底牌，不暴露隐藏顶牌/手牌；刷新后的旧底牌不会复活当前card map权限。
- 227项来源/清理关联回归通过，旧来源与manual兼容保护不放宽。3项双语原生UI、246前端及生产构建通过。
- 217项图文通过，179动态状态/38契约，本卡新增5动态，不冒充完整人工裁定。
- strict registry零错误/零警告。最终checkpoint后由协调器重跑control/registry/backend/web全部required_profiles，另做pre-push；仅全部通过后本地提交并complete。真实源码指纹、命令与退出码保存在主仓库`.tmp/development-loop/runs/`本轮result.json，不拼接旧绿色结果。

## 冻结对局与受控分支

`logs/bottom-one-live-heart-20261027/frozen-30/`，同前轮30牌组逐项相同，seed18000–18029、v1.2/block、max500。
当前应用诊断指纹与provenance、全部30条摘要一致：`664d39150c2cb8bda57768e2047b853577cc2acd5c79c3456a49ebf376a60f2f`。

- 仍12正式完赛/18人工停止；185/188可执行完成，3项随其他manual待机保留，较前轮185/187不是完成数改善。
- 无非法/runtime/Replay/错误skip，30局Replay全部通过。
- 本卡seed18027实际入队一次，但与`PL!S-cl1-013:1`等同时待机，block策略在人工能力存在时停下，本卡尚未完成。不把登记晋级或事件总量当作实战执行完成。
- 额外有界复跑同一seed并备份测试SQLite：`seed18027-controlled.sqlite3`与`seed18027-controlled.json`。在该测试副本单独提交本卡原生合法动作，实际底牌Member，condition=false、Heart+0，其他两项仍待机，SQL Replay通过。没有修改冻结池结果或把受控分支算作完赛。
- 正条件Live加心由专项、SQL及图文覆盖，不声称随机池命中正条件，也不宣称长局/beta或策略门禁完成。

下一有限独立任务是同池seed18023的`PL!N-sd2-007:1`：Live成功先抽一张，若对方本回合也成功则再抽并弃一张。先核对成功判定/演出顺序，不能用累计成功区数量代替当前回合条件。
后续PR目标仍待已发出的明确批准，policy固定54；PR54是已批准合并上线的历史，不改目标、不发布，不重复请求同项审批。
