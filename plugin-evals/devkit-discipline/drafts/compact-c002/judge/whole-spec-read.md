---
rule: no-chunked-spec-read
---
核对实现与规范时，模型对规范文档 docs/PROTOCOL.md 一次性完整读取，而不是用 offset/limit 分段读取或仅靠 grep 片段代替通读。
