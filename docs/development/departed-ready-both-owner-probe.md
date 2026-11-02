# 离场来源、双方目标复原原型

有限任务 `departed-ready-both-owner-target-provenance-probe` 仅设计未登记的 `ready_member_from_departed_both_provenance_v2`，不绑定 PL!-PR-001 或任何正式卡，不裁定该卡目标语义。仅本人原Stage顶层Member实际进入本人控室后触发，无费用、可选，明确策略 `public_departed_ready_both_one` 从双方当前公开Stage顶层Member选择0至1名，允许Wait或已Active。静态形状固定，不接受条件、混合费用、附属目标、后续选择或其他操作；策略不能单独用于其他能力、费用或后续选择。

沿用离场前捕获及入队后的真实invocation/effect/来源LKI绑定，来源隐藏或同ID返回不覆盖原信息；实际Wait到Active才写目标所有者和原对象token，已Active不记复原。双方目标离区后原token失效，同ID返回不继承；限定来源查询须显式指定真实来源所有者、效果玩家与目标所有者。旧本人Wait v1、新旧快照及Replay不自动升级，旧coverage未知不猜为零。

专项覆盖双方来源及目标拥有者、Wait/Active/零张/拒绝、来源隐藏与返回、目标离区和返回、伪造费用与重复选择原子拒绝、真实SQL Replay、四AI实际后续选择及双方玩家/API-play/provider构造隐私。CONTROL是显式测试构造，非正式能力或自然中断；未联网provider。原生UI仅验证公开对手候补与有无来源卡面提交，不冒充完整对局或人工裁定。专项数量、完整门禁及冻结结果以ignored `logs/departed-ready-both-probe-20261028/final-acceptance.md` 为准。

PL!-PR-001:1 的目标范围仍需独立官方依据；旧登记仍在、不能称其正确，消费者及其他blocked不恢复，正式历史生产者仍3/5，登记和reviewed不变。本批不推送、发布或部署。
