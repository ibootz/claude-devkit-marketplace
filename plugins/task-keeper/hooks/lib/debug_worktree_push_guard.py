#!/usr/bin/env python3
"""Debug worktree 禁止 push 守卫（PreToolUse · Bash matcher）

stdin  = PreToolUse 事件 JSON
stdout = 命中「在 DBG fixer worktree 里执行 git push」时输出 permissionDecision=deny
         的 JSON；否则**全空**（放行）

【立规背景】2026-07-30 Human 反馈：曾观察到 AI 在 debug 流程里自动 push 过代码，
这与 tk-debug 全套文档一贯的表述（`skills/tk-debug/references/queue.md` §6、
`wt_supply.py` merge-back 收尾提示都写着"建 commit 但不 push，push 由 Human 确认后
另行处理"）矛盾——说明纯文档描述挡不住实际行为，需要一道机械防线。

Human 明确的范围是"debug 流程里派发出去的实际干活的 subagent 都不允许 push"。
本守卫只覆盖其中**可机械判定的那一半**：fixer。fixer 的工作区是
`wt_supply.py init` 建出的 `<source>/.keeper/worktrees/DBG-NNN/`，按
`skills/tk-debug/SKILL.md` §3 硬规则 1，fixer 的每一条 git 操作都必须写成
`git -C <worktree 绝对路径> ...`——这个约定本身就给了本守卫一个可靠的判定锚点：只要
push 命令的目标路径（`-C` 参数或本次调用的 cwd）落在某个 `.keeper/worktrees/DBG-*/`
目录下，就一定是 fixer 在自己的隔离 worktree 里执行的，可以放心 deny，不会有把
正常 push 误伤的风险（正常 push 走的是主仓/交付 worktree 路径，从不会落在
`.keeper/worktrees/` 里面）。

**debug-keeper 自己呢？** keeper 负责登记 → triage → 派 fixer → 对账 → merge-back
收尾，它通常跑在主工作区或交付 worktree，cwd 与它是不是在做 debug 收尾没有可机械
区分的差异，本守卫**覆盖不到**——这一半只能靠 `agents/debug-keeper.md` 与
`references/queue.md` 里写死的显式指令：merge-back --apply 建完 commit 后 push
不是默认动作，必须等 Human 当轮明确同意后才由 keeper 执行。两条防线合起来覆盖
Human 提出的完整范围，但性质不同——fixer 这一半是机械拦截（本文件），keeper 这一半
是自觉约束（文档）。

【为什么 deny 而非 ask】fixer 结构上从不需要 push——它只需要在自己的 worktree 分支上
commit，回流合并由 debug-keeper 之后跑 `wt_supply.py merge-back` 完成，push 不是
这个流程里任何一步的必要动作。既然没有"这次真的需要 push、只是要弹框确认"的合法
场景，直接 deny 让 AI 自己收手即可，不必用 ask 弹框浪费用户一次点击。

【判定细则】
  1. 命令必须是 git push 的调用形态——覆盖 `git push`、`git -C <path> push`、
     `git --git-dir=<path> push` 等写法，`push` 必须是 git 的子命令（避免误伤
     `echo "please push"` 这类不相关文本）。
  2. 解析目标路径：优先取命令里 `-C <path>` / `--git-dir=<path>` 给出的路径；
     两者都没有时退回本次 PreToolUse 事件的 `cwd` 字段（如果 harness 提供了）。
  3. 目标路径按字符串匹配含 `.keeper/worktrees/` 即命中——不要求路径存在、不要求
     精确到某一层 DBG-id，命中即视为「这是某个 fixer 的隔离 worktree」。
  4. 解析不到任何路径信息（既没有 `-C`/`--git-dir`，事件也没给 cwd）时**放行**——
     宁可漏放（回到"没有本守卫之前"的现状，不劣化），也不无凭无据地 deny 一条
     可能来自主会话的正常 push。
"""
import json
import re
import sys

# git push 调用形态：git（可带 -C/--git-dir 等全局选项）... push（子命令）
GIT_PUSH = re.compile(r"(?:^|[\s;|&(])git\s+(?:-[A-Za-z-]+(?:[= ]\S+)?\s+)*push\b")

# `-C <path>` / `-C=<path>`（git 全局选项不支持 = 形态，但兼容性宽松匹配一下也无妨）
C_FLAG = re.compile(r"-C[\s=]+([^\s;|&]+)")
GITDIR_FLAG = re.compile(r"--git-dir[\s=]+([^\s;|&]+)")

WORKTREE_MARK = ".keeper/worktrees/"


def extract_target_path(command):
    """从命令里抠 -C / --git-dir 给出的路径，抠不到返回 None。"""
    m = C_FLAG.search(command)
    if m:
        return m.group(1).strip("\"'")
    m = GITDIR_FLAG.search(command)
    if m:
        return m.group(1).strip("\"'")
    return None


REASON = """禁止在 DBG fixer worktree 里执行 `git push`（2026-07-30 Human 立规）。

本次命中路径：%s

**为什么禁止**：fixer 在自己的隔离 worktree 里只需要把修复 commit 在本地分支上，
回流合并由 debug-keeper 之后统一跑 `wt_supply.py merge-back` 完成——push 从来不是
这条流水线里任何一步的必要动作。debug-keeper 自己同样不能未经同意就 push（见
`agents/debug-keeper.md`），push 完全是 keeper 在 Human 当轮明确同意后才执行的
动作，不属于 fixer 的职责范围。

如果你是 fixer：不要 push，把改动 commit 好、写完 `receipts/DBG-NNN.md` 回执即可，
push 与你无关。
如果你不是在 DBG worktree 里操作、这次拦截是误判：说明目标路径确实不是某个 fixer
的隔离 worktree（本守卫只在路径含 `.keeper/worktrees/` 时才会触发），可以确认后
换一种不含 `.keeper/worktrees/` 路径字面量的写法重试。"""


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        return  # 基础设施异常 → 放行

    if not isinstance(ev, dict):
        return
    tool_input = ev.get("tool_input")
    command = (tool_input or {}).get("command") if isinstance(tool_input, dict) else None
    if not command or not isinstance(command, str):
        return

    if not GIT_PUSH.search(command):
        return

    target = extract_target_path(command)
    if target is None:
        cwd = ev.get("cwd")
        target = cwd if isinstance(cwd, str) and cwd else None

    if target is None:
        return  # 抠不到任何路径信息，宁可放行也不无凭据 deny

    if WORKTREE_MARK not in target.replace("\\", "/"):
        return  # 目标不在 fixer 的隔离 worktree 里，不是本守卫的管辖范围

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON % target,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 守卫故障不得阻断命令执行
