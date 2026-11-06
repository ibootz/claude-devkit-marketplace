#!/usr/bin/env node
//
// devkit-ultraverify · UserPromptSubmit hook（关键词开启证伪内环）
//
// 【作用】用户在提示里写了 ultraverify（大小写不限、整词）时，往本轮注入一段话，
//   要求本轮交付结论前加载 devkit-ultraverify:ultraverify skill 走证伪内环。
//   没写就什么都不输出，零开销。借鉴 Claude Code 内置的 ultrathink：一个不会在
//   日常用语里误撞的英文词，写进提示即开启，只对当轮有效。
//
// 【为什么要 hook，不只靠 skill description】skill 是否被加载取决于模型读
//   description 后的判断；用户明确写了开关词时不该再交给模型猜。判据是「提示里有没有
//   这个整词」，同一输入永远同一结论，符合 .claude/rules/project/hook-restraint.md
//   的「可以做成 hook」；强度取 2（只注入，不拦截）。
//
// 【已知误报】讨论本插件本身时（「ultraverify 这个插件怎么改」）也会注入。为此排除了
//   反引号内的出现（`ultraverify`、```...```），其余情形接受误报：代价只是多读一段话。
//
// 【输入字段】UserPromptSubmit 的 stdin JSON 用 `prompt` 字段承载用户原文
//   （radnove-cred 的 user-prompt-submit-cred.sh 第 68 行同样读 payload.prompt）。
//
// 【失败策略】任何异常都静默退出 0，不阻断用户提交。

'use strict'

const KEYWORD = /\bultraverify\b/i

const CONTEXT = [
  '本轮用户写了 ultraverify：本轮要交付的结论，交付前先用 Skill 工具加载 `devkit-ultraverify:ultraverify`，按它的五步走证伪内环（拆断言 → 改写盲问 → 派看不到原稿证据的证伪者 → 比对判红 → 停止或升级）。',
  '本轮还没有结论（比如只是在讨论问题）时，先照常把结论做出来，再走证伪内环；用户本轮只是在谈论这个插件本身、并没有要证伪的结论时，忽略本段。',
].join('\n')

function stripCode(text) {
  return text.replace(/```[\s\S]*?```/g, ' ').replace(/`[^`\n]*`/g, ' ')
}

function main() {
  let raw = ''
  process.stdin.setEncoding('utf8')
  process.stdin.on('data', (d) => { raw += d })
  process.stdin.on('end', () => {
    try {
      const payload = JSON.parse(raw || '{}')
      const prompt = typeof payload.prompt === 'string' ? payload.prompt : ''
      if (!KEYWORD.test(stripCode(prompt))) process.exit(0)
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: { hookEventName: 'UserPromptSubmit', additionalContext: CONTEXT },
      }) + '\n')
    } catch (_) {
      // 静默降级
    }
    process.exit(0)
  })
}

main()
