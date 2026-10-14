#!/usr/bin/env python3
"""给一份提问 markdown 数几样客观指标，供揭盲页并列展示。只数，不打分。

用法：python3 metrics.py <message.md> [...]   → 每个文件输出一行 JSON
"""
import json
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"原文未给|原文无|未给出")
TAG = re.compile(r"^\s*\[(要拍板|要信息|要授权)\]")
QHEAD = re.compile(r"^#\s*Q\d+")


def prose_lines(lines: list[str]) -> list[str]:
    """正文行：去掉代码块内部、表格行、标题行、分隔线与空行。"""
    out, in_code = [], False
    for l in lines:
        if l.lstrip().startswith("```"):
            in_code = not in_code
            continue
        s = l.strip()
        if in_code or not s or s.startswith(("|", "#")) or re.fullmatch(r"-{3,}", s):
            continue
        out.append(s)
    return out


def visible_len(s: str) -> int:
    """按读者看到的字数算：去掉链接目标、反引号、加粗星号。"""
    s = re.sub(r"\]\([^)]*\)", "]", s)
    return len(re.sub(r"[`*\[\]]", "", s))


def measure(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    nonblank = [l for l in lines if l.strip()]
    first_q = next((i + 1 for i, l in enumerate(lines) if QHEAD.match(l)), None)
    prose = prose_lines(lines)
    widths = [visible_len(l) for l in prose]
    sentences = [x for l in prose for x in re.split(r"(?<=[。？！])", l) if x.strip()]
    sent_lens = [visible_len(x) for x in sentences]
    return {
        "file": str(path),
        "行数": len(lines),
        "字数": len(re.sub(r"\s", "", text)),
        "首个问题所在行": first_q,
        "问题数": sum(1 for l in lines if QHEAD.match(l)),
        "首行带类型标签": bool(nonblank and TAG.match(nonblank[0])),
        "表格数": len(re.findall(r"^\|[\s:-]+\|", text, re.M)),
        "代码块数": text.count("```") // 2,
        "占位词数": len(PLACEHOLDER.findall(text)),
        "正文行平均字数": round(sum(widths) / len(widths), 1) if widths else 0,
        "正文行超30字占比": f"{100 * sum(w > 30 for w in widths) // max(len(widths), 1)}%",
        "平均句长": round(sum(sent_lens) / len(sent_lens), 1) if sent_lens else 0,
        "最长句字数": max(sent_lens, default=0),
        "超40字句数": sum(n > 40 for n in sent_lens),
        "加粗处数": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "分隔线数": sum(1 for l in lines if re.fullmatch(r"\s*-{3,}\s*", l)),
    }


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(measure(Path(p)), ensure_ascii=False))
