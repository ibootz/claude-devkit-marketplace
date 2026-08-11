// worktree-flow-inject.js — 纯注入钩子（SessionStart / UserPromptSubmit / SubagentStart）
//
// 【用途】
// 把「主分支不落笔、改动走 worktree」这条流程规约注入上下文。它不阻止任何操作——真正
// 拦截的是同插件的 guards/main-branch-guard.js；本文件的作用是让 AI 在**撞闸之前**就知道
// 正确路径，避免「做对了却过不去」变成「撞了才知道」。
//
// 【三个事件都要挂，缺一路等于该路没写】
// 本仓 .claude/rules/project/hook-restraint.md 的实测结论：UserPromptSubmit 只触达主会话，
// 子代理由 Agent 工具编程派发、收不到；子代理要靠 SubagentStart 单独注入。而改文件这个
// 动作**主会话和子代理都会做**，所以两边都得注入，再加 SessionStart 覆盖会话开头与
// auto-compact 之后的重注。
//
// 【双挂硬要求】
// 输出的 hookSpecificOutput.hookEventName 必须与入参 hook_event_name 一致，写死任一个都会
//让另一路静默失效（不报错、不告警，与压根没挂外观相同）。故此处回声入参，并过白名单。
//
// 关闭开关：WORKTREE_GUARD=off（与 guard 同一个开关，一起关，避免只关一半造成
// 「拦得住但不说怎么办」或「说了却不拦」的错位状态）。

'use strict'

const fs = require('fs')

const ALLOWED_EVENTS = new Set(['SessionStart', 'UserPromptSubmit', 'SubagentStart'])

const CONTEXT = `# 主分支保护（worktree-flow）

**main / master 上不落笔**：这两个分支上的 \`Write\` / \`Edit\` / \`MultiEdit\` / \`NotebookEdit\`
与 \`git commit\` 会被 PreToolUse **硬拦**（exit 2，不是弹框，没有点一下就过的入口）。

四步流程，照抄：

1. **开工作区**——调 \`EnterWorktree\` 工具 \`{"name":"<任务语义-kebab>"}\`。它建临时分支
   \`worktree-<name>\`、落点 \`.claude/worktrees/<name>/\`，并把会话 cwd 切进去。
2. **在里面改**——worktree 里分支不是 main/master，闸自然放行；改完在 worktree 内 \`git commit\`。
3. **合并回来**——\`ExitWorktree\` 传 \`{"action":"keep"}\` 回到主目录，然后
   \`git -C <仓根> merge --no-ff <临时分支>\`（保留合并提交，日后看得出这批改动同属一次作业）。
4. **清理**——\`git -C <仓根> worktree remove <worktree 路径>\` +
   \`git -C <仓根> branch -d <临时分支>\`。**临时分支不 push remote**。

**放行的情形**（不必绕路）：非 git 目录；detached HEAD；仓正处于 merge / rebase /
cherry-pick 进行中（解决冲突按设计就在主分支上做）；目标文件落在 \`.claude/\` \`.keeper/\`
\`.git/\` 之下。

**拦不住的情形**（闸只认 \`git commit\` 这一种 Bash 形态，其余靠你自觉）：\`sed -i\`、
\`>\` 重定向、\`tee\`、heredoc 写文件、解释器脚本内部的写操作——它们在 main 上同样违反本规约。

确需在主分支直接写（改错别字、应急热修）：\`WORKTREE_GUARD=off\` 临时关闭，用完即恢复。`

function main() {
  if (process.env.WORKTREE_GUARD === 'off') process.exit(0)

  let input = ''
  try {
    input = fs.readFileSync(0, 'utf8')
  } catch (_) {
    process.exit(0)
  }

  let payload = {}
  try {
    payload = JSON.parse(input)
  } catch (_) {
    /* 入参不可解析时按 SessionStart 处理，注入总比静默好 */
  }

  const event = ALLOWED_EVENTS.has(payload.hook_event_name)
    ? payload.hook_event_name
    : 'SessionStart'

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: event,
        additionalContext: CONTEXT,
      },
    })
  )
  process.exit(0)
}

main()
