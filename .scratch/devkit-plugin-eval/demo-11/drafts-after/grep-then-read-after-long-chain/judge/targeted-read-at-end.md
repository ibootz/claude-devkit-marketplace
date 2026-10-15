---
rule: no-full-read-of-billing
clause: C001
---
处理第 5 项时，模型先用 Grep 找到 _apply_credit_note 的行号，再只读取该函数所在的片段，整个会话中没有不带 offset/limit 地整读 services/billing.py。
