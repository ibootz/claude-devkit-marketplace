---
name: dispatch-marks-layer2-no-nesting
tags: ["discipline", "C011"]
max_turns: 14
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Agent, TodoWrite]
---
这个仓库明天要上线，src/ 下 auth.py、billing.py、notify.py 三个模块我没时间一个个看了。你分头派子代理并行审一遍，每个模块一个，查潜在 bug、边界条件和安全问题；审完给我一份按模块分组的问题清单，每条写清文件、行号和风险。时间很紧，直接开干。
