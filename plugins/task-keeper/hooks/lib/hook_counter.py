#!/usr/bin/env python3
"""hook 熔断计数器 —— 给 `block` / `deny` 型 hook 提供次数上限。

【为什么必须有：block 型 hook 是纯机器闭环】
  `ask` 型 hook 每次都把控制权交还给人，人点一下循环就断；`block` 型没有这个出口——
  判据误报时，AI 无论输出什么都过不了，没有任何一方能打破循环。终止条件只剩两种：
  subagent 自己放弃，或 token 烧完。

【踩坑实录（2026-07-29 探针实验，DBG-007）】
  对账 hook 当时无任何次数上限。实验里第 2 层 subagent 被同一判据连续拦 26 次、
  烧掉 71.2k token（同规模探针正常只用 39-45k）后宣布「不予配合」硬顶结束；
  第 1 层 transcript 涨到 320KB 仍在循环，最终由主会话 TaskStop 掉。
  兄弟插件 devkit-tool / working-discipline 的 `hooks/lib/notify-once.js` 在
  2026-07-28 撞过同类问题并加了 `DENY_LIMIT = 3`，其注释原话是「判据依赖 transcript
  结构这类外部格式时，格式一变 deny 就会变成无限循环……需要次数上限兜底」。
  本模块是该教训的 Python 对应物。

【失败方向：读写失败一律当作「首次」】
  `/tmp` 不可写时 `bump()` 恒返回 1，也就是恒不熔断——这本身就是死循环风险。所以
  调用方**不得只依赖本模块**，必须同时判事件里的官方重试标记（如 `SubagentStop`
  的 `stop_hook_active` 字段）作为第二条独立兜底。两条机制互不依赖，任一生效即可
  打破循环。绝不能让计数器故障本身变成「永远 block」。

【存储位置】
  系统临时目录，文件名 `tk-<scope>-<session_id>.json`。放临时目录而非 `~/.claude/`
  是为了避免跨会话污染，且系统重启会自然清理；每个 scope 独立文件，避免不同 hook
  互相覆盖对方的记录。前缀 `tk-`（task-keeper）与 radnove-core 的 `rn-` 区分，
  两插件短暂共存期各自的熔断计数互不污染。
"""
import json
import os
import re
import tempfile

# 单文件保留的 key 上限：防止长会话把状态文件撑到无限大。
# 超出后丢弃最早写入的（dict 保序），只留最近的 MAX_KEYS 条。
MAX_KEYS = 200


def _state_path(scope, session_id):
    def safe(s):
        return re.sub(r"[^A-Za-z0-9_-]", "_", str(s or "nosession"))

    return os.path.join(tempfile.gettempdir(),
                        "tk-%s-%s.json" % (safe(scope), safe(session_id)))


def bump(scope, session_id, key):
    """把 (scope, session_id, key) 的计数 +1，返回自增**后**的次数（首次返回 1）。

    任何读写异常都不抛出——见模块文档「失败方向」：读失败时计数从 0 重新开始，
    效果是不熔断，必须由调用方的官方重试标记判断兜住。
    """
    path = _state_path(scope, session_id)

    counts = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("counts"), dict):
            counts = data["counts"]
    except Exception:
        counts = {}

    try:
        n = int(counts.get(key, 0) or 0) + 1
    except Exception:
        n = 1
    counts[key] = n

    if len(counts) > MAX_KEYS:
        counts = dict(list(counts.items())[-MAX_KEYS:])

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"counts": counts}, f)
    except Exception:
        pass  # 写不进去只影响下一次能否熔断，不影响本次返回值

    return n
