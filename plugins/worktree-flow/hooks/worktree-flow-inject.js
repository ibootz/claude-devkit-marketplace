// worktree-flow-inject.js — 纯注入钩子（SessionStart / UserPromptSubmit / SubagentStart）
//
// 把「main/master 默认走 worktree；确需直写则由主会话 AskUserQuestion 取 Human 本轮授权」
// 注入上下文。它不阻止操作；实际门控由 guards/main-branch-guard.js 与本轮授权状态机完成。
//
// UserPromptSubmit 只触达主会话，SubagentStart 单独触达子代理，SessionStart 覆盖启动与 compact。
// 输出的 hookEventName 必须回声白名单内的入参事件，否则其中一路会静默失效。

'use strict'

const fs = require('fs')
const { approvalToolInput } = require('./lib/round-approval')

const ALLOWED_EVENTS = new Set(['SessionStart', 'UserPromptSubmit', 'SubagentStart'])
const APPROVAL_TEMPLATE = JSON.stringify(
  approvalToolInput({
    repository: '<finding 中的仓绝对路径>',
    branch: 'main',
    target: '<finding 中的目标>',
  })
)

const CONTEXT = `# 主分支保护（worktree-flow）

**main / master 默认不落笔**：这两个分支上的 \`Write\` / \`Edit\` / \`MultiEdit\` / \`NotebookEdit\`
与 \`git commit\` 若无 Human 本轮授权，会被 PreToolUse 拒绝。

默认走四步：

1. 调 \`EnterWorktree\` 工具 \`{"name":"<任务语义-kebab>"}\`，建临时分支并切入 worktree。
2. 在 worktree 内改与提交。
3. \`ExitWorktree\` 传 \`{"action":"keep"}\` 回主目录，再
   \`git -C <仓根> merge --no-ff <临时分支>\`。
4. \`git -C <仓根> worktree remove <worktree 路径>\`，再
   \`git -C <仓根> branch -d <临时分支>\`。临时分支不 push remote。

**确需本轮直接写 main/master**：主会话按刚才 finding 给出的仓、分支、目标，原样调用其
\`AskUserQuestion {...}\`。结构模板如下（若实际为 master，branch 必须取 finding 的 master）：

\`AskUserQuestion ${APPROVAL_TEMPLATE}\`

不得传 \`answers\` 或 \`annotations\`；须由 Human 在 UI 中亲自选择。Human 选“批准本轮”后，
重试原操作。本授权覆盖当前主会话本轮所有 main/master 写入与 \`git commit\`；下一次用户消息、
本轮结束或会话结束即自动失效。Human 选 worktree 或未明确批准则不得直写。子代理不能调用
\`AskUserQuestion\`，撞闸后须把仓、分支、目标与原因回主会话，由主会话申请。

本机制不使用 \`permissionDecision: "ask"\`，因本机 \`bypassPermissions\` 下该档实测失效。
\`WORKTREE_GUARD=off\` 仍是独立的全局关闭开关，不是 Human 本轮授权；AI 不得自行启用。

**既有自动豁免**：非 git 目录；detached HEAD；merge / rebase / cherry-pick 进行中；目标落在
\`.claude/\`、\`.keeper/\`、\`.git/\` 或显式配置的豁免目录。

**Bash 已知漏报**：守卫只机械识别 \`git commit\`；\`sed -i\`、重定向、\`tee\`、heredoc、
解释器内部写文件虽可能过闸，未经本轮授权仍不得在 main/master 使用。`

function main() {
  if (process.env.WORKTREE_GUARD === 'off') process.exit(0)

  let payload = {}
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
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
