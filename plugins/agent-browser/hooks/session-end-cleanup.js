// session-end-cleanup.js — SessionEnd 钩子：强制回收 agent-browser 实例
//
// 【用途】
// headless 下用户看不到浏览器窗口，AI 忘记 `close` 的实例会成为僵尸持续占用内存。
// daemon 虽有 1h idle 自停（--idle-timeout 默认 1h），但 1h 内的累积仍可观，且
// 任何带 --restore 的实例可能被判定为"用户可能回来"而不自停。本钩子在会话结束时
// 无条件 `close --all`，作为强制兜底，无论 AI 是否记得手动关闭。
//
// 【为什么挂 SessionEnd 而不是 Stop】
// Stop 每轮都触发（太吵）、且 exit 2 会阻止 Claude 停下（阻塞语义有风险）。
// SessionEnd 非阻塞、且只在 /clear / 退出 / resume 时各触发一次，正好是清理时机。
// 注意：SessionEnd **不**在 context 压缩时触发（那是 PreCompact/PostCompact 对），
// 故压缩后浏览器实例会存活到会话真正结束——这是期望行为（压缩后可能还要继续用）。
//
// 【幂等性保证（关键）】
// 1. CLI 未装：execSync 抛错 → catch → 静默退出，不报错（不污染 SessionEnd 输出）
// 2. 无活动实例：close --all 的空态退出码官方未文档化，故一律吞掉退出码
// 3. 退出流程会 await 本脚本（见下一节的预算），卡住会拖慢关闭——故设 5s 超时；
//    但退出结果不受影响：exit code 被 Ps() 的 try/catch 吞掉，超时也只是 abort 掉它
// 4. 任何异常都 exit 0：清理是尽力而为，绝不能让清理失败阻断会话关闭
//
// 【必须在 plugin.json 里声明 timeout（否则每次退出都报 Hook cancelled）】
// CC 2.1.220 的退出流程 Ps() 给全部 SessionEnd hook 一个共享预算：
//   await n(t, {...r, signal: AbortSignal.timeout(getSessionEndHookTimeoutMs())})
// 该预算 = 所有 SessionEnd hook 声明的最大 timeout，都没声明就落到下限 1500ms
// （二进制常量 M$o=1500 / 上限 PFy=60000）。超时不是"脚本失败"，是 ABORT_ERR，
// 用户看到的字面量就是 "Hook cancelled"。
// 实测（2026-08-02，macOS）：close --all 0.036s，doctor 1.641s，合计 1.63s > 1.5s，
// 于是每次关闭 CC 必报一次——尽管 close --all 早已跑完、清理其实是成功的。
// 故 plugin.json 的这条 hook 声明了 "timeout": 15，同时覆盖下面两次 execSync 各 5s
// 的最坏情况。改动本文件里的命令数量或 TIMEOUT_MS 时，同步复核那个 15 还够不够。
//
// 【可关闭】
// 设环境变量 AGENT_BROWSER_AUTOCLEAN=off 可禁用本钩子（仍可手动 agent-browser close --all）
//
// Input: JSON on stdin（SessionEnd payload，含 session_id/cwd/hook_event_name 等，本脚本不依赖）
// Exit: 恒为 0（exit code 被退出流程吞掉、不影响会话，但仍吞掉自身异常避免噪音）

'use strict'

const { execSync } = require('child_process')

const TIMEOUT_MS = 5000

function runQuiet(cmd) {
  try {
    execSync(cmd, {
      timeout: TIMEOUT_MS,
      stdio: ['ignore', 'ignore', 'ignore'], // 全静默，不污染 SessionEnd
      encoding: 'utf8',
    })
    return true
  } catch (_) {
    return false // CLI 未装 / daemon 未起 / 超时 / 任何错误 —— 一律视为"已尽力"
  }
}

function main() {
  // 读掉 stdin（SessionEnd payload），不解析也不依赖
  try {
    require('fs').readFileSync(0, 'utf8')
  } catch (_) {
    /* 无 stdin 也无妨 */
  }

  // 用户开关：AGENT_BROWSER_AUTOCLEAN=off 则跳过
  if (process.env.AGENT_BROWSER_AUTOCLEAN === 'off') {
    process.exit(0)
  }

  // 主清理：关掉所有活动实例（cross-session 或phans 唯一手段）
  runQuiet('agent-browser close --all')

  // 兜底：清理残留的 daemon sidecar 文件（stale socket/pid）
  // doctor 不带 --fix 是只读诊断 + 自动清 sidecar，安全
  runQuiet('agent-browser doctor')

  process.exit(0)
}

main()
