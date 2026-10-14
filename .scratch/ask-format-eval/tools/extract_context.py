#!/usr/bin/env python3
"""从 Claude Code 会话 jsonl 里截出「某条消息之前」的会话记录，作为生成子代理的上下文。

用法：python3 extract_context.py <session.jsonl> <marker_line> <out.md> [budget_chars]

- marker_line：那条待重写的助手消息在 jsonl 里的行号（1 起算）。该行本身不收。
- 从 marker 前一行往回收，直到字数预算用完（默认 120000 字符），再按时间正序写出。
- 剥掉 <system-reminder> 块：里面是 hook 注入的规则，评测要由两组各自给规则，不能混进旧规则。
- 跳过子代理侧链（isSidechain）；工具入参截 400 字、工具结果截 2000 字。
"""
import json
import re
import sys
from pathlib import Path

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def clip(s: str, n: int) -> str:
    s = REMINDER.sub("", s).strip()
    return s if len(s) <= n else s[:n] + f"\n…（截断，原长 {len(s)} 字）"


def render(obj: dict) -> str:
    if obj.get("isSidechain") or obj.get("type") not in ("user", "assistant"):
        return ""
    msg = obj.get("message") or {}
    content = msg.get("content")
    role = "用户" if obj["type"] == "user" else "助手"
    if obj.get("isCompactSummary"):
        role = "会话压缩摘要"
    parts = []
    if isinstance(content, str):
        t = clip(content, 20000)
        if t:
            parts.append(f"### {role}\n{t}")
    elif isinstance(content, list):
        for b in content:
            kind = b.get("type")
            if kind == "text":
                t = clip(b.get("text", ""), 20000)
                if t:
                    parts.append(f"### {role}\n{t}")
            elif kind == "tool_use":
                arg = json.dumps(b.get("input", {}), ensure_ascii=False)
                parts.append(f"### 助手调用工具 {b.get('name')}\n{clip(arg, 400)}")
            elif kind == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if x.get("type") == "text")
                t = clip(str(c or ""), 2000)
                if t:
                    parts.append(f"### 工具结果\n{t}")
    return "\n\n".join(parts)


def main() -> None:
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    src, marker, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    budget = int(sys.argv[4]) if len(sys.argv) == 5 else 120000
    lines = src.read_text(encoding="utf-8").splitlines()
    picked, used = [], 0
    for raw in reversed(lines[: marker - 1]):
        try:
            block = render(json.loads(raw))
        except json.JSONDecodeError:
            continue
        if not block:
            continue
        if used + len(block) > budget:
            break
        picked.append(block)
        used += len(block)
    picked.reverse()
    head = f"# 会话记录（截至待提问时刻，共 {len(picked)} 段、{used} 字；更早的内容因篇幅未收）\n\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + "\n\n".join(picked) + "\n", encoding="utf-8")
    print(out, len(picked), used)


if __name__ == "__main__":
    main()
