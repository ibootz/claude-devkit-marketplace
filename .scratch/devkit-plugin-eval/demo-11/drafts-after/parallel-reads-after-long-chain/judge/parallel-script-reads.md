---
rule: script-reads-in-same-message
clause: C087
---
第 5 项中三个脚本的读取彼此没有依赖，模型把它们放在同一条消息里并发发出，而不是逐个串行读取。
