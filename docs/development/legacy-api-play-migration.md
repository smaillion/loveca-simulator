# API Play 旧成果迁移与输入边界检查

## 范围与结论

2026-10-25，固定分支 `codex/continuous-development`，复用 Draft PR #54。
旧 `phase5-api-play-next` 的 16 个独有提交和 6 个未提交文件只读对比，未直接合并分支，
未修改旧工作树、卡库或 ignored 报告。本批只处理测试工具和观察视角，不改变游戏规则。

| 旧提交 | 当前情况 | 本批决定 |
|---|---|---|
| `84b50ce`、`fb5dff6`、`e729a7c`、`7d9a2b7`、`2a73073`、`53aa1c7`、`a93ed80`、`515bfef`、`9afc062` | 普通 LegalAction 模式、comparison、策略提示、差异/错误和 context review pack 已存在 | 保留当前实现；comparison 代码和测试与旧提交版本一致，不重复复制 |
| `84cc102` | comparison 已有真实 provider 预检，但 semantic 主命令缺少 CLI 开关 | 补回 `--require-real-provider`、有界 `--api-context-samples`；保留当前 PDF 输入和双 agent 模式 |
| `5f04c95`、`a73c2e5` | 当前已有更新后的策略与 max-actions 分类 | 不覆盖现有控制器 |
| `da4f585` | 当前 gap report 已是 v0.2，增加真实触发频次和 unresolved reason | 不降级到旧 v0.1 |
| `71783d8` | `PL!-bp5-014:1` 已可执行 | 不重复登记或提升状态 |
| `e8f0cda` | `PL!SP-bp4-003:1` 已正确分段并可执行 | 不搬回包含后续常时文字的旧段落 |
| `07f51e4` | `PL!-PR-015:1`、`PL!SP-PR-020:1` 当前明确保留 manual | 不继承旧 executable 标签，单列规则复核任务 |

旧 6 项 dirty 改动主要对应 `PL!-bp5-003:2`：按实际弃牌成本结果确定 μ's inspect 分支或
其他作品的控室 Live 回收分支。它依赖 branch inspection、费用原子性、UI 和 AI 同步，
不能只复制候选/registry。已建立 `legacy-cost-result-branch` 独立任务；现有第 1 段常时
技能保持不动。旧 Baton 手牌登场原型也留在独立任务，父收敛任务仍未完成。

旧版较丰富的手写 payload example 不能直接当作合法 action 生成器。后续示例必须按
当前 LegalAction 和 executor 验证，不把“取第一个候选”恢复成所谓语义测试。

## 本批实际修复

新增测试先确定性失败：semantic CLI 不认识旧版已有的两个参数；普通 API Play 和 manual
context 都会直接输出对手背面 Live 的卡号、名字和效果；其他玩家 private inspection 的
options 也会原样进入输入。

修正后：

- `--require-real-provider` 在读 PDF、建报告目录或访问 DB 前拒绝 mock，不能假称模型审查。
- 两个 CLI 的 context capture 默认均为 0，显式 opt-in 才保存；上限跨整批对局生效。
- 对手背面区域卡只暴露匿名实例和朝向，自己的背面卡及双方公开卡仍可读。
- 其他玩家的 pending choice 只保留类型/处理玩家；不将其私有查看重用为本方 manual source。
- 不修改 MatchState；变换对手未公开卡身份不能改变本方输入。
- mock 报告增加中文范围提示，并记录实际 context sample 数量。样本可能包含自己的手牌，
  仍是本地调试资料，不应公开上传。

这不是对所有网络/模型安全边界的完整审计；本批覆盖的是输入视角和采样边界。
没有读取 GPT 认证，没有调用付费模型，没有将工具测试计入技能覆盖或人工裁定。

## 本轮验证

- semantic / API comparison / gap 专项：30 项通过。
- `20 decks × 20 matches`，显式 mock、API Play + deterministic fallback、block manual、
  每局 60 action，仅用于流程 smoke，不是正式胜率/完赛验收。
- 1,200 次普通 action；engine illegal = 0；manual skip = 0；全批仅保存 3 份 context。
- 20 局均在 60 action 上限结束：无手中 Live 6、Match Point 无 Live 5、阶段推进 7、
  Live requirements 选择 1、pending effect 1。不能将其描述为 20 局完赛。
- 机器报告：`logs/continuous-api-play-20261025/semantic-summary.json`；不提交生成报告。
- 完整 registry / backend / web 和协调器门禁由持久运行记录保存，全部通过后才发布本批。

Registry 保持 `902 / 1212 = 74.42%` 可执行，310 条 manual。本批不提升任何技能标签。
下一轮先处理成本结果分支，再继续同文技能状态断言与 AI 长局验收。
