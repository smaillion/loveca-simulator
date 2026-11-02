# エマ・ヴェルデ：顶三控室与Blade Heart颜色

2026-10-27，本地实现验收；固定分支`codex/continuous-development`，不推送、不发布。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-020-N.png" alt="エマ・ヴェルデ PL!N-bp7-020" width="220">

## 身份与官方依据

- `PL!N-bp7-020:1`，エマ・ヴェルデ，cost5、Blade2，虹ヶ咲/QU4RTZ。
- revision883，完整原文hash：`1fd519f551bd331e61e6a8fa1d9cfada8390c609ae73319768e4e7d30701ea04`。
- 全文：`【登場】自分のデッキの上からカードを3枚控え室に置く。それらのメンバーカードの中に2種類以上のブレードハートの色がある場合、ライブ終了時まで、【heart04】を得る。`
- 已真实复现原生登场的mandatory manual，不按牌组持有频次冒充技能触发。
- 本轮实际读取[官方Q&A公开数据](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)的282条记录。Q270直接针对本卡，2026/08/05更新：ALL与绿色不能满足两种颜色。Q112确认ALL、抽牌、得分均属于Blade Heart，但不等于有色种类。
- 官方响应SHA256：`b05d8f59209cbfc508e20095c8c2e0a1f558365a403f8b53922995949811ca0a`。urllib读取成功；curl及web抓取工具的404不作为官网不可用或FAQ不存在的证据。
- 固定PDF`raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256为`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
- 规则2.1.1/2.1.3、2.2.2.2、2.7区分颜色、图标与Member；4.1.4及9.7.7约束来源对象；10.2.2.1为顺序置入控室时的空库刷新；8.4.11处理Live结束期限。

## 受限执行

只绑定上述全文/revision/hash。新操作固定为“顶三控室→Member的六色Blade Heart去重→原来源绿色Heart+1”，并采用独立`original_onplay_mill_source`快照策略。
本卡没有费用、可选放弃、目标选择或玩家分支，使用原生自动处理及双语结果提示，不新增多余确认步骤。

| 本次置入控室的牌 | 颜色种类 | 来源加成 |
|---|---:|---:|
| 无色图标或只有普通Heart | 0 | 0 |
| 三张相同有色Blade Heart | 1 | 0 |
| 两种有色Member Blade Heart | 2 | +1绿Heart |
| 三种有色Member Blade Heart | 3 | 仍仅+1 |
| ALL与绿色，官方Q270 | 1 | 0 |
| Live提供第二种颜色 | 只算Member部分 | 不满足则0 |

短库逐张置入控室，在需要下一张时依正常空库规则刷新，不套用私看的预先补足。
仅一张牌时可刷新后再次置入同一ID，但同色重复不会变成两种颜色；条件计算后空库也正常刷新。
原来源离场后，后续置入控室仍执行；相同ID返回Stage也不继承原来源加成。Stage内Position Change仍是原对象。
加成是目标化的Member Heart，不是全局Heart、Blade或Live分数；来源离场由当前对局清理策略清除，Live结束正常到期。
旧milling操作、旧manual快照和其他来源策略保持原行为，不修改Card/SQL schema、默认AI或未确认技能。

## 验证范围

- 61项专项：精确绑定、六色/重复/零色/普通Heart/特殊图标/Member与Live、短库及刷新、原子拒绝。
- 实际登场自动处理、四AI实际出牌及单独待机决策、隐藏身份不变与不修改输入。
- AP/NAP实际登场并产生两个待机后，先用另一个人工能力移动来源：离场、返回、场内换位三种SQL Replay全部一致；单独待机夹具用于更细的边界测试，不冒充原生触发证据。
- 来源加成后离场再返回、原生Live结束清理，以及旧manual和新自动两类SQL Replay。
- 双视角响应：控室牌公开，未知尾牌和对手手牌不泄露；待机干涉后来源留在手牌时仍隐藏。
- 195项关联专项和202项双语图文通过；图文为164动态状态、38契约，本卡新增6动态场景，不是完整人工裁定。
- 原生UI增加3项双语结果展示：条件失败、成功加成、原来源离场，前端235项及生产构建已通过。
- 结构化registry diff只有本effect ID；登记920/1212（75.91%）、292manual，不提升人工reviewed。

## 冻结30局

证据`logs/mill-three-blade-colors-20261027/frozen-30/`和`illustrated/`。
复用同30牌组、seed18000至18029、v1.2/block、每局500动作；当前诊断指纹与provenance及30条逐局摘要一致：
`417ab0d90390bd45cc9f727c10888be0255c062495da3e16e669171819d3e48a`。

- 仍11完赛/19明确人工停止；可执行技能167/169完成，2个随其他人工待机保留。
- 本卡实际触发三次：seed18008两次、18029一次，相关两局可执行待机均无未完成项。
- 18008推进到第5回合、94动作，在`PL!N-bp4-007:1`停止；18029第2回合、30动作，在`PL!-pb2-005:1`停止。
- 非法/runtime/Replay/错误skip均0，30局Replay通过。只是推进了原阻塞位置，不宣称完赛率或双方Live长局改善。

## 门禁与后续

最终checkpoint后运行完整control/registry/backend/web及pre-push，命令、退出码和当前源码指纹由协调器本轮result.json保存；不复用旧绿色结果。
下一有限独立审计是新实际待机`PL!N-bp4-007:1`的双方从自身控室各取一张Live，先确认顺序/是否同时选择及公开必选边界。
公开四张短牌库和lily white特殊计数仍blocked，不因本卡通过而晋级。
PR54已批准合并上线，但本批不包含在其中；新PR目标仍待明确批准，policy未改，不推送、不新建PR、不合并部署。
