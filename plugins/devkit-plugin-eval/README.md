# devkit-plugin-eval

评测 Claude Code 插件：任给一个你自己写的插件（下称**被测插件**），量出装它与不装、这一版与上一版的差，读本机会话记录统计它实际的触发与拦截，并在发版前判这一版能不能发。

- 运行器是官方的 `claude plugin eval`，本插件只是外围的一个 Python 命令行（只用标准库）。
- 两个 skill：`run-eval`（跑评测）、`handle-pending`（处理待审页与回复码）。
- 不装任何 hook，不在每轮对话里注入文字。

设计依据与全部口径见 [spec](../../.scratch/plugin-eval/spec.md)（插件评测机制的完整设计）。本文只讲怎么用。

## 一、它做哪几件事

| 动作 | 回答什么问题 | 结果 |
|---|---|---|
| **离线对照**（`compare`） | 装了比不装好多少；这一版比上一版有没有退步 | 运行目录 `runs/<时间>-<版本>-compare/` 下的 `run.json` 与 `report.md`，状态「待审」 |
| **会话复盘**（`review`） | 真实使用中插件触发了几次、拦了几次、hook 报错与时延 | `reviews/<日期>.json`，只存计数与定位指针，不存对话原文 |
| **发版闸门**（`gate`） | 这一版能不能发布 | 只输出结论与提示，不落盘 |
| **待审页**（`pending`） | 需要人拍板的项 | 本机 HTML 页；你选完复制回复码贴回对话，命令行写回 |

离线对照分几个**臂**跑，每臂一次 `claude plugin eval --ablation none`，臂与臂相减得到差：

- **不装**：只装一个空桩插件。
- **上一版**：沿 git 历史找版本号与当前不同的最近一版，`git archive` 解出快照。新插件、从没升过版本号、不在 git 仓里时这个臂自动跳过（报告首段写明原因），只比「不装」与「当前版」。
- **当前版**：工作目录里的插件。
- **当前版 + 环境插件**（可选）：复现与别的插件的冲突时才加。

## 二、谁跑、何时跑、占你多少时间

| 动作 | 谁触发 | 何时 | 你的时间 |
|---|---|---|---|
| 离线对照 | 你手动；AI 在会话里执行，长任务放后台 | 你想跑时；AI 提示的三种情形（见下） | 每次一页待审，≤ 10 分钟、≤ 10 项 |
| 会话复盘 | 你手动 | 跑对照或闸门时，距上次复盘超过 7 天会提示 | 每次一页待审，≤ 10 分钟、≤ 10 项 |
| 闸门检查 | 你手动 | 发版（推 main）前 | 0（只读输出） |
| 规则判分子集 | 闸门检查需要时 | 闸门外版本发版前 | 0 |
| pre-commit 单测 | git 自动 | 本仓每次提交 | 0（代价是提交耗时） |

- AI 提示你跑离线对照的三种情形：升版时改动碰到注入文本、skill description 或 agent 定义；Claude Code 升级；换主力模型。
- 合计每月 ≤ 1 小时。超出时调低待判项的抽样比例，不跳过整次评测。
- 花费：评测走你的订阅，不设美元上限。`run.json` 记 token 与标价估算，只作信息。
- 没有定时任务：复盘与闸门都靠你记得跑，命令行只在相关动作里提醒。

## 三、怎么调用

在 Claude Code 会话里直接说要做的事，AI 会按 skill 调命令行：

- 「评一下 my-plugin」「这版比上一版好还是差」「发版前过一下闸门」「跑会话复盘」 → `run-eval`
- 贴回 `PE1 …` 回复码、「还有哪些待审」 → `handle-pending`

手动执行时：

```bash
python3 <插件安装目录>/scripts/plugin_eval.py [--data-dir <数据目录>] <子命令> ...
```

- **用户级数据目录**放登记清单 `registry.json`、待审页 HTML、全量 trace 缓存，缺省是 `~/.claude/plugins/data/devkit-plugin-eval-<市场名>/`。从插件缓存目录执行时自动推出；从源码仓直接执行时推不出，要显式传 `--data-dir`。skill 里传的是 `"${CLAUDE_PLUGIN_DATA}"`。
- `--data-dir` 是顶层参数，写在子命令前面。
- 本文所有命令写 `python3`。**Windows 上把 `python3` 换成 `python` 或 `py -3`**；另外 cmd 不认单引号，`--reply` 的回复码改用双引号包住。

## 四、登记被测插件

```bash
python3 plugin_eval.py register <插件名> --repo <被测插件所在仓的根目录>
python3 plugin_eval.py list
```

- 插件名必须与 `plugin.json` 的 `name` 一致。命令先找 `<仓>/plugins/<插件名>/`，再看仓根本身是不是这个插件。
- **登记即信任声明**：之后每次对照都给 eval 加 `--trust-plugin` 与 `--scaffold`，以你的身份运行插件代码与用例声明的 `scaffold_script`。
- 未登记的插件跑 `compare` 会中止；会话复盘只扫登记清单里的插件。`gate` 不要求登记，`gate --run-subset` 要求。

## 五、命令行子命令

各子命令的参数以 `python3 plugin_eval.py <子命令> --help` 为准，下表只讲用途。

| 子命令 | 做什么 | 调模型 |
|---|---|---|
| `register` / `list` | 登记被测插件 / 列出登记清单 | 否 |
| `check <插件>` | 单跑前置检查：hook 解释器可达、`claude` 与 eval 参数、登录态、`claude plugin validate`、已登记等硬项，工作区未提交改动等软项。`--review` 查复盘前的各项。硬项失败退出码 2 | 否 |
| `clauses <插件>` | 首次抽**条款清单**（从注入文字拆出可单独判定的条款）。只在插件尚无 `clauses.json` 时执行；之后清单过期由 `compare` 第一步增量重抽 | 是 |
| `drafts write <插件>` | AI 按条款清单的缺口起草**用例草稿**，出待审页。`--clauses C001,C007` 只起草点名的条款（点名时已打回的草稿会重写） | 是 |
| `drafts compact <插件>` | 起草 **compact 回放用例**：合成一段对话历史，先 compact 再追问，测压缩后是否仍守条款。每插件合计 ≤ 3 个（含已打回的）；`--clauses` 点名时已打回的不算覆盖、会重写 | 是 |
| `drafts from-review <插件>` | 把复盘待审页里选了「转草稿」的候选改写成用例草稿，出待审页。`--date` 指定哪天的复盘，缺省最新。隐私防护见第六节 | 是 |
| `drafts page` / `list` / `sync` | 只出草稿待审页 / 只读地列草稿区 / 把退役条款的用例退回草稿区并附改挂建议 | 否 |
| `baseline <插件>` | 新用例在「不装」臂跑 3 次，≥ 2/3 通过的打 `baseline-satisfied` 标记，只作**回归守护用例**（比上一版不退化，不计相对不装的差） | 是 |
| `compare <插件>` | 跑一次离线对照。`--base` 指定上一版，`--env-plugin` 加环境插件臂，`--no-judge` 不调 AI 评委。完整时终端最后一行给出生成本次待审页的完整命令（带 `--run`） | 是 |
| `resume <运行目录>` | 续跑不完整的对照：已完成的 run 不重跑，只补判无效与未跑的 run；收尾自动重新生成待审页 | 是 |
| `pending <插件>` | 生成待审页（缺省取最新一次对照、条款或草稿运行；`--run` 指定；`--review` 出复盘页）；`--reply '<回复码>'` 写回 | 否 |
| `review` | 会话复盘：读本机会话记录，给每个已登记插件写 `reviews/<日期>.json`。`--days` 往回看几天 | 否 |
| `gate <插件目录>` | 发版闸门，见第九节。`--run-subset` 缺依据时跑规则判分子集，`--threshold` 定通过口径 | 仅 `--run-subset` |

退出码：0 成功；2 用法、登记、环境类错误（含前置检查硬项失败）；3 对照跑完但结果不完整。`gate` 另用 1 表示未过闸。

### 首次评测一个插件的顺序

1. `register` 登记。
2. `clauses` 抽条款清单，在待审页确认。插件没有常驻注入时它输出「不需要条款清单」、退出码 0，直接下一步。
3. `drafts write` 起草用例，在待审页勾选；通过的草稿在写回时自动移进 `plugins/<插件>/evals/`。
4. `baseline` 判基线。
5. `compare` 跑对照，照终端最后一行的命令（`pending <插件> --run <运行目录名>`）出页，审报告。
6. 发版前 `gate`。

### 不完整与续跑

撞订阅用量限制、eval 超时（`--eval-timeout`）、用例加载失败等，都会让运行判「不完整」：退出码 3，终端列出原因与续跑命令。不完整的结果不计入发版闸门。

续跑时 Claude Code 版本变了照常合并，版本全部记下；主力模型变了则判不完整，再续跑也合不成完整，要重新对照。规则判分子集（`gate --run-subset`）不能续跑，不完整就整个重跑。

## 六、待审页与回复码

需要人拍板的东西集中在一个本机 HTML 页：报告审阅、AI 评委的分歧样本与抽检、条款清单变更、用例草稿勾选、复盘候选选题。

1. `pending <插件>` 生成页，输出页路径与浏览器链接。
2. 你在页上逐项选，页底拼出回复码，形如 `PE1 <run_id> <page_id> 1A 2B ...`，点「复制回复码」。
3. 把回复码贴回对话（或自己执行 `pending <插件> --reply '<回复码>'`）。回复码不合法（页已作废、已写回过、序号或选项码不对）时退出码 2，什么都不写；落盘途中出错时报错列出「已写成」的文件、`run.json` 保持旧状态，排除问题后用同一回复码重试即可补齐。

规则：

- 每页 ≤ 10 项。报告审阅与条款清单变更必上页；其余按「分歧样本 > 抽检 > 用例草稿 > 复盘候选」装入，装不下的随机抽，抽样规则写进报告。没上页的项留到下一页。
- 只认最新一页，且只能写回一次。重新生成页会让旧页作废。
- **待审报告不能作为改插件或发版的依据。** 你审过、写回成「已审」才算数。

### 复盘候选转草稿的隐私防护

`drafts from-review` 读本机真实会话，把选中的候选改写成用例。产出是**由本机真实会话改写**的，通过前要逐字审隐私（prompt、对话历史、grader、文件桩都要看）。防护有四层：

- 原文片段只在内存里交给 AI 改写，不落盘。写盘前对改写结果自检：路径与邮箱形态；从这次会话推断出的私有词（项目目录名、家目录用户名、git 分支名、出现过的主机名与包名里的非通用段）；与原文片段逐字重合 24 字以上（重合部分整段落在被测插件已跟踪文件或 Claude Code 固定文案内时不算）。任一命中整条不写，结果记 `privacy-rejected`。
- 私有词表可补两处，取并集：环境变量 `PLUGIN_EVAL_PRIVATE_TERMS`（逗号分隔），以及数据目录下的 `private-terms.txt`（UTF-8，带不带 BOM 都行；每行一个或逗号分隔，`#` 起注释）。写公司名、项目代号、客户名；这份词表只在本机，不进任何仓库。两处都为空时输出「未配置私有词，只能靠会话推断与形态检测」。词表里的词按子串匹配、不区分大小写：写 `abc` 也拦 `AbcApiClient`、`ABC2024`。
- 每个草稿目录自带内容为 `*` 的 `.gitignore`，通过前 `git add -A` 也带不走它；通过写回时这个文件与 `draft.json` 一起删掉、不进 `evals/`。目录名固定为 `review-<候选 id>`，入库的 `run.json`、`report.md` 与复盘结果里只出现这个目录名；AI 写的用例意图只在 `draft.json` 与待审页正文里。
- 待审页上这类草稿带「隐私：由本机真实会话改写，通过前逐字审隐私」一行；没拿到注入文字、没做注入核对的另有一行说明。

## 七、目录布局

```
<repo>/plugins/<plugin>/evals/<case>/        # 已通过的用例，eval 原生格式，随插件分发
<repo>/plugins/<plugin>/evals/<case>/judge/<id>.md  # 用例声明的 AI 评委判定标准（可选）
<repo>/plugins/<plugin>/unit-tests.json      # 单测声明，随插件分发
<repo>/plugin-evals/<plugin>/                # 插件目录外，入库，不分发
  clauses.json  clauses-injection.txt        # 条款清单与对应的注入文本快照
  clause-rehang.json                         # 条款退役后用例改挂建议
  judge-config.json                          # AI 评委配置（可选）
  drafts/<case>/                             # 用例草稿：eval 原生用例目录 + draft.json
    history.jsonl                            # compact 回放用例的合成对话历史（case.yaml 的 context.history_file）
    .gitignore                               # 只在复盘候选转来的草稿里有，内容 *
  draft-skips.json  baseline.json            # 不宜起草的目标；各用例的基线判定
  runs/<时间>-<版本>-<compare|gate|clauses|drafts|baseline>/
    run.json                                 # 唯一真源
    report.md                                # 给人读
    ...                                      # 各臂结果、注入核验、评委判分、样本 trace
  reviews/<日期>.json                         # 会话复盘结果，日期为本机本地日期
  gold/<id>.json                             # 金标样本（你在待审页裁定过的分歧与抽检）
~/.claude/plugins/data/devkit-plugin-eval-<市场名>/
  registry.json                              # 登记清单
  private-terms.txt                          # 私有词表（可选，你自己建），见第六节
  pending/<plugin>/<run_id>.html             # 待审页，不入库
  traces/                                    # 全量 trace 本机缓存
```

- 草稿必须在 `evals/` 之外：eval 递归扫描 `evals/**`，放进去会被当正式用例跑。
- 把 `<plugin>/evals/results/` 加进被测仓的 `.gitignore`。
- 评内网插件时，用例与结果放内网仓。

### 写用例时要知道的 eval 限制

- 只有 SessionStart 的 hook 注入进 eval 的 trace；UserPromptSubmit、SubagentStart、PreToolUse 等注入进不了。不要写判这类注入文字的规则 grader，注入是否到达由对照的注入核验负责。
- headless 子会话里没有 `AskUserQuestion`，依赖它的条款离线评不了，归会话复盘。
- 只写 `max: 0` 的 `tool_used` grader 时同时写 `min: 0`。
- hook 里的 `node` 经 asdf 等版本管理器的 shim 解析时，在 eval 的临时 HOME 下会 exit 126 且不报错；前置检查的 hook 冒烟专防这一条。

## 八、单测声明格式

被测插件在**插件根**放 `unit-tests.json`，随插件分发：

```json
{
  "tests": [
    { "run": ["python3", "-m", "unittest", "discover", "-s", "tests"], "timeout_sec": 120 },
    { "run": ["node", "hooks/tests/some-guard.test.js"] },
    { "run": ["bash", "hooks/tests/some-check.sh"], "platforms": ["darwin", "linux"] }
  ]
}
```

| 字段 | 必填 | 含义 |
|---|---|---|
| `run` | 是 | argv 数组，不经 shell；工作目录固定为插件根 |
| `timeout_sec` | 否 | 超时判失败，缺省 120 |
| `platforms` | 否 | `darwin` / `linux` / `win32`，缺省全部 |

不设其它字段。只收不联网、结果确定的单测。

`gate` 跑声明里的单测：未声明只提示不拦；声明不合法、解释器解析不到、任一条非零或超时都判失败；平台不在 `platforms` 里的跳过并提示。本仓的 `.githooks/pre-commit` 另有一份读同一声明的实现，只在本仓生效。

## 九、发版闸门

```bash
python3 plugin_eval.py gate <插件目录>          # 退出码 0 过闸、1 未过闸
python3 plugin_eval.py gate <插件目录> --json   # 结构化结果
```

本仓不接 git hook，**推 main 前手动跑**。

**哪些版本要什么依据**：

- major 升版，以及升版提交信息里带 `eval-required: <理由>` 的版本（**闸门内**）：须有**已审**的离线对照报告。
- 其余版本（**闸门外**）：已审的离线对照，或通过的**规则判分子集**，二者之一。
- 有单测声明的，单测先要通过。
- 新插件的第一个版本不算闸门内；需要评测时用 `eval-required:` 声明。
- 升版提交信息里带 `eval-skip: <理由>` 的版本跳过评测，闸门每次都会列出这些版本，由你决定是否补评。`eval-skip:` 不豁免单测。
- 两种声明都写成提交信息末尾的 trailer，闸门读 git log；不另设状态文件，不往 `plugin.json` 加字段。

**依据怎么认**：同版本、插件内容指纹与当前一致（指纹算整个插件目录、排除 `evals/`）、不是 dirty、不是不完整的记录。审后再改插件里任何文件，指纹就变，原报告不再作数；只补用例不影响。

**规则判分子集**：闸门外版本缺依据时，`gate <插件目录> --run-subset` 只跑当前版一臂、只用规则 grader、不调 AI 评委、不进待审页，但真跑模型；跑完自动重判。默认每例 3 次、`--threshold 1.0`，即每例全部 run 都过才算过。`--threshold` 取值 (0, 1]，低于 1.0 时输出会标出。

**每次运行还会输出**：

- 「建议跑对照（会先更新条款清单）」：升版改动碰到 skill description、agent 定义，或注入文本指纹相对上次对照变了。
- 距上次会话复盘超过 7 天的提醒。
- 闸门内版本推到 main 时既无已审报告、也无 `eval-skip:` 的漏检。

## 十、平台

只在 macOS 上实测过。**Windows / Linux 未实测**：hook 冒烟、`claude` 的 `.cmd` 解析、单测声明里 `bash` 解析到 Git Bash 等，首次真跑时补测。命令行实现按跨平台写（解释器按 `python3` → `python` → `py -3` 实测解析，调 `claude` 前先解析出可执行文件路径，读写文件显式 UTF-8，尊重 `CLAUDE_CONFIG_DIR`）。
