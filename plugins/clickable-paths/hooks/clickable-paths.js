// clickable-paths.js — UserPromptSubmit hook
//
// 每轮注入一段极短的输出格式规约：提到本机文件时用 markdown 链接的形态给路径，
// 让 iTerm2 把它渲染成 OSC 8 超链接，cmd+click 直接跳 VS Code 的对应行。
//
// 【为什么是注入而不是拦截】
// 「这段文字里提到的是不是一个本机文件路径」需要理解语义——同一个 `foo/bar.js`
// 可能是真实文件、也可能出现在报错原文、他人仓库的引用、或纯举例里。判据必须靠猜，
// 按 .claude/rules/hook-restraint.md 的分级只能落在强度 2（注入提醒），做成
// PreToolUse 的 deny 会制造「写对了却过不去」。本 hook 不阻止任何操作。
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
// Trigger: UserPromptSubmit
// Output:  additionalContext → 注入到当前轮次 Claude 上下文
// Opt-out: 环境变量 CLICKABLE_PATHS=off（或 0 / false）时不注入

'use strict'

function main() {
  const flag = (process.env.CLICKABLE_PATHS || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') {
    process.exit(0)
  }

  const prompt = [
    '# 文件路径写成可点击链接（clickable-paths）',
    '',
    '在**对话回复正文**里提到本机文件时，用这个形态给路径（iTerm2 会渲染成可点击短文本，' +
      'cmd+click 直接跳 VS Code 对应行）：',
    '',
    '`[<文件名>:<行号>](file:///<绝对路径>#<行号>)`',
    '',
    '- **行号写在 `#` 后面**，不是 `:` 后面——iTerm2 只认 `#` 片段这个位置。',
    '- **没有具体行号时补 `#1`**（指向文件开头），不要省掉片段。',
    '- href 必须是绝对路径：`file://` 加上以 `/` 开头的路径，合起来三条斜杠。相对路径点不开。',
    '- 标签默认 `<文件名>:<行号>`。同名文件本轮出现多处、或需表明模块归属时，标签换成' +
      '相对仓库根的路径 + 行号。',
    '',
    '**只对确认存在的文件套链接。** 判据是你自己的状态、不需要猜：Read / Edit / Grep / ' +
      '`ls` 见过、或工具结果里出现过 = 存在，套链接；**你正在提议新建、或落点还没定 = 不套**，' +
      '改用 inline code 写路径（`plugins/foo/bar.js`）。同一轮里 `Write` 建好之后再提它，' +
      '就按已存在处理、可以套。**拿不准存在性时不套**——点开一个不存在的路径只会得到一个' +
      '空白未保存 buffer，比不可点击更糟；更不要为了凑格式**编造一个绝对路径**，' +
      '落点待定就如实写待定。',
    '',
    '**其余不适用场景（一律裸路径原样）**：代码块与命令行内部、commit message、' +
      '写进文件的 md/代码/注释、派给子代理的 prompt、提交给外部系统的内容（工单/评论/消息）、' +
      '不在本机的路径（他人仓库、报错原文里的路径、纯举例）。',
    '',
    '这个形态**满足** `working-discipline` 3.3 四要素里「引用类与方法带 `path:行号`」那条：' +
      '完整路径在 href 里，点开即到，比裸文本更直达。',
  ].join('\n')

  const output = {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: prompt,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
