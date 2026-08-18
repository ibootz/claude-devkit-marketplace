// clickable-paths.js — UserPromptSubmit + SubagentStart 双挂 hook
//
// 每轮注入一段极短的输出格式规约：提到本机文件时用 markdown 链接的形态给路径，
// 让 iTerm2 把它渲染成 OSC 8 超链接，cmd+click 直接跳 VS Code 的对应行。
//
// 【为什么是注入而不是拦截】
// 「这段文字里提到的是不是一个本机文件路径」需要理解语义——同一个 `foo/bar.js`
// 可能是真实文件、也可能出现在报错原文、他人仓库的引用、或纯举例里。判据必须靠猜，
// 按 .claude/rules/project/hook-restraint.md 的分级只能落在强度 2（注入提醒），做成
// PreToolUse 的 deny 会制造「写对了却过不去」。本 hook 不阻止任何操作。
//
// 【为什么双挂（1.3.0 补）】
// `UserPromptSubmit` 只触达主会话——它的语义是「用户在交互界面提交了一次 prompt」，
// 子代理由 Agent/Task 工具编程派发任务字符串，不存在这个动作。1.2.0 及之前只挂了它，
// 于是**子代理回执里的文件路径从来不可点**：hook 正常执行、正常输出、退出码 0，
// 只是那段文本永远不出现在子代理的上下文里，没有任何报错。同型事故在本仓有实测记录
// （codegraph 引导注入主会话 20 次、而真正做检索的子代理 23 份 transcript 里零调用），
// 判据见 .claude/rules/project/hook-restraint.md 的「注入类 hook 的事件落点」一节。
//
// 双挂的硬要求：输出的 hookSpecificOutput.hookEventName **必须与入参 hook_event_name
// 一致**，写死任一个都会让另一路静默失效——不报错、不告警，与「压根没挂」外观相同。
// 回声前过白名单，不把 payload 里的任意字符串原样回声出去。
//
// 【为什么 1.4.0 要收紧措辞】
// 1.3.0 及之前的注入把「不套链接」的替代形态写成了 inline code，而 inline code 恰好就是
// 模型提到文件名时的默认写法——替代形态比目标形态更容易触达，加上「拿不准就按不存在处理」
// 这条兜底，等于给了一条随时可走的退路。实测一整轮输出里 `gates.g3` / `decisions.md` /
// `contracts.md` / `tasks.md` 全部写成了 inline code，四要素的「现场证据」段则写成裸
// `path:行号`（那是 working-discipline 3.3 的字面形态，模型满足了它就以为交付完了），
// 通篇零链接。1.4.0 三处改动针对这三个成因：把三种失败形态点名写出来、把「只写文件名」
// 与「表格/列表/现场证据/转述回执」显式圈进适用面、把 3.3 与 readable-citations 的
// 关系写成「链接同时满足两边」而不是留给模型自己权衡。
//
// 【机制依赖（都已实测，2026-08-04）】
//   1. Claude Code 的 markdown 渲染器对 `file:` scheme 有专用处理：解析成绝对路径、
//      **保留 `#片段`**、显示文本取方括号标签；终端支持超链接时发 OSC 8 序列。
//      实测 CC 2.1.220 + iTerm2 3.6.11 渲染为带下划线的可点击短文本。
//   2. iTerm2 3.4+ 对 `file` scheme 且带 `#` 片段的 OSC 8 链接**套用 Semantic History
//      规则**打开（官方 escape codes 文档明文）。所以行号必须写在 `#` 后面。
//   3. Semantic History 的 Run command 需指向 CLI 的**绝对路径**——GUI 应用继承的是
//      launchd 环境，`launchctl getenv PATH` 可能为空。配置见 README。
//
// 【与 readable-citations 的分工】
// 本插件管**提到文件时的路径**，并把「写进文件的 md」排除在外（落盘文档里写
// `file:///Users/...` 对别人、别的机器、GitLab 网页全是死链）。落盘 md 里**引用另一份
// md 文档的章节**归 `readable-citations` 管，那边走相对路径 + 标题锚点。两者互补。
//
// Trigger: UserPromptSubmit（主会话） + SubagentStart（每个子代理）
// Output:  additionalContext → 注入到对应代理的上下文
// Opt-out: 环境变量 CLICKABLE_PATHS=off（或 0 / false）时不注入

'use strict'

const fs = require('fs')

// 只回声这两个事件名。payload 里出现别的值时直接静默退出，
// 避免把任意字符串原样回声进 hookSpecificOutput。
const ALLOWED_EVENTS = new Set(['UserPromptSubmit', 'SubagentStart'])

function readStdin() {
  try {
    return fs.readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

function main() {
  const flag = (process.env.CLICKABLE_PATHS || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') {
    process.exit(0)
  }

  let event = ''
  try {
    event = (JSON.parse(readStdin()) || {}).hook_event_name || ''
  } catch {
    event = ''
  }

  if (!ALLOWED_EVENTS.has(event)) {
    process.exit(0)
  }

  const prompt = [
    '# 文件路径写成可点击链接（clickable-paths）',
    '',
    '对话正文每提到一个本机文件，就给一个链接：' +
      '`[<文件名>:<行号>](file:///<绝对路径>#<行号>)`。' +
      '**只写文件名（`decisions.md`）、写成裸 `path/to/file.ext:130`、' +
      '或用反引号包成 inline code，三种都是漏了这一条**——' +
      'inline code 只留给落点还没定的新文件。',
    '',
    '- 行号写在 `#` 后面，没有具体行号写 `#1`。',
    '- href 用绝对路径：`file://` 后紧跟以 `/` 开头的路径（合起来三条斜杠）。',
    '- 标签默认 `<文件名>:<行号>`；同名文件多处出现、或需表明模块归属时换成' +
      '相对仓库根路径+行号。',
    '- 一句话提到三个文件就给三个链接。表格单元格、列表项、四要素的「现场证据」段、' +
      '转述子代理回执的那几行，都是对话正文，照套。',
    '',
    '判据：你 Read/Edit/Grep/ls 见过、或工具结果里出现过的文件 = 存在，套链接。' +
      '拿不准存在性时先 `ls` 或 `Grep` 确认再写，确认不到才退回 inline code' +
      '——不编造绝对路径。',
    '',
    '与 working-discipline 3.3 四要素、readable-citations 的关系：它们要的' +
      ' `path/to/file.ext:行号` 由链接标签与 `#行号` 一并承载，套成链接同时满足两边；' +
      '写成裸路径只满足它们、漏了本条。',
    '',
    '裸路径原样：代码块与命令行内部、commit message、写进文件的 md/代码/注释、' +
      '派给子代理的 prompt、提交给外部系统的内容（工单/评论/消息）、不在本机的路径' +
      '（他人仓库、报错原文、纯举例）。',
  ].join('\n')

  const output = {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: prompt,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
