# 工单 19 实测报告：history_file 回放能否测出「长历史之后」的遵守差

实测时间：2026-10-15 10:59–11:04（Asia/Shanghai）。
Claude Code 版本：2.1.300（各 `logs/*.json` 的 `claudeVersion`）。
被测插件：devkit-discipline 4.1.0，副本在 `/Users/zhangq/.claude/jobs/d1a1f6eb/tmp/history-probe/devkit-discipline/`。
被测模型：全部 run 都是 claude-opus-5-5（eval 默认值）；with 臂派出的子代理带 `model: sonnet`，跑在 claude-sonnet-5-5。
评委：只用免费 grader。
执行者：opus 子代理（第 2 层）。

## 结论速览

| 问题 | 结论 | 一句话证据 |
|---|---|---|
| 1. history_file 接受什么格式 | 能 | 就是 Claude Code 会话转录 jsonl：eval 把它原样当 `--resume <路径>` 传给子 claude；只含 2 条最简记录的文件、以 `compact_boundary` + `isCompactSummary:true` 开头的文件都能回放，模型能复述历史内容 |
| 2. 回放后注入是否照常到达 | 能 | with 臂 9/9 trace 有 `SessionStart:resume`、exit 0；子会话转录里每个 with run 都有 SessionStart 注入 1 条 + UserPromptSubmit 注入 3 条，without 臂全无 |
| 3. 长历史是否拉低遵守率、Δ 是否可测 | 能测；本条款未见拉低 | 无历史 / 约 3k token 摘要 / 约 20k token 历史三种用例，Δ 都是 +0.67，臂内零波动 |

**前提**：回放用例必须显式带 `--ablation with-without`。默认的 auto 模式会把回放用例降成只跑 with 臂、不出 Δ（见 [binary-strings.txt:28](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:28)）。

## 一、命令

所有 eval 都经 [tools/run.sh](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/tools/run.sh:1) 调用，跑法与 05 那轮相同：

- 从 PATH 里去掉 `~/.asdf/shims`。每次都把实际解析到的 node 写进 `logs/<tag>.node`，5 次都是 `/opt/homebrew/bin/node`。
- 用 `env -u` 去掉父会话的一组 `CLAUDE_CODE_*` 环境变量。

公共参数：`--trust-plugin --no-publish --json logs/<tag>.json --ablation with-without --keep-temp`。

| tag | --case | runs | -j | --max-cost-usd | 实际花费 | durationSeconds |
|---|---|---|---|---|---|---|
| smoke-recall | `recall-*` | 1 | 4 | 0.5 | $0.3319 | 13 |
| smoke-dm | `dm-h-compact` | 1 | 2 | 0.7 | $0.4714 | 32 |
| formal-base | `dispatch-model` | 3 | 3 | 1.6 | $1.1729 | 59 |
| formal-compact | `dm-h-compact` | 3 | 3 | 1.6 | $1.3652 | 61 |
| formal-long | `dm-h-long` | 2 | 2 | 1.2 | $1.5143 | 70 |

说明：

- smoke 的两次并行跑；formal-base 与 formal-compact 也并行跑。
- 5 次退出码都是 0。
- formal-long 超出了 $1.2 的上限：上限只在 run 启动前检查，4 个 run 启动时都没超，stderr 原文为「cost ceiling $1.2 exceeded: $1.51 spent by runs already in flight when it was crossed; nothing was skipped」。
- formal-long 只跑 2 次，是因为总预算 $5 只剩约 $1.66。

## 二、用例

全部用例在 `cases/` 下。被测 prompt 与 grader 照搬 05 的 dispatch-model：

- prompt：请分别派一个子代理，各用三句话讲 TCP 三次握手和 HTTP 幂等。
- 计分 grader：`agent-dispatched`、`agent-has-model`、`agent-missing-model-zero`。
- 标记 grader：`marker-sessionstart`、`marker-userpromptsubmit`，都是 `arm: with-only`，不计分。

| 用例 | context.history_file | 历史内容 | 回放给模型的历史量 |
|---|---|---|---|
| dispatch-model | 无 | — | 0 |
| dm-h-compact | `history.jsonl`，6 条记录，10 KB | `compact_boundary` → `isCompactSummary:true` 摘要（虚构记账 CLI「tally」的开发过程，9 节，约 3.4k 字）→ 2 轮尾巴对话 | 约 3k token |
| dm-h-long | `history.jsonl`，54 条记录，78 KB | 同上的边界与摘要，再加 24 轮程序生成的「解释某函数」问答（带代码块），最后是同样的 2 轮尾巴 | 约 20k token |
| recall-min | `history.jsonl`，2 条记录 | 一问一答，只说项目叫 tally、用 Python 与 SQLite；**每条记录只有 7 个字段** | — |
| recall-compact | 与 dm-h-compact 同一份 | 同 dm-h-compact | — |

关于这些用例的补充：

- 「回放给模型的历史量」是推算值：用同一臂首个 API 请求的输入 token 减去无历史用例的值。without 臂三种用例分别约为 10.3k、13.3k、30.1k（[per-run-inspect.txt:7-19](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/per-run-inspect.txt:7)）。
- recall 两个用例只在 smoke 里跑，prompt 是「项目叫什么、金额以什么单位存」，用来证明模型真的读到了历史。
- 合成历史由 [tools/gen_history.py](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/tools/gen_history.py:1) 生成，摘要正文在 [tools/summary.txt](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/tools/summary.txt:1)。全部内容都是本轮手写或由模板生成：不含真实会话原文，不含内网项目名，也不含插件的注入文本（理由见第六节「坑」第 4 条）。

## 三、history_file 的格式要求（字段级）

### 3.1 怎么查到的

- **官方文档**：01 研究文件只记了字段名（[claude-plugin-eval-capabilities.md · 二、用例格式](../../research/claude-plugin-eval-capabilities.md#二用例格式)（case.yaml 独有字段清单）），格式没写。本轮没有再查文档。
- **可执行文件字符串**：在 `strings -n 6 ~/.local/share/claude/versions/2.1.300` 里搜 `history_file`，摘录在 [excerpts/binary-strings.txt](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:1)。
- **实测**：smoke 的 4 个用例都一次被接受，没有触发任何报错，所以报错路径只有字符串里的文案，没有实测报错原文。

### 3.2 eval 层（已证实，出处为字符串摘录）

- `context.history_file` 是字符串、可选（[binary-strings.txt:4](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:4)）。
- 配了它就必须有被测 prompt，否则报「context.history_file requires execution.prompt (the resumed session needs a next turn)」（[binary-strings.txt:8](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:8)）。所以回放只能评「历史之后的下一轮」。
- 路径相对用例目录解析，必须落在用例目录或被测插件目录内，且是普通的单链接文件，否则报「resolves (through a link) outside the case directory and the plugin under test, or is not a plain single-link file」（[binary-strings.txt:20](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:20)）。
- **原样当 `--resume <绝对路径>` 传给子 claude**（[binary-strings.txt:16](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:16)）。eval 自己不解析内容，格式要求全部来自 `claude --resume` 的加载器。
- eval 会读历史里的 `cost-state.totalCostUSD`，作为 restoredCostUsd（[binary-strings.txt:24](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:24)）。本轮的合成历史不含 cost-state，对计费的影响没有验证。
- **臂选择**：`os(case, mode, isAuto)` 在 isAuto 为真且用例有 history_file 时只返回 `["with"]`（[binary-strings.txt:28](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:28)）。auto 模式的提示文案是「a replay case whose history carries the plugin into both arms」（[binary-strings.txt:32](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:32)）。显式 `--ablation with-without` 时 isAuto 为假，两臂都跑；本轮 5 次都两臂都跑，已证实。

### 3.3 加载器层（`--resume <path>`）

已证实的部分：

- 后缀 `.jsonl` 走会话转录加载器；后缀 `.json` 走另一条路径，接受消息数组或 `{messages:[...]}`，上限 268435456 字节（256 MB），超了报「Transcript file too large to load as JSON」（[binary-strings.txt:40-44](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:40)）。
- jsonl 无消息时报「No messages found in JSONL file」；找不到对话链时报「No valid conversation chain found in JSONL file」（[binary-strings.txt:48](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:48)）。
- 文件名去掉 `.jsonl` 后若是 UUID，就被当作 sessionId（[binary-strings.txt:52](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:52)）。本轮用 `history.jsonl`，没有触发这条。

实测可用的最小字段集。recall-min 的每条记录只有下面这几个字段，能回放，且模型复述出了 tally：

- 公共字段：`type`（`user` / `assistant`）、`uuid`、`parentUuid`（首条为 null）、`sessionId`、`timestamp`、`isSidechain:false`、`message`。
- `message` 的写法：user 记录写 `{"role":"user","content":"<字符串>"}`；assistant 记录写 `{"role":"assistant","content":[{"type":"text","text":"..."}]}`。
- 可以不写：`cwd`、`version`、`entrypoint`、`userType`、`gitBranch`，以及 assistant 的 `id` / `model` / `usage` / `stop_reason`。

compact 记录可以用，实测成立：

- 首条写 `{"type":"system","subtype":"compact_boundary","parentUuid":null,"logicalParentUuid":<任意 uuid>,"compactMetadata":{...},"content":"Conversation compacted","level":"info",...}`。
- 下一条写 user 记录，带 `"isCompactSummary":true,"isVisibleInTranscriptOnly":true`，`content` 放摘要文本。
- 这条摘要**真的发给了模型**：首个 API 请求的第一条 user 消息就是摘要正文（[api-request-first-smoke-with.txt:4](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/api-request-first-smoke-with.txt:4)）。recall-compact 两臂都答出「整数分 / amount_cents」，这个信息只存在于摘要里（[prompt-chain-and-recall.txt:22-23](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/prompt-chain-and-recall.txt:22)）。
- recall-min 的历史里没有金额单位，两臂都回答「你还没告诉过我」（同文件第 24-25 行），说明模型只看到了历史里有的内容。

写入时被改写的字段：

- 回放记录被拷进新转录时，`cwd` 被改成沙箱的 cwd。合成历史里写的 `/tmp/tally-demo` 没有保留。
- 子会话的 sessionId 沿用历史记录里的 `sessionId`（trace 的 init 行，[trace-heads.txt:5](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/trace-heads.txt:5)）。

大小上限：

- eval 层只对 prose `.md`（prompt.md 与 graders）设了 1 MB 上限（[binary-strings.txt:60-64](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/binary-strings.txt:60)），对 history_file 没有找到上限。
- jsonl 加载器附近有常量 `MAX_TRANSCRIPT_READ_BYTES = 52428800`（50 MB），用途没有追。
- 实测最大只到 78 KB。

## 四、结果表

分数是 3 个计分 grader 的通过占比。without 臂的固定形态是：派了 2 次但没带 model，所以得 1/3。

| 用例 | 历史量 | WITH 逐次 | W/OUT 逐次 | WITH | W/OUT | Δ | 臂内波动 |
|---|---|---|---|---|---|---|---|
| dispatch-model | 0 | 1 / 1 / 1 | 0.33 / 0.33 / 0.33 | 1.00 | 0.33 | +0.67 | 0 |
| dm-h-compact | 约 3k token | 1 / 1 / 1 | 0.33 / 0.33 / 0.33 | 1.00 | 0.33 | +0.67 | 0 |
| dm-h-long | 约 20k token | 1 / 1 | 0.33 / 0.33 | 1.00 | 0.33 | +0.67 | 0 |
| dm-h-compact（smoke） | 约 3k token | 1 | 0.33 | 1.00 | 0.33 | +0.67 | — |

- 逐次分数与 grader 原文见 `logs/formal-*.stdout` 与 `logs/*.json`，或用 `node tools/summarize.js logs/<tag>.json` 重出。
- 典型的 grader 原文：with 臂是「PASS agent-has-model — Agent called 2x (expected 2..∞)」；without 臂是「FAIL agent-has-model — Agent called 0x (expected 2..∞)」和「FAIL agent-missing-model-zero — Agent called 2x (expected 0..0)」。
- 05 那轮（2.1.299）的同一用例结果是 1/1/1 对 0.33×3，与本轮一致。

## 五、三问的证据

### 1. 格式：能

- smoke-recall 与 smoke-dm 的 4 个回放用例在两个版本的历史上都没有报错，`error` 全为 null。
- 模型能复述历史内容，见第三节。
- 回放历史**不进 eval 的 trace**：12 个回放 run 的 trace 里，「tally」与摘要开头句都出现 0 次。所以 `tool_used` 之类的 grader 不会把历史里的工具调用算进去。这一点只验证了历史里没有工具调用的情形。
- 每个 run 的被测 prompt 都只挂在回放历史上，没有挂到别的 run 的轮次上（[prompt-chain-and-recall.txt:4-17](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/prompt-chain-and-recall.txt:4)，foreign_turns 全为 0）。
- 同臂各次首请求的输入 token 几乎相同，例如 19851 / 19851 / 19848，说明历史不随 run 累积。

### 2. 注入：能

trace 侧：with 臂 9/9 的头两行是 `SessionStart:resume` 的 hook_started 与 hook_response，`exit_code` 为 0（[trace-heads.txt:4-5](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/trace-heads.txt:4)）。

- 对照：无历史用例是 `SessionStart:startup`（同文件第 9-10 行）。
- `marker-sessionstart` 在 with 臂 12/12 PASS。
- 和 05 一样，`marker-userpromptsubmit` 12/12 FAIL，因为 trace 不收 UserPromptSubmit。

子会话转录侧：回放用例的子会话转录**不在沙箱 `config/projects/` 下**，而是写进用例目录的 `<sessionId>.jsonl`，见第六节「坑」第 2 条。

- 每个 with run 都有：
  - 1 条 `hook_success SessionStart:resume`；
  - 1 条 SessionStart 的 `hook_additional_context`（正文以「# AI 工作纪律（会话级常驻」开头）；
  - 3 条 UserPromptSubmit 的 `hook_additional_context`（以「# AI 工作纪律 · 每轮要点」开头；1 条对应被测 prompt，另外 2 条对应两次子代理完成通知）。
- 多数 with run 还有 2 条 `PreToolUse:Agent` 的 additionalContext，内容是 agent-dispatch 自动补 name 的提示。
- without 臂没有任何注入记录。
- 汇总见 [per-run-inspect.txt](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/per-run-inspect.txt:4)，原文片段见 [case-dir-transcript-injections.txt](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/case-dir-transcript-injections.txt:3)。

注入的位置：SessionStart:resume 的注入排在回放历史之后、被测 prompt 之前（[smoke-dm-h-compact-transcript-outline.txt:14-16](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/smoke-dm-h-compact-transcript-outline.txt:14)）。在 API 请求里，它是紧跟被测 prompt 的一条 system 消息（[api-request-first-smoke-with.txt:9](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/api-request-first-smoke-with.txt:9)）。

无历史用例的对照：子会话转录在 keep-temp 沙箱的 `config/projects/*/*.jsonl`，注入计数与回放用例相同（per-run-inspect.txt 第 4-6 行）。

### 3. 长历史与遵守率：能测，本条款未见拉低

- 三种历史量下 with 臂都是 1.00、without 臂都是 0.33，Δ 恒为 +0.67，臂内零波动。
- 约 20k token 的回放历史没有让 with 臂少带一次 `model`；without 臂也没有因为历史而变好或变差。
- Δ 在回放用例里照样可测，信号和无历史用例一样干净。

## 六、坑与意外发现

1. **默认 ablation 下回放用例没有 Δ**。auto 模式按「历史可能把插件带进两臂」处理，只跑 with 臂。必须显式写 `--ablation with-without`，而且要自己保证合成历史里不含插件注入。
2. **子会话转录写到沙箱外的用例目录**。每个回放 run 都往 `<用例目录>/<历史里的 sessionId>.jsonl` 与 `<用例目录>/<sessionId>/subagents/` 写入。
   - 同一用例的所有 run（含两臂）共用同一个 sessionId，往同一个文件交错追加。本轮 formal-compact 6 个 run 合计写了 337 行。
   - 各 run 的对话链经核对是隔离的（第五节第 1 问），但下次再跑之前要清掉这些文件：否则用例目录越积越大，还会混进上一批的转录。
   - 本轮每次跑完都已把这些文件移到工作目录的 `artifacts/`。
   - 被测插件目录被子进程写入，这与「沙箱隔离」的直觉不符，文档里也没写。
3. 回放 run 的 SessionStart hook 收到的 `session_id` 是一个新 id（`6ff0984b-…`），而 init 与转录用的是历史里的 sessionId（[trace-heads.txt:4-5](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/trace-heads.txt:4)）。按 session_id 记账的 hook 在回放里会看到两个 id。只观察到这一现象，没有影响本轮结论。
4. **合成历史里不能放插件的注入文本**。插件注入的 attachment 一旦写进历史，会被回放给两臂，without 臂就不再是「无插件」基线。所以「SessionStart 注入埋在很远的历史里、此后不再重注」这种状态，靠回放造不出来：with 臂每次 resume 都会在末尾新鲜注入一次。
5. formal-long 的花费超过了上限，原因见第一节说明。

## 七、只是推断或未核实的结论

1. 「历史量约 3k / 20k token」是推算值：用 without 臂首请求输入 token 减去无历史用例的值（13.3k − 10.3k、30.1k − 10.3k）。没有直接数 token。
2. 「本条款不受长历史影响」只覆盖到约 20k token 的历史与 1 条条款。真实会话里 compact 前常有 150k 以上的上下文，更长的历史是否拉低遵守率没有测。with 臂 1.00 是天花板，测不出轻微下降。
3. 回放与真实 compact 后状态的等价性：
   - 真实 compact 后的顺序是「边界 → 摘要 → SessionStart:compact 注入 → 后续轮次」（[session-jsonl-signals.md · compact 与会话续接](../../research/session-jsonl-signals.md#compact-与会话续接)（紧随其后的记录顺序））。
   - 回放是「边界 → 摘要 → 尾巴 → SessionStart:resume 注入 → prompt」。
   - devkit-discipline 的 SessionStart 分支不区分 source（[working-discipline.js:971](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/devkit-discipline/hooks/working-discipline.js:971) 只看 `hook_event_name`），所以注入文本相同；差别只在注入与尾巴的先后顺序。尾巴只有 1～2 轮时，这个差别预计可以忽略，但没有对照验证。
4. API 请求里有 3 个消息 blob 在转录里找不到（[api-request-first-smoke-with.txt:6-8](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/plugin-eval/probe/history-file/excerpts/api-request-first-smoke-with.txt:6)），原因未查。按位置推断是两轮尾巴里的 assistant / user / assistant。
5. 历史里含 `tool_use` / `tool_result` 的回放，以及历史含 cost-state 时 restoredCostUsd 怎么抵扣，都没有测。

## 八、对工单 17 第 4 条与工单 09 的影响

- **工单 17 第 4 条（合成回放方案）：可行，需调整三处**。
  1. 跑法必须带 `--ablation with-without`。
  2. 每批跑完要清理用例目录里的 `<sessionId>.jsonl` 与同名目录；也可以在 run.sh 里先删后跑。
  3. 合成历史只放模板化摘要与尾巴，不放任何插件注入文本。
- 格式不用再造：照第三节的最小字段集写 jsonl 就能用，`compact_boundary` + `isCompactSummary` 的组合被接受，摘要也真的发给了模型。
- **工单 09 的重开条件「回放测不出 compact 后差异」：本轮不触发**。回放后 Δ 照样可测（+0.67、零波动），注入照常到达。
- 未覆盖的部分：本轮也没有测出 compact 后**遵守率下降**，因为所选条款在三种历史下都是天花板。要确认回放能复现真实会话里的 compact 后退化，下一步应从 session-jsonl-signals 的违规统计里挑一条「compact 后违规率明显上升」的条款再跑一次。若那时 with 臂仍是天花板而真实会话里有退化，才算触发 09 的重开条件。

## 九、成本与耗时

- 花费：5 次 eval 合计 **$4.8557**（0.3319 + 0.4714 + 1.1729 + 1.3652 + 1.5143），低于 $5 的硬上限。没有其它 `claude -p` 调用。
- 单 run 花费：
  - 无历史：with 臂 $0.20–0.28，without 臂约 $0.14。
  - 约 3k token 历史：with 臂约 $0.29，without 臂约 $0.17。
  - 约 20k token 历史：with 臂约 $0.44，without 臂约 $0.32。
- 墙钟：第一次 eval 启动到最后一次结束是 10:59:22–11:04:14，约 4 分 52 秒；durationSeconds 合计 235 秒。
- 运行状态：error 全为 null，无 partial，未撞限流。

## 十、产物

本目录 `.scratch/plugin-eval/probe/history-file/` 下：

- `cases/`：dispatch-model、dm-h-compact、dm-h-long、recall-compact、recall-min 五个用例，含 `history.jsonl`。
- `logs/`：5 次 eval 的 `--json` 输出、stdout、stderr、exit、start、end 与 node 路径。
- `results/`：5 个时间戳目录，含 aggregate-result.json 与 report.html。
- `excerpts/`：
  - `binary-strings.txt`：可执行文件字符串摘录；
  - `smoke-dm-h-compact-transcript-outline.txt`：smoke 两臂共用的那份转录的逐行大纲；
  - `api-request-first-smoke-with.txt`：首个 API 请求的消息序列；
  - `case-dir-transcript-injections.txt`：注入原文片段；
  - `trace-heads.txt`：trace 头 3 行；
  - `per-run-inspect.txt`：逐 run 汇总；
  - `prompt-chain-and-recall.txt`：prompt 祖先链与 recall 回复。
- `tools/`：`run.sh`、`gen_history.py`、`summary.txt`（摘要正文）、`inspect.py`、`summarize.js`。

仓外未清理的路径：

- `/Users/zhangq/.claude/jobs/d1a1f6eb/tmp/history-probe/`：插件副本、`artifacts/` 里 5 份完整的回放子会话转录（smoke 3 份、formal 2 份）、`strings/all.txt`（61 MB）。
- `/private/tmp/e-*`：本轮 keep-temp 保留的 22 个沙箱，清单见 `/tmp/hp-sandboxes.txt`。
- `/tmp/h-*.jsonl`、`/tmp/hp-base-files.txt` 与 `/tmp/hp-sandboxes.txt`。
