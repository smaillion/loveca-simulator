# 四张公开选择底座：仅原型，不绑定正式卡

## 恢复验收

本轮恢复同一个in_progress，只重新绑定完整control/registry/backend/web与pre-push，不重做原型，不拼接旧检查。最终通过记录单独保存在协调器本轮result.json；通过并审查diff后才本地提交和完成底座任务，仍不发布。

## 历史未提交检查点（2026-10-27 02:59 UTC）

2026-10-27本轮完整检查的control/registry、3612后端及227前端通过，但build因UI测试夹具包含Web CardDefinition未声明的unit_keys失败。
已删除该UI不使用的字段，不放宽类型或validator；最终前端复验以本轮后续web profile结果为准。
修改了测试及检查点后，旧完整检查的源码指纹失效。受45分钟轮次限制，本轮不提交、不complete、不推送；release保留同一in_progress，下一轮先对当前源码重跑全部四组门禁，再审查和提交。
不得把后续web-only绿色当作整个任务已完成，也不得重新实现已经保留的原型或转去其他业务任务。

## 边界

新增snapshot策略`public_four_lily_white_live`仅用于测试构造的`PROTOTYPE-public-four:1`。
官方`PL!-pb2-013:1`仍manual；没有修改registry、generator、manifest、Card/SQL schema或默认AI，执行率保持918/1212、294manual。
不能把此底座的工程验收写成正式卡已支持，也不新增reviewed。

正式卡revision986，全文hash `0a06fcfee9cde86a6c33f9b5369470994fac45e9a4fe236a94aae1e9e7531f86`。
本轮真实登场复现：仍为manual待机，没有开始检查或公开牌；原冻结池三次实际人工待机不是牌组频率。

## 已验证的有限行为

仅在开始时已有至少四张牌库时运行原型；少于四张在任何状态变化前拒绝，是否有控室牌都不擅自补库。
公开的四张保留原牌库区域与顺序，不借用旧私看“先取到解決領域”的实现。

| 情况 / 状態 | 原型断言 / 検証 |
| --- | --- |
| 四张全lily white，存在Live / 全部lily white・Liveあり | 必须取其中一张Live到手，余牌控室；不能主动选零张 |
| 有异unit / 異なるunitを含む | 公开后条件失败，不能取得任何牌，全部仍在原牌库位置，不丢弃 |
| 全lily white但无Live / Liveなし | 明确零张，余牌控室 |
| 原库恰四张 / デッキが四枚 | 公开期间不刷新；实际移走牌导致牌库空后，才按现有规则刷新控室 |
| 旧私看 / 従来の非公開確認 | 即使伪造public marker，旧snapshot仍不公开 |

选择检查原四张仍是当前牌库前缀；错误牌/重复/多张/其他区域选择原子拒绝。
原生inspection期间禁止manual调整，所以不能通过离开再返回替换原对象；本报告不虚称跟踪绕过引擎的任意对象改写。
双方可查看本次公开的四张及其快照，但不能查看未公开尾牌或对手手牌。处理结束后隐藏区继续脱敏，合法公开历史通过revealed_cards保留。

## 未确认语义与依据

正式任务记录`unresolved_reason=simultaneous_public_reveal_short_deck_refresh_semantics`并保持blocked。
固定PDF ver.1.06，SHA-256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
核对1.3.2、4.1.2/3、5.7.1、9.6.3.1/3及10.2.2.1/2、10.2.3。
10.2.2.2写的是上から見る，不能未经确认就把“同时公开四张”等同私看并预先补足四张。

本轮通过官方页面的公开脚本配置定位到[官方Q&A公开数据](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)，实际读取282条published条目。
Q166（2025-09-18）与Q73（2025-02-14）讨论逐张公开直到命中时的中途刷新，排除已公开牌后继续；它们不直接裁定本卡的同时四张。
没有取得本卡的专属FAQ；不把此结果说成FAQ不存在，更不采用非官方攻略作裁定。官方[规则入口](https://llofficial-cardgame.com/rule/)仍标ver.1.06。
条件不成立时，文本的取牌和余牌控室是条件体，不能无条件把公开牌丢进控室。

## 证据

原型专项46项；与旧检索及玩家响应隐私回归的360项关联检查已通过（添加两项已有控室的恰四张边界后，最终结果以协调器完整门禁为准）。
包含四AI、双方可见信息、旧私看隔离、原生选择、SQL Replay、短牌库与非法选择原子性、受限schema；前端增加两项原生交互。
最终control/registry/backend/web、pre-push与源码指纹单独保存在协调器本轮result.json，不复用旧门禁。

本轮真实重新运行冻结30牌组、seed18000–18029、v1.2/block、每局500动作上限。
新源码指纹`c2120ab8380234c5f0025af505b75803f68df2ff98576ab13d8c83daa406d854`与provenance及全部逐局摘要一致。
仍9完赛/21人工停止、158/160可执行完成、2跟随其他人工待机、Replay及错误skip0。
原型不绑定官方卡，所以随机局没有原型触发，不冒充完赛改善。日志`logs/public-four-reveal-foundation-20261027/frozen-30/`。

下一独立任务是`PL!SP-PR-028:1`的10减当前手牌私看最多取二；正式公开四张任务等待短牌库语义澄清。
固定分支/工作树、旧dirty与ignored报告保留；不改PR54的policy、不推送、不新建PR、不合并部署。
