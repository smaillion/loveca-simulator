# Q124 渡辺曜登场多选验证

`PL!S-bp2-005:1` 实际完整原文“【登場】手札を1枚控え室に置いてもよい：自分のデッキの上からカードを7枚見る。その中から【heart02】か【heart04】か【heart05】を持つメンバーカードを3枚まで公開して手札に加えてもよい。残りを控え室に置く。”，revision 548、SHA-256 `1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93`，实际登场费用13。原 CardDefinition、人工登记与历史自动登记保存在 ignored `logs/q124-you-formal-20261028/inventory-before.json`。

已保存官方 Q124 直接针对本卡确认三种颜色取基本 Heart，不看 Blade Heart；这是旧 FAQ 响应，不称本轮新请求。按卡号、完整原文字节（不 strip）、revision、hash 精确绑定 `q124_you_multi_keep_exact_v1` 与已验证 `triggered_inspection_up_to_three_v1`。可选弃本人手牌一张后私看顶七张，选择零至三张合格 Member 公开入手，其他进控室。可主动辞退；不可支付时现有受保护路径不扣费、不查看并结束。短牌库先刷新；来源随后离场不取消已待机能力。

双方真实登场与 SQL Replay 检查费用、零至三张、Blade-only 和不同卡型排除、重复/超量/非候补原子拒绝、短牌库、来源受控离场和四 AI/玩家及 provider 构造隐私。人为 `heart0` 仅检验构造边界不称本卡专属官方裁定；实际卡库 Member 基本 Heart 仅 `heart01` 至 `heart06`。CONTROL 是显式测试构造，不是完整对局或自然中断；未联网 provider。界面、图文、同牌组冻结及全部门禁以 ignored `logs/q124-you-formal-20261028/final-acceptance.md` 为准。

旧人工及旧自动快照只保留历史 Replay，不称旧实现正确。registry 结构化差异只此效果，manifest 同步；不改 Card/SQL 表、卡库、默认 AI 或旧策略。登记 938/1212，274 manual，不提升 reviewed；其他 blocked 与 `PL!-pb2-010:1` 保持。未推送或部署。
