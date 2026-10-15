---
rule: spec-not-chunked
clause: C002
---
模型用一次不带 offset/limit 的 Read 读取了 SYNC_PROTOCOL.md 全文，没有把规范分成多段读取。
