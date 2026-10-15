# 15: 跑评测前检查哪些前置条件

Type: grilling
Status: resolved
Blocked by: 无

## Question

[实测 claude plugin eval 能否评出 hook 注入的效果](05-probe-plugin-eval-on-hook-injection.md) 撞过一次：eval 子进程的 PATH 走 asdf shim，在临时 HOME 下 exit 126，hook 全部静默不跑，结果仍是绿的。[缺口里哪些自建、以什么形态](09-build-vs-extend.md) 定了 `devkit-plugin-eval` 用一个 Python 命令行跑全部动作，这类前置要固化成命令自带的检查，不靠人记。

要决定：

1. 跑离线对照前检查哪些项：PATH 直达真实 node、`claude` 版本与 `plugin eval` 子命令可用、登录态、被测插件目录结构合法、本月账本余额。
2. 跑会话复盘前检查哪些项：会话记录目录可读、本机会话保留期（`cleanupPeriodDays`）是否短于复盘间隔。
3. 检查失败时：直接中止，还是降级继续并在报告里标注。
4. 三个平台（macOS / Windows / Linux）各自的差异项。

## Answer

> **2026-10-15 部分覆盖**：用户 2026-10-15 撤销美元花费上限（原话「由于我使用的是订阅 测评额度不适用 可以去掉 避免因为额度干扰了测评的质量」），随后拍板四项连带决定（原话「Q17 用最贵那一档 比如Fable模型 其他按照建议」），记录见 [08](08-cadence-and-budget.md) Comments。作废：硬项「本月余额 > 0」，以及会话复盘调 AI 评委时的「余额」检查；`--max-cost-usd` 不再是必需参数。现行：其余硬项、软项不变；撞订阅用量限制的处理见 [09](09-build-vs-extend.md) 的覆盖说明。

2026-10-15 用户原话「全部按推荐来」，八问照推荐定（Jev 八题同选）。

**总则：失败分两级。** 硬项失败即中止，不提供绕过开关；软项失败照跑，在报告与待审页标注。检查在对照、复盘、闸门检查三个动作开跑前自动执行，另提供独立 `check` 子命令单跑。

**离线对照前**：

| 检查项 | 级别 | 做法 |
|---|---|---|
| hook 解释器可达 | 硬 | 冒烟：临时空 HOME 加同一 PATH，把被测插件（及环境插件）`hooks.json` 每条 command 真执行一次，exit 126 / 127 判不可达；不调模型、零费用 |
| `claude` 可执行且 eval 参数齐 | 硬 | 解析 `claude` 可执行路径后读 `claude plugin eval --help`，按所需参数（`--ablation` `--keep-temp` `--max-cost-usd` `--no-publish` `--output-dir` `--trust-plugin`）做特性探测，不比版本号 |
| 已登录 | 硬 | `claude auth status --json` 的 `loggedIn` |
| 插件结构合法 | 硬 | `claude plugin validate <被测插件目录>` 通过 |
| 环境插件在 containment root 内 | 硬 | 有环境插件臂时才查 |
| 本月余额 > 0 | 硬 | 读用户级账本；`--max-cost-usd` 仍取 min(10, 余额) |
| 被测插件已登记 | 硬 | 已登记才自动加 `--trust-plugin`，登记即信任声明；未登记中止并提示先登记 |
| 工作区有未提交改动 | 软 | 照跑，报告记 commit 加 dirty 标记，**这份结果不计入发版闸门** |
| Claude Code 版本或主力模型与上次对照不同 | 软 | 照跑，报告标注与上次结果不可直接比 |

跑后的 trace `exit_code` 检查与「注入已到达」核验（09 已定）照旧保留，作第二道防线。

**会话复盘前**：

| 检查项 | 级别 | 做法 |
|---|---|---|
| 会话目录可定位、可读、非空 | 硬 | 尊重 `CLAUDE_CONFIG_DIR`，缺省 `~/.claude/projects` |
| 登记清单非空、各仓路径存在且可写 | 硬 | 结果写回各仓前就查，免得复盘做完才报错 |
| 距上次复盘天数 > `cleanupPeriodDays` | 软 | 报告标出已被清理、未覆盖的时间窗 |
| 登录态与余额 | 硬 | 仅当本次要调 AI 评委时才查 |

**三平台**：检查逻辑平台无关，版本管理器（asdf、mise、volta、nvm 等）的差异由冒烟法吸收，不维护 shim 名单。只在三处分平台：配置目录定位；Python 解释器按 `python3` → `python` → `py -3` 实际执行 `--version` 解析；调 `claude` 前解析出可执行文件路径（Windows 上是 `.cmd`）。Windows / Linux 标「未实测」，首次真跑时补测。

**未选**：扫 PATH 匹配 shim 名单；只靠跑后核验；一律中止；一律降级；硬项可绕过；总是自动 `--trust-plugin`；从不自动信任；dirty 时中止或计入闸门；只自动检查不给子命令；只给子命令靠 skill 提醒；按版本号判 eval 能力；按平台分支维护名单。

**残余不确定**：

- `cleanupPeriodDays` 未设时的默认值未核实；实现时查官方文档或实测，取不到就按「未设置」在报告标注。
- 冒烟用的 stdin 样例与 eval 实际传给 hook 的输入不同，hook 若对输入敏感可能误报；只以 126 / 127 判不可达，其它非零码记为提示、不中止。
- Windows / Linux 上冒烟与 `.cmd` 解析未实测。
- 用户级账本、登记清单、上次对照记录的具体位置由 [13](13-result-layout.md) 定，本票只规定要读它们。

**重开条件**：

- 冒烟通过、跑后核验仍发现 hook 静默失败（说明冒烟环境与 eval 子会话不一致）时，重议冒烟做法。
- 某个硬项频繁误拦正常运行时，重议它的级别。

## Comments

### 2026-10-15 第一轮提问（待答）

已认领。补查事实（本机 Claude Code 2.1.300）：

- `claude auth status --json` 输出 `loggedIn` 字段，可机械判登录态。
- `claude plugin validate <path>` 校验插件清单与 skills / agents / commands，可直接复用为「插件结构合法」检查。
- `claude plugin eval --help` 列出 `--ablation`、`--keep-temp`、`--max-cost-usd`、`--no-publish`、`--output-dir`、`--trust-plugin` 等参数；首次在未信任目录运行会交互确认，`--trust-plugin` 免确认。
- 本机 `~/.claude/settings.json` 的 `cleanupPeriodDays` 为 90；未设时的默认值未核实。
- 本机 PATH 里 `~/.asdf/shims` 排在 `/opt/homebrew/bin` 之前，`which -a node` 先命中 shim——05 的坑在本机仍然会复现。

第一轮问八件，互不依赖（Jev 八题都与推荐一致）：

1. 离线对照检查项（推荐八项：hook 冒烟、eval 参数特性探测、登录态、`plugin validate`、环境插件在 containment root 内、余额 > 0 为硬；工作区未提交改动、Claude Code 版本 / 模型变化为软）。
2. 解释器可达怎么查（推荐：临时空 HOME 下真执行每条 hook command，126 / 127 判不可达）。
3. 会话复盘检查项（推荐：会话目录可定位且非空、登记清单各仓可写为硬；距上次复盘天数超过 `cleanupPeriodDays` 为软；调 AI 评委时才查登录与余额）。
4. 失败处置（推荐：硬项中止且无绕过开关，软项继续并在报告与待审页标注）。
5. 三平台差异（推荐：检查逻辑平台无关，只在配置目录定位、Python 解析、`claude` 可执行路径三处分平台；Windows / Linux 标未实测）。
6. 未信任目录（推荐：只对登记过的被测插件自动加 `--trust-plugin`，未登记的中止）。
7. 工作区未提交改动（推荐：照跑、报告标 dirty、不计入发版闸门）。
8. 入口形态（推荐：各动作开跑前自动检查，另提供独立 `check` 子命令）。

### 2026-10-15 第一轮答复

用户原话「全部按推荐来」，八问照推荐定，见 `## Answer`。本票据此关闭；dirty 结果不计入闸门一条已同轮写进 [12](12-release-gate-coverage.md) 的 Comments。

