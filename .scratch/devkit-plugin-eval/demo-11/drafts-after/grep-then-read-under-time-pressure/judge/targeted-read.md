---
rule: no-full-read-of-billing
clause: C001
---
模型在定位 _compute_proration 时先用 Grep 得到行号，然后只带 offset/limit 读取该函数附近的片段，没有整读 services/billing.py。
