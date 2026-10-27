# 優木せつ菜：对方本回合成功后的追加抽弃

2026-10-27，固定`codex/continuous-development`本地实现，不推送、不新建PR、不合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/NSD02/PL!N-sd2-007-P.png" alt="優木せつ菜 PL!N-sd2-007" width="220">

## 绑定与官方依据

- `PL!N-sd2-007:1`，cost11、Blade4、Heart02/04各二、绿色Blade Heart，虹ヶ咲/A・ZU・NA；revision938。
- 全文hash：`a0652e4321925ae2826d299c309118fb251aa81c1b11b7fc62ca84091f8111fb`。
- 完整日文：`【ライブ成功時】カードを1枚引く。このターン、相手もライブを成功している場合、さらにカードを1枚引き、手札を1枚控え室に置く。`
- 卡号、全文、revision和hash同时精确绑定；已先用原生Live判定复现旧定义只允许manual处理的红测试，原冻结seed18023也真实因此停止。
- 固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。8.3.16在演出不满足时移走Live；8.4.4/8.4.5先产生有Live玩家的成功事件并处理能力，8.4.6才决定胜负；9.6.3.1规定可能时必须选足，9.7.7规定来源离场不取消已待机能力；10.2.2.1为普通空库刷新。
- [官方Q37](https://llofficial-cardgame.com/question/searchresults/)说明每个Live时点能力各触发一次，多个能力可选择顺序，不是本卡专属FAQ。本实现结合通则推导，不冒充专属人工裁定。
- 官方公开API `https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published` 实读282条，响应SHA256 `b05d8f59209cbfc508e20095c8c2e0a1f558365a403f8b53922995949811ca0a`。本轮logs保留原响应与官方卡图；未检出专属条目不代表不存在，web读取404也不等于官网不可用。

## 实现范围

新增受限operation `draw_extra_if_opponent_live_succeeded`，只允许完整的强制Live成功序列：抽一张、条件追加一张、本人手牌选一张弃置。新操作不能作费用，也不能扩大抽牌量/对象或更换时点、选择区域、范围和条件键。

1. 第一张始终抽取。随后在结算时检查当前回合、当前Live判定的成功玩家集合；双方成功不等于双方获胜，也不等于成功区已有牌。
2. 缺失/旧回合/布尔冒充回合号、未开始当前成功判定、来源所有者不在成功集合时原子拒绝，不保留第一步抽牌。
3. 条件成立才追加抽一张，并把判定结果保存在本次待机上下文中。后续只让本人从当前手牌必选一张；第一张、新抽的第二张和原手牌均可选。没有手牌时按可能范围略过弃牌。
4. 使用已有post-action流程，抽牌完成前不接受预选弃牌，选择完成不再抽牌或重判条件。条件不成立时只抽第一张，不启动弃牌。
5. 原来源离场、返回或进入未知牌库不取消能力；已发生的对方成功不因其Live后来移走而撤销。不把旧成功区累计张数、上回合缓存或先后操作指针当条件。
6. 不修改既有post-action条件读取、普通抽牌/弃牌操作、旧manual snapshot、Card/SQL schema或默认AI。

registry结构化diff仅本段，当前924/1212（76.24%）、288manual，不提高人工reviewed，不代表完整人工裁定覆盖率。

## 验证与发现

- `tests/test_opponent_success_draw_discard.py`共86项：精确绑定、单/双方成功、首后攻和所有者组合、历史成功区/缓存、输掉分数但已成功、零/短库及途中刷新、所有者必选弃牌、非法数量/重复/他方/未知牌原子性、上下文及形状门禁。
- 八种原生Live判定加测试CONTROL干涉的SQL组合：来源离场/返回/换位/未知牌库与单/双方成功；另有新自动结构和旧manual两种SQL Replay。CONTROL只是测试构造，不是生产日志或正式卡能力。
- 四AI v0/v1/v1.1/v1.2分别完成两种分支，隐藏身份替换不改变决策，不改输入。双方完整响应不公开新抽手牌/候补，实际弃入公开控室后才可见。
- 179项关联回归含Live边界、图文契约和多玩家来源隐私保护。222图文为184动态/38契约，本卡新增5动态，不冒充完整人工审查。
- UI红测试真实发现：来源在隐藏区域时通用技能面板无条件读取card map会崩溃。标题和多能力选单改为缺卡面时显示能力编号，不恢复隐藏卡面或身份。5项原生UI覆盖中日结果、单/多隐藏来源及严格一张提交，251前端及构建通过。
- 独立测试曾暴露manual夹具操作名拼写、图文helper所有者参数和固定待机ID误用，均修正夹具后重跑；未放宽规则或把失败当绿色。
- strict registry零错误/零警告。最终checkpoint后运行control/registry/backend/web全部required_profiles和pre-push；仅全部通过后本地commit/complete，真实源码指纹与命令日志由协调器本轮result.json保存，不拼接旧结果。

## 源码绑定冻结对局

`logs/opponent-success-draw-discard-20261027/frozen-30/`，与前轮30牌组provenance逐项相同，seed18000–18029、v1.2/block/max500。
诊断指纹与当前源码、provenance及全部30条摘要一致：`1f0cbb5d5a2e3d24404e40069eca532998a86e210ac3d9c35ec10d8a43741c2c`。

- 正式完赛12→13、人工停止18→17，192/195可执行完成，3项随其他manual待机保留。非法/runtime/Replay/错误skip均0，全部30局Replay通过。
- 本卡seed18023真实触发完成一次，第9回合192动作正式结束，成功Live3:2；该局符合双方有Live及10回合内，不代表全池长局或beta门禁达标。
- 额外有界复跑同局捕获原始结果事件，`seed18023-detail.json`确认condition=true、extra_drawn_count=1、discard_required=true；不是只用入队事件推测完成，也不是人工分支替代冻结结果。
- 可执行完成总增7项中，本卡1项，其余来自继续推进后的既有能力，不全算作本卡触发。

下一有限独立任务为seed18020真实待机的`PL!SP-bp7-017:1`：登场放置一张Wait Energy，且仅该对象下回合Active Phase不复原。先核对次回合期限/移区新对象，不能给全体Energy或任意原有Wait卡套标记。
PR54已获批准合并上线；后续PR目标仍待已发出的明确批准，本批不改policy、不推送或创建新PR，后续合并部署另行批准。
