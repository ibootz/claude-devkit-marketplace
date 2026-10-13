#!/usr/bin/env python3
"""Debug worktree 强制删除守卫（PreToolUse · Bash matcher）

stdin  = PreToolUse 事件 JSON
stdout = 命中「针对 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 目录执行强制删除
         类命令」时输出 permissionDecision=ask 的 JSON；否则**全空**（放行）

【立规背景】fixer 的工作区是 `wt_supply.py init` 建出的
`<source>/.keeper/<交付id>/debug/DBG-NNN/worktree/`（v4 一交付一目录布局，
`<交付id>` 也可以是兜底桶 `_main`），里面可能装着 fixer 尚未 commit 的修复
产物。`git worktree remove --force` / `rm -rf` / `git clean -fdx` 这类命令一旦
对准这个目录，删掉的东西不可恢复——而 fixer 的日常操作（改文件、跑测试、写
receipt）不会走到任何一种强制删除形态，真正会撞上这几种命令的场景要么是清理
一个已经失败/已经合并完的 worktree，要么是误操作，两者机械上无法区分，只能
弹框交给 Human 拍板。

【关键设计决定：ask，不是 deny】这一点与同目录的
`debug_worktree_push_guard.py`（deny）不同，必须解释清楚：`rm -rf <worktree
层>` 是**有文档记载的合法恢复手段**，不是应当一律堵死的动作。
`skills/tk-worktree/SKILL.md` 的状态判据表里，`isolated-objdir` 与
`unreachable` 两种层状态给出的处置就是「`rm -rf` 该目录后重跑 `supply`」；
`wt_supply.py` 自己在多处 `Fail` 的 hint 里也这么教（例如
`hint=f"先 \`rm -rf {level.target}\` 再重跑 supply；..."`、
`hint="人工 \`rm -rf\` 这些目录后重跑 remove；若里面有未推送提交，先备份"`）。
如果本守卫像 push 守卫一样一律 deny，就会把这条官方记载的恢复路径堵死，AI
连「照着 SKILL.md 教的做」都做不到。因此正确形态是 ask：让 Human 看一眼再点头，
而不是替 Human 做「这次删除是不是安全」的判断。

【为什么 push 守卫可以 deny 而这个不行】push 那边 fixer 结构上从不需要
push——没有任何合法场景需要弹框，直接 deny 收工即可。这里恰恰相反：合法场景
（清理已损坏的层、走 SKILL.md 记载的恢复流程）和风险场景（未提交产物被误删）
在命令行字面上长得一模一样，唯一能分辨的人是当时在场的 Human。

【判定细则】
命中条件 = 「命令形态属于强制删除类」且「目标路径匹配
`.keeper/<任意交付id>/debug/<任意DBG-id>/worktree` 形态（含兜底桶 `_main`）」。

强制删除类的三种形态（只按命令行字面判定，不猜语义）：
  1. `git worktree remove` 同时带 `--force` 或 `-f`。
  2. `rm` 带递归标志——`-r` / `-R` / `-rf` / `-fr` 等合并短选项、或长选项
     `--recursive`，只要标志集合里出现 r/R 即命中（`-f` 单独出现不算，
     必须是"递归"这个动作本身危险，而不是要求同时带 -f——单纯 `rm -r <目录>`
     对一个目录同样是不可逆的整体删除）。
  3. `git clean` 同时带 `-f`（或 `--force`）**且**带 `-d` 或 `-x`，覆盖
     `-fdx`、`-xdf` 这类合并短选项。`git clean -f` 单独出现不算——不加
     `-d`/`-x` 时 git clean 默认不清未跟踪目录，破坏面小得多，且不是
     `.keeper/<交付id>/debug/<DBG-id>/worktree/` 场景下的典型命令。

短选项判定统一用「命令行里任何形如 `-[A-Za-z]+` 的独立 token，看它去掉开头
的 `-` 之后的字符集合里有没有目标字母」，这样 `-rf`/`-fr`/`-Rf` 等任意换序
组合都能覆盖，不需要为每种排列单独写正则。长选项另外精确匹配
`--recursive` / `--force` 整词，避免把 `--force-delete-branches` 这类无关长
选项的子串误当成 `--force` 命中（`--force` 后面还跟着字符时不是独立 token，
不会被 `(?<!\S)--force(?!\S)` 命中）。

路径判定：直接对整条命令字符串做 `.keeper/<交付id>/debug/<DBG-id>/worktree`
正则匹配——不精确解析是第几个位置参数，因为
`rm -rf /path/to/.keeper/D-001-feat/debug/DBG-017/worktree` 的路径是裸位置
参数、不在 `-C` 这类具名选项里，精确解析反而容易漏。交付 id 与 DBG-id 两段
都用 `[^/]+` 通配，兜底桶 `_main` 同样命中。命令字符串里没有匹配时，退回看
事件的 `cwd` 字段是否匹配（cwd 由 harness 提供，是 AI 发起这条命令时所在的
目录）。两处都没有 → 放行——与 push 守卫同一保守原则：宁可漏放（回到没有
本守卫之前的现状），也不无凭无据弹框打扰 Human。
"""
import json
import re
import sys

# v4 一交付一目录布局：worktree 落在 `.keeper/<交付id>/debug/<DBG-id>/worktree/`
# 下（`<交付id>` 含兜底桶 `_main`）。与 debug_worktree_push_guard.py 用同一形态，
# 两个守卫各自内联判据、不共享 import，保持零依赖的判据风格。
WORKTREE_RE = re.compile(r"\.keeper/[^/]+/debug/[^/]+/worktree(?:/|$)")

# 命令行里的短选项 token，如 -rf / -f / -C / -fdx，取其 "-" 之后的字符集合判定
SHORT_OPT = re.compile(r"(?<!\S)-([A-Za-z]+)(?!\S)")
LONG_RECURSIVE = re.compile(r"(?<!\S)--recursive(?!\S)")
LONG_FORCE = re.compile(r"(?<!\S)--force(?!\S)")

GIT_WORKTREE_REMOVE = re.compile(
    r"(?:^|[\s;|&(])git\s+(?:-[A-Za-z-]+(?:[= ]\S+)?\s+)*worktree\s+remove\b"
)
GIT_CLEAN = re.compile(
    r"(?:^|[\s;|&(])git\s+(?:-[A-Za-z-]+(?:[= ]\S+)?\s+)*clean\b"
)
RM_CMD = re.compile(r"(?:^|[\s;|&(])rm\s")


def _short_opt_chars(command):
    """抠出所有短选项 token，去掉开头 '-' 后的字符集合（大小写不敏感）。"""
    return [m.group(1).lower() for m in SHORT_OPT.finditer(command)]


def is_forced_worktree_remove(command):
    if not GIT_WORKTREE_REMOVE.search(command):
        return False
    if LONG_FORCE.search(command):
        return True
    return any("f" in opt for opt in _short_opt_chars(command))


def is_recursive_rm(command):
    if not RM_CMD.search(command):
        return False
    if LONG_RECURSIVE.search(command):
        return True
    return any("r" in opt for opt in _short_opt_chars(command))


def is_dangerous_clean(command):
    if not GIT_CLEAN.search(command):
        return False
    opts = _short_opt_chars(command)
    has_force = LONG_FORCE.search(command) or any("f" in opt for opt in opts)
    has_dx = any(("d" in opt or "x" in opt) for opt in opts)
    return bool(has_force and has_dx)


def is_forced_destroy(command):
    return (
        is_forced_worktree_remove(command)
        or is_recursive_rm(command)
        or is_dangerous_clean(command)
    )


REASON = """针对 `.keeper/<交付id>/debug/<DBG-id>/worktree/` 目录执行了强制删除类
命令，需要 Human 确认后再继续。

本次命中路径：%s

**为什么弹框而不是直接放行或直接拦截**：
(a) 这个目录里可能装着 fixer 尚未 commit 的修复产物，强制删除（`git worktree
    remove --force` / `rm -rf` / `git clean -fdx` 这类命令）一旦执行不可恢复。
(b) 正常的清理路径是 `wt_supply.py remove --worktree <WT> --yes`——它内部跑的
    是不带 `--force` 的 `git worktree remove`，工作区脏时 git 会自己拒绝、从而
    保住未提交的产物，这是设计意图，不是它的缺陷或障碍。
(c) 但如果你确实是在走 `isolated-objdir` / `unreachable` 状态的恢复流程（见
    `skills/tk-worktree/SKILL.md` 状态判据表，以及 `wt_supply.py` 自身
    `Fail` 提示里教的「先 rm -rf 该目录再重跑 supply」），那么强制删除是文档
    记载的合法手段——确认目录里确实没有未提交的修复内容之后，请放行。"""


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

    if not is_forced_destroy(command):
        return

    target = None
    if WORKTREE_RE.search(command.replace("\\", "/")):
        target = command
    else:
        cwd = ev.get("cwd")
        if isinstance(cwd, str) and cwd and WORKTREE_RE.search(cwd.replace("\\", "/")):
            target = cwd

    if target is None:
        return  # 命令与 cwd 都没有目标目录的字面量，不是本守卫的管辖范围

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": REASON % target,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 守卫故障不得阻断命令执行
