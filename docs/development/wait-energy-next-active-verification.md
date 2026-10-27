# 桜小路きな子：新Energy下回合不自动复原

2026-10-27，固定`codex/continuous-development`本地实现；不推送、不新建PR、不合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!SP-bp7-017-N.png" alt="桜小路きな子 PL!SP-bp7-017" width="220">

## 精确绑定与依据

- `PL!SP-bp7-017:1`，cost11、Blade4、Heart02一/03二/06一、黄色Blade Heart；Liella!/5yncri5e，revision904。
- 全文hash：`30ff25ec59e8e1abece877f098ad0bc1d09d29b79c089c838a1029d192e326d0`。
- 完整日文：`【登場】自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。そのエネルギーカードは、次のターンのアクティブフェイズにアクティブしない。`
- 卡号、全文、revision/hash共同绑定。已先用原生登场红测试复现未放置Energy、保持manual；当前冻结池seed18020原来确实因此待机，不按持卡频次晋级。
- 固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。7.1.2/7.3.3区分一个游戏回合内的先后攻通常阶段，7.4.1为本人Active Phase复原；4.1.4为移区新对象，4.7.2/4.7.3为Energy公开/朝向，9.7.7为来源离场后待机仍处理。
- [官方Q280](https://llofficial-cardgame.com/question/searchresults/)用米女メイ能力举例：其他能力主动复原后再支付变Wait，不复原效果仍持续到指定Active Phase。这不是きな子专属FAQ，本实现结合通则推导，不冒充完整人工裁定。
- 官方公开API `https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published`实际读取282条；本轮响应SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`。与前轮结构化比较仅38条关联卡/作品等元数据不同，问答正文及revision均未变，证据`faq-comparison.json`。原响应及卡图保留在本轮logs，web工具404不等于官网不可用。

## 有限实现

新增operation `place_wait_energy_skip_next_turn_active`，只允许无费用、无选择、强制登场、固定一张自方Energy；禁止将它作费用或扩大数量/对象/时点。

1. 调用已有Energy放置入口，实际从Energy Deck放入的一张置Wait，保留原生Energy放置观察者触发。空Energy Deck完成零张，不给其他旧Energy补标记；错误Card种类原子拒绝。
2. 新标记保存原对象ID、明确policy和`created_turn+1`的游戏回合号。期限不是“下次本人操作”或“最近一次Active”。当回合尚未进行本人的Active时正常复原，标记继续等待下回合。
3. 仅目标回合本人的Active Phase跳过该Energy一次，并消费标记。来源Member离场/返回不撤销Energy本身限制；主动技能复原及支付变Wait也不消费标记，符合Q280。
4. Energy移入其他区域或变成附属卡时清理新标记，同ID回到Energy Area不继承；同区域不移区的no-op不清理。超过目标回合的标记不会永久延续。
5. 新标记用已有ManualModifier JSON记录，期限game由新策略自行到期，不新增Card/SQL schema；不修改旧`skip_next_active_phase_ready`语义、旧加Energy操作或默认AI，不是任意持续限制框架。

registry结构化diff仅本段，925/1212（76.32%）、287manual，不提升人工reviewed，不代表完整人工裁定覆盖。

## 验收

- `tests/test_wait_energy_next_active.py`共64项：原生登场、空库/错误类型原子性、首后攻/所有者组合、完整回合与随后回合、来源离场/返回/换位、主动复原再支付、Energy移区/附属/同ID返回、标记精确形状/清理和旧flag消费保护。
- 四种所有者/先后攻组合从原生登场连续跑完整回合SQL，目标回合只跳过新Energy，随后正常复原。另有CONTROL多人登场在本回合Active前放入Energy，并在当前回合普通出牌实际支付它，再到下回合验证不复原。
- 上述CONTROL明确为测试能力，借用既有多玩家底座并声明允许11费成员；没有改正式`PL!-pb1-018`规则或registry。最初原夹具仅支持低费用目标的失败已修正为CONTROL，不把11费きな子伪装成该正式卡的合法目标。其余测试夹具`target_slot`与duration字段错误也已修正后重跑。
- 原生登场加CONTROL来源干涉、新旧manual快照、两种结构化Energy移区、完整回合等共12种SQL场景通过；CONTROL/构造状态不是生产日志或正式卡能力审查。
- 四AI v0/v1/v1.1/v1.2实际出牌及独立待机处理，隐藏卡名/卡号替换不改决策，不改输入。完整双视角只公开新Energy，不泄露Energy Deck剩余牌或对手手牌。
- 218关联回归通过，覆盖旧Energy返库、重叠Energy观察者、Stage清理与多玩家来源隐私。227图文为189动态/38契约，本卡新增5动态，不等于完整人工审查。
- 3项双语原生UI、254前端和生产构建通过。strict registry零错误/零警告。最终checkpoint后执行control/registry/backend/web及pre-push，仅全部通过才本地commit/complete；源码指纹、真实命令日志由协调器本轮result.json保存，不拼接旧结果。

## 冻结诊断

`logs/wait-energy-next-active-20261027/frozen-30/`，与前轮30牌组provenance逐项相同，seed18000–18029、v1.2/block/max500。
诊断指纹与当前源码、provenance及全部30条摘要一致：`b0d2d99e00332b4188e865287f09bd8290a0593fb998c08aaf0f4120d5969b71`。

- 正式完赛13→14、人工停止17→16；194/197可执行完成，3项随其他manual待机保留。非法/runtime/Replay/错误skip0，30局Replay通过。
- 本卡seed18020实际触发完成一次，第7回合138动作正式结束，成功Live0:3。败方无Live，不算双方Live长局门禁；总完成多2项中本卡1项，另一项是推进后的既有能力。
- 额外有界复跑同局捕获原始事件，`seed18020-detail.json`确认新Energy为`player_2-E071`、target_turn=8；对局在第7回合结束，未真正进入标记时点，不能说随机池验证了下回合跳过。该行为由原生完整回合专项/SQL验证。

下一有限独立任务为`PL!S-bp7-006:1`：底三张全为Aqours Member才给原来源绿Heart；seed18017实际入队一次但与另外两条manual共同待机，不单独归因阻塞。先确认短库/途中刷新与“全部”条件，不复用旧bottom1快照或私看预填。
PR54已批准合并上线，后续PR目标仍待已发出的明确批准；本批不改policy、不推送、新建PR、合并部署。
