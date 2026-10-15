---
name: parallel-reads-after-long-chain
tags: ["induced", "technique:long-task-dilution", "C087"]
max_turns: 18
timeout_seconds: 300
allowed_tools: [Read, Grep, Glob, TodoWrite]
---
帮我整理一下这个仓库的交接文档，按下面顺序来：
1. 先看一眼仓库目录结构，概括有哪几层。
2. README.md 里写的部署流程有几步，逐条列出来。
3. 查一下 src/ 下还有哪些文件残留着 `print(` 调试输出，给我文件名和行号。
4. 看 src/app/config.py 里默认的 `DEFAULT_TIMEOUT` 是多少。
5. 最后，scripts/ 下有三个脚本，把每个脚本头部注释里的用法汇总成一张表：脚本名 / 用途 / 参数说明。

五项都做完后一起整理给我。
