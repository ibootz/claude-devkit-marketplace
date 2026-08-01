#!/usr/bin/env python3
"""截图证据路径守卫（PreToolUse · Write|Edit）

stdin  = PreToolUse 事件 JSON
stdout = 命中时输出 permissionDecision=deny 的 JSON；否则**全空**（放行）

【只管一件事，范围极窄】只在写入路径匹配 `.keeper/debug/issues/<任意>.md` 时才做
判断，其他所有 Write / Edit 一律 exit 0 零成本放行。范围窄是刻意的——曾摘除过
对**所有** .md 写入都拦的语义门控，它的问题正是范围过宽 + 判据是语义判断，
误伤率高到必须下线。本守卫只匹配一个固定路径形态，判据是纯字符串检查。

【判据：只阻断零误报空间的那一条】
  · 写入内容里出现指向 `image-cache` 的行 → deny。这条**没有误报空间**：
    `~/.claude/image-cache/<session-uuid>/` 是会话级临时资源，实测只保留当前活跃
    会话的目录、会话一换整个目录消失，写进跨 session 持久的队列必然 404。
  · 路径指向 `.keeper/debug/attachments/` 下但文件暂不存在 → **不阻断**。因为
    「先写占位、再 mv 图片归位」也是合法顺序，阻断会误伤登记流程。
  · 证据缺 `transcript` → **不阻断**。Edit 传来的往往只是文件片段，片段里没有
    transcript 不代表整个文件没有，机械上无法区分，判断会误报。这条靠 skill 约束。

【为什么用 deny 而不是 ask】deny 的语义是「AI 自己改正后重试」，用户完全无感；ask 会
弹框把决定权交给人、打断手上的事，而且 hook 的 permissionDecision **独立于权限模式**,
用户配了 bypassPermissions 也拦不住。拦疏忽用 deny，交决策才用 ask。

【必须存在可达的通过态】这是探针实验（DBG-007）换来的教训：对账 hook 曾把文档后缀
在配对前从回执集合里整体剔除，导致 subagent 改了 .md 无论申报与否都判幽灵改动，
block 恒成立、连拦 26 次烧掉 71.2k token。所以任何 deny/block 型判据都必须能回答
「什么样的输入能让这个分支不触发」。本守卫的答案有两条，都写在 REASON 里：把路径
换成 attachments 下的副本路径，或者省略路径只写 note 说明原图未落盘。

【熔断】同一 session + 同一文件撞 DENY_LIMIT 次后转为附加上下文放行，防判据失灵导致
无限 deny。理由同上——纯机器闭环必须有次数出口。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from hook_counter import bump
except Exception:
    # 计数器不可用时退化为「每次都算首次」→ 不熔断。可接受：本守卫的判据是纯字符串
    # 匹配、不依赖外部格式，失灵概率远低于依赖 git diff 的判据。
    def bump(*_args, **_kwargs):
        return 1

DENY_LIMIT = 3

# 队列是「一 issue 一文件」，写入目标形如 `.keeper/debug/issues/DBG-017.md`。
# 路径形态由 queue_files.DEBUG spec 拼出；spec 不可用时退回等价字面量，
# 保证守卫在依赖缺失时行为不变（判据本身没有任何语义成分，字面量即真相）。
try:
    from queue_files import DEBUG as _SPEC
    QUEUE_RE = re.compile(
        re.escape("%s/%s/" % (_SPEC.dir_name, _SPEC.item_dir)) + r"[^/]+\.md$")
except Exception:
    QUEUE_RE = re.compile(r"\.keeper/debug/issues/[^/]+\.md$")

# 证据可能写在 markdown 正文里，格式由人和 AI 自由书写（列表项、行内代码、表格
# 都可能），匹配某个固定键名必然漏。改成**行级扫描**：出现 `image-cache` 的行
# 一律可疑，唯一豁免是同一行标注了 `origin_path`——那是刻意保留的来源留档，
# 不是给人后续去读的有效指针。这个判据宽（任何写法都抓得到）且准（不误伤留档字段）。
def bad_image_cache_lines(text):
    out = []
    for line in text.split("\n"):
        if "image-cache" not in line or "origin_path" in line:
            continue
        out.append(line.strip())
    return out

REASON = """\
本次写入 `.keeper/debug/issues/<DBG-id>.md` 的内容里，有指向 `image-cache` 的图片路径：

%s

**这个路径必然在下一个会话失效。** `~/.claude/image-cache/<session-uuid>/` 是**会话级
临时资源**——实测磁盘上同一时刻只保留当前活跃会话的目录，其余全部清理。而 debug 队列
是**跨 session 持久**的（攒批、让位、推到下次交付，登记与实际修复隔几天是常态）。
把它写进 issue 文件等于埋一个几天后必然 404 的假指针，后续会话打开这条 issue 会以为
「有图可看」，实际点开是空的，排查方向就此带偏。

**两条出路，任选一条即可通过本守卫：**

1. **图还在** → 先复制进队列目录，再写副本路径：

       cp "<image-cache 原路径>" "<项目根>/.keeper/debug/attachments/<DBG-id>/01-<说明>.png"
       [ -s "<目标绝对路径>" ] && echo OK    # 必须回读验证——cp 会静默失败

   回读输出 OK 后，正文里写目标**仓库相对路径**（如
   `.keeper/debug/attachments/DBG-017/01-xxx.png`），把 image-cache 原路径挪到同一
   条目下的 `origin_path` 仅作留档——本守卫豁免带 `origin_path` 的行。主会话落盘
   阶段的目标目录是 `.keeper/debug/attachments/_inbox/`，登记时再 mv 到
   `.keeper/debug/attachments/<DBG-id>/`。

2. **图已经取不到**（cp 报错，或回读为空）→ **不要写任何图片路径**，改为在「证据」
   章节写一句「原图未落盘，原因：<具体原因>」，并把图片内容逐字转录成文字。
   宁可没有路径，也不要留一个会 404 的假路径——后者会让后续会话误以为有图可看。

macOS 上还有一条抢救途径：图若刚被粘贴过，可用 `osascript` 从系统剪贴板取回真实像素
（只读剪贴板、不修改），办法见 `skills/tk-debug/references/screenshot.md` §3。
字段规则见同目录 `queue.md` §2。"""

DEGRADE = """\
⚠ 截图路径守卫已连续拦截 %d 次达到上限（DENY_LIMIT=%d），本次放行以免死循环。

仍然存在指向 `image-cache` 的路径：%s

放行不等于这些路径可用——它们在下一个会话必然 404。请人工确认：要么现在补做
`cp` + 回读验证并改写路径，要么省略路径只保留 note 与 transcript。"""


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def deny(reason):
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                 "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def context(text):
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                 "additionalContext": text}})


def collect_written_text(tool_input):
    """把本次工具调用要写入的文本全部拼起来。

    Write 用 content；Edit 用 new_string；MultiEdit（若存在）用 edits[].new_string。
    只看新内容，不看 old_string——把待删除的旧内容也算进来会造成误报：
    「这次修改正是在把 image-cache 路径删掉」也会被拦。
    """
    parts = []
    for key in ("content", "new_string"):
        val = tool_input.get(key)
        if isinstance(val, str):
            parts.append(val)
    for item in (tool_input.get("edits") or []):
        if isinstance(item, dict) and isinstance(item.get("new_string"), str):
            parts.append(item["new_string"])
    return "\n".join(parts)


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        return  # 拿不到事件 → 放行

    if ev.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    tool_input = ev.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "").replace("\\", "/")
    if not QUEUE_RE.search(file_path):
        return  # 不是 issue 文件 → 零成本放行，这是绝大多数情况

    text = collect_written_text(tool_input)
    if not text.strip():
        return

    bad = bad_image_cache_lines(text)
    if not bad:
        return

    listed = "\n".join("    " + b for b in bad[:8])
    attempt = bump("evidence", ev.get("session_id"), file_path)
    if attempt > DENY_LIMIT:
        context(DEGRADE % (attempt, DENY_LIMIT, "、".join(bad[:8])))
    deny(REASON % listed)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 守卫故障不得卡死写入
