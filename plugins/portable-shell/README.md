# portable-shell

跨平台 shell 脚本强制 lint 插件。目标：**当 AI 生成 shell 脚本时，确保脚本同时兼容 Linux 与 macOS**。

## 为什么需要

Linux 与 macOS 的命令行工具链存在真实分裂，同一段脚本在一端能跑、另一端悄悄坏：

- **GNU coreutils（Linux）vs BSD userland（macOS）**：`sed -i`、`readlink -f`、`date -d`、`find -printf`、`grep -P`、`stat -c` 等在两端语义不同或根本不存在。
- **macOS 默认 bash 仍是 3.2**：关联数组 `declare -A`、`mapfile`/`readarray`、`${var^^}`/`${var,,}` 等 bash 4+ 特性在 macOS 默认环境不可用。

这些坑往往在犯错的当下最难自察。本插件把这套「隐性知识」在脚本刚被写出的那一刻精准回灌。

## 工作机理

一个 `PostToolUse` hook（`hooks/portable-shell-lint.js`，Node 实现），匹配 `Write|Edit|MultiEdit`：

1. 从工具入参取出被写入的文本与目标文件路径。
2. 判定是否为 shell 脚本（扩展名 `.sh/.bash/.zsh/.ksh`，或首行是 shell shebang）；不是则放行。
3. 对文本逐行静态扫描（跳过整行注释与 shebang，减少误报）13 类不可移植写法。
4. 命中即把「违规点（含行号与命中片段）+ 可移植改法」写入 stderr 并 `exit 2`——该反馈被喂回给 Claude，促其立即修正；文件已写入，不会回滚。
5. 无命中则静默 `exit 0`。

> `exit 2` 的语义是「stderr 反馈给 Claude」，不是回滚文件，因此形成「写 → 检出不可移植 → 立即改」的闭环，比每轮提示词注入更强、又比 `PreToolUse` 直接拒写更温和。

## 覆盖的规则（13 类）

| 严重度 | 写法 | 问题 |
|--------|------|------|
| 高 | `sed -i`（裸/空串形式） | GNU 需 `-i`、BSD 需 `-i ''`，冲突 |
| 高 | `readlink -f` | macOS 默认无此选项 |
| 高 | `date -d` / `--date` | GNU 专有，macOS 用 `date -v` |
| 高 | `find -printf` | GNU 专有 |
| 高 | `grep -P` / `--perl-regexp` | BSD grep 不支持 |
| 高 | `stat -c` / `--format` | macOS 用 `stat -f` |
| 高 | `declare -A` | 需 bash 4+，macOS 默认 3.2 |
| 高 | `mapfile` / `readarray` | 需 bash 4+ |
| 中 | `${var^^}` / `${var,,}` | bash 4+ 大小写转换 |
| 中 | `mktemp` 未带 `XXXXXX` 模板 | BSD 通常报错 |
| 低 | `realpath` | macOS 默认未安装 |
| 低 | `echo -e` | 跨 shell 转义行为不一致，建议 `printf` |
| 低 | `xargs -r` / `--no-run-if-empty` | GNU 专有 |

命中时报告会给出每条的可移植改法；确需平台专有特性时，建议在脚本内用 `case "$(uname -s)" in Darwin) ... ;; Linux) ... ;; esac` 分支并显式说明。

## 关闭

设置环境变量 `PORTABLE_SHELL_LINT=off`（或 `0` / `false`）即跳过检查。

## 说明

- 仅对**文件写入类工具**（Write/Edit/MultiEdit）生成的 shell 脚本生效，不拦截 `Bash` 工具的临时命令，避免噪声。
- Hook 只读脚本文本做静态扫描，不修改任何用户文件，无副作用。
- Hook 为 Claude Code 专有机制，Codex 侧不生效（本插件无 skill，故 Codex 无对应能力）。
