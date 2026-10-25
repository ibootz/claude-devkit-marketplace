// hyperlink-check.js — SessionStart hook（2.1.0 加）
//
// 会话启动时检查一次：Claude Code 在当前终端里会不会把 markdown 链接发成 OSC 8 超链接。
// 不会发时注入一段说明，让 AI 在第一条回复里告诉用户、并提出代为配置 FORCE_HYPERLINK。
//
// 【为什么要这一道检查】
// 本插件只决定「链接写成什么形态」，「发不发超链接」由 Claude Code 自己判定。后者不通过时
// 链接退化成「标签 (vscode://file/…)」纯文本：能点全靠终端自己的 URL 文本探测，而 Claude
// Code 折行插的是硬换行，长 URL 一折行就被截成两段，后半段点不动。注入正文写得再对也救不回来，
// 且不报错——用户只看到「有时能点、有时不能点」。
//
// 【判据来源：Claude Code 2.1.310 Windows 版二进制，2026-10-25 查】
// 内置的 supports-hyperlinks 在 Windows 构建里被裁成：
//   FORCE_HYPERLINK 有值 → 按它；WT_SESSION 在 → true；否则 return false
// 原包里 `case "vscode"` 那条版本判断成了走不到的死代码。外层兜底 pw() 只再认一张白名单：
//   TERM_PROGRAM / LC_TERMINAL ∈ SUPPORTED_TERMINALS、TERMINAL_EMULATOR=JetBrains-JediTerm、
//   TERM 含 kitty、tmux ≥ 3.4
// 所以 Windows 上 VS Code 内置终端、独立 cmd / PowerShell 窗口（conhost）都判为不支持。
// 非 Windows 构建里 vscode 那条分支是活的，本检查只在 win32 上跑。
//
// 【判据全部取自环境变量，同一环境永远同一结论】
// 落在 hook-restraint.md 的「可以做成 hook」一档。它是纯注入，不拦截任何操作；误报的代价是
// 会话开头多一句提醒。Claude Code 日后若把 vscode 加进白名单，这里会多提醒——届时删掉对应
// 判据即可，失灵方向是「多说一句」而不是「拦住用户」。
//
// 【只提醒、不自己写配置】
// 改用户的 settings 由 AI 在用户同意后做，hook 本身不碰任何文件：静默改用户配置是用户看不见的
// 副作用，且 VS Code settings 是 JSONC，机械改写容易破坏注释与格式。
//
// Trigger: SessionStart（matcher startup|resume|clear；compact 后不重复提醒）
// Output:  additionalContext → 注入主会话上下文；判定为支持时不输出
// Opt-out: CLICKABLE_PATHS=off（整个插件）或 CLICKABLE_PATHS_HYPERLINK_CHECK=off（只关这一道）

'use strict'

const fs = require('fs')

const EVENT = 'SessionStart'

// Claude Code 2.1.310 pw() 里的终端白名单，逐字照抄。
const SUPPORTED_TERMINALS = ['ghostty', 'Hyper', 'kitty', 'alacritty', 'iTerm.app', 'iTerm2', 'WarpTerminal']

const isOff = (v) => ['off', '0', 'false'].includes((v || '').toLowerCase())

// 入参事件名：读得到就用它（只认 SessionStart），读不到按本事件处理；
// 明确是别的事件时返回 null，不回声来路不明的字符串。
function resolveEvent() {
  let payload
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch {
    return EVENT
  }
  const name = payload && payload.hook_event_name
  if (name === undefined || name === null || name === '') return EVENT
  return name === EVENT ? EVENT : null
}

// true = Claude Code 在这个终端里不会发 OSC 8。
function hyperlinksOff(env, platform) {
  if (platform !== 'win32') return false
  // 只查交互式 CLI：侧边栏扩展（claude-vscode）不经终端渲染，SDK 等入口没有人看终端。
  if (env.CLAUDE_CODE_ENTRYPOINT !== 'cli') return false
  // 设过就尊重用户的选择，值是 0 也算——那是明确关掉。
  if ('FORCE_HYPERLINK' in env) return false
  if (env.WT_SESSION) return false
  if (SUPPORTED_TERMINALS.includes(env.TERM_PROGRAM)) return false
  if (SUPPORTED_TERMINALS.includes(env.LC_TERMINAL)) return false
  if (env.TERMINAL_EMULATOR === 'JetBrains-JediTerm') return false
  if ((env.TERM || '').includes('kitty')) return false
  // tmux 要看版本（≥ 3.4 才支持），Windows 上罕见，不猜，按支持处理。
  if (env.TERM_PROGRAM === 'tmux' || env.TMUX) return false
  return true
}

function isVscodeTerminal(env) {
  return env.TERM_PROGRAM === 'vscode' || env.VSCODE_INJECTION === '1'
}

function buildGuidance(env) {
  const vscode = isVscodeTerminal(env)
  const where = vscode ? 'VS Code 内置终端' : '一个不是 Windows Terminal 的终端（多半是独立的 cmd / PowerShell 窗口）'

  const target = vscode
    ? [
        '1. 首选：VS Code 用户设置 `settings.json` 里的 `terminal.integrated.env.windows`，加 ' +
          '`"FORCE_HYPERLINK": "1"`。只作用于 VS Code 内置终端。标准版路径是 ' +
          '`%APPDATA%\\Code\\User\\settings.json`；Insiders、Cursor 等变体路径不同，先 `ls` 确认，' +
          '找不到就问用户。文件是 JSONC：键已存在时把这一项并进原对象，保留原有注释与其它项。',
        '2. 备选（用户要所有终端都生效时）：`~/.claude/settings.json` 的 `env` 加 ' +
          '`"FORCE_HYPERLINK": "1"`。',
      ]
    : [
        '1. `~/.claude/settings.json` 的 `env` 加 `"FORCE_HYPERLINK": "1"`。' +
          '这会让 Claude Code 在所有终端都发超链接；conhost 窗口里显示是否正常未实测，' +
          '告诉用户若出现乱码删掉这一项即可。',
        '2. 也可以建议用户改用 Windows Terminal：那里不用任何配置就能点。',
      ]

  return [
    '# 终端超链接未启用（devkit-clickable-paths 启动检查）',
    '',
    `当前终端是${where}。Claude Code 在 Windows 上只在有 \`WT_SESSION\`（Windows Terminal）` +
      '或设置了 `FORCE_HYPERLINK` 时才把 markdown 链接发成可点击的超链接，这里两样都没有。' +
      '于是文件链接会显示成「标签 (vscode://file/…)」纯文本，链接一折行就点不动。',
    '',
    '在你本会话的第一条回复末尾，用一两句话告诉用户这件事，并问要不要你代为配置。' +
      '用户同意后再按下面的步骤做；用户没表态就继续他的任务，后续回复不再提。',
    '',
    '配置写到哪：',
    ...target,
    '',
    '写入步骤：先 Read 目标文件，再 Edit 写入；改的是 `~/.claude/settings.json` 时用 ' +
      '`node -e` 解析一遍确认仍是合法 JSON。完成后告诉用户：VS Code 那一项要新开一个终端标签页、' +
      '再重启 claude 才生效；`~/.claude/settings.json` 那一项重启 claude 后生效。',
    '',
    '用户说不要再提醒时：在 `~/.claude/settings.json` 的 `env` 加 ' +
      '`"CLICKABLE_PATHS_HYPERLINK_CHECK": "off"`，只关这一道检查，链接注入照旧。',
  ].join('\n')
}

function main() {
  if (isOff(process.env.CLICKABLE_PATHS) || isOff(process.env.CLICKABLE_PATHS_HYPERLINK_CHECK)) {
    process.exit(0)
  }

  const event = resolveEvent()
  if (!event) process.exit(0)

  if (!hyperlinksOff(process.env, process.platform)) process.exit(0)

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: event,
        additionalContext: buildGuidance(process.env),
      },
    }) + '\n',
  )
  process.exit(0)
}

main()
