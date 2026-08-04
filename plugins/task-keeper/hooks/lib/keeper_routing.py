#!/usr/bin/env python3
"""主会话路由注入（分两层：三岔口每轮注入 / 静态参考 SessionStart 注入）

纯注入，零拦截——分诊是语义判断，按 hook 克制原则只能做软约束。

## 为什么分两层（2026-08-01 改）

原先整块只在 `SessionStart` 注入一次。实测遵循度不够：AI 在会话中段收到 bug
报告时会直接自己修、收到杂务时会直接自己做，把「先分诊」整条跳过。成因不是它
没读到，而是**分诊这条规则与 system prompt 的默认行为直接对立**——base 指令是
「有足够信息就动手」，而分诊要求的恰恰是「先别动手，判归属」。会话开头读过一次
的软约束，压不过每轮都在生效的 base 指令。

所以按本仓 `hook-injection-layering` 的分层判据切开：

  · **对抗 system prompt 的段落 → 每轮注入**（`UserPromptSubmit`）：三岔口本身
    + 转发三原则 + 一句反合理化。它必须与 base 指令同频出现才有效。
  · **静态参考 → 留 SessionStart**：决策打包协议、v4 布局、指针。这些是「需要
    时去查」的内容，不与任何默认行为对立，每轮重复只是白烧 token。

两层文本**刻意不重叠**：SessionStart 那份不再复述三岔口，只留一句指明它每轮注入，
避免同一会话里同一段规则出现两遍。

## opt-in 分档

判据是 `.keeper/` 目录存在性（**v4 起由 `keeper_paths` 解析：先跳出 submodule、
fixer worktree 回溯到 delivery、再取当前 worktree 根**。v3 那份「向上找、遇 `.git`
停」的本地实现已删——linked worktree 根自己就有 `.git` 文件，第一轮就返回 None，
交付跑在 worktree 里时这里会误判成「未启用」注入启用引导，成因见 `keeper_paths.py`
模块头）：

  · SessionStart 未启用：≤300 字符的一句话介绍 + 启用方式（每会话一次，可接受）。
  · SessionStart 已启用：静态参考，硬上限 2000（H18 断言）。
  · UserPromptSubmit 未启用：**stdout 全空**，等价于本 hook 不存在。与两个队列
    快照 hook 同一条零成本保证——它每轮触发、装在所有项目里，未启用项目一个字符
    都不能付。
  · UserPromptSubmit 已启用：三岔口，硬上限 800（H19 断言）。

## 调用约定

`--event user-prompt-submit` 出每轮那份；缺省（或 `--event session-start`）出
SessionStart 那份。`hookSpecificOutput.hookEventName` 必须与真实事件名一致，
写错 harness 会丢弃整个输出且不报错。

注意不能用 `python3 - <<'EOF'` 内联写法：heredoc 会占用 stdin，事件 JSON（含
cwd）就读不到了——2026-07-31 实测踩过，遂独立成文件。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from keeper_paths import find_keeper_root
except Exception:
    find_keeper_root = None

NOT_ENABLED = (
    "task-keeper 未在本项目启用（无 .keeper/ 目录）。启用后可把 bug 转常驻 "
    "debug-keeper、杂务转 chore-keeper 托管，主会话只做分诊转发。启用："
    "`mkdir -p .keeper/$(basename $(git rev-parse --show-toplevel))/debug`"
    "（非交付 worktree 用 `_main` 代替 basename）。只需建这一个，"
    "同级 `chore/` 由每轮 hook 自动补建，不必手工创建。")

# 每轮注入：只放与 system prompt 默认行为对立的部分。改这段前先读模块头
# 「为什么分两层」——往里加静态参考会让每轮成本白涨且稀释对抗力。
TRIAGE = """# task-keeper 分诊（本轮先分诊，再动手）

对刚收到的这条用户消息判一次归属。分错代价小，**不要为分类反问用户**：

1. **自己做**：当前主线任务本身、几句话能答的问题、需要你上下文才能做的事。
2. **转 debug-keeper**：bug / 报错 / 异常行为 → 逐字转发（首次用 `Agent` 派出，之后 `SendMessage` 唤醒）。属于项目既有交付流程的活走该流程。
3. **转 chore-keeper**：台账 / 沉淀 / 收尾 / 外部系统小操作等杂务 → 逐字转发。

唤醒前先读 `.keeper/<交付id>/.keeper-instance.json` 取实际 name（name 带随机短哈希，别凭记忆拼），读不到才算首次、按上面用 `Agent` 派出。

三原则：**逐字**（不改写用户原话）、**即回**（转完回主线，不追问 keeper 进度）、**不越位**（`.keeper/` 队列文件你只读，写者是 keeper）。

最常见的失效方式是「这个我顺手做了更快」。转发的目的不是省你的时间——是不让这条任务的状态只活在本轮上下文里，compact 一次就没了。"""

# SessionStart：静态参考。刻意不复述三岔口（那份每轮注入）。
ENABLED = """# task-keeper 主会话侧参考

三岔口分诊规则每轮随 `UserPromptSubmit` 注入，此处不复述。以下是需要时查的静态部分。

## 决策打包（主会话侧职责）

keeper 需要 Human 拍板时会写 `<交付>/decisions/<stamp>-<keeper>.md` 并 SendMessage 打铃。你的动作：**攒批**（待拍板 ≥3 条 / 出现 blocking / 用户问起 / 停顿点，四触发点命中才处理），一次 AskUserQuestion 把多条并列问完（必须用工具本体，禁止文本选项块——手机推送只认工具调用），答复**原文**写 `<交付>/decisions/answers/<同名>.md` 并 SendMessage 通知对应 keeper。每轮注入的「待拍板 N 条」计数由磁盘现算，比你的记忆可靠。

## 布局（v4）

`<worktree 根>/.keeper/<交付id>/{debug,chore,decisions}/`，交付 id 取 worktree 根 basename、非交付 worktree 用 `_main`。一条 bug 的 issue.md / receipts.md / 截图 / fixer worktree 全在 `debug/<DBG-id>/` 一个目录里。文本入库、截图与 worktree 不入库。

指针：协议正典 skills/tk-decisions；队列状态看每轮注入或各队列 index.md（薄索引，按需开单条正文）。"""


def main():
    ev_name = "SessionStart"
    argv = sys.argv[1:]
    if "--event" in argv:
        i = argv.index("--event")
        if i + 1 < len(argv) and argv[i + 1] == "user-prompt-submit":
            ev_name = "UserPromptSubmit"
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        ev = {}
    cwd = ev.get("cwd") or os.getcwd()
    enabled = bool(find_keeper_root and find_keeper_root(cwd))

    if ev_name == "UserPromptSubmit":
        if not enabled:
            return  # 零成本保证：未启用项目一个字符都不注入
        text = TRIAGE
    else:
        text = ENABLED if enabled else NOT_ENABLED

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": ev_name,
            "additionalContext": text,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 注入类 hook 静默降级
