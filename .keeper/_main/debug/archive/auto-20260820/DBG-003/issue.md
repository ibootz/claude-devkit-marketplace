---
id: DBG-003
summary: iTerm2 文件链接未按行号定位 VS Code
status: done
priority: P2
difficulty: easy
type: bug
spec_status: violation
reported_at: '2026-08-20'
reopen_count: 0
---

# DBG-003 · iTerm2 文件链接未按行号定位 VS Code

## 问题

此前在 iTerm2 点击带 `#370` 的 `file:///` 文件链接后，VS Code 能打开目标文件但不能定位到第 370 行。Human 已手动把 Default profile 的 Semantic History 修正为 `/opt/homebrew/bin/code --goto "\1:\2"`；回读值与项目配置契约一致，A/B/C 的 CLI 调用均成功。

根因证据：修复前 Default profile 的命令为 `/opt/homebrew/bin/code "\1" "\2"`，没有 `--goto`；`code --help` 声明行号入口为 `-g --goto <file:line[:character]>`。

## 用户原话

```text
这种带行号的链接通过itmer2点击到vscode之后 不能准确定位到对应行号
```

```text
方法一：改用 VSCode 专属的 vscode://file/ 协议（最推荐）
这是最简单且不需要安装任何插件的方法。将原来的 file:// 替换为 vscode://file/，点击后会直接在 VSCode 编辑器中打开该文件，并支持跳转行号：
```

```text
文档中路径在vscode中跳转不了的问题的可以考虑使用上面的方案，同时思考在终端中输出的文件附带的绝对路径，比如DBG-xx这些文件路径是不是也可以这么改造 从而解决跳到vscode之后无法定位到具体行号的问题
```

## 证据

- `01-file-link-line-number.png`
  - origin_path：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.keeper/_main/debug/_inbox/20260820-153543-04-file-link-line-number.png`
  - 转录：iTerm2 悬停链接显示 `file:///Users/zhangq/.claude/plugins/cache/claude-devkit-marketplace/worktree-flow/1.2.0/hooks/guards/main-branch-guard.js#370`；点击后可打开文件，但不能准确跳到第 370 行。

## 规格依据

- 结论：`violation`。本项目的可点击路径规范明确要求 iTerm2 Semantic History 使用 `/opt/homebrew/bin/code --goto "\1:\2"`；实际 Default profile 配置为 `/opt/homebrew/bin/code "\1" "\2"`，没有调用 VS Code 的行号入口。
- 查过的来源：

| 来源 | 结果 | 备注 |
|---|---|---|
| `plugins/clickable-paths/README.md:21-45` | 命中 | 规定 `file:///绝对路径#行号` 经 Semantic History 的 `\1`（文件）与 `\2`（行号）调用 `code --goto "\1:\2"`。 |
| `plugins/clickable-paths/README.md:184-190` | 命中 | `vscode://file/路径:行号` 不可作为替代，因为 Claude Code 不会把非 `http`/`https`/`file` scheme 包成 OSC 8。 |
| `plugins/clickable-paths/hooks/clickable-paths.js:34-41` | 命中 | hook 保留 `file:` 的 `#` 片段，并说明 iTerm2 将它交给 Semantic History。 |
| 需求文字规格 / view spec | 未找到 | 仓库根正面列举后不存在 `sdlc/` 或独立需求规格目录；本条行为由插件 README 的用户可见配置契约定义。 |
| 原型 html | 未找到 | 本条为终端到编辑器的本机配置行为，无 UI 原型产物。 |
| 交付级决策 / ADR | 未找到 | 仓库根与 `docs/` 中未找到本条独立决策产物。 |
| i18n 文案 / DB 列注释 / API 契约 / 错误码 | 不适用 | 本条不涉及业务字段、持久化数据或服务接口。 |
| 用户原话 | 命中 | 用户明确期望点击带行号链接后准确定位相同行号。 |

- 规格原文摘录：

```text
/opt/homebrew/bin/code --goto "\1:\2"
```

- 期望 vs 实际：iTerm2 应将链接中的文件与 `#` 后行号拼成 `<file>:<line>` 后传给 `code --goto`；实际把文件和行号作为两个普通位置参数传入，VS Code 因而只打开文件、不消费行号。
- 本条的修复判据：保持 `file:///绝对路径#行号` 输出格式；iTerm2 使用 `--goto "\1:\2"` 后，点击输出链接到达其 `#` 所指定行。

## 生效机制

Claude Code 对 `file:` Markdown 链接保留 `#` 片段并以 OSC 8 输出；iTerm2 把文件路径和片段分别替换到 Semantic History 的 `\1` 与 `\2`。VS Code CLI 的定位入口是 `-g --goto <file:line[:character]>`，因此必须把两个值作为同一个 `file:line` 参数传入。当前 Default profile 的命令 `/opt/homebrew/bin/code "\1" "\2"` 不符合该入口形态。

`vscode://file/...:line:column` 不作为本条修复方案：本机已核实 macOS 能将 `vscode` scheme 交给 VS Code，但未取得编辑器光标定位的一手证据；更重要的是现有 Claude Code→iTerm2 链路只稳定处理 `file:`，将对话格式切换为 `vscode:` 会使 OSC 8 交付失效。

## Triage

- `priority: P2`：文件仍能打开，问题影响代码定位效率而非功能可用性或数据正确性。
- `difficulty: easy`：落点是单一 iTerm2 Profile 的 Semantic History 命令，规格锚、根因与改法唯一，不涉及源码或跨模块变更。
- `type: bug`：实际点击行为违反明确的行号定位契约，不是纯观感差异。
- 处置建议：修改 iTerm2 当前使用的 Default profile 的 Semantic History 命令为 `/opt/homebrew/bin/code --goto "\1:\2"`；由于它会改用户本机偏好设置，先经 Human accept 后再执行。
- dup / 相关性：与 DBG-002、DBG-004 都涉及文件链接，但本条独有根因是 iTerm2 到 VS Code 的行号参数传递；未判为同根因，不合并。
- 依赖假设：假设截图中的 iTerm2 Default profile 是用户点击链接时实际使用的 profile；此假设已由本机 Preferences 配置读取支持，但尚未在 iTerm2 图形界面逐次点击确认。

## 验证

- 场景 A：点击 `file:///…/main-branch-guard.js#370`，VS Code 应打开该文件并定位第 370 行。已自动执行 `/opt/homebrew/bin/code --goto "<目标绝对路径>:370"`，目标文件共 397 行，命令退出码为 0、stdout/stderr 均为空；iTerm2 配置已回读为 `--goto "\1:\2"`。未自动读取 GUI 光标，因此定位最终画面以 Human 手动修改后的实际点击体验为准。
- 场景 B：点击无显式业务行号的文件链接时，输出端必须带 `#1`，Semantic History 应调用 `code --goto "<file>:1"` 并定位第 1 行，不能把空行号传成尾随冒号。已自动执行目标文件 `:1` 命令，退出码为 0、stdout/stderr 均为空。
- 场景 C：路径含中文或空格、并带可选列号时，`code --goto "<file>:<line>[:<character>]"` 应保持路径整体为一个参数并定位指定位置。已对临时文件 `/tmp/dbg003-中文路径-*/含 空格.js:2:3` 执行该命令，退出码为 0、stdout/stderr 均为空；临时文件已删除。未自动读取 GUI 光标。

## 修订记录

### 登记（2026-08-20）

已原子认领 DBG-003，并迁移已脱敏截图。

### Triage（2026-08-20）

已追踪 Claude Code 输出 `file:` 链接、iTerm2 Semantic History 与 VS Code CLI 边界。根因从 URI 格式收敛为 Default profile 命令缺少 `--goto`；放弃 `vscode://` 替换方案，原因是它不能稳定经过 Claude Code 的 OSC 8 链路。已通过 `code --help` 核实 `--goto <file:line[:character]>` 参数形态；未读取实际 VS Code 光标坐标，故未把 URI 交付成功表述为定位成功。

### Human 手动修复与回读（2026-08-20）

Human 原话：`itmer2的 profile里面 我已经手动修改好了`。已回读 iTerm2 Default profile 的 Semantic History：`action='command'`，`text='/opt/homebrew/bin/code --goto "\1:\2"'`，与规格锚一致；本实例未写入该偏好设置。已完成 A/B/C 的 CLI 自动验证，结果见「验证」章节。裁决：按 Human 手动修改和配置回读收尾，`status` 改为 `done`；不迁移为 `vscode://`，不修改插件源码。
