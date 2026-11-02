# 津島善子：底三张Aqours与原来源绿Heart

2026-10-27，仅固定`codex/continuous-development`本地开发，不推送、新建PR或合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-006-P.png" alt="津島善子 PL!S-bp7-006" width="220">

## 精确范围与基线纠正

- `PL!S-bp7-006:1`，cost2、Blade1、原Heart04一，Aqours/Guilty Kiss，revision851。
- 全文hash：`3c87d290b7b11b30c7b72683a74b6ec5a871266062a46567c1c8258fe5198821`。
- 日文全文：`【ライブ開始時】自分のデッキの下からカードを3枚控え室に置く。それらがすべて『Aqours』のメンバーカードの場合、ライブ終了時まで、【heart04】を得る。`
- 本卡**原本已是test_validated_executable**，不能说从manual晋级。原冻结seed18017的legal原文也如此；其实际人工阻塞是`PL!S-bp7-021:1`，另有可选manual `PL!S-cl1-012:1`。本卡只是共同待机的一个可执行未完成项。
- 本轮先复现真实规则错误：原生Live开始产生本卡与测试CONTROL待机，CONTROL令来源离场同ID回Stage，旧通用gain_heart仍给新对象加心。红测试保存在`logs/bottom-three-aqours-heart-20261027/native-red.xml`。CONTROL为测试构造，不是正式卡能力或生产日志。

## 官方依据

固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
4.8.3要求牌库多张移区逐张执行；10.2.1/10.2.2.1在牌库空且控室非空时立即中断、刷新并继续，10.2.3规定刷新全部控室。4.1.4为移区新对象，9.7.7保证已待机能力仍处理，8.4.11为Live期结束。

[官方Q104](https://llofficial-cardgame.com/question/searchresults/)直接说明多次置控室途中要刷新，包含刚刚置入的牌，再做剩余次数。Q104以顶五张举例，本卡底部次序由4.8.3结合推导，不冒充本卡专属人工裁定。不是私看10.2.2.2预填，也不用同时公开四张的未确认语义。
官方公开API `https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published`实读282条，响应SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，原始响应及卡图保留在本轮logs；web工具不可读不等于官网不可用，未命中本卡条目不表示不存在专属FAQ。

## 有限实现

新增单个受限operation `mill_bottom_three_aqours_source_heart`与`original_live_start_bottom_three_source`策略，只允许强制Live开始、每Live一次、固定三次底部移动与原来源绿Heart+1。全文/revision/hash绑定，删除本卡旧宽泛pattern，不能扩展时点、费用、数量或条件。

1. 每次实际取底牌入控室后立即检查普通空库刷新，再继续。每次移动分别保存是否Aqours Member和公开卡面历史，条件不依赖最后控室、刷新后底牌或去重集合。
2. 单一实体也可经刷新被实际移动三次，记录三次而不是一张。双方牌库/控室均空则零次、条件不成立；任何可移动非空池可通过普通刷新完成三次。
3. 三次均为Member且work含`love_live_sunshine`才满足；unit标签、Live、旧控室和未移动库顶不替代。只给原来源对象Heart04+1，不加全场或全局Heart。
4. 来源待机后离场仍移动牌，但不给离场对象或同ID返回的新对象加心；Stage换位保留，Wait不取消。新标记按自身policy清理，旧空stage_departure_policy也不会残留；旧无policy标记、旧mill_bottom/gain_heart及manual快照不追改。
5. 公开`revealed_cards`历史不授予刷新后当前隐藏牌库card map权限，不泄露未移动尾牌或对手手牌。默认AI、Card/SQL schema及人工reviewed不变。

## 验收与证据

- `tests/test_bottom_three_aqours_heart.py`61项：来源原生CONTROL干涉六组合、work/unit/Member边界、空库/1/2/3张与重复实体、首后演出、Wait、Live期/离场清理、非法原子性、精确绑定及四AI真实动作/隐藏身份不变/不改输入。
- 15种SQL组合含来源六种、新旧结构化/manual三种、短库五种及历史来源返回一种；历史旧bug快照保持原Replay结果，不把兼容当作正确新规则。第一轮216关联通过后又新增一项历史Replay保护；审查修正夹具hand/deck重复同一实例并增加区域互斥断言，旧完整检查主动停止，最终在修正后的源码重新执行全部profiles，不复用旧结果。
- 新双语原生UI覆盖正条件、失败、零张和来源离场；232图文为194动态/38契约，本卡新增5动态，不等于完整人工裁定。
- strict registry零错误零警告。结构化diff仅本卡，**仍925/1212（76.32%）、287manual**；只改变本卡快照策略，不虚增可执行率。
- 最终checkpoint后全部control/registry/backend/web及pre-push通过才本地commit/complete；真实命令日志和完整源码指纹以本轮协调器result.json为准，不拼接旧检查。

## 冻结诊断与受控分支

`logs/bottom-three-aqours-heart-20261027/frozen-30/`与前轮30牌组provenance一致，seed18000–18029、v1.2/block/max500。诊断指纹`8106112b4ad5c4aeeb6065bd3709ab5c978443645f122e660ec8a279c3ccf3a9`与当前应用源码、provenance及全部30条摘要一致。
仍14正式完赛/16人工停止、194/197可执行完成，3项随manual待机保留，非法/runtime/Replay/错误skip0，30局Replay通过，不称完赛或长局/beta改善。

本卡seed18017实际入队一次，冻结结果未完成；在独立测试SQLite副本中只提交本卡合法原生动作，`seed18017-controlled-final.json`确认三次移动、condition=true、原来源绿Heart+1、另外两条仍待机，SQL Replay通过且原状态hash不变。此为受控分支，不替代冻结结果或算随机完成。首个辅助备份连接未关闭引起Windows临时文件清理错误，已明确关闭连接后重跑；`controlled-final`才是最终证据，旧ignored文件保留。

下一有限任务为`PL!S-bp7-021:1`底五张Member计数/抽牌/原来源Live score，需先确认三人条件时点和来源边界。PR54已获批准合并上线；本次不使用旧批准发布新批，后续PR目标仍待已发出的明确批准。
