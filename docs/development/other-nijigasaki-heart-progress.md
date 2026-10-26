# 桜坂しずく PL!N-PR-036：前置开发检查点

本检查点已在后续切片收口。以下内容为**登记前的历史记录**；
当前支持范围与验证结果以[正式验证报告](./other-nijigasaki-heart-verification.md)为准。

## 当前边界

固定continuous分支、同Draft PR54，canonical registry仍为manual，覆盖率仍915/1212。
此文件记录**尚未验收完成的本地原型**，不代表技能已经在产品对局中支持。
不改Card/SQLite schema、不提升reviewed、不合并部署，旧44/6 dirty与ignored成果不动。

官方段`PL!N-PR-036:1`，revision1225，raw_text_hash：
`efcae675449686825bdddf0b5f7a013d74837a06441dfa296f1677bed2d04ab4`。
来源卡是费用2的虹咲Member「桜坂しずく」。

原登记为强制人工占位。先用原生Live开始Action复现人工暂停，再用候选定义注入固定状态测试。
候选不会自动覆盖registry；尚未生成新manifest或将此段晋级。

## 已实现的受限原型

- 独立`public_other_nijigasaki_cost_heart`策略，不放宽旧的指定姓名Blade策略。
- 只选己方Stage顶层另一名虹咲Member；有目标必须选1，无目标允许0并记录明确未适用理由，不回退到来源。
- 单条Heart03 operation根据所选Member当前卡面信息cost给1或2，避免两条同色modifier生成重复ID。
- 仅适用cost15、强制、无费用、Live开始、Live期限的精确组合；模型拒绝不匹配语义。
- 成员登场支付减费不等于Card信息cost；测试用15→支付5的合成常时效果确认仍获得2颗Heart。
- TS仅补候选策略类型；尚未添加新的交互方式。

规则依据继续固定本地PDFver.1.06，SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
已阅读2.6、9.6.3.1/9.6.3.1.3、11.5.2以及8.4.11相关条款。
测试以`RULE_REFERENCE_IDS`记录引用；不是完整人工裁判审核，也未抓取新FAQ。

## 当前测试证据与待办

定向测试覆盖完整段身份、cost14/15/16、己方/对方/来源/附属/手牌/异作品、
无目标、重复/缺失选择的原子拒绝、待机后费用变化、目标在选择前离场和支付减费。
与两套既有指定姓名Live技能测试一起执行，结果存于本轮终端和共享任务检查点。

当前三套定向测试共120项通过。机器可读证据：
`logs/other-nijigasaki-heart-progress-20261026/targeted.xml`，suite名称绑定
`diagnostic_source_fingerprint`（仅src/sandbox Python、卡库、registry、manifest范围）。
协调器control/registry/web部分门禁通过，web为214项及TypeScript/production build；
**尚未执行本批全量backend门禁，部分绿色不构成发布授权。**

```powershell
python -m pytest tests/test_other_nijigasaki_heart.py tests/test_named_live_blade.py tests/test_named_live_groups.py -q
```

完成前必须继续：

1. 审计来源离场后同instance ID回场是否应被视为新的“其他”对象。当前`exclude_source`按ID排除，不能把这个边界默认为规则正确。
2. 验证目标离场后modifier清理及回场不继承、Live清理、旧manual与新候选的真实SQL Replay。
3. 补四AI、对手隐藏身份替换、双视角响应与真实UI候补契约、图文状态场景。
4. 仅在边界确认且状态测试通过后，精确替换这一个登记段及manifest；不要修改旧Replay snapshot。
5. 同冻结30牌组/seed诊断，按真实入队、辞退、错误skip、人工待机与完赛统计，不冒充beta门禁。
6. 更新中日README/Changelog和正式中文验证报告，运行全部control/registry/backend/web及pre-push，再提交和更新同PR54。

本轮只保存in_progress；本地未完成改动不得以部分门禁证据发布。
