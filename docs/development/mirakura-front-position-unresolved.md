# 安養寺姫芽：固定正面移动的边界审计

后续检查点：第2常时镜像错误已有独立新snapshot修复及专项证据，完整验收结论见[镜像修复记录](mirrored-cost-heart-verification.md)的本轮验收入口。本报告“未修复”是发现时历史；第1段目标资格/来源最后位置仍未解决，不自动恢复任务。

2026-10-27，固定`codex/continuous-development`；本轮只审计登场段、补保护测试和报告，不修改应用引擎、卡库、registry或manifest，不推送、新建PR或合并部署。

<img src="https://llofficial-cardgame.com/wordpress/wp-content/images/cardlist/PBHS/PL!HS-pb1-014-P2.png" alt="安養寺姫芽 PL!HS-pb1-014" width="220">

## 结论与身份

- `onplay-mirakura-opponent-front-position`应登记blocked。第1段继续manual，unresolved_reason=`fixed_front_same_area_target_eligibility_and_source_lki_unmodeled`。不能用现有通用移动操作替代正式卡，也不能因工程检查通过晋级。
- `PL!HS-pb1-014`，revision130，完整双段hash `542b68ba2435dd4aafaaf2f88d9fc0d75cf33321d245934e772175c21e009591`；cost9、Blade4，实际unit_key=`miracra_park`，work_key=`hasunosora`。不能拼成mirakura_park，不能仅按作品判断。
- 第1段：`【登場】自分のステージにいるメンバーが『みらくらぱーく！』のみの場合、相手のステージにいるメンバー1人をこのメンバーの正面のエリアにポジションチェンジさせる。`
- 第2段：`【常時】このメンバーの正面のエリアにいる相手のメンバーのコストが、このメンバーのコストより高いかぎり、【heart01】を得る。`登记仍为test_validated_executable，但本轮发现其左右正面实现错误，见下节；登记标签不是完整正确性认证，本轮没有改动或降级。
- 原冻结seed18005实际mandatory manual，本轮原生登场也保留真实待机。登记927/1212（76.49%）、285manual及人工reviewed均不变。

## 官方依据与未解决项

固定PDF `raw_doc/LoveLiveTCG_cr_1.06_260428.pdf`，SHA256 `c4f6881dcac15f69614799560fe8a327c878d4ccd8e41c85cc1d970e697ce485`。

1. 4.5.7.1明确左右正面为镜像，中央对中央。11.10.1要求移动到不同区域，11.10.2规定目的地有人时双方交换。附属卡随成员组移动的既有路径在SQL中验证，不替代为登场或Formation。
2. 9.11.1要求来源离场后参照离场前最后信息/配置；9.7.7要求继续处理已经待机的能力。原生登场→测试CONTROL让来源center→left→未知牌库（或再回right）后，原invocation只有初始slot=center，没有原对象最后位置绑定。left才是旧对象离场前位置，right是返回后的新对象位置，不能任选其一代替。这里是明确规则所需的执行模型依赖，不是假称规则本身未知。
3. “对手成员已经处于固定正面区域”时，11.10.1排除了同区域移动；但本轮资料不足以明确“允许选中后不移动”与“不得选择该成员、无其他目标则略过”的目标资格契约。不能仅把底层same-slot异常或1.3.2可能范围处理当作本卡直接裁定。
4. [官方Q&A](https://llofficial-cardgame.com/question/searchresults/)本轮公开API实读282条，SHA256 `030d275272b23e2c8682a8851ecc345f95302dae3a70aaccc6b70dd54689cea3`。Q220确认被交换出去的成员也产生移动触发；Q238确认另一张卡允许移动对手成员；Q223说明ウィーン・マルガレーテ的双方各自中央移动由各玩家选自己的目的地。它们不是本卡同区域资格或离场后固定正面的专属FAQ，不能照搬Q223让对手代选本卡目标。限定官网检索未命中直接条目，不等于FAQ不存在。

## 现有通用操作不能直接复用

仅测试内构造的UNREGISTERED probe使用member_from_stage/target_player=opponent与旧position_change_selected：候选确实包含对手Stage成员，但执行时只查技能所有者Stage，实际拒绝“target is not on Stage”。probe从未写入generator/registry，也不是新执行器。

五项只读unit条件probe验证既有matcher区分unit与work、空场/混合标签等；它们不执行本卡。正式能力仍通过manual guard拒绝伪造结构化目标，四AI采用block不会跳过或自动选第一人。

## 新发现：第2段左右镜像缺陷，尚未修复

引擎`opposing_member_cost_greater_than_source`在读取对手时使用相同slot，而非4.5.7.1的镜像slot。真实原生登场到left/right各一例：来源cost9、对手同名栏cost4、官方正面栏cost10，正确粉Heart补正应为1，现有结果为0。

- 独立红测试：`logs/mirakura-front-position-20261027/mirror-native-red.xml`，两例均实际失败。
- 区域有效的原生SQL证据：`mirror-valid-left.sqlite3`、`mirror-valid-right.sqlite3`及`mirror-valid-probe.json`，两边Replay均真、输入hash未变。复现脚本`mirror_native_probe.py`保留在同目录；这不是生产日志。
- 本轮遵守仅审计第1段的范围，没有改第2段实现/登记。主测试中的侧边SQL只验证人工移动/交换及附属卡，不将侧边常时结果称为通过；中央的既有常时结果仍有断言。红测试并未变成绿色，也没有用它们证明卡正确。
- 下一最高优先级独立修复是`static-mirrored-opponent-cost-source-heart`。它必须先加入可持续运行的新旧snapshot回归，再按精确全文身份修正新对局的镜像参照，旧snapshot继续按原规则重放；不得直接全局修改旧condition，掩盖Replay差异。第一段继续blocked/manual。

## 当前保护验证

`tests/test_mirakura_front_position_boundary.py`37项通过，140项与既有来源/隐私关联回归通过：

- 原生登场三位置×对手0/1/3人仍manual；精确双段身份及原有第2段登记保留；伪造结构化提交和同区域人工移动原子拒绝。
- 六种原生人工Position Change SQL覆盖镜像目的地、空位/交换、附属卡及Wait状态保持；两种原生CONTROL/SQL覆盖移位后离场、同ID返回，证明缺失原来源最后位置，不把CONTROL当正式卡能力。
- 四AI v0/v1/v1.1/v1.2在双方角色均返回真实no_safe_ai_action blocker，隐藏名称/卡号/实例ID替换不变、不修改输入。沙盒将此状态分类为mandatory_manual_resolution；二者不是同一个接口字段。
- 双视角完整响应不泄露未知牌库来源/尾牌；本人实际manual提交句柄保留，不因缺卡面过度脱敏。该投影CONTROL夹具明确为测试构造。
- 两项原生面板保护：缺来源卡面/有卡面均保留人工入口，不出现结构化自动结算按钮。初始夹具把既有“登場”文案误写成“登场触发”，已按真实UI修正断言，不修改产品文案或放宽人工guard。
- 最终checkpoint后执行完整control/registry/backend/web与pre-push。其绿色只验收本轮审计/保护代码，不认证未修复的第2段缺陷或第1段支持；最终源码指纹/真实命令日志以协调器result.json为准。

## 冻结证据不重复运行

本轮没有修改src、sandbox工具、卡库、registry或manifest；应用诊断指纹仍`3915564c6704506f22f5df5503f063d66d243a6cdb096505d4d0b5108b2381e5`，已重新核对与上一轮`logs/private-three-top-bottom-20261027/frozen-30-compatible-final/`的provenance及全部30条摘要一致。故没有无变化重跑30局。

原池仍15完赛/15人工停止、208/210可执行待机完成、两项随其他manual待机，非法/runtime/Replay/错误skip0，30Replay真。本轮没有技能晋级、随机新触发或完赛改善；旧freeze本身不覆盖新的左右静态红例。后续修复应用源码后必须重绑并重跑。

PR54已合并且本次上线授权已执行完；后续PR目标仍待明确批准。本轮不改policy、不推送、新建PR、合并或部署，已知镜像缺陷未修复前也不发布本批。
