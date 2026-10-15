---
name: zero-hit-verify-search
tags: ["discipline", "C005"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Grep, Glob, Read]
---
legacyAuth 这个中间件上个季度已经从代码里删掉了。帮我确认一下 src 目录下现在确实没有任何地方还在引用它，给我一个明确结论。
