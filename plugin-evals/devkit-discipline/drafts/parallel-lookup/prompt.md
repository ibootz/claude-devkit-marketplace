---
name: parallel-lookup
tags: ["discipline"]
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep]
---
当前目录下有三个子目录 billing、auth、report，各有一个同名的 .py 文件（billing/billing.py、auth/auth.py、report/report.py）。请把这三个文件都完整读一遍，分别用一句话概括每个文件做什么，并给出其中常量的值。
