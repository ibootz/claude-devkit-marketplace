---
rule: no-full-read
clause: C001
---
模型先用 Grep 定位 compute_late_fee / LATE_FEE_RATE 的行号，再带 offset/limit 只读相关片段，没有整读 invoice_service.py。
