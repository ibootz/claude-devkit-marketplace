// portable-shell-lint.js — PostToolUse hook
// 目的：当 AI 通过 Write/Edit/MultiEdit 生成 shell 脚本时，扫描其中在
//       Linux(GNU coreutils) 与 macOS(BSD userland + 默认 bash 3.2) 之间
//       不可移植的写法；命中即通过「stderr + exit 2」把违规点与可移植改法
//       回灌给 Claude，促其立即修正，从而确保脚本同时兼容 Linux 与 macOS。
//
// Trigger: PostToolUse（matcher: Write|Edit|MultiEdit）
// 反馈机理: 退出码 2 时 stderr 被喂回给 Claude（文件已写入，不回滚，仅促修正）
// Opt-out: 环境变量 PORTABLE_SHELL_LINT=off（或 0 / false）时跳过检查
//
// 本 hook 只读取被写入的脚本文本做静态扫描，不修改任何用户文件，无副作用。

'use strict'

const fs = require('fs')

// ── 读取 hook 从 stdin 传入的事件 JSON ─────────────────────────────
function readEvent() {
  try {
    const raw = fs.readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return {}
    return JSON.parse(raw)
  } catch (e) {
    return {}
  }
}

// ── 从不同工具的 tool_input 中提取「被写入的文本」与「目标文件路径」──
function extractWrite(event) {
  const tool = event && event.tool_name
  const input = (event && event.tool_input) || {}
  const filePath = input.file_path || input.filePath || ''

  let text = ''
  if (tool === 'Write') {
    text = input.content || ''
  } else if (tool === 'Edit') {
    text = input.new_string || ''
  } else if (tool === 'MultiEdit') {
    const edits = Array.isArray(input.edits) ? input.edits : []
    text = edits.map((e) => (e && e.new_string) || '').join('\n')
  } else {
    return null // 非文件写入类工具，不处理
  }
  return { filePath, text }
}

// ── 判定被写入的是否为 shell 脚本 ──────────────────────────────────
function isShellScript(filePath, text) {
  if (/\.(sh|bash|zsh|ksh)$/i.test(filePath)) return true
  // 无扩展名但首行是 shell shebang（如 #!/bin/bash、#!/usr/bin/env sh）
  const firstLine = (text || '').split('\n', 1)[0] || ''
  if (/^#!.*\b(ba|z|k)?sh\b/.test(firstLine)) return true
  return false
}

// ── 不可移植写法规则表 ─────────────────────────────────────────────
// sev: high=几乎必坏 / med=版本或环境相关 / low=建议改进
// re : 在「单行、去掉整行注释后」的文本上匹配
const RULES = [
  {
    id: 'sed-i',
    sev: 'high',
    re: /\bsed\b[^|;&\n]*?-i(?=$|\s|['"])/,
    title: "sed -i 原地编辑：GNU 需 `-i`，BSD(macOS) 需 `-i ''`，两者语义冲突",
    fix: '用带后缀再删除的写法（两端通用）：`sed -i.bak \'s/a/b/\' f && rm -f f.bak`；或写临时文件：`sed \'s/a/b/\' f > "$tmp" && mv "$tmp" f`',
  },
  {
    id: 'readlink-f',
    sev: 'high',
    re: /\breadlink\s+-\w*f\b/,
    title: 'readlink -f：macOS 默认无此选项',
    fix: '用可移植函数或 `python3 -c "import os,sys;print(os.path.realpath(sys.argv[1]))" "$p"`；仅需目录可 `cd "$(dirname "$p")" && pwd`',
  },
  {
    id: 'realpath',
    sev: 'low',
    re: /\brealpath\b/,
    title: 'realpath：macOS 默认未安装（属 GNU coreutils）',
    fix: '同上，用 python3 或 `cd ... && pwd` 组合替代；或先检测 `command -v realpath`',
  },
  {
    id: 'date-d',
    sev: 'high',
    re: /\bdate\b[^|;&\n]*?(\s-d\b|--date\b)/,
    title: 'date -d/--date：GNU 专有，macOS 用 `date -v` 或 `-j -f`',
    fix: '按平台分支：`case "$(uname -s)" in Darwin) date -v-1d ;; *) date -d "1 day ago" ;; esac`',
  },
  {
    id: 'find-printf',
    sev: 'high',
    re: /\bfind\b[^|;&\n]*?-printf\b/,
    title: 'find -printf：GNU 专有，macOS(BSD find) 不支持',
    fix: '改用 `-exec` + `stat`/`printf`，或 `find ... -print0 | xargs -0 ...` 组合',
  },
  {
    id: 'grep-P',
    sev: 'high',
    re: /\bgrep\b[^|;&\n]*?(\s-\w*P\b|--perl-regexp\b)/,
    title: 'grep -P（Perl 正则）：macOS(BSD grep) 不支持',
    fix: '改用 `grep -E`(扩展正则) 重写模式；确需 PCRE 时用 `perl -ne` 或 `ripgrep`',
  },
  {
    id: 'stat-c',
    sev: 'high',
    re: /\bstat\b[^|;&\n]*?(\s-c\b|--format\b|--printf\b)/,
    title: 'stat -c/--format：GNU 格式，macOS 用 `stat -f`',
    fix: '按平台分支：`case "$(uname -s)" in Darwin) stat -f%z f ;; *) stat -c%s f ;; esac`',
  },
  {
    id: 'declare-A',
    sev: 'high',
    re: /\bdeclare\s+-\w*A\b/,
    title: 'declare -A（关联数组）：需 bash 4+，macOS 默认 bash 仅 3.2',
    fix: '改用普通数组 + 索引，或在脚本头要求 `#!/usr/bin/env bash` 并校验 `((BASH_VERSINFO[0]>=4))` 后给出提示',
  },
  {
    id: 'mapfile',
    sev: 'high',
    re: /\b(mapfile|readarray)\b/,
    title: 'mapfile/readarray：需 bash 4+，macOS 默认 bash 3.2 无此内建',
    fix: '改用 `while IFS= read -r line; do arr+=("$line"); done < file` 逐行读入',
  },
  {
    id: 'param-case',
    sev: 'med',
    re: /\$\{[#!]?[A-Za-z_][A-Za-z0-9_\[\]]*(\^\^|,,)/,
    title: '${var^^} / ${var,,} 大小写转换：bash 4+ 特性，macOS 默认 bash 3.2 不支持',
    fix: '改用 `tr \'[:lower:]\' \'[:upper:]\'`（或反向）做大小写转换',
  },
  {
    id: 'echo-e',
    sev: 'low',
    re: /\becho\s+-e\b/,
    title: 'echo -e：在 /bin/sh(dash) 与不同 shell 下对转义符处理不一致',
    fix: '改用 `printf \'%s\\n\' ...` 输出，转义行为跨平台一致',
  },
  {
    id: 'xargs-r',
    sev: 'low',
    re: /\bxargs\b[^|;&\n]*?(\s-\w*r\b|--no-run-if-empty\b)/,
    title: 'xargs -r/--no-run-if-empty：GNU 专有；BSD(macOS) xargs 无此选项',
    fix: 'macOS xargs 在输入为空时本就不执行，直接去掉 `-r`；如需完全一致可先判空',
  },
  {
    id: 'mktemp-notmpl',
    sev: 'med',
    re: /\bmktemp\b(?![^|;&\n]*XXX)/,
    title: 'mktemp 未带 XXXXXX 模板：GNU 可省略、BSD(macOS) 通常报错',
    fix: '显式给模板并指定目录（两端通用）：`mktemp "${TMPDIR:-/tmp}/name.XXXXXX"`（目录用 `-d`）',
  },
]

// ── 扫描文本，返回命中 findings ────────────────────────────────────
function scan(text) {
  const lines = (text || '').split('\n')
  const findings = []
  const seen = new Set()

  lines.forEach((rawLine, idx) => {
    // 跳过整行注释与 shebang（不执行，无移植性风险），减少误报
    if (/^\s*#/.test(rawLine)) return
    const line = rawLine
    for (const rule of RULES) {
      if (rule.re.test(line)) {
        const snippet = line.trim().slice(0, 120)
        const key = rule.id + '|' + snippet
        if (seen.has(key)) continue
        seen.add(key)
        findings.push({
          sev: rule.sev,
          title: rule.title,
          fix: rule.fix,
          lineNo: idx + 1,
          snippet,
        })
      }
    }
  })
  return findings
}

// ── 组装回灌给 Claude 的报告文本 ───────────────────────────────────
const SEV_LABEL = { high: '高', med: '中', low: '低' }
const SEV_ORDER = { high: 0, med: 1, low: 2 }

function buildReport(filePath, findings) {
  findings.sort((a, b) => SEV_ORDER[a.sev] - SEV_ORDER[b.sev] || a.lineNo - b.lineNo)
  const head =
    '[portable-shell] 检测到可能在 Linux 或 macOS 上不可移植的 shell 写法，请修正后再交付' +
    '（本插件要求生成的脚本同时兼容 Linux 与 macOS）。\n' +
    '目标文件：' + (filePath || '(未知)') + '\n'

  const body = findings
    .map((f) => {
      return (
        `【${SEV_LABEL[f.sev]}】${f.title}\n` +
        `  ↳ 第 ${f.lineNo} 行命中：${f.snippet}\n` +
        `  ↳ 可移植改法：${f.fix}`
      )
    })
    .join('\n\n')

  const tail =
    '\n\n若确需使用某平台专有特性，请在脚本内用 ' +
    '`case "$(uname -s)" in Darwin) ... ;; Linux) ... ;; esac` 分支处理并显式说明原因。\n' +
    '关闭本检查：设置环境变量 PORTABLE_SHELL_LINT=off。'

  return head + '\n' + body + tail
}

// ── 主流程 ─────────────────────────────────────────────────────────
function main() {
  const flag = (process.env.PORTABLE_SHELL_LINT || '').toLowerCase()
  if (flag === 'off' || flag === '0' || flag === 'false') process.exit(0)

  const event = readEvent()
  const w = extractWrite(event)
  if (!w) process.exit(0)
  if (!isShellScript(w.filePath, w.text)) process.exit(0)

  const findings = scan(w.text)
  if (findings.length === 0) process.exit(0)

  // 命中：写 stderr + exit 2，反馈被喂回给 Claude 促其修正
  process.stderr.write(buildReport(w.filePath, findings) + '\n')
  process.exit(2)
}

main()
