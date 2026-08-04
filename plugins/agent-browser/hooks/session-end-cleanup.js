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
// 【本脚本必须在 1.5s 内退出，且 plugin.json 的 timeout 帮不上忙】
// CC 2.1.220 的退出流程 Ps() 给全部 SessionEnd hook 一个共享预算：
//   await n(t, {...r, signal: AbortSignal.timeout(getSessionEndHookTimeoutMs())})
// 超时不是"脚本失败"，是 ABORT_ERR，用户看到的字面量就是 "Hook cancelled"。
//
// 该预算的计算函数（二进制里的 kcn）**只扫两处来源，都不含插件清单**：
//   function kcn(){let e=Z.CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS;if(e!==void 0&&e>0)return e;
//     let t=0,r=J0()?[]:Wne()?.SessionEnd??[],n=[...Fie()?.SessionEnd??[],...r];
//     for(let o of n)for(let i of o.hooks)if(i.timeout&&i.timeout*1000>t)t=i.timeout*1000;
//     return Math.max(M$o,Math.min(t,PFy))}          // M$o=1500 下限 / PFy=60000 上限
// Fie() 取 initialHooksConfig ← pas() ← us().hooks（settings.json 合并结果）；
// Wne() 取 mainThreadAgentHooks。**plugin.json 里声明的 timeout 两处都读不到**，
// 于是 t=0、预算恒为下限 1500ms。1.1.1 曾据"声明 timeout: 15 即可"修过一次，
// 那个前提是错的——15 一直没生效，每次退出照样报 Hook cancelled。
// 1.1.3 已把 plugin.json 里那条死配置删掉，别再往回加：读不到的字段留着只会让下一个
// 人以为预算被抬高了。真要抬高只有 settings.json 那条 env（见本段末）。
//
// 实测（2026-08-02 / 2026-08-04 复测，macOS，CC 2.1.220）：
//   close --all 0.036s，doctor 1.6s，两条同步跑合计 1.69s > 1.5s → 必报。
// 故 1.1.2 起 doctor 改为 detached spawn 后台放飞（见 runDetached），本脚本
// 同步部分只剩 close --all，实测总耗时 < 0.1s，远低于 1.5s 下限。
//
// 改动本文件时守住这条：**同步执行的命令总耗时必须 < 1.5s**。新增耗时命令一律
// 走 runDetached，不要靠调 plugin.json 的 timeout 或 TIMEOUT_MS 解决——前者无效，
// 后者只管单条 execSync 自己的上限、管不了共享预算。
// （另一条出路是在 settings.json 的 env 里设 CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS，
//   见 kcn 首行；但那要每台机各配一次，插件侧不该依赖它。）
//
// 【可关闭】
// 设环境变量 AGENT_BROWSER_AUTOCLEAN=off 可禁用本钩子（仍可手动 agent-browser close --all）
//
// Input: JSON on stdin（SessionEnd payload，含 session_id/cwd/hook_event_name 等，本脚本不依赖）
// Exit: 恒为 0（exit code 被退出流程吞掉、不影响会话，但仍吞掉自身异常避免噪音）

'use strict'

const { execSync, spawn } = require('child_process')

const TIMEOUT_MS = 5000

// 同步执行：只给必须在本脚本退出前完成的命令用（当前仅 close --all，0.036s）
function runQuiet(cmd, args) {
  try {
    execSync([cmd, ...args].join(' '), {
      timeout: TIMEOUT_MS,
      stdio: ['ignore', 'ignore', 'ignore'], // 全静默，不污染 SessionEnd
      encoding: 'utf8',
    })
    return true
  } catch (_) {
    return false // CLI 未装 / daemon 未起 / 超时 / 任何错误 —— 一律视为"已尽力"
  }
}

// 后台放飞：脱离本进程继续跑，本脚本立刻退出，不占共享预算的 1.5s
// detached + unref 让子进程改属 init（PPID=1）而非等本进程；stdio 全 ignore
// 避免它持有本进程的管道（持有则父进程 exit 后 CC 仍可能等 fd 关闭）。
// 代价：拿不到结果、失败无从得知——所以只放"失败也无所谓"的收尾命令。
function runDetached(cmd, args) {
  try {
    const child = spawn(cmd, args, {
      detached: true,
      stdio: 'ignore',
    })
    child.on('error', () => {}) // CLI 未装时 spawn 异步抛 ENOENT，不接会打到 stderr
    child.unref()
    return true
  } catch (_) {
    return false
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

  // 主清理：关掉所有活动实例（cross-session orphans 唯一手段）
  // 同步执行——这是本钩子的核心目的，必须在退出前落地。实测 0.036s
  runQuiet('agent-browser', ['close', '--all'])

  // 兜底：清理残留的 daemon sidecar 文件（stale socket/pid）
  // doctor 不带 --fix 是只读诊断 + 自动清 sidecar，安全
  // 后台放飞——实测 1.6s，同步跑会撞破 1.5s 共享预算报 Hook cancelled（见文件头）
  runDetached('agent-browser', ['doctor'])

  process.exit(0)
}

main()
