# 18: 单测声明放哪、长什么样

Type: grilling
Status: resolved
Blocked by: 无

## Question

[现有确定性单测是否并入同一入口](16-existing-deterministic-tests.md) 定了闸门检查命令与本仓 pre-commit 共读一份**单测声明**（被测插件声明自己的确定性单测怎么跑；未声明只提示不拦）；[评测产物与状态落在哪、什么格式](13-result-layout.md) 已定结果目录布局。要决定：

1. 声明放在插件目录内（随插件分发）还是仓内插件目录外的 `plugin-evals/<plugin>/`。
2. 格式：一个 JSON / YAML 文件、`plugin.json` 里的字段，还是约定文件名。
3. 字段：命令、工作目录、超时、跨平台差异（Windows 下怎么跑）、是否需要网络或 node。
4. 本仓 pre-commit 按暂存路径挑出被改插件后怎么读到它。

## Answer

2026-10-15 用户拍板：Q0 选 a（本会话用 Bash 直写主检出里的 `.scratch/plugin-eval/` 与 `CONTEXT.md`，不提交），Q1～Q6 原话「其余全部按推荐来」。Jev（jev-1.13.0）六题与推荐一致。

以 `devkit-tool` 为例，声明长这样：

```json
{
  "tests": [
    { "run": ["python3", "tests/probe-refresh-url-criterion.test.py"] },
    { "run": ["node", "hooks/tests/worktree-cwd-recovery.js"] },
    { "run": ["bash", "hooks/tests/codegraph-hint-gating.sh"], "platforms": ["darwin", "linux"] }
  ]
}
```

1. **位置**：放在被测插件目录内，插件根下，随插件分发。闸门检查命令拿到插件目录就能读到；插件目录就是仓根时同样成立；声明与单测文件同在插件目录。
2. **格式与文件名**：固定文件名 `unit-tests.json`，JSON 格式，node 与 Python 标准库都能直接解析，不引入依赖。顶层只有 `tests` 数组。实测在插件根放这个文件，`claude plugin validate` 静默通过、无 warning。
3. **每条单测只有三个字段**：
   - `run`（必填）：argv 数组，首元素是解释器名，不经 shell。解释器按 `devkit-portable-shell` 约定解析——`python3` 依次试 `python3` → `python` → `py -3`、以实际执行 `--version` 成功为准；其余先解析出可执行文件路径（Windows 上可能是 `.cmd`）。
   - `timeout_sec`（可选，缺省 120）：超时判失败。
   - `platforms`（可选，取值 `darwin` / `linux` / `win32`，缺省全部平台）。

   工作目录固定为插件根，不设字段；`run` 里的相对路径相对插件根解析。不设 `cwd`、`network`、`env`、`name` 等字段——两套实现（Python 闸门检查命令、JS pre-commit 脚本）各自解析同一份声明，字段越少语义越不容易漂移。
4. **只收离线、结果确定的单测**：需要联网的不算单测，不进声明。本仓 12 套实测都不联网（文件里的 URL 都是写死的测试数据）。
5. **跨平台与解释器找不到**：当前平台不在 `platforms` 里，两处都跳过并提示。在列表里但解释器解析不到时，闸门检查命令判失败；pre-commit 跳过并警告（与现有 pre-commit 找不到 node 时的处置一致）。
6. **本仓 pre-commit**：暂存路径命中 `plugins/<name>/**` 即选中该插件（`plugin-evals/<name>/` 下的改动不选中）；读工作区里的声明、在工作区跑；插件目录已删则跳过；未声明的插件静默，不提示（闸门检查命令仍按 [16](16-existing-deterministic-tests.md) 提示「未声明单测」）；声明不是合法 JSON 或字段不合约定时拦下。任一条退出码非零或超时即拦。闸门检查命令遇到不合法的声明同样判失败（随本条推得，未单独问）。

**对其它票的影响**：[现有确定性单测是否并入同一入口](16-existing-deterministic-tests.md) 第 1 条写的「声明文件的位置与格式随结果目录布局一起定」由本票定下，已在 16 的 Comments 标注。

**未选**：Q0 关闭仓库级后台隔离、进 worktree 改副本后手工合回；Q1 放插件目录外的 `plugin-evals/<plugin>/`；Q2 YAML、放 `.claude-plugin/` 下、放 `evals/` 下；Q3 shell 字符串加 `cwd` 字段、不设超时字段统一 120 秒；Q4 未声明插件每次提交都提示、把暂存区版本导出到临时目录再跑；Q5 不设 `platforms` 且找不到解释器时两处都跳过、两处都判失败；Q6 加 `network` 字段、离线时跳过。

**残余不确定**：

- 两套实现各自实现解释器解析与超时，可能对同一份声明给出不同结论。实施时宜备一组共用的声明样例，两边各跑一遍对齐（建议，未拍板）。
- pre-commit 跑的是工作区内容：有未暂存改动时，单测结果与实际提交的内容可能不一致。
- Windows 上 `bash` 能否解析到 Git Bash、`.cmd` 解析，未实测（同 [15](15-preflight-checks.md)）。现有 2 套 bash 单测若声明为不含 `win32`，Windows 上就不测这两套。

**重开条件**：

- Claude Code 官方给插件清单加了测试入口字段时，重议第 1、2 条（同 16 的重开条件）。
- 出现确需联网的确定性测试、且用户要它进闸门时，重议第 4 条。
- 两套实现被发现对同一份声明给出不同结论时，重议是否收敛到单一实现。

## Comments

### 2026-10-15 第一轮提问（待答）

认领前 Edit 被后台会话隔离守卫拦下（`.scratch/plugin-eval/` 未跟踪，只在主检出里有，各 worktree 里没有），先问 Q0 怎么写文件。补查事实：

- 本仓 12 套单测分布在 8 个插件，全部在各自插件目录内；解释器 node 9 套、python3 1 套、bash 2 套。
- 全部用 `__dirname` / `__file__` / `BASH_SOURCE` 或相对 `require` 自锚定路径，与工作目录无关；全部不联网；只写系统临时目录。
- 复制 `devkit-cd-blocker` 到临时目录，在插件根放 `unit-tests.json`、在 `.claude-plugin/` 下放额外 json，`claude plugin validate` 均为 Validation passed、无 warning。

第一轮问六件（位置、格式与文件名、命令与工作目录与超时、pre-commit 挑插件与读声明、跨平台与缺解释器、是否声明联网依赖），Jev 六题与推荐一致（置信 0.82～0.98）。

### 2026-10-15 第一轮答复

用户原话「Q0 选 a，其余全部按推荐来」，见 Answer。本票据此关闭。答案没有带出能立票或该写进地图 Not yet specified 的新问题：两套实现的一致性、Windows 实测都属实施层，记在残余不确定。同轮改写：地图 Decisions so far 追加一行；`CONTEXT.md`「单测声明」词条补「放在被测插件目录内、随插件分发」与「只收离线、结果确定的单测」；16 的 Comments 补本票的落点。
