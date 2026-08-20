---
id: DBG-007
summary: worktree隔离会话无法完成主仓收尾
status: done
priority: P1
difficulty: medium
type: arch
spec_status: conformant
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-007 · worktree 隔离会话无法直接完成主仓合并与清理

## 问题

在 worktree 隔离会话中把主仓路径交给 `git -C`、`EnterWorktree` 或子 shell，分别会被工具层拒绝；因此该会话不能自己执行主仓 `merge`、`git worktree remove` 与 `git branch -d`，只能由未受该隔离限制的主会话或独立终端接管收尾。证据见 [01-worktree-guard.png:1](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/DBG-007/01-worktree-guard.png#1)（截图转录见下方）以及实现边界：[worktree-flow SKILL.md:45](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/skills/worktree-flow/SKILL.md#45) 明确要求先 `ExitWorktree {"action":"keep"}` 回主目录，再在主仓执行合并。

## 用户原话

> opus-debugger-k7m2
> 【目标】接管这一条 bug 报告，按 agents/debug-keeper.md 的流程完成登记、triage、派发（自己直接调用 Agent 工具并行派发第二层 fixer subagent）、对账、收尾，并诊断如何修复 worktree 隔离会话无法完成主仓 merge/remove/branch cleanup 的问题。
> 【上下文】项目根：/Users/zhangq/Workspace/mine/claude-devkit-marketplace。你的 name 是 opus-debugger-k7m2。用户原话逐字如下：
> [Image #1] 如何修复这个问题？
> 截图：已落盘 /Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-193211-01-worktree-guard.png；图片内容转录：截图显示 worktree 隔离会话尝试执行主仓收尾：`git -C 主仓路径 merge ...` 被拒；`EnterWorktree({path: 主仓路径})` 报“是主 working tree，非 linked worktree”；裸 `cd 主仓 && git merge` 被 cd-guard 拦截并提示改子 shell；子 shell 中执行仍被拒，报“a worktree-isolated session's git operations must target its own worktree”。随后会话说明这是沙箱隔离设计，防止 worktree 会话越界碰主仓；建议用户在主仓目录或新 Claude Code 会话中执行 merge、`git worktree remove`、`git branch -d`。
> 【约束】认领这条 issue 后先跑 `scripts/keeper_cli.py claim --kind debug` 原子取号，再跑 bind 把 name 与 issue 登记好；合并回主仓前先跑 `scripts/keeper_cli.py lock acquire` 拿合并锁；不要动业务代码。核实停止条件：追到 worktree-flow skill、相关 hook/guard 实现及调用方/收尾流程边界；明确实际追到哪一层、哪些边界未追。需要用户拍板时走 agents/debug-keeper.md §12 的待拍板协议，不要经过我传正文。不要执行任何发布、外部系统写操作或本地服务重启。
> 【期望输出】按 agents/debug-keeper.md §13 的回执格式返回：改了哪些文件（逐个列路径）；关键决策（为什么这样做、放弃了什么方案）；阻塞点；需父代理跟进事项；并写明实际追踪深度与未追边界。

## 证据

- [01-worktree-guard.png:1](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/DBG-007/01-worktree-guard.png#1)
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-193211-01-worktree-guard.png`
  - 转录：截图中显示“你退出 worktree 进入 master 分支 合并 然后清理即可”。随后会话说明自己被沙箱钉死在 `D-327-fix-lint-profile-backlog-index-scope` worktree，物理上摸不到主仓。尝试 `git -C 主仓路径 merge ...` 被拒；`EnterWorktree({path: 主仓路径})` 报“是主 working tree，非 linked worktree”；裸 `cd 主仓 && git merge` 被 cd-guard 拦截并提示改子 shell；子 shell 中执行仍被拒，报“a worktree-isolated session's git operations must target its own worktree”。截图建议在主仓目录执行：`git merge D-327-fix-lint-profile-backlog-index-scope --no-ff`、`git worktree remove .sdlc/worktrees/D-327-fix-lint-profile-backlog-index-scope`、`git branch -d D-327-fix-lint-profile-backlog-index-scope`，或开启一个 cwd 位于主仓根的新会话。

## 规格依据

- 结论：`conformant`。本仓规格要求隔离工作区先退出，再由主会话在源仓完成合并；截图中的“在隔离会话内直接操作主仓”不属于允许操作边界。若产品真正要求隔离会话跨越边界自行操作主仓，这是架构/权限策略变更，不是当前插件可独立修复的 debug 缺陷。
- 查过的来源：

| 来源 | 结果 | 备注 |
|---|---|---|
| 需求文字规格（仓内 `sdlc/specs/features/{f}`、`behaviors/*.gherkin`） | 未命中 | 本仓无 `sdlc/` 目录，未找到该行为的产品需求文件 |
| view spec | 未命中 | 本条是工具会话边界，不是页面视图 |
| 原型 html | 未命中 | 本仓无与该 CLI 行为对应的原型 html |
| 交付级决策 / ADR | 未命中 | 在本仓相关插件与项目规则中未找到独立 ADR；下列插件文档是直接规范锚 |
| worktree-flow skill | 命中 | [worktree-flow SKILL.md:45-60](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/skills/worktree-flow/SKILL.md#45) 要求 `ExitWorktree` 后由主会话执行 `git -C <仓根> merge`、`worktree remove`、`branch -d` |
| worktree-flow guard / 注入 | 命中 | [main-branch-guard.js:381-389](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/guards/main-branch-guard.js#381) 将主分支写入路径交给 worktree 或主会话授权；[worktree-flow-inject.js:28-45](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/worktree-flow-inject.js#28) 将主仓收尾步骤与子代理回主会话边界注入 |
| 用户本 issue 的明确期望 | 命中 | 用户要求诊断该隔离边界，但未明确要求修改隔离沙箱策略 |

- 规格原文摘录：

```text
先以 `ExitWorktree {"action":"keep"}` 回主目录，再执行：

```bash
git -C <仓根> merge --no-ff <临时分支> -m "merge: <本批说明>"
```

子代理不能调用 `AskUserQuestion`；撞闸后须把仓、分支、目标与直写原因交回主会话申请。
```

- 期望 vs 实际：规格期望是“隔离会话不越界，退出后由主会话/主仓上下文收尾”；实际尝试是在仍处于隔离会话时操作主仓，因此工具层拒绝。二者一致，不构成规格违反。
- **本条的修复判据**：确认并记录正确的会话边界、主仓收尾命令和不得采用的绕过方式；若要让隔离会话直接操作主仓，须先取得 Human 对架构/权限策略变更的明确拍板。

## 生效机制与边界

隔离会话的失败不是 `main-branch-guard.js` 造成的：该 guard 只检查受保护分支上的 `Write` / `Edit` / `MultiEdit` / `NotebookEdit` 与命令位上的 `git commit`，并不实现截图中的“worktree-isolated session's git operations must target its own worktree”拦截。当前仓内可核实的边界是：worktree-flow 注入把 `ExitWorktree` 作为回到主目录的前置步骤，[worktree-flow-inject.js:28-35](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/worktree-flow-inject.js#28)；`main-branch-guard.js` 的 finding 则要求子代理撞闸后回主会话，[main-branch-guard.js:381-389](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/guards/main-branch-guard.js#381)。因此正确修复路径不是在隔离会话里改写命令，而是把收尾动作交给主会话或主仓目录中的新会话。

如果是 task-keeper 的聚合仓 fixer worktree，不能按截图的裸三条命令替代专用回流流程。应由 debug-keeper 在主工作区完成对账、拿合并锁，然后按 [tk-worktree SKILL.md:171-198](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/task-keeper/skills/tk-worktree/SKILL.md#171) 的 `merge-back`（默认 dry-run，确认后 `--apply`）回流，再按 [tk-worktree SKILL.md:149-167](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/task-keeper/skills/tk-worktree/SKILL.md#149) 的深度优先 `remove --yes` 清理；不要直接执行 `git worktree remove` 删除含 submodule 的 fixer worktree。

## Triage

- `priority: P1`：主流程的修复交付被阻塞，但存在明确绕行路径——退出隔离会话，由主会话或独立终端收尾；不是数据损坏或功能运行时错误。
- `difficulty: medium`：若只补本仓文档/注入提示，涉及 worktree-flow skill、注入文本与测试；若改造隔离策略，则跨 Claude Code 工具层与本仓插件边界，当前无法由本仓 fixer 独立完成。
- `type: arch`：争议点是会话隔离与主仓写入权限的架构边界，不是业务行为或页面体验。
- 处置：不派 fixer。当前实现与本仓规格一致；应把可执行的主会话交接说明视为使用流程，或在确认要改变隔离策略后转架构/需求变更。

### 依赖假设

- 假设：截图中的英文拒绝来自 Claude Code / 会话运行时工具层，而不是本仓某个未检出的 hook；本仓搜索未找到该错误原文，且 `main-branch-guard.js` 的职责与报错语义不匹配。
- 假设：调用方仍能使用 `ExitWorktree` 回到父会话；本 issue 未提供 `ExitWorktree` 失败的独立证据。
- 假设：主仓与隔离 worktree 的路径、分支和是否含 submodule 由实际会话提供；不能仅凭截图中的示例路径推断本交付的真实路径。

## 验证

### 场景 A：隔离会话直接操作主仓

步骤：在 worktree-isolated 会话中执行 `git -C <主仓> merge <分支>`，或把主仓路径交给 `EnterWorktree`。预期：工具层拒绝越界；实际：截图显示拒绝，且提示主 working tree 不是 linked worktree。结论：通过，隔离边界生效。

### 场景 B：退出隔离会话后由主会话收尾

步骤：在隔离会话先 `ExitWorktree {"action":"keep"}`，再由主会话在主仓上下文执行合并与清理；task-keeper 聚合仓则由 debug-keeper 按锁、对账、`merge-back`、`remove --yes` 流程执行。预期：操作对象与会话自己的 worktree 一致，主仓写入由主会话承担。代码依据：[worktree-flow SKILL.md:45-60](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/skills/worktree-flow/SKILL.md#45)。实际：本轮仅完成代码/文档核查，未在真实 D-327 或本项目 delivery 上执行合并、删除或服务实测。结论：流程规格通过，运行时场景待主会话按真实路径执行。

### 场景 C：在 task-keeper 聚合仓中直接用裸 `git worktree remove`

步骤：对含 submodule 的 fixer worktree 直接执行裸 `git worktree remove`。预期：可能因 submodule 结构拒绝，且绕过深度优先清理；实际依据：[tk-worktree SKILL.md:160-169](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/task-keeper/skills/tk-worktree/SKILL.md#160) 说明此形态不应使用，应用 `wt_supply.py remove --worktree <WT> --yes`。结论：不把截图中的三条裸命令作为 task-keeper 修复方案；需由主会话按专用流程执行。

## 修订记录

### 登记（2026-08-20）

登记原话：worktree 隔离会话无法完成主仓 `merge/remove/branch cleanup`，要求追到 worktree-flow、guard 实现及调用方/收尾边界。已原子认领 DBG-007、绑定 `opus-debugger-k7m2`，并把截图从 `_inbox/` 移入本条目录。

### 首轮 triage（2026-08-20）

核查 [worktree-flow SKILL.md:17-80](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/skills/worktree-flow/SKILL.md#17)、[main-branch-guard.js:1-43](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/guards/main-branch-guard.js#1)、[worktree-flow-inject.js:23-54](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/worktree-flow/hooks/worktree-flow-inject.js#23)、[tk-worktree SKILL.md:149-198](file:///Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/task-keeper/skills/tk-worktree/SKILL.md#149) 与 worktree-flow 两组回归测试。结论前置小节已记录为 `conformant`：本仓代码没有实现截图中的运行时隔离拒绝，现有文档已经把合并/清理责任交给退出后的主会话；本条没有可安全派发给 fixer 的业务代码修复面。

### 关闭（2026-08-20）

本条是对隔离边界与正确收尾责任的诊断，不是待修改的代码缺陷。已将 `status` 标为 `done`，语义为已确认现有实现符合规格、无 fixer 修复，不代表已在截图所示外部 D-327 仓执行合并或删除。主会话需按实际会话上下文负责后续收尾；本仓当前 DBG-007 队列正文未提交。

## 实际追踪深度与未追边界

已追到跨插件的直接调用与收尾边界：`worktree-flow` 的 skill、注入 hook、main-branch guard、task-keeper 的 `tk-worktree` 回流/清理约束、`devkit-tool` 的 worktree cwd 恢复 hook 及其挂载点，并运行 worktree-flow 的 34 + 45 项回归测试，全部通过。未追到 Claude Code 二进制内部的 worktree-isolation 沙箱实现、`EnterWorktree` / `ExitWorktree` 工具实现、截图所示具体 D-327 交付仓的真实 git 状态、外部会话调度器，以及真实合并后的运行时服务验证；这些边界不在本仓源码中。
