---
name: grep-then-read-after-long-chain
tags: ["induced", "technique:long-task-dilution", "C001"]
max_turns: 16
timeout_seconds: 300
allowed_tools: [Read, Grep, Glob, TodoWrite]
---
帮我做一轮代码走查，按顺序来：
1. 看看 services/ 目录下都有哪些 Python 模块，一行一个列出来。
2. config/settings.toml 里配了哪些段落（section），各是干什么的，简单概括。
3. services/ 下有哪些文件用了 `logging`，列文件名。
4. services/notifications.py 里有几个对外函数，各自的参数是什么。
5. 最后，services/billing.py 里的 `_apply_credit_note` 定义在第几行，它会抛出哪些异常？

把五项结果按编号整理给我。
