# 新卡自身Wait起动：状态与AI验证

## 本轮支持

仅登记以下两段精确日文技能至 `test_validated_executable`，不提升人工 `reviewed`。
卡库/SQLite schema、decklist、控制器API及默认AI策略不变；旧dirty工作树与原报告未改。

| 卡牌 | revision | 技能与处理顺序 | 限制 |
| --- | ---: | --- | --- |
| `PL!SP-bp7-008:1` 若菜四季 | 895 | 自身先支付Wait费用，再抽1张，无后续选择 | 无原文“回合1次”，不能擅加；但Wait状态不能再次支付 |
| `PL!N-bp7-023:1` ミア・テイラー | 886 | 自身先Wait，抽2张，再从抽完后的手牌选2张去控室 | 回合1次；可以弃刚抽到的牌，选择阶段不再次抽牌/支付 |

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!SP-bp7-008-P.png" width="150" alt="若菜四季，第一段起动能力本轮适配">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-023-N.png" width="150" alt="ミア・テイラー，自身Wait后抽弃">

图片为本地卡库保存的官方链接，不抓取或打包图片。

四季第一段原文：

> 【起動】このメンバーをウェイトにする：カードを1枚引く。

ミア原文：

> 【起動】【ターン1回】このメンバーをウェイトにする：カードを2枚引き、手札を2枚控え室に置く。

四季完整原文hash为 `1105aa0ae1ef0d65a9c9856842d388d33aded5b27ba4a34639c225ba1eeb679b`；
ミア为 `2ccbbabf1b733c37305b1210c25e95d59a6e2c900ff3ed047aed4d800072b15e`。
测试从实际卡库加载CardDefinition，核对revision/hash及完整技能段，不模糊匹配近似文本。

## 官方依据与真实断言

固定本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
9.4.1/9.4.2规定费用与支付，9.4.2.3规定不能部分支付；9.5.2与Main阶段规定发动时点。
费用先于效果，抽后弃牌按文字顺序选择；次数限制以各自原文为准，不复制到同类无次数卡。

`tests/test_activated_wait_draw.py` 的36项定向测试包含：

- 实际source卡和当前技能段的精确身份、费用及次数限制。
- 自己Main之外、对手回合、来源已Wait时拒绝，原状态hash不变。
- 初始手牌2张：四季变3张；ミア先变4张，选刚抽到的2张后回到2张，牌库只减少2张。
- 少选、多选、重复、对手手牌ID均被拒绝，已完成的抽牌不会重跑。
- 后续选择结束后pending清空；模拟另一个复原效果后的边界，只有无次数限制的四季能再次发动。
- 两卡原生Action经SQLite保存和真正Replay重执行，最终状态及JSON往返一致。
- 双方payload不暴露对手手牌；改变对手隐藏身份不改变AI决策。

前端增加ミア两张选择回归：少选时确认禁用，选满后仅提交 `resolve_effect`，
显示原文，不打开generic manual、不再次扣费用。未改UI布局。

## manual起动错误修正

初始定向运行确认旧manual起动会进入 `_execute_operations`，尝试执行
`manual_resolution` 占位操作，抛出 `manual effect operations cannot auto-resolve`。
现在只排除这个manual占位操作的自动执行，随后生成绑定来源的pending invocation供用户处理。
已显式登记的费用仍执行；旧快照中原本可执行的结构化前缀也保留，不泛化成“所有manual操作都不执行”。
测试包含旧manual快照JSON、SQLite Replay、已登记Wait费用和保留历史抽牌前缀。
这不是自动理解旧manual的官方卡文，未知费用/效果仍需人工处理。

## AI与报告

- 四种policy均验证合法动作、隐藏信息独立性和后续选择；v0不主动选择起动，不能伪称它已实现该策略。
- v1/v1.1/v1.2的正收益场景使用受控临时Blade降低，使Wait不损失Blade，验证其主动起动并完成选择。
  未修改实际卡牌原始数值，不因测试而改变AI评分。正常场面下可以因Wait损失较大而不发动。
- 固定20Deck池10局v1.2回归全部正式完赛、10回合内且双方成功Live，最长9回合；
  无非法Action、错误skip或Replay错误。5454pass、1项既有动态语义review，另4项Live区域措辞待审。
- **这10局没有触发本次两段新技能**：新技能证据来自定向真实状态/AI测试，不混算随机实战覆盖。
- 既有图文报告新增两项真实operation状态场景，共62项通过，其中23项状态转换、39项registry契约。
  契约数不等于官方规则行为数，不宣称独立人工裁定完成。

复现：

```powershell
python -m pytest tests/test_activated_wait_draw.py tests/test_register_effect_candidates.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --output logs/continuous-wait-draw-effects-20261026
python -m tools.ai_sandbox.ai_rules_acceptance --database data/loveca.sqlite3 --output logs/continuous-wait-draw-ai10-20261026 --decks 20 --attempts 10 --required-qualified 10 --max-turns 10 --max-actions 500 --policy simple_ai_v1_2
```

中文卡图报告：`logs/continuous-wait-draw-effects-20261026/effect-verification-report.zh-CN.md`。
完整对局报告：`logs/continuous-wait-draw-ai10-20261026/比赛总报告.zh-CN.md`。
原始报告保持ignored，不进入Git。

## 登记与未解决项

登记从900/1212增加至 **902/1212（74.42%）**，manual从312降至310；
候选注册工具只更新已批准条目，不给其他条目补写新默认字段，manifest同步检查。

四季 `PL!SP-bp7-008:2` 的移动区域复原仍manual；本轮不冒充整卡全自动化。
六条重叠登场技能也继续manual：完整临时重叠、继承、常时与来源绑定完整性仍缺依据和状态模型。
特别是附属/入场/其他公开来源不能仅因缺少effect ID就视为没有能力。
这些未解决项留在父任务，不为覆盖率放宽判定。

本轮仅推送同一个Draft PR #54，不合并、不部署、不启用Cloud或修改生产数据。
