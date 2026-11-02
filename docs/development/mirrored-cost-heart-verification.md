# 安養寺姫芽：常时正面费用镜像修复

2026-10-27。固定工作树与`codex/continuous-development`，限定本地实现与验收，不推送或部署。

## 验收入口

本轮恢复同一镜像任务，保留原实现与20项现场改动，只重新绑定完整control/registry/backend/web及pre-push。最终源码指纹、真实日志、验收结论和本地提交结果见[本轮验收记录](../../logs/mirrored-cost-heart-20261027/final-acceptance.md)。只有同轮全部门禁通过且diff审查完成，才提交并标记done；不拼接旧绿色证据。下方未完成说明保留为上轮历史，不作为最新任务状态。

## 历史检查点：上轮未完成全量验收

完整检查`20261027T110711-2e4162`的web/control/registry通过（273前端、构建、50控制、strict零错误零警告），但backend为4527通过/1失败。唯一失败为`test_effect_candidate_discovery_is_review_only_after_registry_update`仍要求旧生成器标识`static_opposing_member_higher_cost_heart01`；本轮有意新增精确绑定的`static_mirrored_front_cost_heart_v1`替代该卡旧模式，已同步契约断言，没有删除断言或放宽集合要求。

这一测试修改使旧完整检查失效。下一轮必须显式恢复`static-mirrored-opponent-cost-source-heart`，读取本报告并在当前源码重新运行全部control/registry/backend/web及pre-push；不能拼接旧4527通过或web绿色后complete。受每轮45分钟限制，本轮保留全部WIP、release租约，不提交或领取下个业务任务。应用诊断指纹未因测试/文档修改变化，冻结池无需无变化重跑。

修正全局契约后，原失败项加105专项、37边界及图文契约合计144项通过，证据`logs/mirrored-cost-heart-20261027/targeted-contract-final.xml`。这是定向复验，不是4528后端全绿或任务done。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBHS/PL!HS-pb1-014-P2.png" alt="安養寺姫芽 PL!HS-pb1-014" width="220">

## 身份与范围

仅修复原本已可执行的`PL!HS-pb1-014:2`，不是manual晋级。完整双段revision130、hash `542b68ba2435dd4aafaaf2f88d9fc0d75cf33321d245934e772175c21e009591`精确匹配；cost9、Blade4。常时正文：

> 【常時】このメンバーの正面のエリアにいる相手のメンバーのコストが、このメンバーのコストより高いかぎり、【heart01】を得る。

第1登场段完全未改，仍manual/blocked：`fixed_front_same_area_target_eligibility_and_source_lki_unmodeled`。镜像修复不解决同区域目标资格或原来源最后位置模型，不自动requeue。登记927/1212（76.49%）、285manual，不提升reviewed。

## 依据与红测试

固定官方PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。4.5.7.1明确左右正面镜像、中央对中央；常时能力按9.9.1的当前信息计算。无需猜测本卡专属FAQ。

先写八项原生`play_member`红测试：双方角色乘左右两位置，来源cost9、同名栏4/真正正面10应粉Heart+1；反向同名栏10/正面4应+0。旧实现八项均失败，证据`logs/mirrored-cost-heart-20261027/native-red.xml`。上轮历史证据及第一段边界见[原审计](mirakura-front-position-unresolved.md)。

## 有界实现与回放

- 新条件`opposing_member_cost_greater_than_source_mirrored_v1=true`只接受固定常时/自动/非可选/无费用选择、game持续、单个粉Heart+1的快照；False、数字/字符串冒充、附加条件和扩大动作等均拒绝。
- generator按本卡全文/revision/hash精确绑定。registry结构化diff仅第2段`condition`，其余字段、第1段与其他卡逐项保持；manifest重生成。
- 引擎新条件读取left→对手right、center→对手center、right→对手left。旧`opposing_member_cost_greater_than_source`仍按同名栏读取，仅为旧snapshot确定性Replay兼容，不声称旧规则正确。
- 位置交换、Formation、对手组移动后实时重算；附属高费卡不代替顶层Member，Wait不取消Heart条件。来源离场不生效，返回后按新对象当前位置重新计算，不保存一次性modifier，也不套用登场段LKI。
- Card/SQL schema、默认AI、投影授权和owner manual提交句柄均不改。

## 真实验收

`tests/test_mirrored_cost_heart.py`105项专项；连同原边界37项和图文契约共143项通过。46种SQL覆盖新旧快照/双方来源Position、Formation、离场和返回，双方三位置乘Active/Wait及正反条件的真实Yell，另有双方三位置对手组交换。人工Position调整明确是测试中的人工入口，不冒充已实现第一段。独立Yell夹具在有效公开场面执行原生`advance_phase`，不伪造第一段自动完成。

四AI规则视图得到与实际Yell相同的粉Heart总数，仍因第1段正确返回`no_safe_ai_action`。隐藏卡名/卡号/实例ID/费用替换不改变规则评价或决策，不修改输入。完整双视角保留公开Yell结果，不通过静态条件公开当前手牌或未翻开的牌库对象。

247项双语图文（209动态/38契约）全部通过，本卡新增五个固定常时计算场景，明确不是原生Action或完整人工裁定。另有两项原生UI集成测试读取服务器给出的粉Heart2/3并切换中日显示；前端不另算镜像，也不增加人工补正。测试使用受控响应，不是生产日志或真实对局截图。

完整control/registry/backend/web必须在最终checkpoint后一次验收，最终授权证据以主仓库`.tmp/development-loop/runs/`中该轮`result.json`为准。先前夹具的空人工调整、属性名/观察接口参数及UI牌组/阶段/颜色预期错误已修正，不能把失败或中间绿色拼成最终门禁。

首次完整检查`20261027T110550-fdd0e2`的273前端单测通过，但build拒绝新UI测试`ByRoleOptions`不支持的`exact`参数。已删除多余参数，不放宽类型；该次检查仅到web即失败，不作为最终证据。之后重新checkpoint并执行全部四组，应用诊断指纹不受这一测试修改影响。

## 冻结池与限度

最终证据`logs/mirrored-cost-heart-20261027/frozen-30-final/`；`frozen-30/`为图文步骤说明补正前的中间源码，不作最终依据。同原30牌组、seed18000–18029、v1.2/block/max500，牌组、当前应用指纹、provenance及全部逐局摘要一致，详见`evidence-binding.json`。

最终应用诊断指纹：`c70e9b6d70bf86e198000b62804a0b05f3737b8a02a5ba1725d63fca32e9e771`。保留的`native-old/mirror.sqlite3`与`native-new/mirror.sqlite3`分别重放同一原生登场/人工位置变化，证明旧同栏与新镜像快照都可重放但结果有意不同。

仍15正式完赛/15人工停止、208/210可执行待机完成、两项随其他manual保留；非法/runtime/Replay/错误skip均零，30局Replay通过。seed18005仍在第5回合第1段manual停止，本轮没有从冻结摘要取得第2段正条件Yell事件，不宣称随机正条件覆盖、技能执行率或完赛改善，更不代表双方Live长局/beta达标。

## 下一项与发布边界

当前镜像任务必须先恢复并完成全部验收。之后下一独立有限任务才是审计`PL!SP-bp5-010:1`双方中央成员各自Position Change：冻结seed18013第6回合117动作实际manual。先核对官方Q223与双方顺序、选择/交换同时性，不代对手选择，不直接扩大旧多玩家快照。未确认就保留manual及unresolved。

PR54已获批准合并并发布。后续PR目标仍待此前精确审批，不改policy、不推送或创建PR，不复用一次合并上线许可。旧dirty工作树、stash及ignored报告均保留。
