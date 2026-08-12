#!/usr/bin/env python3
"""sdlc 文档正文编写者守卫（PreToolUse · Write|Edit|MultiEdit）

stdin  = PreToolUse 事件 JSON
stdout = 主会话写 sdlc 正文时输出 permissionDecision=deny；否则**全空**（放行）

【只管一件事】主会话（payload 无 agent_id）直接写 sdlc 流程文档正文时 deny，逼它
改道派 sdlc-writer subagent。sdlc-writer 自己写（payload 带 agent_id）放行。

【为什么需要这个守卫】sdlc-writer 的派发原先纯靠 `UserPromptSubmit` 每轮注入三岔口
第 5 支路提醒（`keeper_routing.py` 的 `SDLC_LINE`），是软约束。但它对抗的是主会话最强
的默认行为——system prompt 的「有足够信息就动手」+ 三岔口第 1 条「自己做：……需要你
上下文才能做的事」。写 sdlc 文档恰需主会话手上的上下文，故主会话在「写」的瞬间自归
第 1 条、不思「转」，第 5 支路遵循度最低。`keeper_routing.py` 模块头实测过同类软约束
（SessionStart 注入一次）压不过每轮生效的 base 指令，才挪到每轮 UserPromptSubmit——
即便如此，写文档是当下主线、主会话最难自废武功，软提醒仍频频被跳过。一次 sdlc 展开
落十几份文档，主会话自写则每份全文进窗口、几份即 auto-compact，挤走真正该留的需求
对话与 Gate 判断——这正是 sdlc-writer 存在的意义（见 agents/sdlc-writer.md §0），软
约束保不住它，故上机械闸。

【判据，三项全机械可判，过 hook-restraint 六问】
  1. tool_name ∈ {Write, Edit, MultiEdit}（plugin.json 的 matcher 只写 Write|Edit，
     MultiEdit 是防御性判据，与 evidence_guard 同构）。
  2. file_path 命中 sdlc 正文区：含 `sdlc/specs/` 或 `sdlc/deliveries/`，且 basename
     非 `_index.md`。`_index.md` 的 frontmatter 承载 gate 状态（`gates.g*.status` /
     `lifecycle`），那是主会话/Human 的门禁动作（见 skills/tk-sdlc §1 切割表），刻意
     放行。主会话在 sdlc/ 下唯一合法落盘的就是这一个文件，其余正文（scope / coverage
     / contracts / entities / nfr / behaviors / ui / storylines / tasks / release-plan
     / concepts / design-digest / decisions 等）全是 sdlc-writer 的写域（agents/
     sdlc-writer.md §2）。拍板落盘走 `.keeper/<交付id>/decisions/answers/`，不在 sdlc/
     下，不撞本守卫。
  3. 调用方是主会话：payload 顶层 `agent_id` 缺省（absent）。Claude Code 2.1.228 二进制
     明文逐字——`agent_id`「Subagent identifier. Present only when the hook fires from
     within a subagent... Absent for the main thread, even in --agent sessions. Use
     this field (not agent_type) to distinguish subagent calls from main-thread calls.」
     既有用例 working-discipline/hooks/guards/probe-throttle.js:184 `if (ev.agent_id)
     return`。子代理发起（agent_id 真值）一律放行——sdlc-writer 写自己的产物不拦。

【为什么 deny 不 ask】同 evidence_guard.py 的论证：deny 是「AI 自己改正后重试」、用户
无感；ask 弹框打断人，且 permissionDecision 独立于权限模式、bypassPermissions 也拦
不住。这里拦的是「该派没派」的疏忽，不是「需人决策」，用 deny。本机 defaultMode 常
bypassPermissions，ask 会直接失效（见用户级 memory bypass-permissions-disables-ask），
deny 是唯一可靠档。

【必须存在可达的通过态】仿 evidence_guard 的 DBG-007 教训——纯机器闭环必须有次数出口，
否则判据误报时 AI 无论输出什么都过不了。本守卫的通过态有四条，都写在 REASON 里：
(a) 派 sdlc-writer；(b) 改写到 `_index.md` 翻 gate；(c) 改写到
`.keeper/<交付id>/decisions/answers/` 落拍板；(d) 由子代理（带 agent_id）发起。
另有熔断兜底（见下）。

【熔断】同 session + 同 file_path 撞 DENY_LIMIT 次后转 additionalContext 放行，防判据
失灵导致无限 deny（复用 hook_counter.bump）。

【残余风险：Bash 绕路】主会话改用 Bash 的 heredoc / `cat >` 写 sdlc 文件可绕过本守卫
（本守卫只挂 Write|Edit|MultiEdit）。暂不堵——现状的主要矛盾是主会话用 Write 直接写
（最顺手路径），堵住它即把默认行为改道到「派 writer」；deny 文案给的是派 writer 的
照抄形态而非绕路提示，正确反应是派 writer。若实测出现 heredoc 绕路（同类事故
agents/sdlc-writer.md §4 与 .claude/rules/project/hook-restraint.md 实证 3 警告过），
再加 PreToolUse(Bash) 闸。

【范围窄是刻意的】判据只锁「sdlc 正文区 + 主会话」这一个组合。非 sdlc 路径、
`_index.md`、子代理发起，一律零成本放行——这是绝大多数 Write|Edit 调用。曾摘除过对
所有 .md 写入都拦的语义门控（见 evidence_guard 模块头），它的问题正是范围过宽 + 判据
是语义判断；本守卫只匹配路径形态 + agent_id 有无，纯字符串/字段检查。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from hook_counter import bump
except Exception:
    # 计数器不可用时退化为「每次都算首次」→ 不熔断。可接受：本守卫判据是纯字段
    # 匹配、不依赖外部格式，失灵概率远低于依赖 git diff 的判据。
    def bump(*_args, **_kwargs):
        return 1

DENY_LIMIT = 3

# sdlc 正文区：路径含 sdlc/specs/ 或 sdlc/deliveries/。concepts（sdlc/specs/concepts/）、
# feature 套件（sdlc/specs/features/）、交付级产物（sdlc/deliveries/<id>/）全在这两个
# 前缀下。`(^|/)` 锚定避免误匹配 `mysdlc/specs/` 这类同后缀路径。
SDLC_AREA_RE = re.compile(r"(^|/)sdlc/(specs|deliveries)/")

# `_index.md` 承载 gate 状态 frontmatter，主会话/Human 翻它——刻意放行。判 False 的
# 代价是漏拦一个正文文件（回落到软约束）；判 True 的代价是误拦 gate 翻转（硬阻断正当
# 操作）。方向选「放行 _index.md」，因为 gate 翻转是主会话的高频正当动作，误拦代价高。
INDEX_RE = re.compile(r"(^|/)_index\.md$")


def is_sdlc_body(file_path):
    """命中 sdlc 正文区且非 `_index.md`。"""
    fp = str(file_path).replace("\\", "/")
    return bool(SDLC_AREA_RE.search(fp)) and not INDEX_RE.search(fp)


REASON = """\
主会话正在直接写 sdlc 流程文档正文：

  %s

这一段应派给 sdlc-writer subagent，不该主会话亲写。

**为什么**：一次 sdlc 展开会落十几份文档（scope / coverage / contracts / entities /
nfr / behaviors / ui / tasks / release-plan / concepts …），主会话逐份亲写，每份全文
都进它的上下文窗口，几份之后即 auto-compact，而主会话真正该留的是与用户的需求对话
和 Gate 判断。派 sdlc-writer 就是为了把这些文档全文移出主会话窗口——每轮注入的「转
sdlc-writer」是软提醒，压不过「顺手写更快」这个默认行为，故此处用机械闸改道。

**派发形态（照抄）**：

  Agent(
    name: "sonnet-sdlc-writer-<分片名>",          // 含身份词 sdlc-writer
    subagent_type: "task-keeper:sdlc-writer",
    description: "写 <feature> 的 spec 套件",      // 3-5 词，≤60 字符
    model: "sonnet",                               // 契约/实体一致性要求高时升 opus
    prompt: "【目标】逐个点名要落盘的绝对路径
             【上下文】ai-sdlc 该阶段 SKILL.md 绝对路径 + 需求锚点(stories.md / scope.md)
             【约束】写域只限点名文件；单 feature 内串行；撞校验 hook 照 finding 改
             【期望输出】改动文件 / 遵照规范 / 关键决策 / 素材缺口 / 待拍板 / 阻塞"
  )

分片规则（依赖链 behaviors → contracts → entities → prototype，并行轴取 feature、单
feature 内串行）与 prompt 四段详见 tk-sdlc skill。

**四条出路，任选一条即放行本守卫**：

1. **派 sdlc-writer** 写这份文档（正路，推荐）。
2. 若要翻 **gate 状态** → 改写到对应 `_index.md` 的 frontmatter（`gates.g*.status` /
   `lifecycle`），`_index.md` 不在本守卫范围。
3. 若要落 **拍板结论** → 改写到 `.keeper/<交付id>/decisions/answers/<同名>.md`，那是
   主会话的写域，不在本守卫范围。
4. 由 **subagent 发起**（payload 带 agent_id）→ 本守卫只拦主会话，sdlc-writer 自己
   写它的产物不会被拦。

本守卫只锁「主会话 + sdlc 正文区 + 非 _index.md」这一个组合，撞到是因该派 writer 却
顺手亲写了。"""


DEGRADE = """\
⚠ sdlc-writer 守卫已连续拦截 %d 次达到上限（DENY_LIMIT=%d），本次放行以免死循环。

仍由主会话直接写：%s

放行不等于这是主会话该做的——若这是 sdlc 流程文档正文，正确做法仍是派 sdlc-writer。
请人工确认：要么现在派 writer，要么确认此文件确属主会话职责（gate 翻转改 _index.md、
拍板改 .keeper/<交付id>/decisions/answers/）。"""


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


def main():
    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        return  # 拿不到事件 → 放行

    if ev.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    # 子代理发起 → 一律放行（sdlc-writer 写自己的产物）。
    # agent_id：子代理真值，主会话 absent（Claude Code 2.1.228 二进制明文，见模块头）。
    # 官方明文禁用 agent_type 做此区分（主会话也可能带非空 agent_type）。
    if ev.get("agent_id"):
        return

    tool_input = ev.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not is_sdlc_body(file_path):
        return  # 非 sdlc 正文区 / _index.md → 零成本放行，这是绝大多数情况

    attempt = bump("sdlc-writer", ev.get("session_id"), file_path)
    if attempt > DENY_LIMIT:
        context(DEGRADE % (attempt, DENY_LIMIT, file_path))
    deny(REASON % file_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 守卫故障不得卡死写入
