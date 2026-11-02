# 僕らの旅は終わらない：底五张Member、抽牌与原Live得分

2026-10-27，固定`codex/continuous-development`本地实现；不推送、新建PR或合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!S-bp7-021-L.png" alt="僕らの旅は終わらない PL!S-bp7-021" width="280">

## 精确身份与真实复现

- `PL!S-bp7-021:1`，Live score5，revision913，Aqours；全文hash `4abd5654a85639e01eb2721a21df5439f133589eeccd1238c04944fb4a0b6261`。
- 全文：`【ライブ開始時】自分のステージにメンバーが3人以上いる場合、自分のデッキの下からカードを5枚控え室に置く。それらの中にメンバーカードが3枚以上ある場合、カードを1枚引く。それらがすべてメンバーカードの場合、さらにこのカードのスコアを＋１する。`
- 卡号、完整文本、revision/hash共同绑定。先用原生Live开始复现mandatory manual、没有移动/抽牌/加分，区域互斥断言通过，红测试保存在`logs/bottom-five-member-score-20261027/native-red.xml`。原冻结seed18017也真实因此停止，不按持卡频次晋级。
- 同局`PL!S-bp7-006:1`早已可执行，前轮修复来源而非晋级，不把它的共同待机算成manual。本轮只晋级本卡，登记926/1212（76.40%）、286manual，不提升人工reviewed。

## 官方依据与条件时点

固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。9.6.2.4.2为执行能力正文，9.7.1/9.7.2为触发待机；4.8.3要求牌库逐张移动，10.2.1/10.2.2.1/10.2.3为空库立即刷新并继续；4.1.4/9.7.7为原对象与来源离场，8.4.11为Live期结束。

[官方Q120/Q119/Q104](https://llofficial-cardgame.com/question/searchresults/)：Q120说明触发后状态改变，要在结算时检查正文条件；Q119说明条件在结算时检查一次，之后改变状态不撤销得分；Q104说明置控室途中刷新包含刚移动的牌，再继续剩余次数。这些不是本卡专属FAQ，本实现结合完整日文和通则推导，不冒充完整人工裁定。
官方公开API `https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published`实读282条，响应SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，原响应/卡图保留。未检索到本卡专属项不等于FAQ不存在。

## 有限实现

新增`mill_bottom_five_members_draw_source_score`与`original_live_start_bottom_five_source`，只允许强制Live开始、每Live一次、无费用/无选择、固定五次移动及本卡的抽牌/得分正文。不接受扩大数量、时点、目标或将正文条件提前放入trigger condition。

1. 结算开始读取本人Stage顶层Member数量；不足三名则移动零次、不抽、不加分，能力仍按本次待机处理完毕。附属卡不补人数。原生CONTROL的2→3、3→2、3→3、0→3证明没有触发时锁定。
2. 从底部逐张放控室，每次立即处理空库刷新并保存Member类型历史；同实体刷新后再次移动仍为新的移动记录。不套私看预填，不按最终控室或去重集合计数。
3. 五次中至少三次Member移动才抽一张，抽完若空库也立即刷新。判断全Member仍只用本次五次移动历史，不包含旧控室、追加抽出的牌或刷新后库顶。
4. 五次全Member才给原来源Live `live_card_score+1`至Live结束；不加玩家全局score，不加其他Live，Member作品/单位不作额外筛选。
5. 原来源在待机后离场仍执行移动和抽牌，但不给新对象加分；同ID返回不继承，Live Area内移动保持。来源离场及Live结束清理得分。新源策略接入已有来源捕获/清理，不改变旧无策略、旧manual及普通mill快照。
6. 五次公开快照保留历史，额外抽牌/未移动尾牌/双方手牌仍私密；历史不能授权刷新后牌库或新手牌的当前card map。默认AI和Card/SQL schema不改。

## 验收

- `tests/test_bottom_five_member_score.py`82项：0–5次Member、0–3名Stage、附属卡不计、正文条件改变、来源离场/返回/Live内移动、短库/重复实体、追加抽牌刷新、新旧快照、非法原子性、精确绑定及四AI真实动作。
- 21种SQL组合：四种三人条件改变、八种原来源干涉、五种短库、新旧快照两种、抽牌后刷新一种、旧通用mill一种。CONTROL仅为测试构造，非正式卡能力/生产日志；原始Replay与完整最终状态一致。
- 271目标/关联回归通过，含Aqours Blade6源Live得分、底三张、既有多玩家隐私及图文。四AI v0/v1/v1.1/v1.2均有原生Live开始与待机处理、隐藏身份替换不变和不改输入断言；完整双视角区分公开历史与私有抽牌。
- 5项双语原生UI、263前端及构建通过。238图文为200动态/38契约，本卡新增6动态，不等于人工裁定覆盖率。
- 最初Live结束测试忽略了两张Live需选择成功区，已补真实`resolve_live_requirements`步骤再检查清理，未改引擎规则迁就夹具。
- 审查补充来源离场UI的Live专属文案及双语断言，旧检查主动停止；最终在新checkpoint上重新执行全部profiles，不拼接旧结果。仅文案/测试变化没有改变应用诊断指纹，不重复冻结池。
- strict registry零错误零警告，结构化diff仅本段。最终checkpoint后执行全部control/registry/backend/web与pre-push，全部通过后才本地commit/complete；完整源码指纹及真实命令日志以本轮协调器result.json为准，不复用源码变化前检查。

## 冻结诊断

`logs/bottom-five-member-score-20261027/frozen-30/`与前轮30牌组provenance一致，seed18000–18029、v1.2/block/max500；诊断指纹`18c30cdfa4cc46b166b311fc8aa9244e87bd63a8e433e227168998cc963bf525`与当前应用源码、provenance及全部30条摘要一致。

仍14正式完赛/16人工停止，201/203可执行完成、2项随其他manual待机；非法/runtime/Replay/错误skip0，30局Replay通过。可执行完成增加7项中本卡2项、其余5项为推进后的既有能力，不全算本卡，不称完赛/长局/beta改善。
seed18017本卡实际完成两次，由第1回合18动作推进到第4回合74动作、Live0:1，停在`PL!S-bp7-008:1`。额外有界复跑`seed18017-detail.json`与冻结摘要完全一致，原始结果为：首次Stage2不移动/不抽；第二次Stage3、移动5次/Member3次/抽1，均score_delta0。不能声称随机覆盖全Member加分，正条件仅在专项/SQL/图文验证。

下一有限任务是小原鞠莉`PL!S-bp7-008:1`登场私看三张后分组排库顶/库底，第2段可选Live开始能力继续manual。PR54已获批准合并上线；本批不复用旧许可，后续PR目标仍待已发出的明确批准。
