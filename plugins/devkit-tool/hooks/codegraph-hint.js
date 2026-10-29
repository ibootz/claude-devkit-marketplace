// codegraph-hint.js — 纯注入 hook（不阻止任何操作），同时挂两个事件
// 仅当**当前仓**已建 codegraph 图时，注入两行：一行强化用 codegraph 的意愿，一行
// 抑制"拿 Grep/Glob 全仓搜符号、为找代码而整读文件"这类同类内置工具的意愿。
// 未建图的仓输出 0 字节 —— 建不建图是用户的决定，本 hook 不劝建、不做阈值扫描。
//
// Trigger: UserPromptSubmit（主会话每轮） + SubagentStart（每个子代理启动时）
// Output:  additionalContext → 注入到对应上下文（找不到 .codegraph/codegraph.db 时无输出）
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
// 「建过图」的判据（6.34.0 起）：`.codegraph/codegraph.db` 是文件，光有 `.codegraph/` 目录不算。
//   - 这是 codegraph 自己的判据：其 directory.js 的 isInitialized 写着
//     `Must have codegraph.db, not just .codegraph folder`（codegraph 1.6.2 实测源码）。
//   - 光有目录的反例（本机实测）：`~/.codegraph` 是 codegraph 的用户级配置目录，只有
//     daemons/、beta-signup.json、telemetry.json、update-check.json；仓里提交了
//     `.codegraph/.gitignore` 却没在本机建图的目录只有那一个文件。旧判据把两者都当图。
// 家目录边界：上溯到 os.homedir() 即停，不看家目录自己的 `.codegraph`（那是配置目录，不是图）。
//   旧版在非 git 目录（如多仓的父目录）里一路走到家目录、命中 `~/.codegraph`，
//   682 个注入回合里 553 个是这样误触发的（2026-10-29 主会话统计）。
// 判据与阈值见同插件 skill：codegraph-index。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')

// 建过图才算：与 codegraph 自身 isInitialized 同一判据（不验 schema，那要开 SQLite）
function hasGraph(dir) {
  try {
    return fs.statSync(path.join(dir, '.codegraph', 'codegraph.db')).isFile()
  } catch {
    return false
  }
}

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

// 从 startDir 逐级向上找建过图的目录；submodule 可穿过，独立仓根、worktree 边界与家目录即停
function findGraphRoot(startDir) {
  let dir = path.resolve(startDir)
  const home = path.resolve(os.homedir())
  for (let i = 0; i < 64; i++) {
    if (dir === home) return null
    if (hasGraph(dir)) return dir
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
    '- 找符号定义/调用方/影响面先跑 `codegraph query|callers|impact <英文符号名>`；跨层链路或原理问题用 `codegraph explore "<含英文类名的问题>"`。只认英文 token，纯中文查不到。',
    '- 全仓搜符号名/整读文件找代码属于绕路：仅 codegraph 返回空、或目标是配置/文档/md 时才回退 Grep/Glob。结果引用为结论证据前仍需 Read 核对行号。',
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
