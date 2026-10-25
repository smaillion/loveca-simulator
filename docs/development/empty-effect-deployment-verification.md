# 空区域效果登场修正记录

## 结论

本轮复核上一轮发现的 10 条旧登记：**修正 6 条，退回手动 4 条**。
可执行登记由 903 降至 **899 / 1212（74.17%）**，manual 为 **313**。
这是正确性修正，不是新扩充覆盖；所有条目仍未提升为 `reviewed_executable`。

规则来源为本地综合规则 `LoveLiveTCG_cr_1.06_260428.pdf`，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
依据 4.3.2.3，无特别说明时以 Active 放入；9.6.2.4.2.1 要求效果登场同样遵守
9.6.2.1.2 的区域选择；11.4.2 要求从非 Stage 区域登场时触发登場能力。
本轮仅实现原文明确写有「メンバーのいないエリア」的子集，不宣称完成全部区域规则。

## 六张卡逐项结果

| 卡牌与卡面（官方链接） | 原文中的处理 | 本轮实际断言 |
|---|---|---|
| `PL!-bp6-003:2`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!-bp6-003-R2.png" width="110" alt="PL!-bp6-003"> | ライブ成功時；从自身附属卡选择 cost 2 以下 μ's Member，空区域登场 | 仅移走选中的附属卡；Active / face-up；新 Member 的登場能力入队；不记为 Baton |
| `PL!HS-bp5-002:2`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP05/PL!HS-bp5-002-R2.png" width="110" alt="PL!HS-bp5-002"> | 起動；支付 2 Energy；控室 cost 2 以下 Member，空区域登场 | 支付 Energy 变 Wait；目标离开控室进入所选空区域并 Active；非法 ID / 区域不支付费用 |
| `PL!HS-bp5-022:1`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP05/PL!HS-bp5-022-L.png" width="110" alt="PL!HS-bp5-022"> | ライブ開始時；支付 2 Energy；Edel Note 条件；二选一 | Live 来源与满足 9 费用条件的 Stage Member 分开建模；满场保留减 Heart 分支并核对该 Live 有效需求 2→1；登场分支支付后选目标和区域，目标消失时记录原因 |
| `PL!HS-bp6-016:1`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP06/PL!HS-bp6-016-R.png" width="110" alt="PL!HS-bp6-016"> | 起動；支付 4 Energy；控室 cost 4 以下蓮ノ空 Member | 合法目标及区域来自引擎；费用和登场同一 Action 验证；Active；Replay 结果一致 |
| `PL!S-sd1-006:1`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/SSD01/PL!S-sd1-006-SD.png" width="110" alt="PL!S-sd1-006"> | 登場；弃 1 手牌；控室 cost 2 以下 Aqours Member | 第一阶段只选弃牌，不混入区域；费用后重新选择目标和位置；目标不可用时记录无法适用原因，不重复支付 |
| `PL!SP-bp4-004:2`<br><img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP04/PL!SP-bp4-004-R2.png" width="110" alt="PL!SP-bp4-004"> | 登場 / センター / 两名 Liella! Baton 条件；先抽 2，再控室登场 | 将选择后移至抽牌完成；先拿到 2 张，再从新状态选卡和空区域；满场仍完成抽牌，不产生无解选择 |

上述测试使用真实 registry 的 revision / hash / 条件与操作定义，在小型确定性局面中逐步执行。
不是仅检查 JSON 字段；核对区间移动、朝向、费用、事件、原状态不变和序列化重放结果。
图像取自当前本地卡库记录的官方链接，不打包或更改卡图。

## UI、AI 与旧数据

- LegalAction 增加 `deployment_choice`，复用已有按候选卡提供位置列表的契约；不增加 HTTP 端点。
- UI 选目标后显示“登場エリア”，不能提交没有合法位置的选择；不打开 generic manual 面板。
- `simple_ai_v0` / `v1` / `v1_1` 和 deterministic sandbox 都提交引擎提供的位置。
  AI 仅给结构化登场一个有界资源估值，不读取对手手牌，不修改规则状态。
- 新登记显式设置 `orientation=active`；旧 snapshot 缺失 orientation 时仍按旧 Wait 执行。
  不改 Card Schema、runtime SQLite schema、decklist 或 controllers API。
- 新 Member 登场后重新入队其登場能力；不伪装为 Baton。对手只收到公开区与公开结果，不收到己方手牌。

## 四条退回 manual 的原因

`PL!N-pb1-013:1` / `015:1` / `017:1` / `023:1` 的原文是从手牌登场指定名字的 cost 4 以下
Member，没有“空区域”限定。原实现只允许空区域且默认 Wait，不能继续算作正确支持。
候选生成器删除了这四个错误的 executable pattern，保留 exact-text 对应的 timing/manual 登记。
不自动收取其费用；gap report 记录
`occupied_stage_deployment_and_current_member_entry_history_not_modeled`。

下一切片仍须实现：当前本回合入场 Member 身份随 Position / Formation 移动后的区域限制，
合法的已占用区域替换、重复 Member 与附属卡清理、离场和登場的触发顺序。
完成后再验证这四条及 `PL!-PR-015:1` / `PL!SP-PR-020:1`。本轮不提前恢复它们的 executable 状态。

## 验证证据与边界

- 新增 37 项真实局面 / AI / Replay / 隐藏信息与候选契约测试，包含实际起动入口的费用只支付一次与 Edel Note 的 9 费用边界；不是将字段检查当作完整规则审查。
- 前端增加两个位置提交 / 无位置禁用测试；完整前后端、manifest 和结构完整性由协调器
  `check --profiles control registry backend web` 保存源码指纹绑定的证据。
- 完整门禁实测：pytest **592 passed**（另有既存 Starlette TestClient 依赖警告 1 条）、
  Vitest **76 passed**、TypeScript / production build 通过，协调器 **18 passed**，
  manifest 与 registry strict 为 **0 errors / 0 warnings**。未将该依赖警告作为规则失败。
- Playwright 对实际技能选择组件在 390×844、430×932、1280×1024 下检查：无横向溢出，确认按钮在视口内，提交包含目标卡和 `right` 区域，页面错误为 0。
  已查看截图；记录在 `logs/continuous-empty-deployment-ui-20261025/`。这是独立组件检查，不冒充整局手机端操作验收。
- 最终代码 20 Deck 固定池的 10 局 AI-vs-AI 全部正式完赛，平均 **7.2** 回合、最长 **19**；
  illegal / blocker / skipped effect / Replay 序列化错误均为 0。
  仅 **7/10** 满足 10 回合内且双方均有成功 Live，未声称完成“10 局严格合格”目标。
  与上一批平均 7.1、最长 18 相比，本轮没有策略提升结论，长局问题保留在后续队列。
- 机器报告：`logs/continuous-empty-deployment-ai-20261025/`；不提交生成日志。
- 自动断言和图文记录不代替人工裁定，也不证明 FAQ / continuous / replacement 全覆盖。

所有改动仅进入固定开发分支及 Draft PR #54，未合并、未部署，等待维护者回程审核。
