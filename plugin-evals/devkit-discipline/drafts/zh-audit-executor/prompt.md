---
name: zh-audit-executor
tags: ["skill-trigger", "skill:zh-disambiguate"]
max_turns: 10
timeout_seconds: 300
allowed_tools: [Skill, Read, Glob, Grep]
---
帮我查一下这段接口说明有没有歧义：

本系统包含客户端、网关和后端服务。收到请求后，验证令牌，再返回结果。验证失败或超时后重试。
