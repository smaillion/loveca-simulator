# Aqours：先选择成员，再判断Blade六与来源Live得分

## 精确范围

`PL!S-bp3-025:1`，revision504，日文全文hash：
`0016b3bd6db1b30ca828f2dec99189841d606578a9d974ba1aaf919a52510cbb`。

> 【ライブ開始時】自分のステージにいる『Aqours』のメンバー1人を選ぶ。そのメンバーが持つ【ブレード】が6つ以上の場合、このカードのスコアを＋１する。

旧登记已真实复现两项错误：Blade5被预先过滤；Blade6结算生成玩家全局score，而不是只给来源Live加分。
新快照采用独立受限policy及operation，先选己方Stage顶层Aqours成员，结算时读取有效Blade。
低Blade仍可选择但不加分；无候补时明确选择0。来源Live离场后，同ID返回不重新绑定原对象；同Live Area移动不视作离场。

固定本地综合规则ver.1.06的SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
依据2.8.1、2.10.1、4.1.4、8.3.8、8.4.2、9.6.3.1/3、9.9.1.5；不把Member专用条款直接泛化到Live，不猜测FAQ。

## 定向验证

- 63项专用测试，连同已有技能及图文报告回归共266项通过。
- 验证Blade0/5/6/7、Active/Wait、临时/已支持常时修正、候补零张、错误作品/区域/附属/对手对象及非法选择原子性。
- 来源离场/同ID返回/原区域移动、多个Live分别计分、成功/失败Live清理有真实状态断言。
- 新旧SQL Replay、待机对象恢复、四AI及双方隐藏身份不变有断言；旧快照保留历史行为，不追改旧Replay。
- 全局双语图文191项全部通过：153项动态状态、38项契约，其中新增4项本卡真实状态场景。
- 两处无关LL登记仅恢复本轮误写；结构化对比确认registry仅本目标变化，strict integrity为0错误/0警告，manifest已重新生成。

## 冻结30局诊断

证据：`logs/aqours-blade-six-score-final-20261027/final-frozen-30/`。
复用原30套合法技能密集牌组，seed18000至18029，AI v1.2、manual=block、每局最多500动作。
provenance及全部30条逐局摘要与当前源码指纹一致：
`30f611b14b8092d4639ec187c385a58d0bd3f794b14b0e1fef4665f1f5b99a1a`。

- 9局正式完赛、21局明确mandatory manual停止，与上一批相同，不宣称提升完赛率。
- 可执行技能158/160完成，2个待机跟随其他人工技能保留；没有静默跳过。
- 非法动作、runtime、Replay及错误skip均为0。全部30局Replay断言通过。
- 本卡实际入队0次，不能用随机局冒充本卡触发验收；本卡依据上述定向状态/SQL/四AI/UI测试。
- 仍不是双方Live长局验收，也不是beta或完整人工裁定。

登记保持918/1212（75.74%）、294 manual；本轮是修正旧可执行项，不新增可执行率，不提升reviewed。
不改Card/SQLite schema、默认AI v1.1或未确认技能。

## 工程门禁与发布边界

最终control/registry/backend/web由协调器独立执行，源码指纹、命令、退出码及日志保存在主仓库`.tmp/development-loop/runs/`；本报告不代替最终门禁授权。
同一源码另执行manifest及AI-DLC固定文件pre-push检查。任何后续源码变化必须重新验收。
PR54已批准合并上线，但不包含本地本切片；policy仍固定54，新发布目标的明确审批另行等待，不推送、不新建PR、不合并、不部署。
下一有限任务为`PL!-pb2-041:2`的lily white成功区两张条件与来源Live score+1，第一段继续manual。
