# 用例草稿待审：devkit-discipline 4.1.0

> 草稿不参与任何运行；在待审页勾选「通过」后才移进 `<插件>/evals/`，随后跑 `baseline` 判基线已满足。

- 运行：`20261015T154630Z-4.1.0-drafts`
- 优先级：1 已证明有差的条款；2 复盘已命中的条款；3 退役条款的用例退回改挂；4 其余；同档按条款号、用例名

## 本页草稿

| 序 | 用例 | 类别 | 条款 | 来源 | 优先级 |
|---|---|---|---|---|---|
| 1 | zh-audit-executor | skill-trigger | — | history | 其余：— |
| 2 | zh-audit-scope | skill-trigger | — | history | 其余：— |
| 3 | zh-rewrite-keeps-meaning | skill-trigger | — | history | 其余：— |

## 没上页的草稿

- eval 加载不了（修好再审）：`spec-read-whole-not-chunked`（graders/spec-not-chunked.md 只写了 max: 0 没写 min（eval 的 min 缺省为 1，恒不通过））
- 已打回：`dispatch-marks-layer2-no-nesting`、`inflight-cap`
