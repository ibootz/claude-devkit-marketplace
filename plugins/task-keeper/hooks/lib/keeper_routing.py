#!/usr/bin/env python3
"""主会话三岔口路由注入（SessionStart）

纯注入，零拦截——分诊是语义判断，按 hook 克制原则只能做软约束。
opt-in 分档判据是 `.keeper/` 目录存在性（从 cwd 向上找，到 .git 止）：
  · 未启用：≤300 字符的一句话介绍 + 启用方式。
  · 已启用：完整三岔口 + 决策打包摘要 + 指针，目标 ≤1600、硬上限 2000（H18 断言）。

注意不能用 `python3 - <<'EOF'` 内联写法：heredoc 会占用 stdin，SessionStart 的
事件 JSON（含 cwd）就读不到了——2026-07-31 实测踩过，遂独立成文件。
"""
import json
import os
import sys
from pathlib import Path

NOT_ENABLED = (
    "task-keeper 未在本项目启用（无 .keeper/ 目录）。启用后可把 bug 转常驻 "
    "debug-keeper、杂务转 chore-keeper 托管，主会话只做分诊转发。启用："
    "`mkdir -p .keeper/debug/issues`（debug 队列）或 "
    "`mkdir -p .keeper/chore/items`（杂务队列）。")

ENABLED = """# task-keeper 主会话路由（三岔口分诊）

每收到一条用户消息，先分诊再动手（分错代价小，不要为分类反问用户）：

1. **即时同步做**：用户当前主线任务本身、几句话能答的问题、需要你上下文的事 → 你自己做。
2. **转已有体系**：bug / 报错 / 异常行为 → 逐字转发给 debug-keeper（tk-debug skill，首次 Agent 派出、之后 SendMessage 唤醒）；属于项目既有交付流程的活 → 走该流程。
3. **转 keeper 攒批**：台账 / 沉淀 / 收尾 / 外部系统小操作等杂务 → 逐字转发给 chore-keeper（tk-chore skill）。

转发三原则：**逐字**（不改写用户原话）、**即回**（转完回原任务，不追问 keeper 进度）、**不越位**（.keeper/ 队列文件的写者是 keeper，你只读）。

## 决策打包（主会话侧职责）

keeper 需要 Human 拍板时会写 `.keeper/decisions/<stamp>-<keeper>.md` 并 SendMessage 打铃。你的动作：**攒批**（待拍板 ≥3 条 / 出现 blocking / 用户问起 / 停顿点，四触发点命中才处理），一次 AskUserQuestion 把多条并列问完（必须用工具本体，禁止文本选项块——手机推送只认工具调用），答复**原文**写 `.keeper/decisions/answers/<同名>.md` 并 SendMessage 通知对应 keeper。每轮注入的「待拍板 N 条」计数由磁盘现算，比你的记忆可靠。

指针：协议正典 skills/tk-decisions；队列状态看每轮注入或 .keeper/*/index.md（薄索引，按需开单条正文）。"""


def find_keeper_root(start):
    try:
        cur = Path(start).resolve()
    except Exception:
        return None
    for _ in range(30):
        try:
            if (cur / ".keeper").is_dir():
                return cur / ".keeper"
            if (cur / ".git").exists():
                return None
        except OSError:
            return None
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        ev = {}
    cwd = ev.get("cwd") or os.getcwd()
    text = ENABLED if find_keeper_root(cwd) else NOT_ENABLED
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 注入类 hook 静默降级
