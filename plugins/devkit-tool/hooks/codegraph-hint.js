// codegraph-hint.js — 纯注入 hook（不阻止任何操作），同时挂两个事件
// 仅当**当前仓**已建 codegraph 图时，注入两行：一行强化用 codegraph 的意愿，一行
// 抑制"拿 Grep/Glob 全仓搜符号、为找代码而整读文件"这类同类内置工具的意愿。
// 未建图的仓输出 0 字节 —— 建不建图是用户的决定，本 hook 不劝建、不做阈值扫描。
//
// Trigger: UserPromptSubmit（主会话每轮） + SubagentStart（每个子代理启动时）
// Output:  additionalContext → 注入到对应上下文（无 .codegraph/ 时无输出）
// Opt-out: 环境变量 CODEGRAPH_HINT=off（或 0 / false）时不注入
//
// 为什么必须双挂（2026-08-04 实测，勿改回单挂）：
//   UserPromptSubmit 的语义是"用户在交互界面提交了一次 prompt"，而子代理是被
//   Agent/Task 工具以编程方式派发任务字符串的，不存在这个动作，**注入到不了子代理**。
//   实测某会话（xxstar-ai-spsd-work）主会话收到本注入 20 次，而该项目 23 份
//   transcript 里 codegraph 的实际调用为 0 —— 因为真正做符号检索的是 keeper /
//   fixer 子代理，它们一次都没收到过这段文本。SubagentStart 的 additionalContext
//   则被直接写进子代理自己的初始消息数组（Claude Code 2.1.220 二进制实证），
//   这是当前唯一可靠的触达子代理的注入落点。
//   注意：输出里的 hookEventName 必须与入参 hook_event_name 一致，写死任一个都会
//   让另一路静默失效（不报错、只是不生效）。
//
// 向上查找的边界（关键，靠 `.git` 的形态区分三种情况）：
//   - `.git` 是**目录** → 独立仓根，到此为止，不上溯到无关父目录。
//   - `.git` 是**文件**且 gitdir 指向 `.../worktrees/X` → 这是另一个 checkout，**停**。
//     父仓的图里是**另一个分支**的符号（实测：分支新增类 SeqModel4Create 在 worktree
//     图查得到、父仓图查不到），且 worktree 目录通常被 gitignore、根本不在父仓图里。
//     宁可不注入，也不能把 AI 指到一份内容对不上的图。
//   - `.git` 是**文件**且 gitdir 指向 `.../modules/X` → submodule，**继续上溯**。父仓
//     建图时会把 submodule 源码一并索引（实测 sptalentsdapi 的 1,893 个 java 文件就在
//     父仓图里），所以在 submodule 内干活时该注入。
// 判据与阈值见同插件 skill：codegraph-index。

'use strict'

const fs = require('fs')
const path = require('path')

function readStdinSync() {
  try {
    return fs.readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

// 返回 'repo'（.git 目录，独立仓根）| 'worktree' | 'submodule' | null
function gitBoundaryKind(dir) {
  const p = path.join(dir, '.git')
  let st
  try {
    st = fs.statSync(p)
  } catch {
    return null
  }
  if (st.isDirectory()) return 'repo'
  let gitdir = ''
  try {
    gitdir = fs.readFileSync(p, 'utf8')
  } catch {
    return 'repo' // 读不出内容时按最保守的「仓根」处理，不上溯
  }
  // 顺序不能反：submodule 的 worktree 其 gitdir 同时含两段，形如
  // `.git/modules/src/spgwnlpc/worktrees/spgwnlpc`（实测）。它仍是「某个仓的
  // submodule」，外层那个仓才是真边界，所以先判 modules、继续上溯。
  if (/\/modules\//.test(gitdir)) return 'submodule'
  if (/\/worktrees\//.test(gitdir)) return 'worktree'
  return 'repo'
}

// 从 startDir 逐级向上找 .codegraph/；submodule 可穿过，独立仓根与 worktree 边界即停
function findGraphRoot(startDir) {
  let dir = path.resolve(startDir)
  for (let i = 0; i < 64; i++) {
    try {
      if (fs.statSync(path.join(dir, '.codegraph')).isDirectory()) return dir
    } catch {
      /* 无 .codegraph，继续 */
    }
    const kind = gitBoundaryKind(dir)
    if (kind === 'repo' || kind === 'worktree') return null
    const parent = path.dirname(dir)
    if (parent === dir) return null
    dir = parent
  }
  return null
}

function main() {
  const flag = (process.env.CODEGRAPH_HINT || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') process.exit(0)

  let cwd = process.cwd()
  // 回声 hook_event_name：两个事件共用本脚本，输出的 hookEventName 必须与入参一致。
  // 白名单兜底——payload 给了本脚本没挂的事件名时按 UserPromptSubmit 处理，
  // 避免把任意字符串回声进 hookSpecificOutput。
  const KNOWN_EVENTS = ['UserPromptSubmit', 'SubagentStart']
  let hookEventName = 'UserPromptSubmit'
  try {
    const payload = JSON.parse(readStdinSync() || '{}')
    if (typeof payload.cwd === 'string' && payload.cwd) cwd = payload.cwd
    if (KNOWN_EVENTS.includes(payload.hook_event_name)) hookEventName = payload.hook_event_name
  } catch {
    /* payload 不可解析时退回 process.cwd() 与 UserPromptSubmit */
  }

  if (!findGraphRoot(cwd)) process.exit(0)

  const prompt = [
    '# codegraph 已建图仓（devkit-tool）',
    '',
    '- 本仓已建 codegraph 代码图。找符号定义 / 调用方 / 改动影响面，**先跑** `codegraph query|callers|impact <英文符号名>`；跨层链路或「这块怎么工作」用 `codegraph explore "<含英文类名的问题>"`。图只认英文标识符 token，纯中文提问查不到。',
    '- 在本仓用 `Grep`/`Glob` 全仓搜符号名、或为「找代码在哪」而整读文件，**属于绕路**：只有 codegraph 返回空、或目标是配置 / 文档 / md（图不索引这些）时，才回退到内置检索工具。codegraph 结果可直接用于定位，但作为结论证据引用前仍需 Read 原文核对行号。',
  ].join('\n')

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName,
        additionalContext: prompt,
      },
    }) + '\n'
  )
  process.exit(0)
}

main()
