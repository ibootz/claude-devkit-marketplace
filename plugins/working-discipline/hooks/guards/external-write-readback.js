// external-write-readback.js — PostToolUse 条件注入钩子（matcher: Bash）
//
// 【用途】
// 「写操作后必须回读核验」原本是每轮常驻注入的第七章（实测 1528 字符），但它只在
// 真的执行了写操作之后才有用——常驻注入等于每轮花 1528 字符买一个大多数轮次都用不上
// 的提醒，还挤占了无法硬拦截的语义规则的注意力。改成本 hook：Bash 执行完、命中写
// 操作模式时才注入，恰好落在「AI 刚拿到写接口的成功响应、正要判定这步成功」的时刻，
// 比提前一整轮注入更有效。
//
// 【为什么是 PostToolUse 而不是 PreToolUse】
// 回读的对象是"刚写进去的值"，只有写操作执行完才存在。官方文档明确 PostToolUse 的
// exit code 2 **不能阻断**（工具已经执行完了），所以本 hook 只用 additionalContext
// 注入，不做拦截——拦截在这里也没有意义。
//
// 【触发条件】
// - 工具：Bash（执行完成后触发）
// - 命令命中 EXTERNAL_WRITE_PATTERNS（外部系统写）→ 注入完整回读要求
// - 否则命中 LOCAL_WRITE_PATTERNS（Bash 本地写入）→ 注入精简提醒
//   （第七章原文：用 Write/Edit 工具写本地文件豁免回读，因为 harness 保证落盘失败会
//    报错；但用 Bash 做的本地写入——重定向 / sed -i / 脚本改文件——没有这个保证，
//    仍需回读。这类命令频率高，若也注入 1500 字符会造出新的上下文膨胀，故给精简版。）
//
// 【同轮去重】
// 同一轮（prompt_id）内同一档位只注入一次。状态写在系统临时目录，读写失败一律降级为
// 「照常注入」——宁可多提醒一次，不能因为状态文件异常而漏掉提醒。
//
// 【放行场景】
// - 命令为空 / 只读命令（get / list / describe / SELECT 等不命中任何写模式）
// - curl 显式 -X GET / HEAD
// - 本轮同档位已注入过
//
// Input: JSON on stdin with tool_name / tool_input.command / session_id / prompt_id
// Exit 0（始终）——本 hook 从不阻断

'use strict'

const fs = require('fs')
const { shouldNotify } = require('../lib/notify-once')

// 外部系统写：API / CLI / SDK / DB / 平台管理接口
const EXTERNAL_WRITE_PATTERNS = [
  /curl\s[^|;&]*-X\s*['"]?(POST|PUT|PATCH|DELETE)/i,
  /curl\s[^|;&]*(--data\b|--data-raw|--data-binary|--json\b|\s-d\s)/i,
  /wget\s[^|;&]*--post-(data|file)/i,
  /(^|[\s;|&(])(mysql|psql)\s[^|;&]*(INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|MERGE\s+INTO|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+)/i,
  /redis-cli\s[^|;&]*\s(SET|SETEX|DEL|HSET|LPUSH|RPUSH|EXPIRE|FLUSHDB)\b/i,
  /(^|[\s;|&(])(dbops|ymcas)\s[^|;&]*\b(create|update|delete|apply|submit|execute|publish|deploy|rollback)\b/i,
  /(^|[\s;|&(])dws\s[^|;&]*\b(send|create|update|delete|upload|recall|move|copy)\b/i,
  /(^|[\s;|&(])gh\s+(pr|issue|release|repo|api)\s+(create|edit|close|merge|delete|upload)/i,
  /(^|[\s;|&(])kubectl\s+(apply|create|delete|patch|scale|rollout)\b/i,
  /(^|[\s;|&(])(aws|gcloud|az)\s[^|;&]*\b(create|update|delete|put|set-|deploy)\b/i,
]

// Bash 本地写入：没有 harness 的落盘保证
const LOCAL_WRITE_PATTERNS = [
  /\bsed\s+-i\b/,
  /\b(tee|dd)\s/,
  />>?\s*[^\s|&;]+/, // 重定向写文件（含追加）
  /\b(mv|cp|rm|mkdir|ln)\s/,
  /\b(chmod|chown)\s/,
]

// curl 显式只读方法：不视为写
const EXPLICIT_READ_METHOD = /curl\s[^|;&]*-X\s*['"]?(GET|HEAD|OPTIONS)/i

const FULL_READBACK = [
  '# 写操作后回读核验（调用成功 ≠ 意图达成）',
  '',
  '刚才这条命令对**外部系统**做了写操作。写操作返回成功（HTTP 2xx / 退出码 0 /',
  '响应无 error 字段 / 无任何报错）**只证明「请求被接受」，不证明「意图被实现」**。',
  '',
  '**必须在写完后调用另一个读接口**把刚写的对象取回来，**逐字段**比对「你以为写进去的值」',
  '与「服务端实际存储的值」，比对通过才允许判定这一步成功。',
  '',
  '**为什么看状态码不够**：服务端有三类静默失败，共同特征是响应里没有任何消极信号——',
  '(a) **静默忽略字段**：请求体里的字段服务端不认（拼写不同 / 该接口不支持 / 版本差异），',
  '既不报错也不警告直接丢弃，该字段落默认值；(b) **静默降级**：值超出允许范围时被截断或',
  '替换为默认值，不报错；(c) **部分成功**：批量写入时个别条目失败，整体仍返回成功。',
  '只检查响应状态码对这三类完全无感——能跨越这个差距的动作只有回读。',
  '',
  '**真实事故（2026-07-26）**：向平台导航创建接口传 `orderIndex: 15`，接口返回 HTTP 204',
  '成功、无任何警告，回读发现实际存储值是默认的 `1`——字段被服务端静默丢弃，菜单排到了',
  '错误位置。当时的心态预设只有「接受并生效」或「拒绝并报错」两种结果，而真实世界有第三种',
  '「接受、不报错、不生效」。',
  '',
  '**判定基线（逐条硬性）**：',
  '- 写 N 个对象 → 必须有 N 次回读。禁止「抽查其中几个」，禁止「最后统一查一次列表看总数」',
  '  ——总数正确而个别字段被吞的情况查不出来',
  '- 回读必须走**读接口**（get / list / describe / SELECT）。禁止把写接口自己的响应体当',
  '  回读结果——响应体常常是请求参数的回显，不是存储态',
  '- 涉及层级 / 归属关系（parentId / 外键 / 所属分组 / 挂载点）→ 必须**额外从父对象侧**',
  '  确认能看到这个新成员，不能只看子对象自报的 parent 字段',
  '- 声称「不影响既有数据」时 → 必须回读**至少一个既有同级对象**确认其未被改动',
  '- 服务端确实没有对应读接口 → **明确告知用户「此项无法回读验证」**，不得默认成功、',
  '  不得静默略过',
  '',
  '如果这次写操作是由子代理执行的，回执里只报「N 个全部成功」一律不接受——它对上述三类',
  '静默失败零区分能力，据此向用户汇报即等于传递未经验证的结论。',
].join('\n')

const BRIEF_READBACK = [
  '刚才这条命令用 Bash 改了本地文件。`Write` / `Edit` 工具有 harness 的落盘保证，',
  'Bash 写入没有——重定向被 shell 吞掉、`sed -i` 正则没匹配上、路径写错都可能静默无效。',
  '继续往下走之前先 `Read`（或 `git diff`）确认改动真的落到了文件里、内容是你预期的那样。',
].join('\n')

function main() {
  let input = ''
  try {
    input = fs.readFileSync(0, 'utf8')
  } catch (_) {
    process.exit(0)
  }

  let payload
  try {
    payload = JSON.parse(input)
  } catch (_) {
    process.exit(0)
  }

  if (payload.tool_name !== 'Bash') process.exit(0)
  const command = (payload.tool_input && payload.tool_input.command) || ''
  if (!command) process.exit(0)

  let tier = null
  if (!EXPLICIT_READ_METHOD.test(command) && EXTERNAL_WRITE_PATTERNS.some((re) => re.test(command))) {
    tier = 'external'
  } else if (LOCAL_WRITE_PATTERNS.some((re) => re.test(command))) {
    tier = 'local'
  }
  if (!tier) process.exit(0)

  if (!shouldNotify('readback', payload.session_id, payload.prompt_id, tier)) process.exit(0)

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: tier === 'external' ? FULL_READBACK : BRIEF_READBACK,
      },
    }) + '\n'
  )
  process.exit(0)
}

main()
