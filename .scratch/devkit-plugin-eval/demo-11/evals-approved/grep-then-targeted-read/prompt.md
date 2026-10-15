---
name: grep-then-targeted-read
tags: ["discipline", "C001", "baseline-satisfied"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep]
---
src/billing 目录下有个 compute_late_fee 函数，帮我看一下它定义在哪个文件的第几行，滞纳金费率用的是哪个常量、常量的值是多少。
