// readable-citations.js — UserPromptSubmit + SubagentStart 双挂 hook
//
// 注入一段写作规约：引用其它文档的章节时，让引用**自足**——读者不点链接也能读懂
// 这句在说什么，想点时又点得动。
//
// 【为什么双挂】
// `UserPromptSubmit` 只触达主会话（它的语义是"用户在交互界面提交了一次 prompt"，
// 子代理由 Agent/Task 工具编程派发任务字符串，不存在这个动作）。而落盘文档大量由
// 子代理写——sdlc-writer、keeper、general-purpose 的实现者都在写 md。只挂前者
// 等于漏掉产出文档的主力。判据与实证见 .claude/rules/project/hook-restraint.md
// 的「注入类 hook 的事件落点」一节。
//
// 双挂的硬要求：输出的 hookSpecificOutput.hookEventName **必须与入参
// hook_event_name 一致**，写死任一个都会让另一路静默失效——不报错、不告警，
// 与"压根没挂"的外观完全相同。回声前过白名单，不把 payload 里的任意字符串
// 原样回声出去。
//
// 【为什么是注入而不是拦截】
// "这段引用够不够自足"要理解语义，判据只能靠猜，按 hook-restraint.md 的强度阶梯
// 只能落在强度 2（注入提醒）。本 hook 不阻止任何操作，失败模式只是多占上下文预算。
//
// 【与 clickable-paths 的分工】
// 那个插件管**对话正文里的文件路径**（`[文件名:行号](file:///绝对路径#行号)`），
// 明文把"写进文件的 md"排除在外。本插件管的是**文档章节的引用**，两者互补不重叠：
// 引用 md 文档的章节 → 相对链接 + 标题锚点（本插件）；
// 提到源码文件的某一行 → 裸路径或 file:// 绝对路径（那个插件）。
//
// Trigger: UserPromptSubmit（主会话） + SubagentStart（每个子代理）
// Output:  additionalContext → 注入到对应代理的上下文
// Opt-out: 环境变量 READABLE_CITATIONS=off（或 0 / false）时不注入

'use strict'

const fs = require('fs')

// 只回声这两个事件名。payload 里出现别的值时直接静默退出，
// 避免把任意字符串原样回声进 hookSpecificOutput。
const ALLOWED_EVENTS = new Set(['UserPromptSubmit', 'SubagentStart'])

const GUIDANCE = [
  '# 引用别处的章节要自足（readable-citations）',
  '',
  '**自足** = 读者不点链接也读得懂这句在说什么。引用其它文档的章节时按序做四件事：',
  '',
  '1. **结论只有一句就内联**——把那句原文抄进正文，引用退为溯源标注。让读者不必跳转，' +
    '是这四条里最省他事的一条。',
  '2. **带标题原文**——写「§5.2 模型档位」而不是「§5.2」。编号一插节就漂移且静默失效，' +
    '标题原文全文可搜，链接失效时仍找得回来。',
  '3. **括注 20 字提要**——用一句话说这一节讲什么，供读者判断值不值得点进去。',
  '4. **写明引用关系**——它是前置条件、反例、详细版、还是相反的做法？' +
    '必读的内联进正文，延伸阅读的才给链接。',
  '',
  '链接形态按**落点**分两轨，各自只在对应场合有效：',
  '',
  '- **对话正文**（你在终端里说的话）——绝对路径 + 行号，iTerm2 里 cmd+click 直达编辑器：',
  '  `[SKILL.md · §5.2 模型档位](file:///abs/path/SKILL.md#128)（三档模型分别什么时候用）`',
  '- **落盘 md**（写进文件的文档）——相对路径 + 标题锚点，VS Code 预览与 GitLab 网页都能跳：',
  '  `[working-discipline · §5.2 模型档位](../working-discipline/SKILL.md#52-模型档位)' +
    '（三档模型分别什么时候用）`',
  '',
  '落盘 md 走相对路径的理由：文档 commit 之后会被别人、别的机器、GitLab 网页读到，' +
    '`file:///Users/...` 在那些地方是死链，而死链不报错——点了没反应而已。',
  '',
  '**锚点由标题原文算出**，三步：转小写 → 删去标点 → 空格转 `-`。两个坑：' +
    '中文标点（`、`「」（））**直接消失且不留分隔符**，' +
    '`## 五、Agent 工具派发子代理` 的锚点是 `#五agent-工具派发子代理`（「五」与「agent」直接粘连，' +
    '唯一那个 `-` 来自原文里真实存在的空格）；' +
    '你写在链接标签里的 `§5.2` 这类前缀**不进锚点**，锚点只认标题原文。',
  '',
  '**什么时候不触发**：引用源码文件（`.js` / `.py` / `.java` 等非 md）的某一行时保持原路径写法，' +
    '锚点对它们无效；同一份文档内部的自引用直接写标题、不必给链接；' +
    '代码块与命令行内部、commit message、提交给外部系统的内容（工单 / 评论 / 消息）一律原样。',
].join('\n')

function readStdin() {
  try {
    return fs.readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

function main() {
  const flag = (process.env.READABLE_CITATIONS || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') {
    process.exit(0)
  }

  let event = ''
  try {
    event = (JSON.parse(readStdin()) || {}).hook_event_name || ''
  } catch {
    event = ''
  }

  // 读不到或不认识的事件名一律不注入：宁可这一路静默失效，
  // 也不回声一个来路不明的字符串。
  if (!ALLOWED_EVENTS.has(event)) {
    process.exit(0)
  }

  const output = {
    hookSpecificOutput: {
      hookEventName: event,
      additionalContext: GUIDANCE,
    },
  }

  process.stdout.write(JSON.stringify(output) + '\n')
  process.exit(0)
}

main()
