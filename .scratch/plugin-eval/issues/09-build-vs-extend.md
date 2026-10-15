# 09: 缺口里哪些自建、以什么形态

Type: grilling
Status: resolved
Blocked by: 05, 06, 07, 10, 11, 12

## Question

[05](05-probe-plugin-eval-on-hook-injection.md) 实测出 `claude plugin eval` 覆盖不到的缺口后，结合 [06](06-scope.md) 定下的范围与 [07](07-questions-eval-must-answer.md) 定下的问题清单，逐个缺口决定：

- 不做；
- 在 `claude plugin eval` 用例上加外围脚本补（如预处理会话、后处理 `aggregate-result.json`）；
- 以 wenyan 装置为原型自建独立 harness。

## 已知输入（来自 05）

- eval 能直接承担：SessionStart 注入留痕、工具入参或调用形状类纪律、正则可检的回复格式、多插件同载。
- eval 承担不了：UserPromptSubmit / PreToolUse / SubagentStart 注入留痕（只能自建 `--include-hook-events` harness，或读 `--keep-temp` 转录）、依赖 `AskUserQuestion` 的条款、多轮交互、「A 单装 vs A+B 同装」对照。
- 详见 [probe/REPORT.md 第六节](../probe/REPORT.md#六对工单-09-的影响)。

## 已知输入（来自 06）

- 机制是通用的：只接收一个被测插件目录作参数，不写死本仓路径；用例与结果放在被测插件所在仓。
- 会话复盘与离线对照两条都要；会话复盘只入库抽取结果。
- 离线对照默认纯净环境，要留「手动加一两个环境插件」的口子。

## 已知输入（来自 10）

- 会话复盘能机械取到：skill 调用与归属插件、PreToolUse deny（带插件名与版本）、`Agent` 等工具入参类违规、子代理与 compact 关联。
- 已知缺口：注入类 hook 事件不带插件名，只能靠脚本指纹加内容标签归因；插件历史版本无法还原，只能复盘时现读当前版本。
- 抽取脚本必须做的事：按 `uuid` 去重、并入子代理文件、按 marketplace `renames` 归一旧插件名、字段按 Claude Code 版本容错。
- 详见 [会话 jsonl 里能取到哪些评测信号](10-session-jsonl-signals.md)。

## 已知输入（来自 07）

- 问题清单按五类作用方式（skill、agent、注入、拦截、副作用）列出，见 [评测要回答哪些问题](07-questions-eval-must-answer.md) 的表。每个必答问题都要落到「eval / 外围脚本 / 自建 / 会话复盘」之一。
- 注入类要**逐条款**出结论，且要测 compact 之后是否仍遵守——后者 eval 单轮用例做不到。
- 拦截类的「被拦后是否一次改对」、副作用类的「失败是否静默」主要靠会话复盘。
- 四处人工介入点的形态在 [11](11-judging-and-human-checkpoints.md) 定，自建部分要为它们留界面。

## 已知输入（来自 11）

- 判分三档：规则 / AI 评委 / 用户终裁，逐问题归属见 [判分分工与人工介入点](11-judging-and-human-checkpoints.md) 的表。eval 自带的免费 grader 只覆盖「规则」档；AI 评委档要判两遍、要能先跑金标样本校准。
- 自建部分要产出一个本地 HTML 待审页（分歧样本、随机抽检、用例草稿、复盘候选、报告待审集中一页，回复码贴回对话），并管理报告的「待审 / 已审」状态。
- 人工环节每次 ≤ 10 分钟、≤ 10 项，超出自动抽样。

## 已知输入（来自 08）

- 会话复盘每周一次，由**本机定时任务**自动跑规则判分部分并生成待审页。机制要能评任何人的插件，定时任务需跨 macOS / Windows / Linux，与本仓「交付脚本跨平台」约定（devkit-portable-shell）一起考虑。
- 离线对照手动触发；升版本碰到注入文本、skill description、agent 定义时 AI 提示；Claude Code 升级或换模型时也跑——后者要有办法检测「Claude Code 版本或主力模型变了」。
- 单次对照 `--max-cost-usd 10`，每月合计 $50，需要有跨次累计花费的记账；用户时间每月 ≤ 1 小时，超出时调低抽样比例。
- AI 评委先用便宜一档、金标一致率不够再升档，评委模型要可配置。
- 发版闸门要做，覆盖范围与落点见 [12](12-release-gate-coverage.md)。

## 已知输入（来自 12）

- 闸门覆盖 major 与用户声明的版本：要有一种跨仓通用的**声明方式**（提交信息标记、plugin.json 字段或别的），检查命令据此判断某版本是否在闸门内。
- 闸门外的版本须过**规则判分子集**：只跑新版一臂、免费 grader、不调 AI 评委；子集大小受「每月升版数 × 子集单价 ≤ 每月 $50 减对照与复盘花费」约束（近 30 天约 37 个闸门外版本）。
- 提供通用的**闸门检查命令**（入参插件目录）：查该版本是否有已审报告或规则子集通过记录、或 `eval-skip:` 标记；本仓不接 git hook，手动运行。
- 每周会话复盘的待审页要列出 `eval-skip:` 版本，并检出「闸门内版本推到 main 时既无已审报告也无 eval-skip」的漏检——这是 12 的重开条件。

## Answer

> **2026-10-15 部分覆盖**：用户 2026-10-15 撤销美元花费上限（原话「由于我使用的是订阅 测评额度不适用 可以去掉 避免因为额度干扰了测评的质量」），随后拍板四项连带决定（原话「Q17 用最贵那一档 比如Fable模型 其他按照建议」），记录见 [08](08-cadence-and-budget.md) Comments。作废：「跨次花费」一行与第二轮第 5 问的用户级账本、跑前算余额、`--max-cost-usd` 取 min(10, 余额)。现行：不设上限、不建账本、不查余额，`run.json` 记 token 与标价估算只作信息；**撞上订阅用量限制而失败的 run 判为无效、不计分，整次运行标「不完整」、可从断点续跑，不完整的结果不计入发版闸门**。

2026-10-14 用户三轮拍板（第一轮「全部按ai的推荐」、第二轮「其他按照推荐来」、第三轮「Q15 选 c」）。

**总判断：不建独立 harness。** 离线对照唯一的运行器是 `claude plugin eval`；它覆盖不到的部分，要么由外围脚本补，要么交给会话复盘。[已有散装评测怎么处理](04-existing-eval-artifacts.md) 定的「wenyan 装置作原型」只作外围脚本的参考。

**逐缺口处置**：

| 缺口 | 处置 | 做法 |
|---|---|---|
| UserPromptSubmit / PreToolUse / SubagentStart 注入不进 trace | 外围脚本 | 读 `--keep-temp` 转录，核验「注入已到达」；作前置检查，不计分。遵守与否仍由 eval 判 |
| compact 之后是否仍遵守 | 会话复盘为主，eval 补充 | 真实会话按 compact 关联统计；离线用 `context.history_file` 回放一份 compact 之后的会话再评下一轮 |
| 多轮交互 | eval | `context.history_file` 回放 |
| 依赖 `AskUserQuestion` 的条款 | 会话复盘 | 离线对照不评 |
| 臂（不装 / 上一版 / 当前版 / 加环境插件） | 外围脚本 | 每个臂各跑一次 `eval --ablation none`，脚本自己相减；四种基线一套逻辑 |
| AI 评委（判两遍、金标校准） | 外围脚本 | eval 里只用规则 grader；AI 评委在 eval 之外读完整转录判分 |
| 常驻 token | 外围脚本 | 直接执行 hook 脚本、按输出计数，不调模型，发版前可得 |
| hook 时延 | 会话复盘 | 取 `hook_success.durationMs` |
| Claude Code 版本 / 主力模型变了 | 会话复盘 | 比对会话记录的 `version` / `model` 与上次对照时的记录，变了在待审页列「建议跑对照」 |
| 升版碰到注入文本、skill description、agent 定义 | 闸门检查命令 | 输出「建议跑对照」 |
| `eval-skip:` 版本列表、闸门内版本漏检 | 闸门检查命令 | 每次运行时列出（覆盖 [12](12-release-gate-coverage.md) 第 4 条与重开条件里的「每周复盘」） |
| 跨次花费 | 外围脚本 | 用户级账本；跑前算本月余额，`--max-cost-usd` 取 min(10, 余额)；每份结果记自身花费 |
| 本地 HTML 待审页 | 外围脚本 | 每次离线对照一页、每次复盘一页，各 ≤ 10 项 |

**会话复盘**：**手动触发，不做定时任务**（覆盖 [谁跑、何时跑、花多少](08-cadence-and-budget.md) 第 2 条「每周、本机定时任务」）。跑离线对照或闸门检查时，若距上次复盘超过 7 天，提示先复盘。复盘范围是**用户登记的被测插件清单**（每项写插件名与所在仓路径），结果写回各自的仓。

**交付形态**：本仓新插件 **`devkit-plugin-eval`**。一个 Python 命令行承担全部动作（跑对照、复盘、待审、闸门检查、记账）；skill 只拆两个决策时刻——「跑离线对照」「处理待审」。不加常驻 hook。

**未选**：自建 harness 真跑到 compact、eval 内置 `llm` 评委（单用或与外围评委叠用）、MCP 打桩冒充 `AskUserQuestion`、`--include-hook-events` harness、不核验注入到达、「不装」用 eval 自带双臂而其余臂另比（Jev 选此项，置信 0.34）、代价全在离线或全在复盘测、`devkit-eval` 命名、每动作一个 skill 或一个统领 skill、复盘全部已装插件、账本放各仓、SessionStart hook 检测版本变化、全局待审页、每周定时复盘（含三平台定时注册与稳定启动器）、纯手动复盘不提醒。

**残余不确定**：

- 用 `history_file` 回放「compact 之后」的会话能否测出差异，未实测；构造方式归地图 fog「用例从哪来」。
- `--keep-temp` 转录的格式随 Claude Code 版本是否稳定，未查。
- 复盘改手动后，拦截类、副作用类、`AskUserQuestion` 类问题的答案依赖用户响应「超 7 天」提示。

**重开条件**：

- 回放测不出 compact 后差异、且会话复盘里 compact 后样本不足以下结论时，重议是否自建 harness。
- 连续两次「超 7 天」提示后仍没有复盘记录时，重议是否恢复定时任务。

## Comments

### 2026-10-14 第一轮提问（待答）

已认领。补查两条事实：eval 支持 MCP 打桩（`mocks/<server>/<tool>.md`，见 01 研究第 28 行）；会话 jsonl 的 `hook_success` 带 `durationMs`、`hook_additional_context` 带注入原文（见 10 研究第 65–66 行）。

第一轮问七件，互不依赖：

1. compact 之后是否仍遵守——载体（推荐：会话复盘为主 + eval `history_file` 回放补充，不建 harness）。
2. 依赖 `AskUserQuestion` 的条款（推荐：只靠会话复盘）。
3. AI 评委放哪（推荐：eval 只用规则 grader，评委在 eval 外自建、读 `--keep-temp` 全量转录）。
4. 对照的臂谁管（推荐：外围脚本按臂各跑一次 `--ablation none` 再自算差；Jev 选「不装用 eval 自带双臂、其余另比」，置信 0.34）。
5. 非 SessionStart 注入不进 trace（推荐：外围读转录做「注入已到达」前置核验，不计分）。
6. 代价指标（推荐：常驻 token 离线静态算，hook 时延取会话复盘）。
7. 交付形态（推荐：本仓新插件，skill 入口 + Python 脚本；定时任务指向稳定入口）。

若 1、2、5 都不选自建 harness，则 04 定的「wenyan 装置作原型」只剩外围脚本的参考价值，独立 harness 不建。

### 2026-10-14 第一轮答复

用户原话「全部按ai的推荐」，七问照推荐定：

- Q1 compact 后是否仍遵守：**会话复盘为主 + eval `history_file` 回放补充**，不建 harness。
- Q2 依赖 `AskUserQuestion` 的条款：**只靠会话复盘**，离线对照不评。地图 fog「依赖人机交互的纪律怎么评」随之消解。
- Q3 AI 评委：**eval 只用规则 grader；AI 评委在 eval 外自建**，读 `--keep-temp` 全量转录，判两遍、金标校准。
- Q4 臂：**外围脚本按臂各跑一次 `eval --ablation none`，自己算差**；四种基线一套逻辑。Jev 选 b（置信 0.34），未采纳，理由是改版占多数、「比上一版」本就要外围做。「臂」已写入 `CONTEXT.md`。
- Q5 非 SessionStart 注入：**外围读转录核验「注入已到达」，作前置检查、不计分**。
- Q6 代价：**常驻 token 离线静态算（直接执行 hook 脚本计输出），hook 时延取会话复盘 `durationMs`**。
- Q7 交付形态：**本仓新插件，skill 入口 + Python 脚本**。

推论：三处都没选自建 harness，**独立 harness 不建**；离线对照的唯一运行器是 `claude plugin eval`，其余（臂编排、AI 评委、注入到达核验、静态 token 计数、会话复盘）都是新插件里的外围脚本。

### 2026-10-14 第二轮提问（待答）

补查：`~/.claude/plugins/installed_plugins.json` 每项带 `installPath`（当前版本缓存目录）；会话记录每条带 `"version"`（Claude Code 版本）、assistant 记录带 `"model"`。

1. 插件名（推荐 `devkit-plugin-eval`）。
2. 入口切分（推荐：一个 Python CLI 承担全部动作；skill 按决策时刻只拆「跑离线对照」「处理待审」两个）。
3. 每周复盘评哪些插件（推荐：用户登记的被测插件清单，每项含所在仓路径，结果写回各自仓）。
4. 定时任务入口（推荐：系统定时任务调一个固定位置的极小启动器，启动器运行时读 `installed_plugins.json` 找当前版本脚本）。
5. 记账（推荐：用户级账本，跑前算本月余额，`--max-cost-usd` 取 min(10, 余额)）。
6. 版本 / 模型变化检测与升版提示（推荐：每周复盘比对 `version`/`model`，变了在待审页列「建议跑对照」；升版提示由闸门检查命令输出，不加常驻 hook）。
7. 待审页粒度（推荐：每次离线对照一页、每周复盘一页，各 ≤ 10 项）。

### 2026-10-14 第二轮答复

用户原话「Q11- 之前的决策中不是已经 去掉每周定时评估这个功能和定时功能了， 为啥这里还在问 / 其他按照推荐来」。

- 插件名 **`devkit-plugin-eval`**。
- 入口：**一个 Python 命令行承担全部动作；skill 只拆「跑离线对照」「处理待审」两个**。
- 复盘范围：**用户登记的被测插件清单**（插件名 + 所在仓路径），结果写回各自仓。
- 记账：**用户级账本**，跑前算本月余额，`--max-cost-usd` 取 min(10, 余额)；每份结果记自身花费。
- 版本 / 模型变化与升版提示：**复盘时比对 `version`/`model`，变了在待审页列「建议跑对照」；升版提示由闸门检查命令输出；不加常驻 hook**。
- 待审页：**每次离线对照一页、每次复盘一页，各 ≤ 10 项**。
- 定时任务入口（第二轮第 4 问）：**未定**。用户认为定时复盘已去掉；核查书面记录：[08 Answer 第 2 条](08-cadence-and-budget.md) 写的是「会话复盘每周一次，由本机定时任务自动跑」，地图 Decisions so far 同；[12](12-release-gate-coverage.md) 的 `eval-skip:` 收口与重开条件依赖每周复盘；`.scratch/`、`docs/`、记忆目录均未找到去掉定时的记录。已向用户确认（第三轮）。

### 2026-10-14 第三轮提问与答复

问：会话复盘怎么启动——a 保留每周定时、b 去掉定时纯手动、c 去掉定时、手动触发、超 7 天在跑对照或闸门检查时提醒（推荐 c，Jev 同选 c，置信 0.62）。

答：用户原话「Q15 选 c」。第二轮第 4 问（定时任务入口）随之作废。已同轮改写：[08](08-cadence-and-budget.md) 第 2 条划掉并标注覆盖、[12](12-release-gate-coverage.md) 第 4 条与重开条件改由闸门检查命令承担、`CONTEXT.md`「发版闸门」词条同步、地图 Decisions so far 对应两行同步。

本票据此关闭。新开 [13](13-result-layout.md)、[14](14-previous-version-arm.md)、[15](15-preflight-checks.md)、[16](16-existing-deterministic-tests.md)，由地图 fog 毕业而来。

### 2026-10-15 来自 20 的修订输入

[条款清单的生命周期](20-clause-list-lifecycle.md) 细化缺口表「升版碰到注入文本、skill description、agent 定义」一行的注入文本部分：触发条件落实为**注入文本指纹**（真实 HOME、空 cwd 执行注入 hook 取输出算指纹）相对上次对照变化，提示文字为「建议跑对照（会先更新条款清单）」，只出一条。skill description、agent 定义两部分不变。
