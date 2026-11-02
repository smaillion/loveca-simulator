# 正式离场与登场复原混用审计

独立审计 `printemps-mixed-formal-departure-onplay-coverage-audit` 在真实 Baton 登场中同时入队 `PL!-PR-001:1` 的旧离场能力及 `PL!-pb1-012:1` 的来源历史能力。两张卡均使用当前正式登记；人为配置 Stage 与测试卡，故这是受控状态检查，不冒充完整对局。显式开启 `qualified_source_v1` 仅供测试，正式默认策略仍为 `None`。

双方均验证两种合法待机顺序。南ことり实际复原原目标，旧穂乃果复原另一目标时，已离场旧来源没有可信证明，相关限定查询保持 `None`；明确辞退旧能力时查询仅列出可信原目标。来源进入手牌、未知牌库及同 ID 返回不补造来源证明。可信目标离区或同 ID 返回后不继承旧对象；旧能力实际复原造成的未知不因目标移区消失。`CONTROL` 是显式测试构造，不是正式卡能力。回合边界沿用已验证的限定来源原型，未知不能从当前区域或朝向猜为零。

双方四种 AI 对真实双待机实际选择并提交；替换隐藏牌 ID、名称、卡号、单位、作品与 Blade 后动作相同、输入不变。双方玩家视图及 API-play/agent provider 构造上下文检查内部来源和范围账本不泄露，未联网 provider。没有新增产品 UI；既有 UI 测试按原有能力使用。专项 30 项包括 22 份 SQL Replay，详细清单与最终门禁以 ignored `logs/printemps-mixed-formal-20261028/final-acceptance.md` 为准。

本审计没有修改卡库、registry、产品逻辑、SQL 结构、默认策略或旧 Replay。它不裁定 `PL!-PR-001:1` 能否选对手或已 Active 成员，不称现有旧登记正确，也不解除 `PL!-pb2-010:1` 和其他 blocked。正式来源历史仍 4/5，不增加 manual 或 reviewed 完成数。
