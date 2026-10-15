# 05: 实测 claude plugin eval 能否评出 hook 注入的效果

Type: task
Status: resolved
Blocked by: 无

## Question

用 `claude plugin eval` 给 `plugins/devkit-discipline` 写 2～3 个用例，跑一次有无插件双臂对照，回答四件事：

1. hook 注入的 `additionalContext`（SessionStart、UserPromptSubmit）是否出现在 grader 能读到的 `trace` 里？
2. 只看最终回复与 `trace`，现有 6 种 grader 能否判出「注入的纪律有没有被遵守」？Δ 是否明显大于同臂内的波动？
3. `plugins` 字段列多个插件目录时，能否同时加载？（决定多插件干扰能不能在它里面评）
4. 这一次的实际成本、耗时，以及各 grader 的判定是否稳定。

## 约束

- 成本上限 `--max-cost-usd 10`，加 `--no-publish`，结果不发到 claude.ai。
- 用例与结果放 `.scratch/plugin-eval/probe/`，不写进 `plugins/**`。
- 用例挑注入纪律里**能机械判定**的条款，用免费 grader 判，例如：
  - 派发 `Agent` 时是否带了 `model` 字段（`tool_used` + `input_match`）；
  - 有待拍板问题时是否没调 `AskUserQuestion`（`tool_used` 的 `max: 0`）；
  - 互不依赖的多个检索是否在同一条消息里并发发出（看 `trace`）。
- 第 3 问另起一个最小用例，同时列 devkit-discipline 与 devkit-clickable-paths 两个目录，看两者的注入是否都生效。
- 跑完把命令、用例、`aggregate-result.json` 的关键字段、结论都写进本票 `## Answer`；原始结果目录保留，不删。

## 完成判据

四问各给出「能 / 部分能 / 不能」加证据（`trace` 片段、grader 输出原文）。

## Answer

2026-10-14 实测完成，详见 [probe/REPORT.md](../probe/REPORT.md)，花费约 $4.12（上限 $10），墙钟约 4 分钟。

1. **注入是否进 trace：部分能。** SessionStart 注入在 trace 里，regex grader 19/19 命中；UserPromptSubmit 注入实际发生了，但 trace 不收（0/19）。只有 `--include-hook-events` 的 stream-json，或 `--keep-temp` 沙箱里的子会话转录看得到，两者都进不了 grader。
2. **免费 grader 能否判纪律遵守：部分能。** 工具入参类条款信号干净（派发带 `model`：Δ=+0.67，臂内零波动）；回复格式类能判但噪声大（四要素 Δ=+0.33，with 臂内波动 0.5）；依赖 `AskUserQuestion` 的判不了——headless 子会话里没有这个工具；基线已经做到的测不出 Δ（并发读文件 Δ=0）。
3. **多插件同时加载：能，有约束。** 所列插件目录必须在 containment root 内，用「外层目录放多个插件」布局即可，两份注入都生效。基线臂是全都不装，「A 单装 vs A+B 同装」要自己拆对照。
4. **成本与稳定性：** Opus 5.5 单 run $0.05–0.31；3 例 × 3 次 × 双臂约 $2.5。免费 grader 判定确定；llm 评委未测。

**关键坑**：hook 里的 `node` 若经 `~/.asdf/shims` 解析，在 eval 的临时 HOME 下会 exit 126，eval 不报错、分数照算，表现为「插件没效果」。跑 eval 前必须让 PATH 直接命中真实 node。

**未决，交 [09](09-build-vs-extend.md)**：四要素这类格式条款要不要加 runs 重测，取决于 09 是否把它划给 eval。

## Comments
