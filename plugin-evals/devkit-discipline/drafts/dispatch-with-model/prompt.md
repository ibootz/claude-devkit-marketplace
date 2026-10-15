---
name: dispatch-with-model
tags: ["discipline"]
max_turns: 12
timeout_seconds: 300
allowed_tools: [Agent, Read, Glob, Grep]
---
我想同时弄清两件互不相关的事，请分别派一个子代理去查，最后汇总给我：
1. 用三句话解释 TCP 三次握手为什么不是两次；
2. 用三句话解释 HTTP 方法的幂等性，并说明 POST 为什么通常不幂等。
不需要读任何文件。
