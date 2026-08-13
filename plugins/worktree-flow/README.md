# worktree-flow · 主分支保护

在 `main` / `master` 分支上禁止直接改代码。所有改动走「开 worktree 临时分支 → 在里面改并
提交 → `--no-ff` 合回主分支 → 删 worktree 与临时分支」，临时分支不 push remote。

## 构成

| 组件 | 挂载点 | 强度 | 作用 |
|---|---|---|---|
| `hooks/guards/main-branch-guard.js` | `PreToolUse(Write\|Edit\|MultiEdit\|NotebookEdit\|Bash)` | **deny（exit 2）** | 受保护分支上的写操作硬拦，文案给可照抄的下一步 |
| `hooks/worktree-flow-inject.js` | `SessionStart` + `UserPromptSubmit` + `SubagentStart` | 注入 | 撞闸之前先讲清正确路径 |
| `skills/worktree-flow/SKILL.md` | skill | — | 四步流程全文、base ref 坑、冲突处理、清理核验 |

三个注入事件缺一不可：`UserPromptSubmit` 只触达主会话，子代理收不到；而**改文件这个动作
主会话和子代理都会做**，子代理那一路必须靠 `SubagentStart`。`SessionStart` 覆盖会话开头
与 auto-compact 之后的重注。

## 为什么是 deny 而不是 ask

本仓 `.claude/rules/project/hook-restraint.md` 的强度阶梯建议「能退到 `ask` 就别用 `deny`」，
因为 `ask` 给用户一个点一下就过的出口。**但本机 Claude Code 的 `defaultMode` 是
`bypassPermissions`，`permissionDecision: "ask"` 实测全部失效**——弹框不出现、直接放行。
可用强度只剩「注入提醒」与「硬拒 deny」两档，没有中间档。

2026-08-11 用户在这两档之间拍板选 deny，并要求配环境变量逃生阀。逃生阀 `WORKTREE_GUARD=off`
同时关掉 guard 与注入（不能只关一半，否则会出现「拦得住但不说怎么办」或「说了却不拦」的
错位状态）。

## 判据（对照 hook-restraint 的六问）

**0. 挂在哪个事件、能不能真的阻止？** `PreToolUse` + `exit 2`，能真正拦下调用。不是
`PostToolUse`（那个拦不住任何东西，文件已经写完了）。

**1. 确定字段是哪个？**

| 步骤 | 取值方式 | 比较方式 |
|---|---|---|
| 目标仓 | `Write`/`Edit`/`MultiEdit` 取 `tool_input.file_path`、`NotebookEdit` 取 `notebook_path`，向上找到第一个存在的目录后跑 `git rev-parse --show-toplevel`；`Bash` 用 `payload.cwd` 或该次调用自己的 `-C <path>` | 命令失败即非 git 仓 → 放行 |
| 分支 | `git rev-parse --abbrev-ref HEAD` | **逐字**等于 `main` 或 `master`。detached HEAD 返回 `HEAD`，不在集合内 |
| 豁免路径 | 目标文件相对仓根的路径 | 前缀是否为 `.claude/` `.keeper/` `.git/`，或 `WORKTREE_GUARD_EXEMPT` 列出的前缀 |
| 合流进行中 | `git rev-parse --absolute-git-dir` 下是否存在 `MERGE_HEAD` / `CHERRY_PICK_HEAD` / `REVERT_HEAD` / `rebase-merge` / `rebase-apply` | 文件存在性 |

全部是确定字段或文件存在性，没有一处在猜语义。

**2. 假阳性长什么样？** 三类，都是有意接受的：

- 在 main 上改一个错别字、补一行文档 → 被拦。用户拍板不按扩展名豁免文档，理由是 `.json`
  / `.yml` 落在代码与文档的灰区，按扩展名切会切出一条模糊边界。出口是逃生阀或按目录豁免。
- 仓里恰好有个叫 `main` 但不作主干用的分支 → 被拦。同一个出口。
- 默认三前缀（`.claude/` `.keeper/` `.git/`）是白名单式的：主分支上写这三处之外的**任何**
  路径都拦，包括 `docs/`、`README.md`。`WORKTREE_GUARD_EXEMPT` 可追加前缀（见下「按目录
  豁免」），那是配置者主动开的口子，不算误杀。

**3. 假阴性长什么样？** Bash 侧的漏报面是**有意收窄**的结果，不是疏漏。hook-restraint 明令
「判据需要理解语义的规则不得做成 deny」，而「这条 shell 命令算不算写操作」正是那类判据。
故 Bash 侧只拦 `git commit` 这一种可定位到命令名位置的闭合形态。下列在 main 上一律放行：

- `sed -i` / `>` `>>` 重定向 / `tee` / `cp` `mv` `rm` / heredoc 写文件
- 解释器脚本内部的写操作（`python - <<EOF` 里的 `open(w)`、`node -e`、`awk -i inplace`）
- `$(which git) commit`、`G=git; $G commit` 等命令替换与变量间接调用
- heredoc 终止符写法非常规、`stripHeredocs` 没剥干净时藏在正文里的 `git commit`

兜住这些的是注入的流程规约（软约束）与 SKILL.md 的「拦不住但同样违反」一节，不是这道闸。

**4. AI 撞到能不能一次改对？** finding 文案里直接给了 `EnterWorktree` 的调用 JSON 与
`merge --no-ff` / `worktree remove` / `branch -d` 三条可照抄的命令，以及逃生阀写法。

**5. 失灵时会怎样？** 所有 git 调用带 3 秒超时并 `try/catch`，失败一律返回 `null` →
**放行**（fail-open）。git 不可用、payload 字段改名、仓损坏等情形下本插件静默退化为不拦，
不会出现「永久拒绝」这种把 AI 逼到绕路的失败模式。

## 回归用例

```bash
node plugins/worktree-flow/tests/main-branch-guard.test.js
```

用例在临时目录里真建 git 仓（不 mock），`spawnSync` 喂 JSON 到 stdin、**不经过 shell**
（经 shell 的测试脚本一旦引号失衡，guard 会把测试数据当真命令拦下并原样回灌进 finding）。
两侧都有：该拦的确实拦（main 上 Edit / `git commit`），该放的确实放（feature 分支、
detached HEAD、`.claude/` 路径、`WORKTREE_GUARD_EXEMPT` 路径、合并进行中、非 git 目录、
`sed -i` 这类已知漏报）。

## 与内置 EnterWorktree 的关系

流程第 1 步用 Claude Code 自带的 `EnterWorktree`（落点 `.claude/worktrees/`、会话 cwd 自动
切换），而不是本插件自带脚本——用户 2026-08-11 拍板。已知边界：

- **base ref**：`EnterWorktree` 默认 `worktree.baseRef = fresh`，从 `origin/<默认分支>` 分叉。
  本地 main 领先 origin 时新工作区缺你的本地提交。SKILL.md 给了开工前的比对命令与两条出路。
- **submodule**：`git worktree add` 只建父仓工作区，submodule 目录是空的，`EnterWorktree`
  不补。含 submodule 的聚合仓改用 `task-keeper:tk-worktree`。

## 按目录豁免

`WORKTREE_GUARD=off` 是整仓放行；若只想让某些目录在主分支上可直接改（如 `docs/`、
`config/`），用更细的 `WORKTREE_GUARD_EXEMPT`——逗号分隔的目录前缀，并进默认三前缀之后：

```json
// .claude/settings.json（团队共享）或 .claude/settings.local.json（个人本地）
{ "env": { "WORKTREE_GUARD_EXEMPT": "docs/,config/" } }
```

settings.json 的 `env` 注入会话进程，PreToolUse hook 作为子进程经 `process.env` 继承，
settings 改动会被 reload，无需重启即生效。落 `.claude/settings.json` 随仓入库、全队共享；
落 `.claude/settings.local.json` 自动 gitignore、仅本人。判据仍是确定的前缀匹配：列了
`docs/` 只放 `docs/` 下，`src/` 照拦。

## 关闭

```bash
WORKTREE_GUARD=off <命令>          # 单次
```

或写进 settings.json 的 `env`（长期关闭等于卸载本插件，还留着一份「以为受保护」的错觉，
不建议）。

## Codex 侧

`.codex-plugin/plugin.json` 已登记，但 **hook 是 Claude Code 专有**，Codex 侧只有
`skills/worktree-flow/SKILL.md` 生效——即只有流程指引，没有硬拦。
