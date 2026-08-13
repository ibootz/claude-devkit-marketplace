#!/usr/bin/env node
'use strict';
// token-saver hook：运行时提醒 AI 节用 token。
// 纯注入：SessionStart 注入 5 行核心纪律；PreToolUse(Read) 整读大文件时软提醒先定位行号。
// 恒 exit 0（零硬拦）。关闭：TOKEN_SAVER=off
//
// 设计依据（hook-restraint 规则）：
//   - SessionStart 纯注入不受判据严格性约束（不阻止任何操作，失败模式仅多占上下文预算）。
//   - PreToolUse 判据取 fs.statSync().size（确定字段，非猜语义）：仅 >100KB 且无 offset/limit
//     的整读触发，文本极短。低频 + 极短 = 提醒自身不沦为 token 负担（省 token 第一性）。
//   - hookSpecificOutput.hookEventName 用入参 event 变量回声，与 hook_event_name 一致，
//     写死任一个会让另一路静默失效。

const fs = require('fs');

const SESSION_PROMPT = [
  '# token 节用（frugal）',
  '读前先 grep 定位行号，再定点 Read（offset/limit），免整读大文件。',
  '大输出命令先收窄（head/wc/grep）。独立操作并发，勿串行。',
  'verbose 输出交子代理，主上下文仅留摘要。模型档位匹配任务难度。',
  '长会话及时 /compact。详：references/principles.md'
].join('\n');

const BIG_FILE_BYTES = 100 * 1024; // 整读阈值：超此且无 offset/limit 则提醒

function emit(event, payload) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: Object.assign({ hookEventName: event }, payload)
  }));
  process.exit(0);
}

function readPayload() {
  try { return JSON.parse(fs.readFileSync(0, 'utf8')); }
  catch (_) { return null; }
}

function handleRead(payload, event) {
  if (payload.tool_name !== 'Read') process.exit(0);
  const input = payload.tool_input || {};
  if (input.offset != null || input.limit != null) process.exit(0); // 已收窄
  const filePath = input.file_path;
  if (!filePath || typeof filePath !== 'string') process.exit(0);
  let size;
  try { size = fs.statSync(filePath).size; }
  catch (_) { process.exit(0); } // 不可 stat（不存在/远程/权限）→ 不判
  if (size < BIG_FILE_BYTES) process.exit(0);
  const kb = Math.round(size / 1024);
  emit(event, {
    additionalContext:
      '此文件约 ' + kb + ' KB，整读将占大量 context。先 grep -n 定位行号，' +
      '再 Read 带 offset/limit 只读必要段。详 references/principles.md §读前定位。'
  });
}

function main() {
  if (process.env.TOKEN_SAVER === 'off') process.exit(0);
  const payload = readPayload();
  if (!payload) process.exit(0);
  const event = payload.hook_event_name;
  if (event === 'SessionStart') return emit(event, { additionalContext: SESSION_PROMPT });
  if (event === 'PreToolUse') return handleRead(payload, event);
  process.exit(0);
}

main();
