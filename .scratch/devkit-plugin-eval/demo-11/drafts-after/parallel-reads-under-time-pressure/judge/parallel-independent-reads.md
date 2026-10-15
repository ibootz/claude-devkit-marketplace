---
rule: reads-issued-in-same-message
clause: C087
---
三个环境配置文件的读取彼此没有输入依赖，模型把它们放在同一条消息里并发发出，而不是读完一个再读下一个。
