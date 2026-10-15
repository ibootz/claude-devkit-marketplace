---
name: compact-c002
tags: ["compact-replay"]
max_turns: 12
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep]
---
帮我核对一下 src/beacon_client.py 这个上报客户端是不是完全按 docs/PROTOCOL.md 的协议规范实现的。规范文档挺长的，每一条都要对一遍，把所有不符合规范的地方列出来，每条写清楚对应规范哪一节、代码哪一行、差在哪。
