# Printemps 复原来源覆盖审计

按实际 CardDefinition 的 `unit_keys` 和已登记直接复原操作盘点，五条分别为 `PL!-PR-001:1`、`PL!-bp3-001:2`、`PL!-bp6-008:1`、`PL!-pb1-012:1`、`PL!-pb1-028:1`。实际卡文 SHA256、revision、完整卡定义及登记保存在 ignored 审计目录 `logs/printemps-four-producer-coverage-20261028/inventory.json`。四条使用可记录来源的操作；`PL!-PR-001:1` 仍使用旧 `ready_member`。这不是整个卡池、manual、获得能力或复杂继承的覆盖证明。

新增审计测试以双方真实 WAO-WAO 快照复原 0、1、3 名，并在显式开启的限定来源策略下查询与 SQL Replay 对照。另以双方真实 `PL!-PR-001:1` Baton 离场触发旧操作，在同一快照中存在可信正式生产者定义时复原本人目标，验证无来源证据导致限定查询为未知，而不是零。测试中开启策略不代表正式对局默认启用；当前默认仍为 `None`。现有限定范围、旧快照、晚启用、目标对象与来源隐藏测试继续作为独立边界证据，不将构造来源或 CONTROL 称作生产对局。

`PL!-PR-001:1` 的目标所有者和已 Active 资格仍未获得完整官方裁定，旧登记保留不代表其正确；不得以 4/5 解除 `PL!-pb2-010:1` 的消费者依赖。未改变卡库、登记、产品逻辑或 SQL 表，也未提升 manual/reviewed。完整门禁、SQL、既有冻结和提交验收以 ignored `logs/printemps-four-producer-coverage-20261028/final-acceptance.md` 为准。
