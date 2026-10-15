---
name: zh-rewrite-keeps-meaning
tags: ["skill-trigger", "skill:zh-disambiguate"]
max_turns: 10
timeout_seconds: 300
allowed_tools: [Skill, Read, Glob, Grep]
---
把这段排障结论改得简洁一点：

从日志看，可能是令牌过期，也可能是权限不足，通常前者更常见。服务更新配置。
