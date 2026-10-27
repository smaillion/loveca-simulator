# 桜内梨子：应援公开卡排序入底

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/CLLS01/PL!S-cl1-002-CL.png" width="160" alt="桜内梨子 PL!S-cl1-002">

## 精确范围与规则依据

仅登记`PL!S-cl1-002:1`，revision961，全文hash：
`78ec1681287a8bd2a185e7342012afd53d066ee9dea57b3e5b40fe6480c511f1`。

> 【ライブ成功時】エールにより公開された自分のカードの中から、『Aqours』のカードを3枚まで、好きな順番でデッキの下に置く。

固定本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。
本轮阅读相关条文并查看第8页原版排版，不重新抓取官网或推测FAQ。

- `8.4.4`、`8.4.5`、`11.6.2`：Live成功事件与技能待机发生在胜者比较之前，不能仅为最终获胜方触发。
- `8.4.8`：入底先于剩余Live/应援卡进入控室；移出的卡不能再次清理入控室。
- `9.6.3.1.1`：“最多3张”允许0张，不是可选发动或默认强制选满。
- `4.1.4`：离开公开区再回来的同ID不是原应援对象；仅在同一公开区内重排不换对象。
- `4.1.5.1`：卡公开过不等于对手有权获知其进入非公开牌库后的排列。

新增受限policy，仅允许自己的原应援对象、Aqours、0–3张、有序入底。
不把整个Resolution Area当作应援历史，也不把“Aqours卡”限成Member。
新快照在Yell时记录`remaining_yell_instance_ids`，离开该区域即移除追踪，
不重新加入同ID回来的对象。选择时再和当前区域交集。
这增加了可选的嵌套MatchState JSON字段，不修改Card Schema或SQLite表结构。
旧manual快照不启用此字段，序列化时省略None，旧Replay仍使用自己的技能快照。
新策略缺少追踪数据时明确拒绝，不猜测历史或偷偷执行。

## 状态与界面验证

42项专项全部通过；连同图文报告契约43项通过。

| 场景 | 实际断言 |
|---|---|
| 选0/1/2/3张 | 精确按提交顺序追加到牌库底部，背面，不进入控室 |
| 混合Member与Live | 都可作为Aqours候补 |
| 第4张、重复、异作品、非Yell公开牌、来源卡、未知ID | 原子拒绝，输入状态hash不变 |
| 触发前或待机后被其他效果移走 | 不可继续选择 |
| 同ID移走又回来 | 新对象不继承应援资格 |
| 同公开区内移动 | 原对象仍可选择 |
| 空/单张牌库 | 正确追加，不额外刷新、不重算已经确认的应援/Live结果 |
| 原生Performance→Yell | 仅新策略初始化对象追踪，旧manual保持旧快照形状 |
| 新自动/旧manual SQLite Replay | 确定性重放一致 |
| 四种AI与替换对方隐藏手牌身份 | 决策一致，动作由LegalAction生成并可执行 |
| 对方响应 | 不泄露所选卡入底的真实ID/顺序 |
| 实际前端交互 | 可选0、最多3、上下移动排序，并提交排序后的ID；2项通过 |

双语图文报告183项全部通过：145状态/边界，38登记契约。
新增混合类型排序、选0、无候补3场景，均附规则条款。
这是自动状态断言，不等同完整人工裁判审查；不提升`reviewed_executable`。
仅本段916→917/1212（75.66%），296→295manual。

## 冻结技能密集诊断

原30套合法牌组、seed18000–18029、`simple_ai_v1_2/block`、最多500动作不变。

| 指标 | 前批 | 本批 |
|---|---:|---:|
| 正式完赛 |7|8|
| 明确mandatory manual停止 |23|22|
| 可执行待机完成 |142/146|150/154|
| 随其他manual保留的可执行待机 |4|4|
| 非法动作/runtime/Replay/错误skip |0/0/0/0|0/0/0/0|

之前seed18007第9回合1个、seed18022第4回合2个本段强制人工待机，合计3个。
本批本段共7次入队、无manual/错误skip：18007一次、18022六次。
18007推进至第10回合其他manual；18022第6回合正式完赛，但败方成功Live为0，
不能冒充双方均完成Live的验收。整体仍未达到beta发布门禁。
所有30局的源码指纹与provenance逐一核对一致：
`db167f4ecf8bdbd7357802012ddae915940accb9e9025b39a91badf4aa91ab1d`。

## 复现与下一项

```powershell
python -m pytest tests/test_aqours_yell_bottom.py tests/test_effect_verification_report.py -q
python -m tools.ai_sandbox.effect_verification_report --database data/loveca.sqlite3 --output logs/aqours-yell-bottom-final-20261026/verification
python -m tools.ai_sandbox.blackbox_playtest --database data/loveca.sqlite3 --output logs/aqours-yell-bottom-final-20261026/final-frozen-30 --deck-directory logs/continuous-manual-focus-30-bound-20261026/decks --decks 30 --matches 30 --manual-policy block --policy simple_ai_v1_2 --seed-base 18000 --max-actions 500
```

完整top40及24个实际manual待机（22局，可同局多个）见同目录`gaps/`。
下一有限切片：`PL!N-sd2-026:1`两次实际mandatory阻塞，审计有效Blade至少4的虹咲目标及双Heart02。
先核对基础信息/有效Blade、无候补与结算时点，不按入队次数自动晋级。
`PL!S-bp2-005:1`待审与旧44/6 dirty成果不动，默认AI仍v1.1。
最终control/registry/backend/web及manifest/pre-push结果由协调器绑定源码保存。
同Draft PR54，不合并、不部署，不读取GPT认证，不调用付费模型API。
