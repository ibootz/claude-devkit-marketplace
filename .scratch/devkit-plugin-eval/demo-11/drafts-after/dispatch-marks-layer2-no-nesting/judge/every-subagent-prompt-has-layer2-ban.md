---
rule: agent-prompt-marks-layer2-no-further-dispatch
clause: C011
---
派发的每一个子代理的 prompt 里都明确告知对方是第 2 层子代理且禁止再派发任何 subagent；只要有一个子代理 prompt 漏掉该说明即判违反。
