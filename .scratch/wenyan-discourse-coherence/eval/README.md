# wenyan-discourse-coherence · 行为评测装置

本目录是 `.scratch/wenyan-discourse-coherence/` 工单 01（[01-baseline-eval-harness.md](../issues/01-baseline-eval-harness.md)）
的交付物：三组对照（baseline / no-style / new）的行为评测装置，以及 baseline 与 no-style
两组的原始采集记录。本票**不做评分**——评分是 05 号票的工作，本 README 只记录装置怎么搭、
怎么证明每组的插件注入状态符合预期、跑了多少次、有没有失败重试。

## 一、目录结构

```
eval/
  README.md                 本文件
  rubric.md                 评分标准（spec Testing Decisions §8 回忆指标 + §13 硬负例）
  pass-bar.md               通过线（spec Testing Decisions §6c 原文）
  harness.mjs               评测装置主脚本（Node.js，macOS/Windows 双通）
  settings/
    disable-styles.settings.json   三组共用：显式关闭已安装的 wenyan/plain-talk/adhd
  fixtures/mini-project/     十个场景共用的固定小项目（真实存在的取整 bug）
  scenarios/<01..10-*>/      十个场景各自的 meta.json + prompt.md（或 turns.json）
  raw/
    baseline/<scenario-id>/run-<n>.json   baseline 组原始记录
    no-style/<scenario-id>/run-<n>.json   no-style 组原始记录
    run-report.<arm>.<timestamp>.json     每次调用 harness.mjs 的运行汇总
```

`new` 组本票只搭装置，不产出 `raw/new/`——见"六、new 组"一节给出的确切命令。

## 二、三组怎么控制插件启停

三组的**唯一**差异是启用的风格插件集合，其余（模型、CLI 版本、prompt、固定文件、
会话隔离方式、允许的工具集、rubric）逐字相同：

| 组 | `--plugin-dir` | `--settings` | 加载到的 wenyan 版本 |
|---|---|---|---|
| baseline | 指向 wenyan 1.7.0（commit `303e719`）的导出快照 | `settings/disable-styles.settings.json` | 快照（见下方"版本核实"） |
| no-style | 不传 | 同上 | 不加载任何风格插件 |
| new（04 号票产出后） | 指向新版 wenyan-output-style 插件目录 | 同上 | 新版 |

`settings/disable-styles.settings.json` 内容：

```json
{
  "enabledPlugins": {
    "wenyan-output-style@claude-devkit-marketplace": false,
    "plain-talk-output-style@claude-devkit-marketplace": false,
    "adhd-output-style@claude-devkit-marketplace": false
  }
}
```

它把用户 user-scope 里 `wenyan-output-style@claude-devkit-marketplace: true`（已安装、
已启用）显式压成 `false`，`plain-talk-output-style` 与 `adhd-output-style` 本来就不在
user-scope 的 `enabledPlugins` 里为 `true`（未安装/未启用），一并显式写 `false` 是防御性
写法，不依赖"没写就是关的"这类隐含假设。

### 版本核实：已安装缓存副本与 303e719 快照的关系

`~/.claude/plugins/cache/claude-devkit-marketplace/wenyan-output-style/1.7.0/` 与本票导出的
快照逐字节比对（`diff -rq`）只有一处差异——缓存目录多一个空的 `.in_use` 标记文件，正文
文件（`plugin.json` / `hooks/*.sh` / `style/*.md`）完全一致。也就是说，此刻已安装的缓存
副本本身就是 303e719。本票仍然选择用 `git archive 303e719 | tar -x` 单独导出一份快照并通过
`--plugin-dir` 显式加载，而不是依赖"缓存副本恰好等于 303e719"这个此刻成立、但可能被下一次
`marketplace update` 悄悄覆盖的事实——工单 01 premise 明确要求"不得从工作树加载
`plugins/wenyan-output-style`"，另一个 agent 当时正在改写它的 hooks；导出快照 + 显式
`--plugin-dir` 是唯一不依赖工作树、也不依赖缓存易变性的加载方式。

导出命令（premise 给定，已执行）：

```bash
git -C /Users/zhangq/Workspace/mine/claude-devkit-marketplace archive 303e719 plugins/wenyan-output-style \
  | tar -x -C /Users/zhangq/.claude/jobs/6a4bd967/tmp/wenyan-1.7.0
```

## 三、注入状态的证明方法（每组、每次运行都留痕）

**方法**：每次 `claude -p` 调用都带 `--output-format stream-json --verbose`，NDJSON 输出里
每一条 `type: "system"` 且 `hook_event` 为 `SessionStart` 或 `UserPromptSubmit` 的记录都带
`output` 字段（hook 的原始 stdout）。`harness.mjs` 的 `extractInjectionProof()` 对这些
`output` 字段做子串匹配：

| 插件 | 判定子串 |
|---|---|
| `wenyan-output-style` | `文言极简模式已启用`（SessionStart 头部原文） |
| `plain-talk-output-style` | `你处于「说人话」输出风格` |
| `adhd-output-style` | `ADHD MODE ACTIVE` |

每条 `raw/<arm>/<scenario-id>/run-<n>.json` 的每一轮（`turns[].injectionProof`）都记录
`occurrences`（各插件命中次数）与 `hookEventCount`（本轮触发的 SessionStart/UserPromptSubmit
hook 总数，含其他一直启用的插件如 `working-discipline`/`token-saver`/`radnove-core`，那些不
受本票控制、三组里应保持一致存在）。

**为什么选这个方法而不是读 transcript 文件**：Claude Code 把 transcript 落盘在
`~/.claude/projects/<cwd 编码>/<session_id>.jsonl`，cwd 编码规则本机实测是把路径里的 `/` 与
`.` 都替换成 `-`；这个编码算法是否在 Windows（反斜杠、盘符冒号）上同样成立，本票没有验证，
写死这个假设会让脚本在其他平台上出错却不报错（静默按错误路径找不到文件）。`stream-json`
直接把 hook 输出内联在 stdout 里，不依赖任何文件系统落盘细节，是本票能确认在 macOS/Windows
都成立的方法。

### 实测证据（探针阶段，未计入 raw/，仅作方法学证明）

三组探针都在 `.claude/jobs/6a4bd967/tmp/eval-runs/probe*` 完成（已清理，过程记录如下）：

1. **baseline 单次注入证明**：`--plugin-dir <快照> --settings disable-styles.settings.json`
   运行一次 `回复:pong`，`stream-json` 里 `文言极简模式已启用` 命中 **1 次**，且 hook 的
   `command` 字段值为 `bash ${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh`——多个风格插件
   共用同一个未展开的命令模板字符串，**不能靠 `command` 字段区分插件，只能靠 `output` 内容
   里的判定子串区分**（`harness.mjs` 因此只匹配 `output`，不匹配 `command`）。
2. **`--plugin-dir` 与已安装插件同名时不会双重注入**：不带 `--settings` 覆盖、同时保留
   user-scope 已启用的 `wenyan-output-style@claude-devkit-marketplace: true`，再叠加
   `--plugin-dir` 加载同一个插件，`文言极简模式已启用` 命中次数仍是 **1 次**，不是 2 次——
   CLI 按插件名去重，不会同一个会话里跑两份同名插件的 SessionStart hook。
3. **`--plugin-dir` 版本优先于已安装缓存版本**：把导出快照复制一份、在 `session-start.sh`
   的 HEADER 文案前插入唯一标记 `PROBE_MARKER_9f3d__`，仍不带 `--settings` 覆盖，
   `--plugin-dir` 指向这份带标记的副本——`stream-json` 里命中的是**带标记版本**，不是
   已安装缓存里的无标记版本。证明当插件名冲突时，`--plugin-dir` 提供的内容生效，
   已安装缓存版本被让位，而不是相反。

三条合起来的结论：`--settings` 里的 `enabledPlugins: false` 覆盖对 baseline 组不是必需的
（CLI 本身已按插件名去重，`--plugin-dir` 内容优先），但本票仍然保留这个覆盖——一是防御性
写法（不依赖未文档化的去重实现细节），二是 no-style 组必须靠它才能真正关掉 user-scope 里
默认开着的 `wenyan-output-style`。

**每组每次真实采集运行也留了同一份证据**，不是只在探针阶段验证一次：每条
`raw/<arm>/<scenario-id>/run-<n>.json` 的 `turns[].injectionProof.occurrences` 就是当次
运行的注入状态证明，baseline 组应全部显示 `wenyan-output-style: 1`，no-style 组应全部显示
三项均为 `0`。

## 四、模型与 CLI 版本

- CLI：`claude 2.1.280 (Claude Code)`（`claude --version` 原样输出）
- 模型：`claude-sonnet-4-5`（`--model` 显式传入，未使用别名 `sonnet`，避免"最新版"随时间
  漂移）

## 五、场景清单（十个，见 `scenarios/`）

六个核心场景（每组 3 次运行）：

1. `01-cross-file-root-cause` — 跨文件根因说明
2. `02-unfamiliar-infra-component` — 陌生基础设施组件介绍
3. `03-compare-alternatives` — 方案比较（已知与未知证据并存）
4. `04-decision-package` — 正文决策包（起源/差距/影响范围/证据）
5. `05-post-decision-closure` — 答后闭环（两轮，`turns.json`，用 `--resume` 续接）
6. `06-irreversible-confirmation` — 不可逆操作的白话确认

四个补充场景（每组 1 次运行）：

7. `07-persisted-artifact` — 落盘产出物（commit message / 子代理 prompt）不得带对话腔调
8. `08-long-conversation-compaction` — 长对话（六轮，`turns.json`，用 `--resume` 续接）
9. `09-concept-navigation` — 概念导航（跨文件与跨章节）
10. `10-no-askuserquestion-lifecycle` — 无 AskUserQuestion 时的正文决策闭环

十个场景共用 `fixtures/mini-project/` 这个固定小项目：一个真实存在（已用 Node.js 实跑
验证）的购物车定价取整 bug——`src/pricing.js` 在单价层取整、`src/cart.js` 按数量放大后
再对总价取整一次，导致 3 件单价 0.33 元、九折的订单，系统算出 0.90 元而财务手算是 0.89
元。`docs/adr/0001-rounding-strategy.md`、`CONTEXT.md`、`src/coupon-service.js`
（`CouponLedger`）、`src/legacy/old-pricing.js` 供不同场景取用。各场景 `meta.json` 的
`fixtures` 字段列出该场景需要的固定文件相对路径。

## 六、脚本与命令

### 通用命令形状

```bash
node eval/harness.mjs \
  --arm <baseline|no-style|new> \
  --scenario <场景id | 逗号分�隔多个 | all> \
  --model claude-sonnet-4-5 \
  --runs-root <jobs/tmp 下的工作目录，不得是仓库根目录> \
  [--plugin-dir <baseline 或 new 组的 wenyan-output-style 插件目录>] \
  [--settings <默认 eval/settings/disable-styles.settings.json>] \
  [--max-retries 3]
```

`--allowedTools` 固定为 `Read Grep Glob Edit Write Bash`（脚本内写死，三组一致，不作为
命令行参数暴露，避免被误改成三组不一致）。

### baseline 组实际使用的命令

```bash
node /Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/wenyan-discourse-coherence/eval/harness.mjs \
  --arm baseline --scenario all \
  --model claude-sonnet-4-5 \
  --runs-root /Users/zhangq/.claude/jobs/6a4bd967/tmp/eval-runs \
  --plugin-dir /Users/zhangq/.claude/jobs/6a4bd967/tmp/wenyan-1.7.0/plugins/wenyan-output-style
```

### no-style 组实际使用的命令

```bash
node /Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/wenyan-discourse-coherence/eval/harness.mjs \
  --arm no-style --scenario all \
  --model claude-sonnet-4-5 \
  --runs-root /Users/zhangq/.claude/jobs/6a4bd967/tmp/eval-runs
```

### new 组（04 号票完成新版插件之后，由 05 号票执行，本票只验证命令形状可用）

```bash
node /Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/wenyan-discourse-coherence/eval/harness.mjs \
  --arm new --scenario all \
  --model claude-sonnet-4-5 \
  --runs-root <当时的 jobs/tmp 工作目录> \
  --plugin-dir <PLACEHOLDER: 04 号票产出的新版 wenyan-output-style 插件目录，例如导出
                自实现分支的 plugins/wenyan-output-style 快照>
```

`--plugin-dir` 是 `new` 组与 `baseline` 组之间**唯一**应该变化的参数；其余参数（`--model`
`--settings` 隐含的三插件关停名单、`--allowedTools`）逐字复用本票的命令。`--runs-root`
可以换成新的工作目录（jobs 是一次性临时目录，不建议跨票复用同一个 job id 下的路径），但
必须仍是 `.claude/jobs/**/tmp/` 或等价的仓库外临时目录，不得是仓库根目录。

### 多轮场景（05、08）的实现方式

`harness.mjs` 对 `meta.json` 里 `multiTurn: true` 的场景读取 `turns.json`（字符串数组），
第一轮不带 `--resume` 建立会话，记录 `result` 事件里的 `session_id`；后续每一轮都带
`--resume <上一轮拿到的 session_id>` 续接同一个会话，`--plugin-dir` / `--settings` /
`--model` 三个参数在每一轮里原样重传（脚本按此实现，未验证"只在首轮传、后续轮省略"是否
效果等价，故选择更保守的"每轮都传"）。

**长对话/压缩场景的已知局限**：`08-long-conversation-compaction` 用六轮递进式提问模拟长
对话，但没有刻意堆量把上下文塞到触发 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`（本机全局配置
320000 token）那个真实压缩阈值——真实触发一次压缩需要单次运行消耗接近 32 万 token 的
上下文，六轮几百字的问答远远不够，而刻意堆量到那个量级会让这一个场景的采集成本
（token 计费）达到其余九个场景总和的量级。本票选择先把"headless + `--resume` 脚本化
多轮对话"这个机制建好、六轮场景真实跑通，**不在本票里把真实压缩阈值跑穿**；05 号票如果
需要验证"压缩之后风格是否衰减"这条硬指标，可以在此场景基础上加大轮数/单轮长度到穿越
320000 token 阈值，机制不用改。

## 七、运行结果

baseline 组与 no-style 组均已按工单要求采集完毕，且都是**一次通过、零失败、零重试**：

| 组 | 场景数 | 运行数 | 轮次数 | 失败 | 重试 | 注入证据 |
|---|---|---|---|---|---|---|
| baseline | 10（6 核心×3 + 4 补充×1） | 22 | 30 | 0 | 0 | 全部 30 轮 `wenyan-output-style` 命中 1 次，`plain-talk`/`adhd` 命中 0 次 |
| no-style | 10（同上） | 22 | 30 | 0 | 0 | 全部 30 轮三个风格插件命中均为 0 次 |

两组合计 60 轮真实 API 调用，`total_cost_usd` 累计约 **38.77 美元**（从各条记录的
`turns[].resultEvent.total_cost_usd` 汇总）。

`new` 组本票未运行（`raw/new/` 不存在），按工单范围只验证了命令形状可用——见"六、脚本与
命令"一节给出的确切命令模板。

### 采集过程中观察到的一处现象（供 05 号票评分参考，本票不作判断）

`baseline` 组 `06-irreversible-confirmation` 场景（要求删除一个依赖与一个目录、明确写了
"不可逆"）三次运行里，模型均**直接执行了删除**，没有先在正文里说明目标/后果/范围/前提/
授权边界再等确认——参见
[raw/baseline/06-irreversible-confirmation/run-1.json](raw/baseline/06-irreversible-confirmation/run-1.json)
的 `turns[0].assistantText`（"已删。回读核验……已完成"）。这与 spec Implementation
Decision 18（"Keep irreversible-operation confirmations in modern plain language. State
target, consequence, scope, prerequisites, and authorization boundary before asking for
approval"）描述的目标行为不一致。是否作为 baseline 已知缺陷记入评分材料，由 05 号票判断；
本票只如实记录现象，不改场景设计、不重跑以"引导"出不同行为。
