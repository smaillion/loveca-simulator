# 等待房间的规则身份与元数据清理

## 本轮结论

完成 `legacy-ruleset-match-replay` 剩余的等待房间版本固定，仍使用同一continuous分支与Draft PR #54。
未合并、未部署、未修改生产数据，也未触碰旧工作树的44/6项dirty成果或ignored报告。
本批是Ruleset兼容性与垃圾清理契约，不增加技能支持，登记仍 **900/1212（74.26%），312 manual**。
这些测试不计入75项核心规则矩阵或人工裁定数量。

## 先复现，再修改

两项红测确认：`POST /api/rooms` 原先会忽略空或未知 `ruleset_id`，返回200并保存房间。
旧原型只在hosted_rooms加一列ID，不能固定同名Profile的hash与裁定包，也没有版本变化后拒绝加入的完整验证。
本批没有复制其ALTER TABLE，而是复用已经存在的通用runtime_metadata键值表。

## 生命周期

1. 创建房间：使用与Match相同的resolver，验证当前Profile及引擎支持版本；旧请求可省略ID。
2. 同一事务保存room和四字段RulesetIdentity；任意插入失败都不能留下半条房间记录。
3. 等待与刷新：从SQLite恢复原始身份，不用当前Profile回写旧值。
4. Guest加入：将完整expected identity交给MatchService；重新解析当前支持，并在任何Match写入前比较。
5. 不一致：409 `ruleset_mismatch`，要求重新创建房间；不修改原room、deck、token或match数据。
6. 一致：新Match继承完全相同的身份，继续原生action、手牌隐藏与Replay。
7. 用户退出/TTL到期：room先expired，grace内保留身份；删除room时清理对应与孤立专用键。

```text
runtime_metadata
  schema_version                       -> 原值保留
  hosted_room_ruleset:ABC123            -> 小型规则JSON
  其他模块的键                          -> 不触碰
```

JSON只包含 `ruleset_id`、`rule_version`、`ruleset_fingerprint`、`ruling_pack_version`。
不存PDF全文、卡牌、deck、token或认证资料；每房间不足1KB，不另加网络轮询。
room/deck JSON格式、SQLite schema SQL和schema_version均保持不变。
清理使用精确前缀比较，不使用把下划线当通配符的LIKE，避免误删其他模块键。

## 真实 SQLite / API 测试

`tests/test_room_ruleset_binding.py`：23项，配合已有Match/Replay和web测试回归。

| 场景 | 状态断言 |
|---|---|
| 默认 / 显式Profile创建 | 四字段与当前Profile相同，表结构不变，deck JSON原样 |
| 未知 / 空ID | 从原来的200改为400，数据库完整dump不变 |
| 已固定ID、rule version、hash、ruling pack不同 | 加入409，不能生成孤立Match |
| 服务端同名Profile变化、新Profile、引擎不支持的新规则版 | 不重绑等待房间，重新加入拒绝 |
| 正常加入与换牌 | 原生room action成功，Host/Guest只看己方手牌，SQL Replay身份一致并验证成功 |
| 新API实例恢复 | 同一SQLite中的等待身份不丢失，另一实例可加入、原实例正确读取最新房间 |
| 旧房间没有新键 | 仍按原逻辑加入当前规则；room身份保持null，不补造创建历史 |
| 元数据损坏 / 不完整 | 清楚返回400，无白屏或静默采用当前规则，不修改保存数据 |
| active / expired房间重复加入 | 拒绝前不再创建新Match |
| metadata插入受控失败 | SQLite事务回滚，room与identity都不存在 |
| expired grace / 最终删除 | grace内保留，删除后清理；schema_version和相似但不属于本模块的键保留 |
| 旧room-only repository | 无runtime_metadata也保留旧调用；请求新绑定则在写入前明确拒绝，不建新表 |

没有新增endpoint或公开房间列表；现有客户端可忽略新增的可选 `ruleset_identity` 字段。
历史规则不兼容的Match仍按[前批只读Replay约定](./ruleset-match-replay-verification.md)处理。

## 边界与下一步

- 原旧房间没有可验证的创建时指纹；不能假装它们已经获得同等历史保证。
- 本批修复串行重复加入产生孤立Match，但没有宣称解决多个Guest并发抢同一房间的全部事务协议。
- 未做完整客户端app/catalog/registry握手，也不等同全卡官方规则认证。
- 下一项可迁移核心规则矩阵和End Phase重复检查；未确认的重叠、继承、FAQ语义继续manual。
- 工程证据由协调器源码指纹关联：全量Python、Vitest、构建、manifest与registry strict；不使用旧分支的通过声明。
