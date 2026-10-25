# 卡面选择 CI 回归修复

## 失败证据

PR #54，GitHub Actions `40174561978`，frontend job `121112341452`：
`switches the card face printing inside the deck-builder preview dialog` 期望
`LL-TEST-001-SR`，实际读到默认 `LL-TEST-001-PR`。不能仅靠重跑忽略失败。

## 可重复复现

增加受控组件测试：打开包含 PR / SR / R 的详情，选择 SR，再同步更新摘要默认值为 R 并
反转印刷版列表。旧实现确定性失败，得到 R 而非 SR；这复现了异步默认值覆盖显式选择的
缺陷家族。该状态测试不声称还原了原 Linux runner 的全部调度顺序。

根因是用 effect 将默认印刷版同步到同一个用户选择 state。默认值晚到或变化时，会覆盖
已经完成的人工选择。本批将显式选择与派生默认值分开：先取有效的人工选择，否则使用
当前摘要默认值，再退回第一张印刷版。不再用异步 effect 回写用户选择。

详情弹窗按 card_code 重建；等待另一张卡的详情时不展示上一张卡的缓存详情。

## 验收

- 受控默认值更新不会覆盖 SR 选择，图片 URL 与选择值一致。
- 用户尚未选择时，晚到的摘要默认值仍生效。
- 切换到另一张卡时，选择与图片从该卡的默认印刷版初始化。
- 保留原 App 集成测试，执行全部 Vitest 和 production build，真实结果由持续协调器保存。
- 不改变 API、数据库、decklist.v0、技能 registry 或 MatchState。
- 继续使用原分支和 PR #54，不合并或部署。
