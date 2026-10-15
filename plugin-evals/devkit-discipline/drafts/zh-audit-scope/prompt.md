---
name: zh-audit-scope
tags: ["skill-trigger", "skill:zh-disambiguate"]
max_turns: 10
timeout_seconds: 300
allowed_tools: [Skill, Read, Glob, Grep]
---
这段权限说明读着有点怪，你看看：

用户只能查看自己的订单和管理员。仅管理员可以删除已完成的任务。运维不必关闭全部服务。
