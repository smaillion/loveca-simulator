# オードリー：选择Member后严格比较Blade

## 本轮结果

新增适配 `PL!N-bp7-027:1`，将旧测试池中实际出现的3次manual blocker改为结构化选择和结算。
当前登记 **900/1212（74.26%）可执行，312 manual**；仅提升到test_validated，不自动提升reviewed。
仍在同一continuous分支与Draft PR #54，不合并、不部署，不修改卡库或runtime SQLite schema。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/BP07/PL!N-bp7-027-L.png" width="180" alt="オードリー官方卡面示意，非UI测试截图">

| 项目 | 精确绑定 |
|---|---|
| 卡号 / 名称 / 基础分数 | `PL!N-bp7-027` / オードリー / 2 |
| effect / revision / index | `PL!N-bp7-027:1` / 921 / 1 |
| raw text hash | `4c9f50c82ec56c823425e62731d8e0c65cbf30cbf31d3a07e6813a2c3cfe0df0` |
| 时点 | Live成功时，胜者比较之前 |
| 选择 | 己方Stage的一位虹咲Member，有目标时必须选1位 |
| 条件 | 其有效Blade严格多于双方Stage上其他所有Member |
| 效果 | 仅此来源Live加1分；相等或更低均不加分 |

卡面来自本地卡库的官方链接，不是伪造的测试截图；本轮未重新抓取官网。
候选生成器仅命中这一条当前精确日文技能，沿用原effect ID、revision和hash，不做模糊绑定。

## 官方依据

本地综合规则ver.1.06，PDF SHA-256：
`c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

- 8.4.4–8.4.6：发生Live成功事件，处理待机能力后再比较总分。
- 9.6.3.1 / 9.6.3.1.3：按指示选择目标；没有目标时忽略其相关处理。
- 9.9.1.4–9.9.1.5：先确定数值，再加减；临时与有效常时Blade参与比较。
- 4.1.4：Live离开原区域后视为新对象，原卡牌分数补正不能跟随进入手牌或成功Live区。

Wait状态只影响应援贡献，不抹去Member自身持有的Blade；下方附属卡不作为另一个顶部Member比较。
场上其他Member包含双方，不能只看己方，也不能用原始印刷Blade代替当前有效数值。

## 实测3次：均应为加0

冻结30套牌及seed保持与前一轮相同。实际原生Replay中的比较事件如下：

| 原局 / seed | 选择Member的Blade | 其他Member最高 | 判定 | 来源Live加分 |
|---|---:|---:|---|---:|
| 9 / 9008 | 1 | 2 | 不足 | 0 |
| 30 / 9029，第1次 | 2 | 4 | 不足 | 0 |
| 30 / 9029，第2次 | 4 | 4 | 同分，不是严格多于 | 0 |

第9局8回合/162步、第30局8回合/182步结束，均通过SQLite重放。
这里没有出现实战正向加分，不能把“去掉manual提示”当作正向效果证明；正向由下方真实状态场景验证。
UI会显示所选/其他最高Blade、条件成立或不成立，以及来源Live实际加分，避免像是什么也没做。

## 正向与边界状态

37项专项使用当前实际候选与卡牌属性，其他Stage卡和对照Live为明确构造的fixture：

| 场景 | 期望与实际断言 |
|---|---|
| 所选4，其余最高3 | 来源Live 2→3；同场另一张Live仍为2 |
| 双方本来总分均4 | 结算后己方5、对手4；己方成为唯一胜者 |
| 对手或己方其他Member同为4 | 不加分 |
| 对手5或更高 | 不加分 |
| 主动选择较弱虹咲Member | 选择合法，但可能不满足条件；不会替玩家改选 |
| Wait Member、临时Blade、Blade基础值替换 | 比较有效值而不是应援贡献或印刷值 |
| 常时Blade与对手Wait上的临时Blade | 同样计入，6对6仍不加分 |
| 手牌、下方附属Member有99Blade | 不进入顶部Stage比较，也不泄漏到公开结果 |
| 多张Live与来源先离场 | 不给其他Live加分 |
| 成功Live移动、原生回手、手动区域移动 | 清除新定向补正；旧全局score不变 |
| 分数设为固定值与加1 | 无论记录先后，按规则数值层先设定再加减 |
| 对手、非虹咲、重复、空选、缺失ID | 非法选择原子拒绝，不改变原状态 |
| 过期revision | SQLite状态和revision不变 |
| 无虹咲目标或失败Live | 明确不可发动或不触发，不打开自由manual兜底 |
| 旧manual snapshot | 仍要求原手动处理，不被新registry静默替换 |

原生Live成功、胜者比较、成功Live选择、回手和SQL Replay均有状态断言。
四种AI policy可提交合法选择；v1及以后使用Rule Engine提供的候选有效Blade，选最高者，不另行计算规则。
没有针对所有同类卡自动注册，也不宣称继承、replacement或完整continuous系统已解决。

## 大样本与审计

冻结30Deck × 50局，v1.2、block模式、260步：

- 48局正式结束，2局仍为既有步数上限；不靠增大上限掩盖它们。
- mandatory manual blocker、错误skip、非法动作、运行异常、Replay错误均为0。
- 573次可执行invocation：572次解算/可选拒绝，1次明确不可发动，0次未完成。
- 不可发动仍为此前的DOLLCHESTRA回收目标耗尽，未把它算作成功解算。
- 原始结果：`logs/continuous-niji-blade-block50-20261025/`。

另跑20Deck池10局原生步骤审计：10局均满足双方成功Live并在10回合内结束，
5454项pass、1项review、0项fail；现有9项Live边界通过，PDF引用无缺失。
review仍是 `PL!S-bp7-024:1` 的Heart替换词典缺口，不自动晋级为人工审查结论。
这10局不是上方冻结30Deck对照，不混算；完整报告在 `logs/continuous-niji-blade-audit10-20261025/`。
新比较操作只接受精确文本的审计映射；该词典检查不是独立Agent读PDF或完整裁判认证。

## 接续

本轮关闭这一个实测技能任务；原重叠/继承限制和312条manual仍保留。
后续继续队列中的Ruleset兼容性、规则矩阵和未收口的遗留语义，不以覆盖数字取代正确性。
