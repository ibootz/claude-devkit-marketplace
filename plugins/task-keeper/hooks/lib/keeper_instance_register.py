#!/usr/bin/env python3
"""keeper 实例落盘登记（PreToolUse · Agent matcher）

stdin  = PreToolUse 事件 JSON
stdout = 永远空——本 hook **不拦截任何操作**，不输出 permissionDecision，不 exit 2。
         它唯一的动作是把 keeper 的 `name`（连同这次派发所在的 `session_id`，2026-08-05
         补）写进 `<worktree 根>/.keeper/<交付id>/.keeper-instance.json`，供主会话
         下次唤醒时读取真实 name（keeper 的 name 现在强制带 4 位随机短哈希，主会话
         没法靠记忆或文档拼出来，见 `keeper_paths.py` 模块头「`.keeper-instance.json`」）。
         写进 `session_id` 是为了让跨会话读到的登记能被识别成"陈旧"——否则新会话
         第一次读到上一个会话的死 name，唤醒失败后会误判成"重派"，见 `keeper_paths.py`
         模块头「`.keeper-instance.json` 的会话隔离」那一节的事故描述。

【判据：只用确定字段，白名单枚举，不做模糊匹配】
  1. `tool_name == "Agent"`——不是这次调用就不用往下看。
  2. `tool_input.subagent_type` 取冒号后的 slug，必须**恰好等于**
     `"debug-keeper"` 或 `"chore-keeper"` 这两个值之一。含 "keeper" 字样但不在
     白名单内的（假设的第三种 keeper、名字里带 keeper 的普通 subagent）一律不算。
  3. `tool_input.name` 必须是非空字符串——它是真正要落盘的值。缺失或空值时没有
     可登记的东西，直接放弃，不报错、不用占位值顶替。

  这三条都是对 `tool_input`/`tool_name` 字段的直接读取和字符串比较，没有语义猜测，
  符合本仓 `.claude/rules/hook-restraint.md` 对"可以做成 hook 的判据"的要求。

【`session_id` 读取：读不到不影响登记本身】
  `ev.get("session_id")` 是这次 `PreToolUse` 事件所在会话的 id，随 `name` 一起传给
  `keeper_paths.write_keeper_instance`。若它缺失或不是字符串——理论上不该发生，
  但本 hook 一贯的口径是"异常静默降级"——就传 `None`，`write_keeper_instance` 内部
  会据此跳过 `session_id` 键（见其模块头），name 照常写入。这条记录之后没法被会话
  比对认领，只是退回"下次一律当陈旧处理、走首次派发"这条已验证安全的路径，不是
  登记失败。

【为什么不校验 name 是否满足短哈希正则】那是 `working-discipline` 的
  `agent-dispatch.js` 的职责（判断该不该放行这次派发）。本 hook 运行在它之后
  （PreToolUse 同一时机点，两个插件各自独立挂载），如果那道闸已经 deny 了这次
  调用，Agent 根本不会真正派发；如果它放行了，说明 name 已经合规，本 hook 直接
  原样登记即可，重复校验只会引入两处判据不同步的风险。

【异常处理：任何一步失败都静默放弃，绝不影响本次 Agent 派发】
  - stdin 读不到 / 不是合法 JSON → 直接返回，不写任何东西。
  - `tool_input` 缺失、字段类型不对 → 直接返回。
  - 找不到 git 工作区（`find_worktree_root` 返回 `None`，例如 cwd 不在任何 git
    仓库内）→ 直接返回，没有 `.keeper/` 该挂的地方。
  - 目标目录建不出来 / 文件写不进去（权限、磁盘满、只读挂载）→
    `keeper_paths.write_keeper_instance` 内部吞掉异常返回 `False`，本文件不重试、
    不报错，因为这只是一个"下次唤醒可能读不到最新 name、退回首次派出"的降级，
    不是"这次 Agent 派发失败了"。

  一句话概括：这个 hook 写得进就写，写不进就算了，**永远不吭声、永远不拦**。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import keeper_paths
except Exception:
    keeper_paths = None

# 白名单枚举——只认这两个值，不做「含 keeper 就算」的模糊匹配。
KEEPER_SUBAGENT_KIND = {
    "debug-keeper": "debug",
    "chore-keeper": "chore",
}


def keeper_kind(subagent_type):
    """`tool_input.subagent_type` 命中白名单则返回 `"debug"`/`"chore"`，否则 `None`。

    冒号前的插件名不参与判断（`task-keeper:debug-keeper` 与裸 `debug-keeper` 都算
    命中），因为落点判据只在于"这是不是 debug-keeper/chore-keeper"，不在于是哪个
    插件派发的它。
    """
    if not isinstance(subagent_type, str):
        return None
    slug = subagent_type.rsplit(":", 1)[-1].strip()
    return KEEPER_SUBAGENT_KIND.get(slug)


def main():
    if keeper_paths is None:
        return

    try:
        ev = json.loads(sys.stdin.read())
    except Exception:
        return
    if not isinstance(ev, dict):
        return

    if ev.get("tool_name") != "Agent":
        return

    tool_input = ev.get("tool_input")
    if not isinstance(tool_input, dict):
        return

    kind = keeper_kind(tool_input.get("subagent_type"))
    if kind is None:
        return

    name = tool_input.get("name")
    if not isinstance(name, str) or not name.strip():
        return  # 没有可登记的 name，静默放弃——不用占位值顶替

    cwd = ev.get("cwd") or os.getcwd()
    root = keeper_paths.find_worktree_root(cwd)
    if not root:
        return  # 不在任何 git 仓库内，没有 .keeper/ 该挂的地方

    session_id = ev.get("session_id")
    session_id = session_id if isinstance(session_id, str) and session_id.strip() else None

    delivery_id = keeper_paths.resolve_delivery_id(root)
    keeper_paths.write_keeper_instance(root, delivery_id, kind, name.strip(), session_id=session_id)
    # 不打印任何东西：本 hook 没有需要回灌给 harness 的输出。


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # 纯副作用 hook，任何异常都不得影响本次 Agent 派发
