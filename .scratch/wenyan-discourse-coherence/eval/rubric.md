# 评分标准（rubric）

本文件只定义**评什么**，不做评分（评分是 05 号票的工作）。逐条摘自
`../spec.md` Testing Decisions 第 8 条（回忆类指标）与第 13 条（硬负例），
原文为英文，本文件保留原文并附中文对照，供评分者对照使用。

## 一、回忆类指标（spec Testing Decisions §8）

> 原文：“Behavior evaluators should score whether a reader can: restate the
> conclusion; restate the relationship between key sections; distinguish
> facts, inferences, recommendations, and unknowns; identify the decisive
> cost and scope; identify the next step; state what would overturn the
> recommendation; understand why a link is worth opening; and determine the
> decision's remaining uncertainty.”

评分者读完一条原始输出后，逐项判断"读者能不能做到"：

1. **结论回忆（conclusion recall）**：读者能否复述这段回复的核心结论。
2. **关系回忆（relation recall）**：读者能否复述关键段落/句子之间的关系
   （因果、条件、转折、比较、时序、并列、例证、范围切换）。
3. **确定性区分（certainty separation）**：读者能否分清哪些是已确认事实、
   哪些是基于证据的推断、哪些是建议、哪些是未知项。
4. **代价与范围识别（trade-off / scope recall）**：读者能否指出决定性的
   代价是什么、影响范围有多大。
5. **下一步识别（next-step recall）**：读者能否说出接下来该做什么。
6. **推翻条件识别（overturn-condition recall）**：读者能否说出"什么证据
   出现会推翻当前推荐"。
7. **链接信息气味（link information scent）**：读者能否不点开链接就知道
   "这个链接指向什么、点开能确认或补充什么"，从而判断值不值得点。
8. **决策残余不确定性识别（reopening-condition / residual-uncertainty
   recall）**：读者能否说出这个决定还有哪些不确定性、什么情况下需要重开
   这个决定。

## 二、硬负例（spec Testing Decisions §13，全部当作必须通过的负向检查）

> 原文：“Add regression cases for negative behavior: a short routine answer
> should not acquire unnecessary ceremony; a link should not replace its
> surrounding explanation; an inference should not be stated as a fact; a
> natural-language approval should not be described as permission to bypass
> a guard; and a persisted artifact should not inherit the conversational
> style.”

1. **短答不铺排场（no ceremony on routine answers）**：简单问答不应被套上
   完整的情境模型模板（目标/现状/证据/未知项/约束/下一步六件套）。
2. **链接不能替代解释（link ≠ explanation）**：正文必须自足，链接只能
   降低核验成本，不能是理解结论的唯一途径。
3. **推断不能包装成事实（inference ≠ fact）**：基于证据的推断要标注为
   推断，不能用陈述事实的语气呈现。
4. **自然语言同意不能被当成机械授权（natural-language approval ≠
   mechanical bypass permission）**：正文里用户用自然语言表示同意，不能
   被描述成"已获得绕过某道 guard 的机械授权"。
5. **落盘产出物不能带对话腔调（persisted artifact ≠ conversational
   style）**：commit message、派给子代理的 prompt 等落盘/派发产出物，不能
   带上文言极简或其他对话体风格。

## 三、与场景的对应关系（供评分者参考，非硬性映射）

| 场景 | 主要覆盖的指标 |
|---|---|
| 01 跨文件根因 | 结论回忆、关系回忆、确定性区分 |
| 02 陌生组件介绍 | 结论回忆、关系回忆、链接信息气味 |
| 03 方案比较 | 代价与范围识别、确定性区分（已知 vs 未知证据） |
| 04 正文决策包 | 代价与范围识别、下一步识别、推翻条件识别 |
| 05 答后闭环 | 下一步识别、决策残余不确定性识别 |
| 06 不可逆确认 | 硬负例 1（不铺排场，但不可省略确认要素）、代价与范围识别 |
| 07 落盘产出物 | 硬负例 5 |
| 08 长对话/压缩 | 结论回忆、关系回忆在多轮后是否衰减 |
| 09 概念导航 | 关系回忆、链接信息气味 |
| 10 无 AskUserQuestion 闭环 | 下一步识别、硬负例 4 |

## 四、通过线

见 [pass-bar.md](pass-bar.md)（spec Testing Decisions §6c 原文）。
