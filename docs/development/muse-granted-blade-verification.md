# 星空凛：临时获得μ's常时Blade能力

2026-10-27，固定`codex/continuous-development`本地实现；本批不推送、不新建PR、不合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLL02/PL!-pb2-005-PP.png" alt="星空凛 PL!-pb2-005" width="220">

## 绑定与官方依据

- `PL!-pb2-005:1`，星空凛，cost5，原始Blade为0；revision978，hash `e972ec2ccacf722aa4a5f2ff2f55ece68dabbc676d988590c3d27079da601682`。
- 完整日文：`【登場】自分の成功ライブカード置き場に【スコア】を持つ『μ's』のカードがある場合、ライブ終了時まで、「【常時】自分のステージにいる『μ's』のメンバーは、【ブレード】を得る。」を得る。`
- generator同时核对完整文本、effect ID对应卡号、revision和hash；不做模糊前缀绑定。
- 已先复现原生登场仍产生mandatory manual的红测试；原池seed18029也真实因此停止，不按持卡频率挑选。
- 固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。2.7及2.12.2用于Blade Heart图标与群组；4.1.4/9.7.7用于来源移区；9.9.1–9.9.3用于常时能力和区域动态信息；8.4.11用于Live结束。
- [官方Q112与Q78](https://llofficial-cardgame.com/question/searchresults/)：Q112确认得分等特殊图标属于Blade Heart；Q78说明获得常时能力的来源离场后，该能力不继续生效。Q78不是本卡专属FAQ，本实现结合通则推导，不冒充本卡专属裁定。
- 通过官方公开API读取282条published记录：`https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published`，响应SHA256 `b05d8f59209cbfc508e20095c8c2e0a1f558365a403f8b53922995949811ca0a`。原始响应和实际官方卡图保存在本轮logs；未检出本卡专属条目不代表FAQ不存在。

## 实现范围

新增受限operation `grant_muse_blade_aura_if_success_score_icon` 与来源policy `original_onplay_muse_blade_aura`，只允许无费用、无选择、强制登场和Live期限的固定Blade+1授予。

1. 结算时检查本人成功区的μ's卡是否持有特殊得分Blade Heart图标。普通Live数值score、抽牌/ALL等图标、其他群组、其他区域及对方成功区都不能代替。
2. μ's使用标准群组`work_key=love_live`，不能误用lily_white或任意unit字符串。存在性条件不涉及lily white两枚计数的未解决依赖。
3. 条件成立时，在原来源对象上保存带policy的Live期常时能力标记。有效Blade和实际Yell共用动态计算，后续入场的己方μ's Member也立即获得+1；不是当时场面的逐个一次性加成。
4. 来源自身也可获得加成，多个来源叠加。来源Wait不关闭常时能力，但Wait Member自身不提供Yell；对方、手牌和附属卡不作为受益的顶层Stage Member。
5. 成功区条件只在授予时判断；授予后移动条件卡不撤销常时能力。来源离场会撤销它；同ID返回不继承旧标记。场内Position Change不改变对象，继续生效。
6. 新标记即使在旧的空stage_departure_policy快照中也按自身policy清理；旧标记、旧无policy操作及旧manual Replay行为不变。未匹配policy、错误duration/amount或无来源的标记不提供加成。
7. Live结束清理该常时能力。来源在结算前离场或离场返回时，能力仍完成处理但不向新对象授予常时能力。

Card/SQL schema和默认AI未改。新受限effect snapshot允许记录该语义，不是通用任意常时能力DSL。

## 保留的未确认边界

不声称解决重叠/继承。完整公开来源绑定的重叠门禁遇到这个新授予类型时，以`overlap_granted_static_ability_requires_review`明确拒绝，原生Action测试验证在支付前拒绝且原状态不变。旧无该门禁的历史snapshot仍按原规则重放；六条复杂重叠卡不因此晋级。

## 验证

- 75项专项：精确绑定、数值score与特殊图标、构造Member/Live区别、群组/区域/所有者、结算前条件改变、动态后入场、多来源叠加、来源离场返回/换位、实际Yell及Live结束。
- SQL包含原生登场加测试CONTROL能力干涉的来源离场/返回/换位、条件增减和新旧manual快照；CONTROL只用于测试，不是正式卡能力或生产日志。
- 四AI v0/v1/v1.1/v1.2实际出牌与待机选择、隐藏身份替换不变和不改输入；本人/对方完整响应保护；保留上一轮manual来源句柄兼容保护。
- 234项来源/重叠相关回归通过；3项双语原生UI结果状态、243前端及生产构建通过。
- 212项图文验证全部通过，其中174动态状态/38登记契约，本卡新增6动态场景。它们是可复核程序证据，不等于完整人工裁定。
- 独立SQL回归有一次未设置工作区TEMP导致21项夹具初始化错误，未当作代码失败绕过；正确TEMP/TMP下同组234项全部通过。正式门禁由协调器重新运行全部required_profiles，不拼接旧结果。
- registry结构化差异只有本卡；还原其他条目的原有键序，避免无关格式改动。登记922/1212（76.07%）、290manual，不提升人工reviewed。

最终checkpoint后执行control/registry/backend/web及pre-push。全部通过才本地commit和complete；真实源码指纹、命令与退出码记录在主仓库`.tmp/development-loop/runs/`本轮result.json，不改源码后复用旧绿色检查。

## 源码绑定冻结对局

`logs/muse-granted-blade-audit-20261027/frozen-30/`，同前轮30牌组、seed18000–18029、v1.2/block/max500。
诊断指纹与当前源码、provenance及全部30条摘要一致：`ad79e0672c94cdf8b67222d7ac2405b06e2957c3be4485137e26d03d54762b59`。

- 仍12正式完赛/18人工停止；185/187可执行完成，2项随其他manual待机保留；无非法/runtime/Replay/错误skip，30局Replay通过。
- 凛在seed18029真实触发并完成两次。额外复跑同一局捕获原始事件，证据`seed18029-detail.json`：两次condition_met=false、aura_delta=0，不能说随机池验证了正条件加成；正条件由专项及SQL真实状态覆盖。
- 该局从第2回合30动作推进至第4回合77动作，双方成功Live为1:1，最后在`PL!-pb2-010:1`人工待机。不是新增完赛或beta/长局门禁达标。
- 总可执行完成增加的5项并非全是本卡，本卡2项，另3项来自对局继续推进后的既有能力。

下一有限独立切片为seed18027真实待机的`PL!S-bp7-015:1`：Live开始牌库底一张置控室，若Live则仅原来源Heart02+1至Live结束。先核对底部移动/刷新与来源对象，不能套用私看预先刷新。
后续PR目标仍待明确批准，policy继续固定54，不推送或创建新PR，任何后续合并和上线另行批准。
