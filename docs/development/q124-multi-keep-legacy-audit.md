# Q124 多张检索旧快照审计

本审计保留 `PL!S-bp2-005:1` 的正式人工登记，不将旧执行行为当作整卡已裁定。卡文 revision 548，SHA-256 `1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93`。此前保存的官方 Q124 直接针对本卡，说明指定颜色只看基本 Heart、不参照 Blade Heart；这是该筛选边界的证据，不代表全部费用、刷新和公开时点均已完整裁定。原始 FAQ 文件和 hash 见 ignored `logs/q124-legacy-executor-20261028/final-acceptance.md`；没有把旧响应称作本轮新请求。

历史 fixture 按旧登记重建；单独将其标准化模型与隔离前 commit `8fe260f7f34cd11d589e1f697e5add81c2c621fe` 的登记逐字段比较，完全相同。测试不依赖 Git 历史，以兼容浅克隆；构造状态不冒充完整正式对局。双方实际支付一次弃牌后私看七张，检验基本 Heart、排除 Blade-only、选 0 至 3 张、实际公开所选以及其余进入控室。私看期间对手视图既不展示牌面映射，也不包含七张内部实例引用。16 份 SQL Replay、四 AI 双方的实际费用与后续选择、对手隐藏手牌替换后的后续决策不变和输入不变均有检查。API-play 与 agent provider 为构造 context，不调用联网服务。

四项前端检查仅验证历史快照 0 至 3 张的显式选择及非法候补禁用；当前正式人工入口仍由既有 UI 测试保护，未新增产品 UI。短牌库刷新、非法重复/超量和费用失败由先前独立历史回归覆盖，不算本轮新 SQL。未改卡库、registry、引擎、SQL schema、默认 AI 或旧 Replay；Q124 不自动提升 manual/reviewed，也不解除其他 blocked。完整同源码门禁和最终状态以 ignored 验收记录为准。
