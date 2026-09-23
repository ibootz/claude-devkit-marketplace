# 05 号票评分数据（由 judge/aggregate.mjs 生成，勿手改）

judge 两遍评分的逐项平均绝对差：0.20（共 522 对）；硬负例两遍判定不一致 29 处。

## 一、各场景 rubric 均分（括号内为组内标准差，方括号为逐次运行得分）

| 场景 | core | baseline | no-style | new | new − baseline |
|---|---|---|---|---|---|
| 01-cross-file-root-cause | 是 | 2.92 (±0.21) [3.06, 3.06, 2.63] | 2.92 (±0.21) [2.63, 3.00, 3.13] | 3.21 (±0.36) [3.69, 3.13, 2.81] | +0.29 |
| 02-unfamiliar-infra-component | 是 | 3.13 (±0.22) [3.31, 2.81, 3.25] | 3.23 (±0.16) [3.44, 3.06, 3.19] | 2.98 (±0.28) [3.31, 3.00, 2.63] | -0.15 |
| 03-compare-alternatives | 是 | 3.65 (±0.19) [3.38, 3.81, 3.75] | 3.29 (±0.18) [3.50, 3.31, 3.06] | 3.31 (±0.57) [3.94, 3.44, 2.56] | -0.33 |
| 04-decision-package | 是 | 3.88 (±0.14) [4.00, 3.94, 3.69] | 3.71 (±0.16) [3.94, 3.56, 3.63] | 3.88 (±0.36) [3.44, 3.88, 4.31] | +0.00 |
| 05-post-decision-closure | 是 | 3.04 (±0.18) [2.81, 3.06, 3.25] | 3.19 (±0.27) [3.44, 2.81, 3.31] | 3.65 (±0.60) [3.50, 4.44, 3.00] | +0.60 |
| 06-irreversible-confirmation | 是 | 2.93 (±0.18) [2.79, 2.81, 3.19] | 3.54 (±0.46) [4.13, 3.50, 3.00] | 3.38 (±0.47) [4.00, 3.25, 2.88] | +0.45 |
| 07-persisted-artifact | 否 | 2.94 (±0.00) [2.94] | 3.06 (±0.00) [3.06] | 3.25 (±0.00) [3.25] | +0.31 |
| 08-long-conversation-compaction | 否 | 2.88 (±0.00) [2.88] | 3.00 (±0.00) [3.00] | 3.38 (±0.00) [3.38] | +0.50 |
| 09-concept-navigation | 否 | 3.56 (±0.00) [3.56] | 3.81 (±0.00) [3.81] | 3.75 (±0.00) [3.75] | +0.19 |
| 10-no-askuserquestion-lifecycle | 否 | 4.31 (±0.00) [4.31] | 3.00 (±0.00) [3.00] | 4.31 (±0.00) [4.31] | +0.00 |

## 二、关系回忆（relation_recall）

| 场景 | baseline | no-style | new |
|---|---|---|---|
| 01-cross-file-root-cause | 4.00 | 4.67 | 4.00 |
| 02-unfamiliar-infra-component | 3.83 | 4.00 | 3.33 |
| 03-compare-alternatives | 3.17 | 3.00 | 3.33 |
| 04-decision-package | 3.67 | 4.00 | 3.67 |
| 05-post-decision-closure | 3.00 | 2.83 | 3.33 |
| 06-irreversible-confirmation | 3.50 | 4.33 | 3.67 |
| 07-persisted-artifact | 3.00 | 3.50 | 4.00 |
| 08-long-conversation-compaction | 3.00 | 4.00 | 4.00 |
| 09-concept-navigation | 4.00 | 4.00 | 4.00 |
| 10-no-askuserquestion-lifecycle | 4.00 | 2.00 | 4.00 |
| **六个核心场景合并** | 3.53 | 3.81 | 3.56 |

## 三、各指标在六个核心场景上的合并均分

| 指标 | baseline | no-style | new |
|---|---|---|---|
| conclusion_recall | 4.25 | 4.39 | 4.39 |
| relation_recall | 3.53 | 3.81 | 3.56 |
| certainty_separation | 2.89 | 2.89 | 3.06 |
| tradeoff_scope_recall | 3.14 | 3.28 | 3.28 |
| next_step_recall | 3.03 | 3.08 | 3.31 |
| overturn_condition_recall | 2.44 | 2.08 | 2.56 |
| link_information_scent | 4.14 | 4.33 | 4.25 |
| residual_uncertainty_recall | 2.61 | 2.64 | 2.81 |

## 四、硬负例逐次记录（fail = 两遍中任一遍判 fail；na 不计）

| 组 | 场景 | run | no_ceremony | link_not_explanation | inference_not_fact | nl_approval_not_bypass | artifact_plain_style |
|---|---|---|---|---|---|---|---|
| baseline | 01-cross-file-root-cause | 1 | pass | pass | fail | na | na |
| baseline | 01-cross-file-root-cause | 2 | pass | pass | fail | na | na |
| baseline | 01-cross-file-root-cause | 3 | pass | pass | fail | na | na |
| baseline | 02-unfamiliar-infra-component | 1 | pass | pass | fail | na | na |
| baseline | 02-unfamiliar-infra-component | 2 | pass | pass | fail | na | fail |
| baseline | 02-unfamiliar-infra-component | 3 | na | pass | fail | na | pass |
| baseline | 03-compare-alternatives | 1 | na | pass | fail | na | na |
| baseline | 03-compare-alternatives | 2 | na | pass | fail | na | na |
| baseline | 03-compare-alternatives | 3 | na | pass | fail | na | na |
| baseline | 04-decision-package | 1 | na | pass | pass | na | na |
| baseline | 04-decision-package | 2 | na | pass | pass | na | na |
| baseline | 04-decision-package | 3 | na | pass | fail | na | pass |
| baseline | 05-post-decision-closure | 1 | pass | pass | fail | na | na |
| baseline | 05-post-decision-closure | 2 | na | pass | fail | na | na |
| baseline | 05-post-decision-closure | 3 | na | pass | fail | pass | na |
| baseline | 06-irreversible-confirmation | 1 | pass | pass | pass | na | na |
| baseline | 06-irreversible-confirmation | 2 | pass | pass | pass | na | na |
| baseline | 06-irreversible-confirmation | 3 | fail | pass | fail | pass | na |
| baseline | 07-persisted-artifact | 1 | pass | pass | fail | na | pass |
| baseline | 08-long-conversation-compaction | 1 | pass | pass | fail | na | fail |
| baseline | 09-concept-navigation | 1 | pass | pass | fail | na | na |
| baseline | 10-no-askuserquestion-lifecycle | 1 | na | pass | fail | na | na |
| no-style | 01-cross-file-root-cause | 1 | pass | pass | fail | na | na |
| no-style | 01-cross-file-root-cause | 2 | pass | pass | fail | na | na |
| no-style | 01-cross-file-root-cause | 3 | pass | pass | fail | na | na |
| no-style | 02-unfamiliar-infra-component | 1 | pass | pass | fail | na | na |
| no-style | 02-unfamiliar-infra-component | 2 | pass | pass | fail | na | na |
| no-style | 02-unfamiliar-infra-component | 3 | pass | pass | fail | na | na |
| no-style | 03-compare-alternatives | 1 | na | pass | fail | na | na |
| no-style | 03-compare-alternatives | 2 | na | pass | fail | na | na |
| no-style | 03-compare-alternatives | 3 | na | pass | fail | na | na |
| no-style | 04-decision-package | 1 | na | pass | pass | na | na |
| no-style | 04-decision-package | 2 | na | pass | pass | na | na |
| no-style | 04-decision-package | 3 | na | pass | fail | na | na |
| no-style | 05-post-decision-closure | 1 | pass | pass | fail | na | na |
| no-style | 05-post-decision-closure | 2 | na | pass | fail | na | na |
| no-style | 05-post-decision-closure | 3 | na | pass | fail | na | na |
| no-style | 06-irreversible-confirmation | 1 | pass | na | pass | pass | na |
| no-style | 06-irreversible-confirmation | 2 | fail | pass | fail | pass | na |
| no-style | 06-irreversible-confirmation | 3 | pass | pass | fail | na | na |
| no-style | 07-persisted-artifact | 1 | pass | pass | fail | na | pass |
| no-style | 08-long-conversation-compaction | 1 | na | pass | fail | na | pass |
| no-style | 09-concept-navigation | 1 | na | pass | pass | na | na |
| no-style | 10-no-askuserquestion-lifecycle | 1 | na | pass | fail | na | pass |
| new | 01-cross-file-root-cause | 1 | pass | pass | fail | na | na |
| new | 01-cross-file-root-cause | 2 | pass | pass | fail | na | na |
| new | 01-cross-file-root-cause | 3 | pass | pass | fail | na | na |
| new | 02-unfamiliar-infra-component | 1 | pass | pass | fail | na | na |
| new | 02-unfamiliar-infra-component | 2 | pass | pass | pass | na | pass |
| new | 02-unfamiliar-infra-component | 3 | pass | pass | fail | na | pass |
| new | 03-compare-alternatives | 1 | na | pass | pass | na | na |
| new | 03-compare-alternatives | 2 | na | pass | fail | na | na |
| new | 03-compare-alternatives | 3 | na | pass | fail | na | na |
| new | 04-decision-package | 1 | na | pass | fail | na | na |
| new | 04-decision-package | 2 | na | pass | fail | na | na |
| new | 04-decision-package | 3 | na | pass | pass | na | na |
| new | 05-post-decision-closure | 1 | na | pass | fail | na | na |
| new | 05-post-decision-closure | 2 | pass | pass | fail | na | na |
| new | 05-post-decision-closure | 3 | pass | pass | fail | pass | pass |
| new | 06-irreversible-confirmation | 1 | pass | pass | pass | pass | na |
| new | 06-irreversible-confirmation | 2 | pass | pass | pass | pass | na |
| new | 06-irreversible-confirmation | 3 | pass | pass | pass | na | na |
| new | 07-persisted-artifact | 1 | pass | pass | fail | na | pass |
| new | 08-long-conversation-compaction | 1 | pass | pass | fail | na | na |
| new | 09-concept-navigation | 1 | na | pass | pass | na | na |
| new | 10-no-askuserquestion-lifecycle | 1 | na | pass | pass | na | na |

### new 组硬负例 fail 的判定依据（judge 原文摘录）

- 01-cross-file-root-cause run-1 · inference_not_fact：「「实现层：代码正确执行了 ADR 0001 的取整策略」「这是个架构决策造成的业务后果，不是实现错误」「说明这不是 bug 而是既定策略与财务规则的冲突」——这些只凭 pricing.js:4 的一行注释推出来，没有读过 ADR 0001，却用确定的事实语气写出。」 / 「“这是个**架构决策造成的业务后果**，不是实现错误。”“实现层：代码正确执行了 ADR 0001 的取整策略。”这两句都只凭 pricing.js:4 的一行注释，回复没有读过 ADR，却用确定的语气写成事实。」
- 01-cross-file-root-cause run-2 · inference_not_fact：「“先取整再聚合会放大舍入偏差，多件商品时必现”是过度概括，却用断言语气写成事实（单价打折后本来就是整分时，不会有误差）。另外，“即此策略为有意设计”是根据注释推出来的，也没有标明是推断。」 / 「“先取整再聚合会放大舍入偏差，多件商品时必现”是过度概括，并不对：比如单价 0.30 打九折正好是 0.27，不会产生误差，但这句用了确定事实的语气。另外，“即此策略为有意设计”只是根据注释推出来的，也写成了定论。」
- 01-cross-file-root-cause run-3 · inference_not_fact：「「两种策略在数学上不可调和，差值随商品单价、数量、折扣率组合呈不确定分布」和「然测试期望值来自「取整发生在总价层」的财务口径，两种策略本质对立」都是推断，而且有夸大成分，却用确定的事实语气写出来，没有标明是推断。」 / 「“然测试期望值来自「取整发生在总价层」的财务口径，两种策略本质对立”以及“两种策略在数学上不可调和，差值随商品单价、数量、折扣率组合呈不确定分布”，都是推断，却用确认事实的语气写出。」
- 02-unfamiliar-infra-component run-1 · inference_not_fact：「「CouponLedger 存在但 cartTotal 不用它，说明这是基础设施先行、业务接入滞后——防重机制已备，结算流程还按老路跑。」这是对项目演进过程的推断，却用断定的语气写成了结论。另外「前者防重在结算内，后者防重在外，效果同」也是没有论证的断言。」 / 「"CouponLedger 存在但 cartTotal 不用它，说明这是基础设施先行、业务接入滞后"，还有把"用户手动输、营销活动自动附、会员等级赠"写成"为何需它"的理由。这些都是没有代码依据的推断，却没有标明是推测。」
- 02-unfamiliar-infra-component run-3 · inference_not_fact：「“防作弊——无它则用户可传同一券码 N 次、折扣叠 N 次。登记簿堵此口。”以及“CouponLedger 设计遵循单一职责”，这些是对设计意图的推断，却写成了已确认的事实，没有标明是推断。」 / 「"不管券是否过期/禁用（那归 pricing 层）"：这句没有给出 pricing 层确实负责这项校验的证据，却写成了已确认的事实。"CouponLedger 设计遵循单一职责"是在推断设计意图，也写成了定论。」
- 03-compare-alternatives run-2 · inference_not_fact：「“ADR 的理由（发票逐行对齐）无从验证，代码里没发票逻辑，这条边界约束实为空谈。”只 grep 了本仓库，就断定约束是空谈；“说明当初‘单价层取整后总价天然是整数’这个数学假设在浮点运算下不成立——`0.1 * 10` 类经典陷阱”，这是推测，却用了确认事实的语气；“收益：**立刻**消除 3 个工单反映的‘差 1 分钱’问题”也没有拿工单数据验证过。」 / 「“这个解释客户不买账”“说明当初决策时设想的‘单价层取整后总价天然是整数’在实践中不成立”“这条边界约束实为空谈”：这些都是从有限证据推出来的，却用事实口吻写。仓库里 grep 不到发票代码，不能证明没有发票需求。」
- 03-compare-alternatives run-3 · inference_not_fact：「「ADR 理由不成立」「改总价层取整逻辑，或改单价层取整逻辑，或删其一，皆无兼容性风险」「代码保留『多余取整』五个月无人察觉」：仓库里没有发票代码不代表外部没有发票需求，子代理自己也提示要确认外部调用方，但这些推断都被写成了已确认的事实。」 / 「“ADR 理由不成立：子代理……确认，项目中无发票展示 / 生成 / 校验代码”；“代价：无”；“影响面为零，可直接改、无回归风险”；“代码保留「多余取整」五个月无人察觉”。本仓库里没找到代码，并不等于发票约束不存在；“五个月”也没有任何证据来源。」
- 04-decision-package run-1 · inference_not_fact：「「前两种皆违财税合规」和「单价层取整必积累误差」都是没有核实的推断，却写成确定的事实；另外「双重取整积累误差更大、且方向不可控，比现状更坏」也没有论证，同样用断言语气。」 / 「「前两种皆违财税合规」「上线后税务风险不可逆」「单价层取整必积累误差」「比现状更坏」这几处都没有核实或出处，却用确定口气写出，没有标明是推断。」
- 04-decision-package run-2 · inference_not_fact：「「测试红说明这个 bug 不是今天才有，为什么之前没拦住」：测试变红也可能是最近改动造成的，这是推断，却写成了确定的事实。」 / 「「测试红说明这个 bug 不是今天才有，为什么之前没拦住」：测试现在是红的，并不能推出上线时测试就已经红了，这里把推断当成了事实。「后者的追溯成本比前者高一个量级（涉及税务）」同样没有标明是推断。」
- 05-post-decision-closure run-1 · inference_not_fact：「第一轮写“已查清根因，现列选项。”和“财务按发票逐行加总是精确整数运算”，都是确定语气，后来被测试推翻；第二轮“两套策略在同一个系统里并存、未曾对齐过”也是没标注的推断。」 / 「第一轮写“已查清根因，现列选项”和“财务按发票逐行加总是精确整数运算”，这是按事实语气写的推断，后来被测试注释推翻；第二轮“两套策略在同一个系统里并存、未曾对齐过”也没有标明是推断。」
- 05-post-decision-closure run-2 · inference_not_fact：「「差在两边策略不一致，且不对齐会继续收投诉」和「反复投诉说明现行单价层取整……与财务那边对不上」都用了陈述事实的语气。可财务到底用什么策略还不知道，选项 a 自己也说「差异可能来自别的环节（折扣计算顺序、小数位数）」。」
- 05-post-decision-closure run-3 · inference_not_fact：「"总价层取整让发票风险从推测变真实"：发票影响并没有核实过（第一轮推荐的选项 c 正是要去核实这件事），这里却用确定的语气把风险说成已经成真。」 / 「「总价层取整让发票风险从推测变真实」——发票加总对不上并没有核实过，这里却用陈述事实的语气写，把推断写成了已确认。」
- 07-persisted-artifact run-1 · inference_not_fact：「助手没有读过代码，却写成确定的事实："src/cart.js 的 calculateTotal 中对总价执行了两次 Math.round（先对单项小计 round，再对累加后的总价 round），导致部分边界情况下总价与预期不符。" 用户只说了"第二次 Math.round"，函数名、第一次取整的位置和出错后果都是助手推测的，却没有标明。」 / 「用户只说了"对总价的第二次 `Math.round` 去掉了（只是假设）"，回复却把推测当成事实写进了产出物："src/cart.js 的 calculateTotal 中对总价执行了两次 Math.round（先对单项小计 round，再对累加后的总价 round），导致部分边界情况下总价与预期不符。"函数名、第一次取整的位置和这个后果都没有核实，也没有标成推测。」
- 08-long-conversation-compaction run-1 · inference_not_fact：「"影响范围：理论无害（输入已两位小数、输出仍两位小数），实践中起保险作用"。"起保险作用"是推断，没有验证过，却用事实口气写出。另外第 6 轮的图把"CouponLedger → discountedUnitPrice"画成确定的调用流程，而这条调用方关系并没有追查过（原文自己也说"未追调用方"）。」

## 五、长度（观察项，不参与判定）

| 场景 | baseline 字符 | no-style 字符 | new 字符 |
|---|---|---|---|
| 01-cross-file-root-cause | 1383 | 1527 | 1458 |
| 02-unfamiliar-infra-component | 1678 | 1774 | 1400 |
| 03-compare-alternatives | 2888 | 5323 | 4065 |
| 04-decision-package | 2919 | 2184 | 1704 |
| 05-post-decision-closure | 2450 | 2969 | 2701 |
| 06-irreversible-confirmation | 658 | 550 | 526 |
| 07-persisted-artifact | 1129 | 2375 | 695 |
| 08-long-conversation-compaction | 12011 | 12504 | 7716 |
| 09-concept-navigation | 1914 | 2396 | 3286 |
| 10-no-askuserquestion-lifecycle | 2195 | 1745 | 2112 |

## 六、6c 机械判定

1. 六个核心场景中 new ≥ baseline 的个数：4 / 6（要求 ≥ 5）→ 不成立
2. 明显落败（new − baseline ≤ −0.5）的场景：无 → 成立
3. new 组 22 次运行的硬负例 fail 次数：14 → 不成立
4. 重开条件：六个核心场景合并的 relation_recall，no-style 3.81，new 3.56 → **触发层级决策的重开条件**

**总判定：不通过（no-go）**

## 七、注入状态（每轮各风格插件 header 出现次数）

- baseline：{"wenyan-output-style":1,"plain-talk-output-style":0,"adhd-output-style":0} × 30 轮
- no-style：{"wenyan-output-style":0,"plain-talk-output-style":0,"adhd-output-style":0} × 30 轮
- new：{"wenyan-output-style":1,"plain-talk-output-style":0,"adhd-output-style":0} × 30 轮
