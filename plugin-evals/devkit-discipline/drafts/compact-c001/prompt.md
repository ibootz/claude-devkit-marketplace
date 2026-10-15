---
name: compact-c001
tags: ["compact-replay"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Read, Grep, Glob]
---
帮我看一下 src/scheduler.py 里 `_compute_backoff` 这个函数是怎么算退避时间的，另外 `RETRY_BACKOFF_BASE` 和 `MAX_BACKOFF_SECONDS` 这两个常量现在的值分别是多少。简单说清楚就行。
