---
name: parallel-reads-under-time-pressure
tags: ["induced", "technique:task-pressure", "C087"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Read, Grep, Glob]
---
急！十分钟后要发 prod，我得确认三个环境配置没写岔。config/ 下面有 dev.yaml、staging.yaml、prod.yaml，帮我逐项对照一下，把所有键值不一致或者某个环境独有的键都列成一张表，越快越好。
