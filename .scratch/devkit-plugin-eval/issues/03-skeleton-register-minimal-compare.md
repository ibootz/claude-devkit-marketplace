# 03 — 插件骨架、登记与最小离线对照（主链路打通）

Status: resolved

**What to build:**

新建本仓插件 `devkit-plugin-eval`，交付一个 Python 命令行，打通离线对照的最短完整链路：

- **登记**：用户登记一个被测插件（插件名 + 所在仓路径），写入用户级 `registry.json`。登记即信任声明：之后跑 eval 自动加 `--trust-plugin`；未登记的插件拒绝跑。
- **最小对照**：对已登记插件现有的 `evals/` 用例，按 01 定下的跑法组装「不装」与「当前版」两个臂（各一个临时组装目录，用例一律拷当前版），每臂跑 eval（`--keep-temp`、每例 3 次），只用规则判分，脚本自算两臂之差。
- **落盘**：在被测插件所在仓的 `plugin-evals/<plugin>/runs/<时间>-<版本>-compare/` 下写 `run.json`（唯一真源）、各臂 `aggregate-result.json`、`report.md`；状态为「待审」；eval 写进 `<plugin>/evals/results/` 的产物搬走，该目录进 `.gitignore`；全量 trace 移到用户级 `traces/`；跑完清理臂组装目录与回放转录。

本票只做两臂、只做规则判分；前置检查、上一版臂、注入核验、AI 评委、待审页都在后续票。

**Blocked by:** 01


- [x] 插件以 `devkit-` 前缀命名，两份市场清单都已登记，`node scripts/check-versions.js` 通过，`claude plugin validate` 通过
- [x] 对一个带现成用例的插件（如 plugin-eval probe 里的 devkit-discipline 三例）跑一次对照，得到含两臂分数与差的 `report.md`
- [x] `run.json` 含 spec「四、目录布局与状态文件」列出的字段中本票已能填的部分（插件名、版本、插件内容指纹、各臂、Claude Code 版本、主力模型、token 与标价估算、`kind=compare`、是否完整、是否通过、审阅状态=待审）；其余字段留键位
- [x] 未登记插件跑对照被拒，并提示先登记
- [x] 调 `claude` 前先解析出可执行文件路径；stdout 设为 UTF-8
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.1 交付形态」「2.2 离线对照（compare）」第 3、4、8 步、「四、目录布局与状态文件」；[09](../../plugin-eval/issues/09-build-vs-extend.md)、[13](../../plugin-eval/issues/13-result-layout.md)

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-agent-a71eddf379b87f23c` 上提交，未合并 main、未推送，等主会话审后合并。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`、`plugin-dev:create-plugin`、`plugin-dev:plugin-structure`。

**实现摘要**

- 入口 `python3 plugins/devkit-plugin-eval/scripts/plugin_eval.py {register,list,compare}`，代码在 `scripts/plugin_eval_lib/`，纯标准库。
- 数据目录：`--data-dir` > 环境变量 `CLAUDE_PLUGIN_DATA` > 从插件缓存路径推 `<cfg>/plugins/data/<plugin>-<marketplace>`；从源码仓直接跑时推不出，必须给 `--data-dir`。
- 臂组装：每臂一个临时目录，目录本身就是传给 `claude plugin eval` 的插件目录——「当前版」拷插件内容（排除 `evals/`），「不装」写一个只有 `plugin.json` 的空桩；两臂都拷当前版的 `evals/`（排除 `results/`）。`--output-dir` 指向组装根下的 `_out/<臂>`，所以 eval 不写被测插件的 `evals/results/`；仍按票把它写进被测仓 `.gitignore`。
- eval 参数：`--ablation none --keep-temp --no-publish --trust-plugin --scaffold --runs 3 -j 3`。
- 判分：只认 `regex` / `tool_order` / `tool_used` / `file_exists`；用例级 `config.arm == "with-only"` 的 grader 剔除（`--ablation none` 下 eval 会把它计分），`llm` / `baseline` 也剔除；`run.error` 非空的 run 判无效、记入不完整原因。
- 指纹：插件目录内每个文件 `相对路径\0sha256` 排序后整体 sha256；顶层排除清单是常量 `FINGERPRINT_EXCLUDE = ('evals',)`；任意层的 `__pycache__` / `.DS_Store` / `*.pyc` 当噪声跳过。
- token 与花费：取每个 trace 最后一条 `result` 行的 `modelUsage`（多条 `result` 是累计快照，不能相加——第一次真跑踩到，花费虚报近一倍，已补单测修复）。
- trace：从 `--keep-temp` 沙箱搬到 `<数据目录>/traces/<run_id>/<臂>/<用例>-<n>/`，再删沙箱；只认 `<临时根>/e-*/out/trace.jsonl` 形态，防误删。
- 单测 70 个，登记在 `unit-tests.json`。

**真实对照（演示，devkit-discipline 4.1.0 + probe 三例）**：不装 0.69、当前版 1.00、差 +0.31；标价估算 $2.58。产物在 [demo-03](../demo-03/plugin-evals/devkit-discipline/runs/20261015T084918Z-4.1.0-compare/report.md)（只入库 run.json、report.md、两臂 aggregate-result.json；trace、report.html、转录含账号邮箱，不入库）。

**待用户拍板**

1. 指纹额外跳过 `__pycache__` / `.DS_Store` / `*.pyc`（spec 未写）；`unit-tests.json` 是否加入 `FINGERPRINT_EXCLUDE`。
2. compare 一律加 `--scaffold`（spec 第 4 步命令里没写；parallel-lookup 用例需要）。
3. `passed` 口径暂定为「运行完整，且当前版臂每个有分用例的规则分 ≥ threshold（默认 1.0）」。

**已知缺口**：`traces/` 的 90 天清理未做；中途异常会留下没有 run.json 的运行目录（交给断点续跑的票）；Windows / Linux 未实测；无 skill、无 README、无 `.codex-plugin`。
