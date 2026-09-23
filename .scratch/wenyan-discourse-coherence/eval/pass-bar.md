# 通过线（go/no-go threshold）

原样照抄 `../spec.md` Testing Decisions 第 6c 条，不做任何改写或摘要——
这是父票（issue 01）Acceptance Criteria 明确要求"原样照抄"的条款。

> 6c. Go/no-go threshold: the new arm must score at least equal to baseline
> on the rubric mean in at least five of the six core scenarios, lose
> clearly in none, and pass every hard negative case in every run. Length is
> recorded but never decides the result. If the no-style arm scores at or
> above the new arm on relation recall, record it as evidence that wenyan
> compression is a cause of the symptom; this triggers the reopening
> condition of the layer decision recorded under Comments.

## 本票（01）与通过线的关系

本票只搭装置、采集 baseline 与 no-style 两组原始输出，**不判定通过线**——
通过线的判定需要 new 组的输出（04 号票完成后由 05 号票跑），本票没有 new 组
数据，无法计算"new 组是否在六个核心场景里至少五个不低于 baseline"。

唯一在本票范围内就能预先观察的信号是通过线最后一句——"no-style 组若在
relation recall 上不低于 new 组，则视为 wenyan 压缩本身是症状成因的证据"。
本票采到 no-style 组的原始输出后，05 号票评分时可以直接对照 baseline 组，
初步判断"no-style 是否已经不差于 baseline"——但这只是通过线最后一句的
前置观察，不是通过线本身的判定（通过线判的是 no-style vs new，不是
no-style vs baseline）。
