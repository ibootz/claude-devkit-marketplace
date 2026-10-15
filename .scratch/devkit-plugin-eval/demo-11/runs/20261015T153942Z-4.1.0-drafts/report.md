# 用例草稿待审：devkit-discipline 4.1.0

> 草稿不参与任何运行；在待审页勾选「通过」后才移进 `<插件>/evals/`，随后跑 `baseline` 判基线已满足。

- 运行：`20261015T153942Z-4.1.0-drafts`
- 优先级：1 已证明有差的条款；2 复盘已命中的条款；3 退役条款的用例退回改挂；4 其余；同档按条款号、用例名

## 本页草稿

| 序 | 用例 | 类别 | 条款 | 来源 | 优先级 |
|---|---|---|---|---|---|
| 1 | dispatch-with-model | discipline | C093 | history | 已证明有差的条款：历史实测已证明有差：probe 实测：装 1.00、不装 0.33，Δ=+0.67（.scratch/plugin-eval/probe/REPORT.md 第 93 行） |
| 2 | inflight-cap | discipline | C100 | rehang | 退役条款的用例退回改挂：退役条款 C007 的用例退回改挂 |
| 3 | grep-then-targeted-read | discipline | C001 | ai | 其余：— |
| 4 | spec-read-whole-not-chunked | discipline | C002 | ai | 其余：— |
| 5 | zero-hit-verify-search | discipline | C005 | ai | 其余：— |
| 6 | dispatch-marks-layer2-no-nesting | discipline | C011 | ai | 其余：— |
| 7 | parallel-lookup | discipline | C087 | history | 其余：— |
| 8 | zh-audit-executor | skill-trigger | — | history | 其余：— |
| 9 | zh-audit-scope | skill-trigger | — | history | 其余：— |
| 10 | zh-rewrite-keeps-meaning | skill-trigger | — | history | 其余：— |

## 本批 AI 起草

- 模型：claude-fable-5-1；调用 3 次；花费（标价估算）：$1.4707
- 写进草稿区 4 个；挂上条款 2 个；结构不合格未写 0 个；判为离线评不了而跳过 8 条
- 跳过 clause:C003：规矩针对执行命令前用 wc -l / head 收窄输出，沙箱没有 Bash，无法跑任何命令。
- 跳过 clause:C004：触发条件是命令输出收窄后仍超 200 行，离线沙箱无法运行命令产生输出，也看不到「第 2 层子代理」的层级状态。
- 跳过 clause:C006：规矩要求用 ls 列父目录确认非 ASCII 路径，沙箱没有 Bash；改用 Glob 列目录在不装插件时也是常规动作，无法区分守与不守。
- 跳过 clause:C008：TaskList / TaskGet 不在可用工具集内，不用它们统计是必然结果，而「自己记账」是模型内部状态，会话里看不出来。
- 跳过 clause:C009：单次 claude -p 会话无法触发 auto-compact，compact 之后的派发策略离线观察不到。
- 跳过 clause:C010：claude -p 会话本身是顶层代理，无法让被测模型处于「已是第 2 层子代理」的位置；子代理内部是否再派发也不出现在轨迹里。
- 跳过 clause:C012：单次 claude -p 会话无法进入 team 模式，也无法在不点名规矩的前提下自然触发嵌套派发或代派前的 reference 阅读。
- 跳过 clause:C013：触发条件是作为 teammate 调 Agent 被拒并收到 omit the name parameter 报错，离线普通会话里 Agent 不会这样拒绝，行为无从观察。
