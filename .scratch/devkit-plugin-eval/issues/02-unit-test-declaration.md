# 02 — 单测声明与本仓 pre-commit 单测

Status: resolved

**What to build:**

插件作者在插件根放一份 `unit-tests.json`（单测声明），写明自己的确定性单测怎么跑。本票做两件事：

1. 本仓 `.githooks/pre-commit` 调起一个本仓 JS 脚本（node 调起，不依赖 `devkit-plugin-eval` 已安装）：按暂存路径命中 `plugins/<name>/**` 选出被改插件，读工作区里的声明、在工作区跑，任一条失败或超时即拦。
2. 给本仓已有确定性单测的插件写上声明；另备一组共用的声明样例（合法、不合法、平台跳过、解释器缺失、超时），供本票的 JS 实现与 14 的 Python 实现各跑一遍对齐。

声明格式：顶层只有 `tests` 数组；每条只有 `run`（argv 数组，不经 shell，cwd 固定插件根）、`timeout_sec`（缺省 120）、`platforms`（`darwin` / `linux` / `win32`，缺省全部）。

**Blocked by:** None — can start immediately


- [x] 改某插件的文件并提交时，该插件声明里的单测被执行；单测失败或超时，提交被拦下，输出指明是哪条
- [x] 未声明单测的插件静默放行；声明不是合法 JSON 或含约定外字段时拦下并指明原因
- [x] 当前平台不在 `platforms` 里的条目跳过并提示；解释器解析不到时跳过并警告；`python3` 按 `python3` → `python` → `py -3` 实际执行 `--version` 解析
- [x] 只改 `plugin-evals/<name>/` 下的文件不触发该插件单测；插件目录已删则跳过
- [x] 本仓现有确定性单测都已登记进各自插件的 `unit-tests.json`，`claude plugin validate` 对这些插件无新增 warning
- [x] 共用声明样例集已就位，本票 JS 实现对每个样例的判定结果写进样例旁的期望文件
- [x] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.7 确定性单测」；[16](../../plugin-eval/issues/16-existing-deterministic-tests.md)、[18](../../plugin-eval/issues/18-unit-test-declaration.md)

## Comments

### 2026-10-15 实现完成

在 worktree 分支 `worktree-impl-02` 上提交，未合并 main、未推送，等主会话审后合并。动 `plugins/**` 前已用 Skill 读过 `mattpocock-skills:writing-for-agents`、`skill-creator:skill-creator`、`plugin-dev:plugin-structure`。

**实现摘要**

- [run-unit-tests.js](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/scripts/run-unit-tests.js:1)：单测运行器。
  - 选插件：`--staged` 按暂存路径命中 `plugins/<name>/**` 选插件。用 `--no-renames`，所以改名时新旧两侧的插件都会被选中。
  - 读与跑：读工作区里插件根的 `unit-tests.json`，cwd 固定插件根，不经 shell 逐条跑。
  - 手动入口：`node scripts/run-unit-tests.js plugins/<name>`。`--json` 输出结构化结果，`--platform` 覆盖当前平台，这两个参数供样例对齐用。
  - 校验：顶层只认 `tests`，每条只认 `run` / `timeout_sec` / `platforms`。`run` 必须是非空字符串组成的非空数组。`timeout_sec` 必须是正数，JSON 里的 `true`、`"120"`、`0` 都不合法。`platforms` 必须是三个取值的非空子集。
  - 错误码：声明不合法时给出稳定错误码（`not-json` / `not-object` / `unknown-field` / `bad-tests` / `bad-test` / `bad-run` / `bad-timeout` / `bad-platforms`），并附中文原因。
  - 解释器：`python3` 依次试 `python3` → `python` → `py -3`，实际执行 `--version` 且输出是 `Python 3.x` 才算解析成功。版本要求是审阅后补的：老环境的 `python` 可能是 2，被当成可用后单测会判成失败，按约定它应当跳过并警告。其余解释器在 PATH 上解析出可执行文件；Windows 下按 PATHEXT 只取带扩展名的文件，`.cmd` 经 cmd.exe 跑。
  - 进程管理：POSIX 下每条单测自成进程组，超时时整组 SIGKILL。单测退出后，同组残留的孙进程也一并收掉。按 Ctrl-C 时，运行器转杀正在跑的单测。
  - 子进程环境：剥掉 `git rev-parse --local-env-vars` 列出的变量。原因是 git 调 hook 时注入 `GIT_INDEX_FILE` 等变量，单测在临时仓里跑的 git 命令会继承它们、改到本仓索引上。
  - 失败输出：指明 `tests[i]` 与 argv，写明退出码、信号名或超时，附输出末尾 40 行。
- [pre-commit](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.githooks/pre-commit:1)：版本校验之后调 `node scripts/run-unit-tests.js --staged`。
  - 脚本不存在时跳过。原因：本机的 `core.hooksPath` 是主检出的绝对路径，合并前切出的 worktree 提交时也跑主检出的 hook，而这些 worktree 里没有这个脚本。
  - 顺手修了一个老问题：原写法是 `git diff --cached --name-only | grep -q`，`grep -q` 命中即退出，暂存清单很长时 `git diff` 会收到 SIGPIPE，`pipefail` 下整条管道判失败，所有校验被静默跳过。现在先把暂存清单读进变量再 grep。
  - 新增一道：暂存路径改到单测脚本自身或共用样例时，跑 [run-unit-tests.test.js](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/scripts/tests/run-unit-tests.test.js:1)，约 8 秒。
- 声明：8 个插件写上声明，共 12 套单测。
  - `devkit-cd-blocker`、`devkit-clickable-paths`、`devkit-readable-citations`、`devkit-style-wenyan` 各 1 套。
  - `devkit-discipline`、`devkit-worktree-flow` 各 2 套。
  - `devkit-task-keeper` 1 套，声明了 `timeout_sec: 300` 与 `platforms: ["darwin", "linux"]`。
  - `devkit-tool` 3 套，其中 bash 那套声明了 `platforms: ["darwin", "linux"]`。
  - 这 8 个插件跑 `claude plugin validate` 均为 Validation passed，无 warning。
- 共用样例：[unit-tests-fixtures](vscode://file/Users/zhangq/Workspace/mine/claude-devkit-marketplace/scripts/unit-tests-fixtures/README.md:1) 下 23 个样例：合法 2、未声明 1、失败 1、超时 1、平台跳过 1、解释器缺失 1、python3 解析 1、不合法 15。每个样例旁的 `expected.json` 是本 JS 实现的判定结果，格式与对齐方法见该目录的 README。
- 自测：
  - `scripts/tests/run-unit-tests.test.js` 共 35 条，全部通过。
  - 在一次性克隆里用真实 `git commit` 走了 10 个场景：失败被拦、约定外字段被拦、非法 JSON 被拦、超时被拦、平台跳过与解释器缺失照常放行、未声明的插件静默放行、只改 `plugin-evals/` 不触发、插件目录已删则跳过、样例期望被改坏时拦、只改 `scripts/` 下其它脚本放行。结论都符合本票。

**各插件单测实测耗时**

测量环境：本机 macOS，经 hook 用真实 `git commit` 跑。一次提交改全部 8 个插件时，hook 总耗时 44.2 秒。

| 插件 | 条目与耗时 | 合计 |
|---|---|---|
| devkit-cd-blocker | cd-guard.test.js 0.7s | 0.7s |
| devkit-clickable-paths | clickable-paths.test.js 0.7s | 0.7s |
| devkit-discipline | guard-verify.js 4.3s、probe-throttle-verify.js 0.6s | 4.9s |
| devkit-readable-citations | readable-citations.test.js 0.3s | 0.3s |
| devkit-style-wenyan | wenyan-output-style.test.js 0.4s | 0.4s |
| devkit-task-keeper | run-tests.sh 30.8s（另一次手动跑 39.4s） | 31～39s |
| devkit-tool | probe-refresh-url-criterion.test.py 0.1s、worktree-cwd-recovery.js 0.4s、codegraph-hint-gating.sh 0.3s | 0.8s |
| devkit-worktree-flow | main-branch-guard.test.js 2.6s、round-approval.test.js 2.1s | 4.7s |

**版本号**

未升任何插件的版本号，devkit-tool 没有占用 6.26.0，也没有占用其它版本号。理由：`Agents.md`「版本与发布」只要求「插件功能变更」时升版；`unit-tests.json` 不被 Claude Code 加载，不改变插件行为；升 8 个插件只会让用户白刷 8 次缓存。合并时如果主会话认为随插件分发的文件有变动也要升版，再补。

**未覆盖项**

- pre-commit 跑的是工作区，不是暂存区快照。只暂存一半改动时，单测结论可能与实际提交的内容不符，已在一次性克隆里复现。18 已把这条列为接受的残余风险，本票未改。
- Windows 上四件事全部未实测：`.cmd` 经 cmd.exe 时的参数引号、`taskkill /T` 收进程树、`bash` 能否解析到 Git Bash、Ctrl-C 转杀。
- 只改仓根共用文件（如 `scripts/check-versions.js`）时，不跑任何插件的单测（同 16 的残余风险）。
- 留给 14 的 Python 实现：要对齐的不只是 `expected.json`。三处解析细节样例覆盖不到：
  - `python3` 回退链要求 `--version` 输出是 `Python 3.x`；
  - `timeout_sec` 超大时不能当成立即超时（JS 侧钳到 `setTimeout` 上限）；
  - Windows 下不取无扩展名的同名文件。

  另外，`invalid-nan`、`invalid-timeout-bool` 两个样例按 Python 的默认写法会判错，改法写在样例目录的 README 里。
