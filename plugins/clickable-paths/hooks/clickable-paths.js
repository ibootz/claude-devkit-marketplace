// clickable-paths.js — UserPromptSubmit + SubagentStart 双挂 hook
//
// 每轮注入一段极短的输出格式规约：提到本机文件时用 markdown 链接的形态给路径，
// 让当前宿主把它渲染成可点击的东西，点一下直接跳 VS Code 的对应行。
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
// 【为什么 1.8.0 再收一次：示范本身在教坏写法】
// 1.4.0 把三种漏套形态点名写出来，但**正例自己就是坏的**——注入里给的模板是把整条链接
// 用反引号包成 inline code，周围几条 bullet 又清一色是 inline code。模型照抄这个示范，
// 产出的是被反引号包住的整条链接：markdown 只生成 code span、**不生成 link 节点**，
// Claude Code 拿不到 URL、不发 OSC 8，终端上就是一段灰底文字——看着像链接、点不动，
// 且不报错，比「压根没写链接」更难发现。前三种漏套管的是「路径被写成了 inline code」，
// 这第四种不同：链接已经写对，只是外面多套了一层反引号，整条一起失效。
//
// 1.8.0 三处改动：正例换成可逐字照抄的裸链接、把「整条链接外面再套一层反引号」立为第四种
// 漏套并写清后果、把注入里所有尖括号占位符删掉（尖括号是非法 URL 字符，模板本身就在示范
// 失效形态——同 keeperQueues() 里现算前缀的理由）。这三条各有一条回归用例钉着。
//
// 【为什么 1.9.0 改成按宿主切形态】
// 2026-09-19 在四个宿主里逐一实测同一批链接，结果**两两无交集，不存在通吃的形态**：
//
//   iTerm2（macOS）           只认 file: 加 `#行号`（Semantic History）
//   Windows Terminal          只认 vscode://file/ 加 `:行号`
//   VS Code 内置终端          绝对路径两种 scheme 都能点
//   VS Code 侧边栏 webview    绝对路径一条都不通，只认相对 workspace 根的路径
//
// 1.8.0 及之前对所有宿主写死 file: 一种，于是在 Windows 的三个宿主里注入的全是
// **渲染成蓝色可点的样子、点下去没反应**的链接——不报错、不告警，与上面第四种漏套
// 同一类失效，只是成因在宿主而不在写法。1.9.0 起先探宿主再选形态，判据见 detectHost()。
//
// 【机制依赖（都已实测）】
//   1. Claude Code 的 markdown 渲染器对 `file:` scheme 有专用处理：解析成绝对路径、
//      **保留 `#片段`**、显示文本取方括号标签；终端支持超链接时发 OSC 8 序列。
//      实测 CC 2.1.220 + iTerm2 3.6.11 渲染为带下划线的可点击短文本（2026-08-04）。
//   2. iTerm2 3.4+ 对 `file` scheme 且带 `#` 片段的 OSC 8 链接**套用 Semantic History
//      规则**打开（官方 escape codes 文档明文）。所以那一支的行号必须写在 `#` 后面。
//   3. Semantic History 的 Run command 需指向 CLI 的**绝对路径**——GUI 应用继承的是
//      launchd 环境，`launchctl getenv PATH` 可能为空。配置见 README。
//   4. VS Code 的 markdown 预览拒渲染 `file:` 链接（2026-08-24 查 VS Code 侧
//      `extensions/markdown-language-features/dist/extension.js`）：markdown-it 默认
//      `validateLink` 的黑名单正则是 `/^(vbscript|javascript|file|data):/`（只放行
//      `data:image`），VS Code 的覆盖额外放行的只有 `vscode:` 与 `vscode-insiders:`
//      ——**没有 file**。判为非法时 markdown-it 不生成 link_open，整条原样输出成纯文本，
//      看起来像「md 写坏了」。所以落盘 md 走 vscode://file/ 加 `:行号`（VS Code 的
//      URL handler 语法，与 file: 那轨的 `#行号` 不同）。
//   5. Windows 侧 `file:` 带行号必挂（2026-09-19 实测）：Windows Terminal 把 `file:` URL
//      交给 `ShellExecute`，后者当纯文件路径处理，既不解析 `#行号` 也不解析 `:行号`，
//      于是去找一个名叫 `X.md#1` / `X.md:1` 的文件——不存在（`:` 在 Windows 文件名里
//      本就非法），点了没反应也不报错。`#行号` 能跳行是 iTerm2 独有的能力，不是 `file:`
//      scheme 的通用语义。
//
// 【与 readable-citations 的分工】
// 本插件管**提到文件时的路径**。落盘 md 里**引用另一份 md 文档的章节**归
// `readable-citations` 管，那边走相对路径 + 标题锚点。两者互补。
//
// Trigger: UserPromptSubmit（主会话） + SubagentStart（每个子代理）
// Output:  additionalContext → 注入到对应代理的上下文
// Opt-out: 环境变量 CLICKABLE_PATHS=off（或 0 / false）时不注入

'use strict'

const fs = require('fs')
const path = require('path')

// 只回声这两个事件名。payload 里出现别的值时直接静默退出，
// 避免把任意字符串原样回声进 hookSpecificOutput。
const ALLOWED_EVENTS = new Set(['UserPromptSubmit', 'SubagentStart'])

// 宿主环境探测。判据全部取自 Claude Code 与终端**自己注入**的环境变量，
// 2026-09-20 在四个宿主里逐一实采得到，对照表见 README 的「宿主判别表」。
//
// 顺序从最特异到最泛，**不可调换**：VS Code 内置终端同时带 `VSCODE_*` 与
// `CLAUDE_CODE_ENTRYPOINT=cli`，只有先判 webview 才不会把两者混为一谈。
//
// 四个信号各自的来源：
//   CLAUDE_CODE_ENTRYPOINT=claude-vscode  扩展启动 CLI 时写入，webview 独有且充分
//   TERM_PROGRAM=vscode / VSCODE_INJECTION=1  VS Code 给内置终端注入的 shell 集成标记
//   WT_SESSION                            Windows Terminal 给每个 tab 的会话 GUID
//
// 三个都不命中时落到 'generic'：cmd.exe / conhost、远程 SSH、CI，以及未来 Claude Code
// 改了变量名的情况。generic 不是「未知所以不给链接」，而是「用在最多宿主里验证过的那种」，
// 见 pickInlineForm()。
function detectHost(env) {
  if (env.CLAUDE_CODE_ENTRYPOINT === 'claude-vscode') return 'vscode-webview'
  if (env.TERM_PROGRAM === 'vscode' || env.VSCODE_INJECTION === '1') return 'vscode-terminal'
  if (env.WT_SESSION) return 'windows-terminal'
  return 'generic'
}

// 宿主 + 平台 → 对话正文那一轨用哪种形态。
//
// 【Windows 侧首选与兜底都是 vscode:】
// 它是 Windows 三个终端宿主里唯一能**跳到行**的形态（机制依赖第 5 条解释了 `file:`
// 为什么在这里必挂）。代价要算进来：vscode://file/ 硬依赖本机装了 VS Code 并注册了
// 协议处理器，没装的机器上这个形态必然失效——而 `file:` 至少还能把文件打开。用户
// 2026-09-20 拍板接受这个代价，判据是本机与目标用户都装了 VS Code。
//
// 【非 Windows 保留 file:】
// `file:` 加 `#行号` 能跳行是 iTerm2 Semantic History 的能力，2026-08-04 在 iTerm2
// 实测可用，**同一次实测里 vscode: 走不通**。macOS 侧至今没有新数据推翻这条，
// 把它一并切成 vscode: 会拿一个已验证可用的配置去换一个没验证过的。
function pickInlineForm(host, platform) {
  if (host === 'vscode-webview') return 'workspace-relative'
  return platform === 'win32' ? 'vscode-absolute' : 'file-absolute'
}

// 把绝对路径归一化成 URL 能用的样子：反斜杠转正斜杠，Windows 盘符前置单个斜杠
// （`C:/x` 变成 `/C:/x`），好让 `file://` 加上它合起来正好是三条斜杠。
function toUrlPath(abs) {
  return abs.replace(/\\/g, '/').replace(/^\/?/, '/')
}

// 落盘 md 那一轨的示范，三支共用、不随宿主变。
// 写成裸链接而不是模板：注入里的每一个字符都要能被逐字抄进输出，留占位符就等于
// 在示范一个失效形态（1.8.0 的判据，有回归用例钉着）。
const PERSISTED_SAMPLE = '[decisions.md:11](vscode://file/abs/path/decisions.md:11)'
const PERSISTED_WHY =
  '理由：VS Code 的 markdown 预览把 `file:` 判为非法链接、整条原样吐成纯文本，' +
  '它的白名单里只有 `vscode:`。落盘这一轨**不跟宿主变**——文件 commit 之后会被别人、' +
  '别的机器、GitLab 网页读到，跟着本机宿主变只会在别处变成死链，而死链不报错。'

// 每种形态自带它在注入文本里的措辞与队列链接的算法。
// 三支共享的那些规则（四种漏套、判据、适用面、与 3.3 的关系）不在这里，见 buildGuidance()
// ——同一条规矩只写一处，改的时候不必三支各改一遍。
//
// 这里的每一段文字都不许出现尖括号：尖括号是非法 URL 字符，照抄即坏链（1.8.0 的判据）。
function inlineSpec(form, cwd) {
  if (form === 'workspace-relative') {
    return {
      sample: '[decisions.md:130](docs/decisions.md#130)',
      shape:
        '方括号里写 `文件名:行号`，圆括号里写**相对 workspace 根**的路径，' +
        '接 `#`，再接行号',
      rules: [
        '- 行号写在 `#` 后面（写成 `#L130` 也能点，`L` 带不带都行），' +
          '整个文件没有具体行号时把 `#` 连同行号一起省掉。',
        '- href 用**相对 workspace 根**的路径，不带 scheme、不带前导斜杠，' +
          '形如 `docs/decisions.md#130`。这个宿主里绝对路径一条都点不开，' +
          '`file:` 与 `vscode:` 一起失效，所以只用相对路径。',
      ],
      driftNote:
        '**落盘 md 换一个 scheme，同样整条裸露**：' + PERSISTED_SAMPLE +
        '——写进文件的 md 里提到本机文件时用这个形态，行号跟在 `:` 后面' +
        '（可再跟一个 `:` 与列号）。' + PERSISTED_WHY,
      queueHref: (dir, sample, file) => {
        const rel = path.relative(cwd, dir).replace(/\\/g, '/')
        return `${rel}/${sample}/${file}`
      },
    }
  }

  if (form === 'vscode-absolute') {
    return {
      sample: '[decisions.md:130](vscode://file/C:/abs/path/decisions.md:130)',
      shape:
        '方括号里写 `文件名:行号`，圆括号里写 `vscode://file/`，' +
        '接绝对路径，再接 `:`，最后接行号',
      rules: [
        '- 行号写在 `:` 后面（可再跟一个 `:` 与列号），没有具体行号写 `:1`。',
        '- href 用绝对路径，盘符照写、分隔符一律正斜杠。' +
          '**这个宿主里 `file:` 带行号点不动**——它被交给 `ShellExecute`，' +
          '后者把 `#1` 或 `:1` 当成文件名的一部分去找，找不到也不报错。',
      ],
      driftNote:
        '**落盘 md 用同一个形态，同样整条裸露**：' + PERSISTED_SAMPLE +
        '——它在 VS Code 的 markdown 预览里同样能跳行，而这正是落盘那一轨一直在用的形态。' +
        PERSISTED_WHY,
      queueHref: (dir, sample, file) =>
        `vscode://file${toUrlPath(dir)}/${sample}/${file}:1`,
    }
  }

  // file-absolute：非 Windows 的默认，走 iTerm2 的 Semantic History。
  return {
    sample: '[decisions.md:130](file:///abs/path/decisions.md#130)',
    shape:
      '方括号里写 `文件名:行号`，圆括号里写 `file://`，' +
      '接以斜杠开头的绝对路径（合起来三条斜杠），再接 `#`，最后接行号',
    rules: [
      '- 行号写在 `#` 后面，没有具体行号写 `#1`。',
      '- href 用绝对路径：`file://` 后紧跟以斜杠开头的路径，合起来三条斜杠。',
    ],
    driftNote:
      '**落盘 md 换一个 scheme，同样整条裸露**：' + PERSISTED_SAMPLE +
      '——写进文件的 md 里提到本机文件时用这个形态，行号跟在 `:` 后面' +
      '（可再跟一个 `:` 与列号）。' + PERSISTED_WHY +
      '反过来对话正文只用 `file:`——Claude Code 只对 `file:` 发 OSC 8。',
    queueHref: (dir, sample, file) => `file://${toUrlPath(dir)}/${sample}/${file}#1`,
  }
}

function readStdin() {
  try {
    return fs.readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

// 从 cwd 逐级上溯找 `.keeper/`，返回该项目实际存在的队列路径前缀。
//
// 【为什么要现算，而不是在注入文本里写一个模板】
// 队列条目的路径含两个只有运行时才知道的变量：仓根绝对路径与交付 id。写成模板就得留
// 占位符，而尖括号是非法 URL 字符——iTerm2 对含尖括号的 file:// 识别失败，整条链接
// 不可点。于是模板本身在示范一个失效形态，照抄它的人得到的是坏链接。
// 现算把这一层去掉：注入里给的就是可以逐字照抄的真实前缀。
// 探不到 `.keeper/` 时返回空数组，那一段整体不注入——没有队列的项目不必读这几行。
function keeperQueues(startDir) {
  const out = []
  try {
    let dir = fs.realpathSync(startDir)
    for (let up = 0; up < 8; up++) {
      const keeper = `${dir}/.keeper`
      let deliveries = null
      try {
        deliveries = fs.readdirSync(keeper, { withFileTypes: true })
      } catch {
        deliveries = null
      }
      if (deliveries) {
        for (const d of deliveries) {
          if (!d.isDirectory() || d.name.startsWith('.')) continue
          for (const [queue, file] of [['debug', 'issue.md'], ['chore', 'item.md']]) {
            const qdir = `${keeper}/${d.name}/${queue}`
            try {
              if (fs.statSync(qdir).isDirectory()) out.push({ queue, file, dir: qdir })
            } catch {
              /* 该队列尚未建，跳过 */
            }
          }
        }
        return out
      }
      const parent = fs.realpathSync(`${dir}/..`)
      if (parent === dir) break
      dir = parent
    }
  } catch {
    /* 探测失败一律降级为「没有队列」，不让 hook 因此报错 */
  }
  return out
}

function buildGuidance(spec, queues) {
  const lines = [
    '# 文件路径写成可点击链接（clickable-paths）',
    '',
    '对话正文每提到一个本机文件，就给一个链接：' + spec.sample + '。' +
      '**方括号、圆括号、整条链接都直接裸露在正文里，外面不套反引号**；' +
      spec.shape + '。',
    '',
    '**四种漏套，命中任一种都等于没给链接**：只写文件名（`decisions.md`）、写成裸 ' +
      '`path/to/file.ext:130`、把路径包成 inline code、**把整条链接外面再套一层反引号**。' +
      '第四种最像「已经写好了」，实际最坏——反引号一包就成了 code span，markdown 不再' +
      '产生 link 节点，终端拿不到 URL、不发 OSC 8，点不动。' +
      'inline code 只留给落点还没定的新文件。',
    '',
    ...spec.rules,
    '- 标签默认写 `文件名:行号`；同名文件多处出现、或需表明模块归属时换成' +
      '相对仓库根路径加行号。',
    '- 一句话提到三个文件就给三个链接。表格单元格、列表项、四要素的「现场证据」段、' +
      '转述子代理回执的那几行，都是对话正文，照套。',
    '- **队列编号同样是文件**：`DBG-140` / `CHR-014` 是队列条目的别名，说到编号就是' +
      '说到那条条目文件，照上面的形态套链接，并在链接后紧跟括号写 ≤20 字问题简述，' +
      '让人不点开也知道这条讲什么。debug 编号对应 `issue.md`，chore 编号对应 ' +
      '`item.md`，两个文件名不可互换。条目归档后路径多一层归档批次目录，' +
      '先 `ls` 确认再链。',
    '',
    '判据：你 Read/Edit/Grep/ls 见过、或工具结果里出现过的文件 = 存在，套链接。' +
      '拿不准存在性时先 `ls` 或 `Grep` 确认再写，确认不到才退回 inline code' +
      '——不编造绝对路径。',
    '',
    '与 working-discipline 3.3 四要素、readable-citations 的关系：它们要的' +
      ' `path/to/file.ext:行号` 由链接标签与行号一并承载，套成链接同时满足两边；' +
      '写成裸路径只满足它们、漏了本条。',
    '',
    spec.driftNote +
      '引用另一份 md 文档的章节仍走相对路径加标题锚点（readable-citations 那一条）。',
    '',
    '裸路径原样：代码块与命令行内部、commit message、代码与注释、' +
      '派给子代理的 prompt、提交给外部系统的内容（工单/评论/消息）、不在本机的路径' +
      '（他人仓库、报错原文、纯举例）。',
  ]

  if (queues.length) {
    lines.push(
      '',
      '本项目实际存在的队列前缀（已从磁盘探到，逐字照抄这个形状）。' +
        '下面给的是**对话正文**的形状；把同一条编号写进 md 文件时换 `vscode://file/` ' +
        '开头、行号写在 `:` 后（那份绝对路径原样接在后面）：')
    for (const q of queues) {
      const sample = q.queue === 'debug' ? 'DBG-140' : 'CHR-014'
      lines.push(
        `- ${q.queue}：[${sample}](${spec.queueHref(q.dir, sample, q.file)})（≤20 字问题简述）`)
    }
  }

  return lines.join('\n')
}

function main() {
  const flag = (process.env.CLICKABLE_PATHS || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') {
    process.exit(0)
  }

  let payload = {}
  try {
    payload = JSON.parse(readStdin()) || {}
  } catch {
    payload = {}
  }
  const event = payload.hook_event_name || ''

  if (!ALLOWED_EVENTS.has(event)) {
    process.exit(0)
  }

  const cwd = payload.cwd || process.cwd()
  const host = detectHost(process.env)
  const spec = inlineSpec(pickInlineForm(host, process.platform), cwd)
  const prompt = buildGuidance(spec, keeperQueues(cwd))

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
