# Member与Live混合Heart检索审计

## 本批结论

三条已有可执行技能接入已验证的`triggered_inspection`费用检查。
原有混合Heart筛选在本批边界测试中正确，**不声称修复了不存在的Heart计算错误**。
登记仍**915/1212（75.50%），297 manual**，不提升人工`reviewed`。
不改engine、Card/SQLite schema、牌组及对战API；旧effect snapshot不补policy，旧Replay保留。
同一continuous分支及Draft PR54，未合并、未部署；旧44/6项dirty及ignored报告不动。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLS/PL!S-pb1-013-N.png" width="140" alt="黒澤ダイヤ">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLS/PL!S-pb1-014-N.png" width="140" alt="渡辺 曜">
<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBLS/PL!S-pb1-015-N.png" width="140" alt="津島善子">

| effect ID（均:1） | 官方名 | revision / 实际登场cost | 取得条件 |
|---|---|---|---|
| PL!S-pb1-013 | 黒澤ダイヤ |533 /4|Member的绿Heart（heart04）至少2，或Live的绿必要Heart至少2|
| PL!S-pb1-014 | 渡辺 曜 |534 /4|同上，红Heart（heart02）|
| PL!S-pb1-015 | 津島善子 |535 /4|同上，蓝Heart（heart05）|

共同费用为「手札を1枚控え室に置いてもよい」，查看顶4，满足条件的卡任选0–1张公开入手，余牌到控室。
完整日文段、独立revision与SHA-256固定在`tests/test_mixed_heart_inspection.py`。
本批Member明确限定「ハートに」，Live明确限定「必要ハートに」，不是泛指卡面任何Heart图标。
不限作品或组合；不把三个不同颜色合计2颗当作指定色2颗。

## 复现与状态断言

改动前逐卡实际cost4登场、耗尽手牌后直接确认，均报`effect cost card selection is not legal`。
旧版仍可拒绝技能结束，并非整局完全卡死；新版明确费用不足，取消所选待机，不查看、不付费、不记错误skip。

| 操作 | 实际核对 |
|---|---|
| 三种颜色 × Member/Live × 数量0/1/2/3 | 只按指定信息栏判断，0/1不符、2/3符合 |
| 错误颜色或错误字段，合计72项交叉边界 | Member不读Live必要Heart，Live不读Member Heart；异色和错误字段不满足 |
| 1颗指定色Heart + 同色Blade Heart + ALL | 不升格成2颗持有Heart；Blade Heart属Yell信息，不是本卡文指定栏 |
| 全局Heart+99及Live必要Heart-99的受控modifier | 不改变正在查看的牌库卡信息；这是限定区域fixture，不外推所有continuous/FAQ语义 |
| 第5张条件符合但只看顶4 | 不出现在候补，强行选取原子拒绝 |
| Member/Live作手牌费用、取得Member/Live/零张 | 原生登场支付4张Energy；手牌费用只付一次，余牌到控室，正常结束 |
| 对手手牌、已登场来源、重复费用或重复取得 | 原子拒绝，原state hash/revision不变 |
| 其他待机先抽牌补费用 | SQL原生动作之后可以支付，不在触发时删除待机 |
| 短牌库与只剩费用牌刷新 | 先付费再刷新，既有顶牌保留，选择只针对实际查看牌 |
| 对手完整响应、四AI、新旧SQL | 查看不泄露；公开取得对手可见；决策不改输入、不依赖隐藏卡身份，Replay等于最终snapshot |

候补、跨字段与modifier使用明确AUDIT fixture，不代表官方卡面同时有Member和Live数值，
也不冒充完整合法牌组历史。实际来源费用由真实卡库加载，图文cost0仅隔离技能。

## 规则依据与边界

本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
2.7.1区分Blade Heart的Yell用途，2.9.1–3与2.11.1–2区分持有Heart和Live必要Heart；
9.3.4限定能力有效区域，4.1.4规定跨区域不自动继承旧效果。
本批是牌库/查看卡的信息栏检索，不是Stage有效Heart汇总或Live成功判定。
费用按9.4.1–2、9.7.3.1.1/9.7.3.2；私有查看按5.7.1；不足张数刷新按10.2.2.2/10.2.3。
公开取得和可选零张来自卡文，不泛化为任何私有选择都可空选。

**2.1.3把带Blade的Heart图标视为同色图标，但不能据此忽略本批「ハートに/必要ハートに」的信息栏限定。**
余下一条`PL!S-bp2-005:1`没有同样的「ハートに」措辞且最多取3张，必须单独核对，不能自动继承结论。

## 验证证据

- 165项专项通过，其中72项类型/颜色/数量交叉边界；其他含费用、原子性、刷新、SQL Replay、四AI与双视角。
- 前端213项及TypeScript/build通过，三个ID都有无费用结束和公开零张交互。
- 图文172/172，133项真实状态、39登记契约；三个ID各有正常结算与费用不足场景。
  `logs/continuous-mixed-heart-effects-20261026/effect-verification-report.zh-CN.md`。
- 固定AI10/10在`3,6,5,6,9,4,9,5,7,6`回合决胜，双方有成功Live、Replay一致、错误skip为0；
  **本批三条实际触发0次**，不代替专项。报告在`logs/continuous-mixed-heart-ai10-20261026/`。
- 5454项步骤pass/1 review与4项Live解释待审仍保留，脚本审计不等于人工全规则裁定。
- 完整control/registry/backend/web、manifest和pre-push以最终源码指纹证据为准。

单弃牌扫描本批后仅余顶7最多取3张的独立审计，不代表其他费用/条件/FAQ语义都已支持。
六条复杂重叠manual保留，默认AI仍v1.1。
