# 16: 现有确定性单测是否并入同一入口

Type: grilling
Status: resolved
Blocked by: 无

## Question

本仓已有 `guard-verify.js` 等十来套 hook 确定性单测（清单见 [仓内历史评测实践盘点](02-prior-eval-practices.md)），它们覆盖拦截逻辑与副作用的正确性——[评测要回答哪些问题](07-questions-eval-must-answer.md) 把这两项划为「单测负责，评测不答」。[缺口里哪些自建、以什么形态](09-build-vs-extend.md) 定了 `devkit-plugin-eval` 的命令行与闸门检查命令。

要决定：

1. 闸门检查命令是否要求被测插件自带的确定性单测先通过；若要，怎么发现一个任意插件的单测入口（约定文件名、`plugin.json` 字段、还是不管）。
2. 本仓这十来套单测是否接 `.githooks/pre-commit`（现在只跑 `scripts/check-versions.js`），与评测体系各管各。

## Answer

2026-10-15 用户拍板「全部按推荐来」。Q2 与 Jev 不一致，用户采纳 AI 推荐。

1. **闸门检查命令跑被测插件自带的确定性单测，入口靠声明**：被测插件放一份**单测声明**，写一条或多条单测命令；闸门检查命令逐条执行，任一条退出码非零即拦。没有声明的插件只输出「未声明单测」提示、不拦——机制要能评任意插件，不能要求每个插件都带单测。声明文件的位置与格式随结果目录布局一起定（见地图 Not yet specified）。
2. **本仓单测接 `.githooks/pre-commit`**：按暂存文件路径找出被改的插件，只跑这些插件声明的单测；判据形态与现有 `scripts/check-versions.js` 一致，`--no-verify` 可绕过。跑单测的脚本用 JS、由 node 调起（`devkit-portable-shell` 约定），读同一份单测声明，不在本仓另维护清单；它是本仓脚本，不依赖已安装的 `devkit-plugin-eval`。实测代价：改 `devkit-task-keeper` 时每次提交多约 37 秒，其余插件 0～5 秒。

**与 [发版闸门覆盖哪些版本](12-release-gate-coverage.md) 第 3 条「本仓不接 git hook」的关系**：那条只管要真跑模型、花钱的评测闸门；确定性单测零花费、秒级，挂 pre-commit 不与之冲突。

**未选**：Q1 约定文件名自动扫描（本仓 `guard-verify.js`、`codegraph-hint-gating.sh` 会漏，`cases/*.sh` 会误跑）、`plugin.json` 加 `tests` 字段（`claude plugin validate` 每次报 unknown field warning）、闸门不管单测；Q2 只靠手动闸门（Jev 选此项，置信 0.87）、接 pre-push、维持现状。

**范围外**：给 9 个有 hook 无单测的插件补单测，不归本图。

**残余不确定**：

- pre-commit 里 37 秒的 task-keeper 单测会不会让用户习惯性 `--no-verify`，未知。
- 一次提交若改了多个插件共用的文件（如仓根脚本），按路径找不到被改插件，不跑单测。

**重开条件**：

- 发现 `--no-verify` 成为常态（如连续多次提交带它绕过单测）时，重议是否把慢单测移到 pre-push。
- `claude plugin validate` 或 Claude Code 官方给出测试入口字段时，重议 Q1 的声明位置。

## Comments

### 2026-10-15 第一轮提问（待答）

已认领。补查事实：

- 子代理实跑仓内全部单测：12 套、分布在 8 个插件，全部通过，总耗时约 55 秒，其中 `devkit-task-keeper` 的 `hooks/tests/run-tests.sh` 占 37 秒，其余每套 0～5 秒；解释器混用 node / python3 / bash；都只写系统临时目录。比 02 的清单多出 `devkit-tool` 的 `hooks/tests/codegraph-hint-gating.sh` 与 `hooks/tests/worktree-cwd-recovery.js`。
- 命名与位置不统一（`tests/*.test.js`、`test/guard-verify.js`、`hooks/tests/run-tests.sh` 会 source 24 个不能单跑的 `cases/*.sh`）；仓内无统一入口，`plugin.json` 无测试字段。
- 在 `plugin.json` 加未知字段 `tests`，`claude plugin validate` 报「Unknown field 'tests'. Claude Code ignores it at load time.」，结论为 passed with warnings。
- 另有 9 个插件有 hook 但没有单测（补单测不归本图）。

第一轮问两件：

1. 闸门检查命令是否跑被测插件自带单测、怎么发现入口（推荐：声明式，未声明只提示不拦；Jev 同选，置信 0.60）。
2. 本仓单测是否接 `.githooks/pre-commit`（推荐：接，按暂存路径只跑被改插件；Jev 选「只靠闸门检查命令」，置信 0.87）。

### 2026-10-15 第一轮答复

用户原话「全部按推荐来」：

- Q1：**声明式**，未声明只提示不拦。Jev 同选（置信 0.60）。
- Q2：**接 pre-commit，只跑被改插件的单测**。Jev 选「只靠闸门检查命令」（置信 0.87），未采纳，理由是闸门手动、pre-commit 注释记录过手动提醒执行率为零，且 12 第 3 条只管评测闸门。

术语「单测声明」写入 `CONTEXT.md`，「发版闸门」定义补一句单测要求。

### 2026-10-15 来自 18 的补充

第 1 条「声明文件的位置与格式随结果目录布局一起定」已由 [单测声明放哪、长什么样](18-unit-test-declaration.md) 定下：被测插件根下的 `unit-tests.json`，随插件分发；每条 `run`（argv 数组）、`timeout_sec`、`platforms` 三个字段；pre-commit 对未声明的插件静默，闸门检查命令仍提示「未声明单测」。
