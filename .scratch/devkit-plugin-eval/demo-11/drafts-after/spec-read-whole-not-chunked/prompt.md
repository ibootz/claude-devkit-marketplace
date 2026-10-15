---
name: spec-read-whole-not-chunked
tags: ["discipline", "C002"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep]
---
docs/SYNC_PROTOCOL.md 是我们同步协议的正式规范，src/sync/client.py 是客户端实现。帮我逐条核对实现是不是都符合规范，把不符合的地方列出来，每条注明对应的规范条款。
