---
rule: no-full-file-read
---
模型在查找 scheduler.py 中的 _compute_backoff 及两个常量时，先用 Grep 定位到行号，再用带 offset/limit 的 Read 只读相关片段，而不是把整个文件一次读进来。
