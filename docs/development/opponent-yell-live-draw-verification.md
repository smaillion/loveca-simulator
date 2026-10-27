# 渡辺曜：对方当前Yell含Live时抽一张

2026-10-28 JST。有限任务`live-success-opponent-yell-live-draw`，沿用固定分支及工作树，仅本地开发提交，不push/publish、合并部署或主机操作。完整门禁、提交和最终状态见[最终验收入口](../../logs/opponent-yell-live-draw-20261027/final-acceptance.md)，定向绿色不替代全部profiles。

## 精确绑定与依据

`PL!S-PR-046:1`，渡辺曜，cost5/Blade0、work=`love_live_sunshine`、unit=`cyaron`，revision1219，完整文本hash`a8e630b24ea2d9956c6e64421ef222f7f627a68a36eb7ee148b9600fdbb5c97e`。全文：`【ライブ成功時】エールにより公開された相手のカードの中にライブカードがある場合、カードを1枚引く。`先从原生Live成功复现manual，`native-red.xml`保留；原seed18027有两个来源共同mandatory manual，不是唯一一条待机。

官方公开[FAQ API](https://llofficial-cardgame.com/manage/rule-qa/list?per_page=5000&status=published)本轮实际读取282条，响应SHA256仍`030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`，保存`official-qa.json`。Q253直接规定另一张同句式卡`PL!S-bp6-023`在结算前回收唯一Yell Live后不加分；Q107只参照再次Yell后当前公开的牌，Q153明确未进行Live视为Yell零张。结合Q119/Q120和固定PDF9.6.2.4.2，这是结算时的当前对象条件，不是永久公开历史计数。它们不是本卡专属FAQ；未命中本卡不代表不存在FAQ，web不可读不等于官网不可用。

固定PDF8.4.4/8.4.5、11.6.2界定本人Live成功及待机处理，9.7.7保护来源离场后待机；4.1.4为移区新对象。对方Live失败或离开Live Area不删除其仍公开的Yell对象；不要求对方也成功，不用当前Live区、累计成功区、己方Yell或旧回合缓存替代。

## 有限快照

仅新`draw_if_opponent_current_yell_live`固定强制Live成功/每Live一次/无费用条件及选择/本人抽1。generator精确核对卡号、全文、revision和hash；validator拒绝费用、可选、附加动作、改数量/对象/时点/期限。单条可自动结算，多来源仍按既有AP/NAP由玩家选顺序，两个来源各处理一次。

只在包含新operation的快照启用`LivePerformanceResult.yell_tracking_turn`与既有原Yell对象追踪；新可空整数None不序列化，旧快照SQL Replay不增加该字段。实际Yell和无Live略过均记录本游戏回合，原生阶段重置保护旧缓存。执行要求真实当前Live判定、本人已成功、invocation真实回合和非布尔Yell回合一致，缺失/陈旧/重复或畸形追踪原子拒绝，不猜历史。

仅对方`remaining_yell_instance_ids`、原公开列表、当前Resolution Area的交集内实际Live计数。原对象离区即失资格，同ID返回不继承，同区no-op保留，新进入处理区的非原Yell牌不计；0张不抽，1或2张都只抽1。短空库普通刷新，抽空后显式刷新仅用于新operation，不追改旧draw/manual或其他旧Yell条件。来源Member离场/回手牌/未知牌库/返回不取消待机。

非法额外费用/选择/分支/颜色、错玩家/旧revision/重复提交原子拒绝，兼容空选择/energy数组及ai_decision记录。新抽手牌只给本人卡面，隐藏来源不复活；未改隐私投影、默认AI、Card或SQL表结构。新增的是旧JSON可省略的Live结果元数据，不是Card schema迁移。

## 行为验收

77专项含33种SQL：双方角色/先后演出与0/1/2 Live、两来源12；原生CONTROL来源干涉8；原Yell离区/同ID返回/同区/移走一个/新对象5；短空库抽牌4；Performance→Yell新旧快照及无Live4。区域互斥，引用存在，Replay逐项相等。CONTROL只是测试构造，不是生产日志或正式卡能力。

四AI v0/v1/v1.1/v1.2在双方角色和正/失败条件实际处理两来源，隐藏ID/名称/卡号/Blade替换不改变决定、不改输入，完整双视角保护手牌/库尾与隐藏来源。关联保护包含旧Yell、来源隐私、图文及全局候选契约。286图文为248动态/38契约，本卡新增5动态；5原生UI含0/1/2结果中日显示及单/双隐藏来源的无费用提交，不冒充完整对局或人工裁定，也未声称语义provider联网验收。

原生阶段四例初期因构造Live需求未满足而未触发，已在副本清空需求隔离阶段后重跑；不冒充正式卡面下的完整合法对局。故意向追踪注入布尔值的负例明确捕获预期Pydantic警告，不放宽产品规则。登记结构化diff仅本段，935/1212（77.15%）、277manual，不提升reviewed；工具造成的无关字段排序已恢复原样，manifest重生成。

## 同牌组三十局

最终目录`logs/opponent-yell-live-draw-20261027/frozen-30/`，原30牌组与前轮provenance相同，seed18000至18029、v1.2/block/max500。应用诊断指纹`9a0779c49f3ddff61ce37cc1de7044c8e7d5b2c06dc3f3a76646e4a6282bdf05`与当前src/sandbox/卡库/registry/manifest、provenance和全部30摘要一致，`evidence-binding.json`保留，30Replay真；不同于完整门禁指纹。

仍19正式完赛/11人工停止，232/232可执行完成，非法/runtime/Replay/错误skip0。比前轮多4项完成，本卡2项，另外2项为推进后的既有能力，不全归本卡。seed18027实际处理两来源，第4回合84动作推进至第6回合118动作、成功Live1:1，停`PL!S-PR-045:1`。`seed18027-detail.json`有界复跑与冻结摘要完全相同，两条原事件均condition=false、opponent_yell_live_count=0、drawn_count=0；不声称随机正条件抽牌覆盖、完赛率或beta改善。正条件在专项/SQL/图文中验证。

## 新发现的既有风险

独立有效SQL复现`PL!S-bp6-023:1`的旧通用条件仍读已离区原Yell ID，唯一Yell Live回手后产生score补正+1，违背该卡直接Q253。区域互斥、Replay真；最终证据`q253-valid-final.json/sqlite3`。初次误测卡级分数而不是实际score补正、旧SQLite同ID冲突均不作证据，旧ignored文件保留。本轮未改该卡登记；已只读确认origin/develop条目相同，旧通用条件源码也未改，不是本轮引入。

本任务只完成曜的独立新快照，不把工程绿色当上述风险已解决。下一优先有限提案为该卡Q253当前对象/原来源得分修复，先将红例纳入专项、核对仅原Live范围及来源离场/返回，再新版本绑定，不全局追改旧condition/Replay。当前整批不发布，全部旧blocked继续保留。
