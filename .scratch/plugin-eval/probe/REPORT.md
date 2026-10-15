# 工单 05 实测报告：claude plugin eval 能否评出 hook 注入的效果

实测时间：2026-10-14 14:23–14:30（Asia/Shanghai）。
Claude Code 版本：2.1.299（aggregate-result.json 的 `claudeVersion`）。
被测插件：devkit-discipline 4.1.0、devkit-clickable-paths 2.0.0，均为 `/tmp/plugin-eval-probe/` 下的副本。
被测模型：全部 run 都是 claude-opus-5-5（eval 默认值，未钉死）。
评委：只用免费 grader，未用 llm 评委。

执行者：opus 子代理；主会话抽查了第 1 问与意外发现 1 的证据（hook_event 计数、exit 126、aggregate 关键字段），与下文一致。

## 结论速览

| 问题 | 结论 | 证据 |
|---|---|---|
| 1. 注入是否进 trace | 部分能 | SessionStart 原文在 trace 第 2 行 `hook_response.output`，with 臂 19/19 命中；UserPromptSubmit 0/19——实际发生了（子会话转录里有），但 trace 不收 |
| 2. 免费 grader 能否判出纪律遵守 | 部分能 | `model` 字段 Δ=+0.67、臂内零波动；四要素 Δ=+0.33 但 with 臂内波动 0.5；AskUserQuestion 子会话里没有该工具，判不了；并发检索基线本就并发，Δ=0 |
| 3. plugins 列多个目录 | 能（有约束） | 两插件都加载、两份注入都在，可点击链接 Δ=+1.0；所列目录必须在 containment root 内 |
| 4. 成本、耗时、稳定性 | 能给出 | 5 次 eval 共 $4.107；durationSeconds 合计 270 秒，墙钟约 4 分钟；免费 grader 判定一致 |

## 一、命令

所有 eval 经 `tools/run.sh` 调用，它做三件事：

1. cd 到 eval 目标目录。
2. 把 `~/.asdf/shims` 从 PATH 里去掉（原因见「意外发现 1」）。
3. 用 `env -u` 去掉父会话的 `CLAUDE_CODE_SESSION_ID`、`CLAUDE_CODE_CHILD_SESSION`、`CLAUDE_CODE_MESSAGING_SOCKET`、`CLAUDE_CODE_MESSAGING_TOKEN`、`CLAUDE_CODE_SESSION_ATTENDED`、`CLAUDE_CODE_ENTRYPOINT`、`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`。

公共参数：`--trust-plugin --no-publish --json logs/<tag>.json`。

| tag | 目标 | 参数 | 备注 |
|---|---|---|---|
| smoke | devkit-discipline | `--runs 1 --ablation none -j 3 --scaffold --keep-temp --max-cost-usd 2` | hook 因 asdf 全部 exit 126，只用于摸清 trace 格式 |
| smoke2 | devkit-discipline | 同上，`--max-cost-usd 1.5` | 修好 PATH 后重跑 |
| multi-smoke | multi | `--runs 1 -j 2 --scaffold --keep-temp --max-cost-usd 0.8` | |
| main | devkit-discipline | `--runs 3 -j 3 --scaffold --keep-temp --max-cost-usd 6` | 正式结果 |
| multi-main | multi | `--runs 3 -j 2 --scaffold --keep-temp --max-cost-usd 1.5` | 正式结果 |

旁证：两次 `claude -p`，`--plugin-dir` 加载副本、`--model haiku`：

- `claude -p "回复 pong，不要别的" --output-format stream-json --verbose`
- 同上，再加 `--include-hook-events`

退出码：main 与两次 smoke 为 1，原因是有用例低于默认阈值 1.0（smoke 另有一个用例加载失败），不是运行失败；两次 multi 为 0。

## 二、用例与 grader

devkit-discipline 下每个用例都带两个 `arm: with-only` 的标记 grader，双臂模式下只作指示、不计分：

- `marker-sessionstart`：trace 里匹配「AI 工作纪律（会话级常驻」
- `marker-userpromptsubmit`：trace 里匹配「AI 工作纪律 · 每轮要点」

**dispatch-model**

- prompt：请分别派一个子代理，各用三句话讲 TCP 三次握手和 HTTP 幂等。
- `allowed_tools`：Agent、Read、Glob、Grep。
- 计分 grader：
  - `agent-dispatched`：tool_used Agent，min 2
  - `agent-has-model`：tool_used Agent，`input_match '"model"\s*:\s*"'`，min 2
  - `agent-missing-model-zero`：tool_used Agent，`input_match '^(?![\s\S]*"model"\s*:)'`，min 0，max 0

**decision-no-ask**

- prompt：订单服务要不要加缓存，三种方案，「需要我来拍板，请把需要我决定的问题提给我」。
- `allowed_tools`：AskUserQuestion、Read、Glob、Grep。
- 计分 grader：
  - `no-ask-user-question`：tool_used AskUserQuestion，max 0
  - `four-elements`：last_message 正则 `起源[\s\S]*差距[\s\S]*影响范围[\s\S]*现场证据`

**parallel-lookup**

- scaffold 建三个 .py 文件；prompt 要求读完三个文件，概括每个文件并给出常量值。
- `allowed_tools`：Read、Glob、Grep。
- 计分 grader：
  - `answer-correct`：last_message 同时含 0.137、2719、83
  - `parallel-tool-calls`：trace 里有两行 tool_use 共用同一个 `msg_` id（同一条消息的每个 content block 各占一行）

**multi-plugin**

- 目标目录 `multi/`，`plugins: ["../../devkit-discipline", "../../devkit-clickable-paths"]`。
- scaffold 建 notes.md，第 4 行是 TODO；prompt 问 TODO 在哪个文件哪一行。
- 计分 grader：`clickable-link-in-reply`，last_message 正则 `\]\((file|vscode)://[^)\s]*notes\.md[#:]4`。
- 另有 with-only 标记 `marker-clickable`，trace 里匹配 devkit-clickable-paths 注入的标题。

## 三、aggregate-result.json 关键字段

| 套件 | overallScore | casesPassed | meanDelta | costUsd | durationSeconds | partial |
|---|---|---|---|---|---|---|
| main | 0.944 | 2/3 | +0.333 | 2.5470 | 146 | false |
| multi-main | 1.0 | 1/1 | +1.0 | 0.4902 | 19 | false |

| 用例 | WITH | W/OUT | Δ | with 臂逐次 | without 臂逐次 |
|---|---|---|---|---|---|
| dispatch-model | 1.00 | 0.33 | +0.67 | 1/1/1 | 0.33/0.33/0.33 |
| decision-no-ask | 0.83 | 0.50 | +0.33 | 1/0.5/1 | 0.5/0.5/0.5 |
| parallel-lookup | 1.00 | 1.00 | 0 | 1/1/1 | 1/1/1 |
| multi-plugin | 1.00 | 0.00 | +1.0 | 1/1/1 | 0/0/0 |

## 四、四问的证据

### 1. 注入是否进 trace：部分能

**SessionStart 能。** `traces/main/dispatch-model-with-1/trace.jsonl` 第 2 行：

    "hook_event":"SessionStart","output":"{\"hookSpecificOutput\":{...\"additionalContext\":\"# AI 工作纪律（会话级常驻，auto-compact 后自动重新注入）

- `marker-sessionstart` 在 12 个 with 臂 run 里全部 PASS。
- 13 个 without 臂 trace 里，该串出现 0 次。

**UserPromptSubmit 不能。**

- `marker-userpromptsubmit` 12/12 FAIL（pattern not found in trace），`marker-clickable` 3/3 FAIL。
- 全部 32 个 trace 里，`hook_event` 只出现过 SessionStart，共 38 次（19 个 with 臂 trace × 2 行）。

注入实际发生了。子会话转录 `traces/multi-main/multi-plugin-with-1/child-transcript-*.jsonl`：

- 第 4 行：hook_additional_context，SessionStart 注入
- 第 12 行：hook_additional_context，「AI 工作纪律 · 每轮要点」
- 第 13 行：hook_additional_context，「文件路径写成可点击链接（devkit-clickable-paths）」

19 个 with 臂 run 的子会话转录都有 UserPromptSubmit 注入，without 臂全无。grader 读不到这份转录：`{source: file}` 只读工作区，转录在沙箱的 `config/` 下。

**原因**：普通 `claude -p` 的 stream-json 默认只输出 SessionStart 的 hook 事件，加 `--include-hook-events` 才有 UserPromptSubmit。plugin eval 没有相应开关。

| 文件 | hook 事件 | UserPromptSubmit 注入原文 |
|---|---|---|
| `logs/streamjson-probe.ndjson` | 只有 SessionStart | 无 |
| `logs/streamjson-probe-hookevents.ndjson` | 多出 UserPromptSubmit（第 31、32 行是其 hook_response）与 Stop | 有 |

### 2. 免费 grader 能否判出纪律遵守：部分能

**model 字段：能，信号干净。**

- with 臂：`dispatch-model-with-1/trace.jsonl` 第 10、14 行都有 `"model":"sonnet"`，modelUsage 里出现 claude-sonnet-5-5，说明字段生效。
- without 臂：`dispatch-model-without-1/trace.jsonl` 第 2、7 行的 Agent 入参都没有 model。
- 两臂各自 3 次分数一致。permission_denials 都为空，说明 deny 没触发，代理第一次调用就带了 model。

**四要素：能判，但 Δ 没有明显大于波动。**

- with 臂 2/3 通过，without 臂 0/3。
- with#2 只跑 1 轮、4 秒，最终回复是一句纪律原文片段（`decision-no-ask-with-2/trace.jsonl` 第 4 行）：「Prompt 必含六项（5.6）在会话开始注入的纪律里，派发前逐条对照。」改写自 `working-discipline.js` 第 752 行的 5.6 条。

**AskUserQuestion：判不了。** `decision-no-ask-with-1/trace.jsonl` 第 3 行 init 的 tools 是 `["Task","Glob","Grep","Read","Skill","TaskStop","ToolSearch"]`，延迟加载工具里也没有它。

**并发检索：grader 能判，本用例测不出 Δ。** 两臂 6/6 都是同一条消息里发 3 个 Read。

### 3. 多插件同时加载：能，有约束

- 约束：`logs/smoke.stderr` 第 5 行报「outside the containment root ... Only plugins under it can be loaded from case.yaml」。
- 换成外层目录 `multi/` 后：
  - `suite.plugins` 与子会话 `init.plugins` 都有两个插件（@inline）；
  - 两份 UserPromptSubmit 注入都在子会话转录里；
  - with 臂 3/3 回复形如 `[notes.md:4](file:///.../notes.md#4)`，without 臂 0/3。
- 基线臂是两个插件都不装。

### 4. 成本、耗时、稳定性

- 成本：smoke 0.3077、smoke2 0.5993、multi-smoke 0.1629、main 2.5470、multi-main 0.4902，合计 $4.1071；加旁证 $0.0167，总计约 $4.12（标价估算）。
- 单 run：with 臂 $0.09–0.31，without 臂 $0.05–0.17。
- 耗时：durationSeconds 合计 270 秒，墙钟约 4 分钟。
- 运行状态：error 全为 null，无 partial，未撞限流。
- 稳定性：免费 grader 是确定性匹配，唯一一次波动来自被测代理；llm 评委未测。

## 五、意外发现

1. **插件 hook 在 eval 里 exit 126，且 eval 不报错。** hook 的 `node` 先解析到 `~/.asdf/shims/node`，eval 给子会话临时 HOME，asdf 找不到版本。分数照算，看起来就像「插件没效果」。证据：`traces/smoke/*/trace.jsonl` 第 2 行 `"exit_code":126`。
2. trace 默认不含 UserPromptSubmit 等事件，与 [wenyan README](../../wenyan-discourse-coherence/eval/README.md) 第 76 行「stream-json 里两类 hook 都带 output」的说法在 2.1.299 上不符。
3. headless 子会话里没有 AskUserQuestion，与官方文档把它列为可授权工具不一致。
4. `plugins` 字段有 containment root 限制，文档未写。
5. 注入后出现过一次回复偏航（1/12），见上文四要素一节。
6. `--keep-temp` 保留的沙箱里，`config/projects/*.jsonl` 子会话转录可读（`home/`、`tmp/` 被封成 mode 000），是唯一能看到 UserPromptSubmit 注入的地方。

## 六、对工单 09 的影响

1. **注入留痕**：SessionStart 用 eval 自带 trace + regex grader 就够。UserPromptSubmit、SubagentStart、PreToolUse 的注入，eval 的 trace 与 grader 都看不到，只有两条路：
   - 自建 harness，用 `claude -p --output-format stream-json --verbose --include-hook-events`；
   - eval 加 `--keep-temp`，在 eval 之外读沙箱子会话转录——结果不进 grader、不进分数。
2. **能复用 eval 的条款**：表现为工具入参或调用形状的纪律（`model`、`subagent_type`、同一条消息里并发），以及能用正则检出的回复格式（四要素、可点击链接）。
3. **eval 判不了的条款**：
   - 依赖 AskUserQuestion 的（工具不存在）；
   - 依赖多轮交互的（只能用 `history_file` 回放）；
   - 基线已经满足的（要换基线容易失败的诱导 prompt 才测得出 Δ）。
4. **多插件干扰**：用外层目录布局可以在 eval 里评；但基线臂是「全都不装」，「A 单装 vs A+B 同装」要拆成两个用例或两个套件自己算。
5. **环境前置**：eval 子进程的 PATH 必须能直接找到真实 node 二进制，不能走 HOME 下的 shim。不论自建还是复用 eval 都要满足。
6. **成本基准**：Opus 5.5 单 run $0.05–0.31；3 例 × 3 次 × 双臂约 $2.5、2.5 分钟（`-j 3`）。

## 七、只是推断的结论

1. 「eval 没有办法把 UserPromptSubmit 注入放进 trace」：依据是 `--help` 无相关开关、32 个 trace 全无；`plugin.json` 的 `experimental` 下有无隐藏配置未查。
2. 「trace 记录的是 hook `updatedInput` 改写前的 Agent 入参」：依据是 with 臂 trace 里没有 `name`，而 `agent-dispatch.js` 缺 name 时会自动补；补名是否发生没有直接取证。
3. 「with#2 的偏航由注入引起」：只有 1 例，无对照。
4. 「`tool_used` 是否把子代理内部的工具调用也计入」：未验证。
5. 「llm 评委的稳定性」：未使用，无数据。

## 八、产物

全部在本目录（`.scratch/plugin-eval/probe/`）下，共约 6.3 MB：

- `cases/devkit-discipline/evals/`：dispatch-model、decision-no-ask、parallel-lookup 三个用例（最终版）。smoke 时 parallel-lookup 的旧版 prompt 在 `logs/smoke.json` 的 `promptMarkdown` 里。
- `cases/multi/evals/multi-plugin/`：多插件用例。
- `results/devkit-discipline/2026-10-14T06-27-31-438Z/`、`results/multi/2026-10-14T06-27-31-553Z/`：正式结果的 aggregate-result.json 与 report.html；另有 smoke 的时间戳目录。
- `logs/`：各次 eval 的 `--json` 输出、stdout、stderr、退出码、起止时间，以及两份 stream-json 旁证。
- `traces/<套件>/<用例>-<臂>-<序号>/`：32 个 run 的 trace.jsonl、子会话转录与 `source.txt`（原沙箱路径）。**未入库**：子会话转录里有 eval 注入的账号邮箱，本仓公开，只留本机（2026-10-15）。
- `tools/run.sh`、`tools/summarize.js`。

仓外未清理：`/tmp/plugin-eval-probe/`（插件副本）与 `/private/tmp/e-*`（keep-temp 沙箱）。
