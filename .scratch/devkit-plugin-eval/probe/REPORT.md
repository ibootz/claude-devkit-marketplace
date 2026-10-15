# 票 01 实测报告：「不装」臂的跑法与三项 eval 未知行为

实测时间：2026-10-15 16:00–16:03（Asia/Shanghai）。
Claude Code 版本：2.1.300（各 `out/*.json` 的 `claudeVersion`）。
被测模型：eval 默认的 claude-opus-5-5；真实会话旁证用 `--model sonnet`。
评委：只用免费 grader。
执行者：主会话（impl-01 worktree），未派子代理跑 eval；文档原文由一个 claude-code-guide 子代理抓取。

## 结论速览

| 问题 | 结论 | 一句话证据 |
|---|---|---|
| 1. 空桩插件跑 `--ablation none` | **可行**，等同「不装」 | eval 接受只有 `plugin.json` 的插件；空桩臂与 eval 自带 without 臂的工具、skill、slash 命令、agent、MCP 五项清单逐项相同，首请求输入 token 同为 10313–10319，计分 grader 结果相同（1/3） |
| 2. 改用 `--ablation with-without` 取 `W/OUT` | 也可行，作备选 | 同一用例的 `W/OUT` 为 0.33×3，与空桩臂相同；回放用例必须显式带该参数（沿用票 19 结论） |
| 3. 用例目录放 eval 不认识的附加文件 | **用例目录、evals 根目录可放；`graders/` 里不能放带 frontmatter 的非 grader 文件** | 4 种附加文件都被静默忽略；`graders/` 下无 frontmatter 的 md 也被忽略；`graders/` 下带 frontmatter 却无 `type:` 的 md 让整个用例加载失败 |
| 4. skill 调起的 Python 拿不拿得到 `CLAUDE_PLUGIN_DATA` | **环境变量拿不到；SKILL.md 正文里写 `${CLAUDE_PLUGIN_DATA}` 会被替换成路径** | eval 沙箱与真实会话两处实测，`env.CLAUDE_PLUGIN_DATA=<unset>`，单引号参数 `'${CLAUDE_PLUGIN_DATA}'` 收到的是绝对路径 |
| 5. `cleanupPeriodDays` 默认值 | **30 天**，最小 1，设 0 校验失败 | 官方文档 settings-reference 与 2.1.300 可执行文件里的 settings schema 两处一致 |

**对 03 设计最要紧的一条新发现**：`--ablation none` 下，标了 `arm: with-only` 的 grader **计入分数**，不再是不计分的指示器。空桩臂因此得 0.2（5 个 grader 过 1 个），而不是 0.33（3 个计分 grader 过 1 个）。按臂跑 `--ablation none` 时，外围脚本要么不写 `with-only` grader，要么算分时自己剔除它们。见第六节第 1 条。

## 一、命令

所有 eval 都经 [tools/run.sh](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/devkit-plugin-eval/probe/tools/run.sh:1) 调用，跑法同 plugin-eval 的两轮实测：

- 从 PATH 去掉 `~/.asdf/shims`，实际解析到的 node 写进 `out/<标签>.node`，7 次都是 `/opt/homebrew/bin/node`。本机 `which -a node` 第一个命中的是 `~/.asdf/shims/node`，不去掉就会出现 hook exit 126 而 eval 不报错。
- 用 `env -u` 去掉父会话的一组 `CLAUDE_CODE_*` 环境变量。
- 被测插件目录都先拷到仓外临时目录再跑，避免 eval 往仓内写 `evals/results/`。

公共参数：`--trust-plugin --no-publish --json out/<标签>.json --keep-temp`。

| 标签 | 目标插件 | 额外参数 | 退出码 | 花费 | durationSeconds |
|---|---|---|---|---|---|
| extras | `cases/extras`（x-casedir、x-graders-junk 两例） | `--ablation none --runs 1 -j 2` | 0 | $0.0831 | 4 |
| envprobe | `cases/envprobe` | `--ablation none --runs 1 --allow-tools Bash` | 0 | $0.1453 | 13 |
| stub-none | `cases/stub` | `--ablation none --runs 3 -j 3` | 1 | $0.4813 | 21 |
| stub-ww | `cases/stub` | `--ablation with-without --runs 3 -j 3` | 1 | $0.8549 | 39 |
| real-ww | devkit-discipline 4.1.0 副本 + `cases/stub/evals` | `--ablation with-without --runs 3 -j 3` | 0 | $1.1876 | 59 |
| x-graders-fm | `cases/extras` 里的 x-graders-fm 单例 | `--ablation none --runs 1` | 1 | $0 | 0 |
| x-prompt-fm-key | `cases/extras` 里的 x-prompt-fm-key 单例 | `--ablation none --runs 1` | 1 | $0 | 0 |

- 退出码 1 的含义：stub-none 与 stub-ww 是有用例低于默认阈值 1.0，不是运行失败；两个 `x-*` 是用例加载失败，一个 run 都没跑。
- 另有一次真实会话旁证（非 eval）：[tools/realsession.sh](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/devkit-plugin-eval/probe/tools/realsession.sh:1)，`claude -p --plugin-dir cases/envprobe --model sonnet`，加载本机全部用户配置与插件，退出码 0，输出在 `out/realsession.out`。
- 花费合计 $2.7523（7 次 eval，标价估算；订阅用户，未设上限）。真实会话旁证的花费没有记录。
- 全部 run 的 `error` 为 null，无 partial，未撞订阅用量限制。

## 二、问题 1：空桩插件能否当「不装」臂

### 用例

`cases/stub/` 只有 `.claude-plugin/plugin.json`（name 为 `eval-noplugin-stub`）与 `evals/dispatch-model/`。用例照搬 plugin-eval 票 05 / 19 的 dispatch-model：

- prompt：请分别派一个子代理，各用三句话讲 TCP 三次握手和 HTTP 幂等。
- 计分 grader：`agent-dispatched`、`agent-has-model`、`agent-missing-model-zero`。
- 标记 grader：`marker-sessionstart`、`marker-userpromptsubmit`，都是 `arm: with-only`。

选它的理由：devkit-discipline 装与不装的差在这个用例上是 +0.67、臂内零波动（票 05、19 两轮一致），「不装」的固定形态是「派 2 次、都不带 model」，分数上一眼能分辨空桩臂像哪一边。

### 结果

| 标签 / 臂 | 逐次分数 | 计分 grader 逐次 | 首请求输入 token |
|---|---|---|---|
| stub-none / with（空桩） | 0.2 / 0.2 / 0.2 | 派 2 次、0 次带 model：1/3 | 10316 / 10316 / 10316 |
| stub-ww / with（空桩） | 0.33 / 0.33 / 0.33 | 同上 | 10316 / 10313 / 10316 |
| stub-ww / without | 0.33 / 0.33 / 0.33 | 同上 | 10313 / 10319 / 10316 |
| real-ww / with（devkit-discipline） | 1 / 1 / 1 | 派 2 次、都带 model | 16887 / 16893 / 16893 |
| real-ww / without | 0.33 / 0.33 / 0.33 | 派 2 次、0 次带 model：1/3 | 10319 / 10316 / 10412 |

- stub-none 的 0.2 与另两行的 0.33 只差在 `with-only` 标记是否计分，计分 grader 的通过情况完全相同，见第六节第 1 条。
- stub-ww 的 Δ = 0（`meanDelta: 0`）：同一个 eval 里，装空桩与不装分不出差别。
- 逐次 grader 原文：`node tools/summarize.js out/<标签>.json`。

### 结构比对

[tools/compare-init.js](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/devkit-plugin-eval/probe/tools/compare-init.js:1) 从每个 run 的 trace 里取 `system/init` 行，比对模型可见的五项清单（tools、skills、slash_commands、agents、mcp_servers），结果在 `out/compare-init.jsonl`：

- 空桩臂 6 个 run 与两组 without 臂 6 个 run，五项清单逐项相同（工具都是 `Glob,Grep,Read,Skill,Task,TaskStop,ToolSearch`，skill 17 个，slash 命令 45 个）。
- 唯一差别是 `init.plugins` 多出一项 `eval-noplugin-stub`；它不进模型上下文，首请求输入 token 与 without 臂落在同一区间可以佐证。
- 空桩臂 trace 里 hook 事件行 0 条，子会话转录里 `hook_additional_context` 0 条；real-ww 的 with 臂分别是 2 条与 4–6 条，without 臂都是 0。
- real-ww 的 with 臂多出 skill `devkit-discipline:zh-disambiguate`，首请求多约 6.6k token，这是被测插件真实带来的差。

### 结论

空桩插件可行：eval 接受无组件插件，跑出来的「with 臂」在模型可见面、注入、分数上都等同「不装」。03 照 spec 原设计走，每臂各跑一次 `--ablation none`，「不装」臂用空桩目录承载用例。

因为空桩可行，「改用当前版臂的 `--ablation with-without` 取 `W/OUT` 列」这条备选不必采用。它本身也可用：real-ww 的 `W/OUT` 与空桩臂计分 grader 结果相同；若以后改用它，回放用例必须显式带 `--ablation with-without`，否则 auto 模式只跑 with 臂（票 19 结论，本轮未重测）。

## 三、问题 3：用例目录里放 eval 不认识的附加文件

| 位置 | 附加文件 | 结果 |
|---|---|---|
| 用例目录（与 `prompt.md` 同级） | `clauses.md`（带 frontmatter，键为 `clause`、`note`）、`meta.json`、`notes.txt` | 静默忽略，用例照常跑、照常计分 |
| 用例目录下的子目录 | `sub/README.md` | 静默忽略，没被当成用例 |
| `evals/` 根目录 | `README.md`、`clauses.json` | 静默忽略，`casesTotal` 仍是 2 |
| `graders/` 下，无 frontmatter | `README.md` | 静默忽略，grader 列表只有 `reply-ok` |
| `graders/` 下，有 frontmatter、无 `type:` | `clause-note.md` | **整个用例加载失败**，stderr：`graders/clause-note.md: frontmatter must include "type:" (regex \| tool_order \| tool_used \| file_exists \| llm \| baseline)`，`1 case file(s) failed to load`，退出码 1 |
| `prompt.md` frontmatter 加未知键 | `clause: C-001` | **整个用例加载失败**，stderr：`prompt.md: unknown frontmatter key "clause" (expected one of: schema_version, name, description, tags, plugins, runs, expected_outcome, model, max_turns, timeout_seconds, allowed_tools, disallowed_tools, artifact_publish, growthbook_overrides, append_system_prompt, env)`，退出码 1 |

结论：条款归属说明可以作为独立文件放在用例目录或 `evals/` 根目录，eval 不报错；不能写进 `prompt.md` 的 frontmatter，也不能以带 frontmatter 的 md 形式放进 `graders/`。spec 现有做法「条款归属先只用 `tags`」仍然成立；`tags` 接受自定义字符串值，extras 各用例的 `tags: [extras-probe]` 照常加载。

证据：`out/extras.json`、`out/x-graders-fm.stderr`、`out/x-prompt-fm-key.stderr`；用例在 `cases/extras/evals/`。

## 四、问题 4：skill 调起的 Python 进程与 `CLAUDE_PLUGIN_DATA`

### 用例

`cases/envprobe/` 带一个 skill `env-probe`，正文要求用 Bash 原样执行：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/probe.py" --dq-data "${CLAUDE_PLUGIN_DATA}" --sq-data '${CLAUDE_PLUGIN_DATA}' --dq-root "${CLAUDE_PLUGIN_ROOT}" --sq-root '${CLAUDE_PLUGIN_ROOT}'
```

[probe.py](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/devkit-plugin-eval/probe/cases/envprobe/skills/env-probe/scripts/probe.py:1) 打印四个环境变量与四个参数。单引号参数 shell 不展开，收到路径就只能是 Claude Code 在加载 skill 文本时做了替换。

### 结果

| 项 | eval 沙箱（`out/envprobe.json`，trace 里的 tool_result） | 真实会话（`out/realsession.out`） |
|---|---|---|
| `env.CLAUDE_PLUGIN_DATA` | `<unset>` | `<unset>` |
| `env.CLAUDE_PLUGIN_ROOT` / `CLAUDE_SKILL_DIR` / `CLAUDE_PROJECT_DIR` | 都是 `<unset>` | 都是 `<unset>` |
| `'${CLAUDE_PLUGIN_DATA}'`（单引号） | `/private/tmp/e-sCiF3S/config/plugins/data/eval-envprobe-inline` | `/Users/zhangq/.claude/plugins/data/eval-envprobe-inline` |
| `'${CLAUDE_PLUGIN_ROOT}'`（单引号） | 插件目录绝对路径 | 插件目录绝对路径 |
| 数据目录是否已存在 | True | True |

- 两处结论一致：Bash 工具的子进程环境里没有这些变量；SKILL.md 正文里的 `${CLAUDE_PLUGIN_DATA}` 在加载时被替换成绝对路径，目录在首次引用时自动创建。
- 与官方文档一致：「The variables aren't present in the environment of commands Claude runs through the Bash tool ... In skill, command, and agent content, write the `${...}` reference in the Markdown body instead」（原文与出处见 [excerpts/docs-quotes.md](excerpts/docs-quotes.md#claude_plugin_data-与-bash-工具)）。
- `--plugin-dir` 加载的插件，数据目录名是 `<name>-inline`。

### 给 03 / 13 的做法

1. **首选**：SKILL.md 里把路径作为参数传给 Python，例如 `python3 "${CLAUDE_SKILL_DIR}/scripts/x.py" --data-dir "${CLAUDE_PLUGIN_DATA}"`。不要在 Python 里读 `os.environ["CLAUDE_PLUGIN_DATA"]`。
2. **兜底**（脚本被人手动执行、拿不到参数时）：按脚本自身路径推出数据目录。
   - marketplace 安装的插件，脚本路径形如 `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/...`，`cache/` 后第一段是 marketplace 名，第二段是插件名。
   - 数据目录是 `~/.claude/plugins/data/<plugin>-<marketplace>/`，id 里字母、数字、`_`、`-` 以外的字符都换成 `-`（文档原文见 [excerpts/docs-quotes.md](excerpts/docs-quotes.md#claude_plugin_data-与-bash-工具)）。
   - 本机核对：`~/.claude/plugins/cache/claude-devkit-marketplace/devkit-discipline/4.1.0/` 对应 `~/.claude/plugins/data/devkit-discipline-claude-devkit-marketplace/`，两者都存在。
   - 脚本路径不在 `plugins/cache/` 下（如 `--plugin-dir` 加载）时推不出来，应要求显式传参。
   - 设了 `CLAUDE_CODE_PLUGIN_CACHE_DIR` 时 plugins 根目录会变，数据目录是否随之变，文档未写，本轮未测。

## 五、问题 5：`cleanupPeriodDays` 默认值

- **默认 30 天**，整数，最小 1；设 0 校验失败（以前设 0 会静默关闭全部转录写入，现已拒绝）。
- 出处一，官方文档 settings-reference：「**Default**: `30`」「Setting `0` fails validation」；claude-directory 页：「The default is 30 days and the minimum is 1」。原文见 [excerpts/docs-quotes.md](excerpts/docs-quotes.md#cleanupperioddays)。
- 出处二，2.1.300 可执行文件里的 settings schema：`cleanupPeriodDays:()=>E().int().positive().optional().describe("Number of days to retain chat transcripts before automatic cleanup (default: 30). ...")`，摘录在 [excerpts/cleanup-period-days-binary.txt](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/devkit-plugin-eval/probe/excerpts/cleanup-period-days-binary.txt:3)。
- 清理范围不止会话转录：`projects/<project>/<session>.jsonl`、其下 `subagents/` 与 `tool-results/`，以及 `file-history/`、`plans/`、`debug/` 等，都按同一期限删除。
- 给 15（前置检查）的两条边界，来自同一份字符串摘录：
  - settings 有错误时清理暂停：「Transcript retention cleanup is paused until the settings errors above are fixed」。
  - 用 `--setting-sources` 关掉 userSettings 且别处没设时跳过清理：「Skipping retention cleanup: userSettings source is disabled ...」。
- 本机 `~/.claude/settings.json` 第 2 行设了 `"cleanupPeriodDays": 90`，所以本机保留 90 天；别人的机器未设时按 30 天算。

## 六、坑与意外发现

1. **`--ablation none` 下 `arm: with-only` grader 计分**。stub-none 的 trace 显示两个标记 grader 都算进分数（summarize 输出里没有 `(unscored)`），stub-ww 里同样的 grader 标为 `(unscored)`。影响：按臂各跑 `--ablation none` 时，每个臂的分数都会被这些标记拉低或拉高；被测插件臂里标记命中会抬分，「不装」臂里必然不中会压分，臂间相减时这部分差不是被测行为带来的。03 的外围脚本应在算分时只取计分 grader，或者用例里不写 `with-only` 标记、注入核验改走 `--keep-temp` 转录。
2. **eval 沙箱里每个臂都自带 3 个内置插件**：`init.plugins` 里两臂都有 `cc-plugin-agents-md`、`cc-plugin-plugin-authoring`、`cc-plugin-sec-default`。它们在所有臂里都一样，不影响臂间相减；但「不装」臂并非零插件，与真实用户环境也不同。
3. **slash 命令清单有与插件无关的抖动**：`extra-usage`、`usage-credits` 两个命令在 real-ww 的 4 个 run 里出现、其余 run 没有，与臂无关。比对模型可见面时这两项要排除。按推断与账号用量状态有关，未核实。
4. **用例加载失败时退出码同为 1**，与「有用例低于阈值」不可区分。外围脚本要看 `--json` 里的 `aggregates.casesTotal` 与 stderr 的 `failed to load`，不能只看退出码。

## 七、只是推断或未核实的结论

1. 「空桩等同不装」只在一个用例、一种行为信号上验证了分数；模型可见面的五项清单与首请求 token 比对覆盖了全部 run，但没有逐字比对 system prompt。
2. 空桩插件的 name 是否会影响什么：本轮用的是与被测插件不同的名字，与被测插件同名的空桩未测。
3. `CLAUDE_CODE_PLUGIN_CACHE_DIR` 对数据目录的影响：未测。
4. 真实会话旁证只测了 `--plugin-dir` 加载（数据目录为 `-inline`），没有安装一个 marketplace 插件来测替换值；marketplace 插件的数据目录名靠文档规则与本机已有目录核对。

## 八、产物

本目录 `.scratch/devkit-plugin-eval/probe/` 下：

- `cases/`：`stub/`（空桩插件 + dispatch-model 用例）、`extras/`（附加文件探针，4 个用例）、`envprobe/`（`CLAUDE_PLUGIN_DATA` 探针 skill 与用例）。
- `out/`：7 次 eval 的 `--json` 输出、stdout、stderr、exit、start、end、node、cmd；`compare-init.jsonl`（逐 run 结构比对）；`tabulate.txt`（花费与耗时汇总）；`realsession.out` / `realsession.exit`（真实会话旁证）。
- `excerpts/`：`docs-quotes.md`（官方文档原文）、`cleanup-period-days-binary.txt`（可执行文件字符串摘录）。
- `tools/`：`run.sh`、`realsession.sh`、`summarize.js`、`compare-init.js`、`tabulate.js`。
- `traces/`：19 个 run 的 trace.jsonl、子会话转录与 `source.txt`（原沙箱路径）。**未入库**：子会话转录含 eval 注入的账号邮箱，本仓公开，已加进仓根 `.gitignore`。

仓外未清理：`/Users/zhangq/.claude/jobs/7058cce7/tmp/p01/`（插件副本与 `evals/results/` 下的 report.html）、`/private/tmp/e-*`（本轮 keep-temp 保留的 19 个沙箱，逐个路径见 `traces/*/*/source.txt`）、`/Users/zhangq/.claude/plugins/data/eval-envprobe-inline/`（真实会话旁证自动建的空目录）。
