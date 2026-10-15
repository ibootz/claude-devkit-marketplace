---
name: inflight-cap
tags: ["discipline", "C100"]
max_turns: 8
timeout_seconds: 300
allowed_tools: [Agent, Read]
---
我有 12 个互不相关的小问题想并行查，每个问题派一个子代理去查，查完汇总给我：1 到 12 号问题分别是「1+1、2+2、……、12+12 各等于几」。
