---
name: orphan-process-cleaner
description: "查找与清理游离的 Claude Code 子进程。Use when: 用户说\"有没有游离进程\"、\"清理孤儿进程\"、\"之前启动的服务还在跑\"、\"会话压缩后丢失了后台任务\"、\"背景任务引用丢失\"、\"TaskList 找不到但进程还在\"、\"cleanup orphan\"。适用于 Linux/WSL 环境，自动识别 claude 发起但已失去 Task 句柄的后台进程并安全终止。"
---

# Orphan Process Cleaner（游离进程清理）

## 你要做什么

作为系统侦探，找出所有由 Claude Code 发起但已**失去 TaskList 句柄**的后台服务进程，评估后安全终止。

## 什么是"游离进程"

Claude Code 通过 `run_in_background: true` 启动 Bash 任务时，会创建子 zsh 进程。若发生以下任一情况，Task 句柄就会丢失：
- 会话被压缩（context compression）
- 用户手动 `/clear`
- Claude Code 实例重启
- Worktree 切换导致上下文切断

此时进程本身仍在运行，但：
- `TaskList` 中无对应记录
- `TaskOutput` 无法再获取输出
- 进程成为"孤儿"，占用端口和内存

## 执行工作流

### 第一阶段：识别 Claude Code 进程树

```bash
# 1. 找出所有 claude 主进程
ps aux | grep -E "\bclaude\b" | grep -v grep

# 2. 对每个 claude PID，查其直接子 zsh（= 后台任务壳）
ps -o pid,ppid,stat,cmd --ppid <claude_pid>

# 3. 查看 zsh 下的真实服务进程
pstree -p <zsh_pid>
```

### 第二阶段：判断是否游离

| 判断条件 | 命令 |
|----------|------|
| TaskList 是否有记录 | （在 Claude 内）调用 `TaskList` tool |
| 父 claude 是否存活 | `ps -p <ppid>` |
| zsh 是否有 tty | `ps -o tty -p <zsh_pid>`（`?` = 后台，无 tty） |
| 启动命令是否含 shell-snapshot | `ps -o cmd -p <zsh_pid>` 含 `shell-snapshots/snapshot-*` |

**游离判定**：`TaskList` 中无对应任务 + zsh 状态为 `Ss`（session leader，无 tty）= 游离进程

### 第三阶段：确认服务类型

```bash
# 查看进程树，确认是什么服务
pstree -p <zsh_pid>

# 常见类型：
#   java → Spring Boot / Maven 应用
#   node → 前端 dev server / Node.js 服务
#   python → FastAPI / Flask 服务
#   mvn  → Maven 构建
```

### 第四阶段：安全终止

```bash
# 第一步：SIGTERM（优雅关闭，给应用清理机会）
kill <service_pid>
sleep 2

# 第二步：确认是否已退出
ps -p <service_pid> 2>/dev/null || echo "已退出"

# 第三步：若仍存在，SIGKILL
kill -9 <service_pid>
```

> **注意**：终止 zsh 壳（父进程）或直接终止服务进程（子进程）均可。推荐终止服务进程本身（java/node），更精准。

## 快速诊断命令（一键扫描）

```bash
# 找出所有 claude 发起的后台 zsh（shell-snapshot 特征）
ps aux | grep "shell-snapshots/snapshot" | grep -v grep | \
  awk '{print $2, $8, $11}' | head -20
```

```bash
# 查看某 claude 进程下的所有子进程树
pstree -p $(pgrep -x claude | head -1)
```

## 常见场景

### 场景 1：Java 服务对 SIGTERM 无响应

```bash
# Spring Boot 某些配置下忽略 SIGTERM
kill -9 <java_pid>   # 直接用 SIGKILL
```

### 场景 2：多个 claude 实例（--dangerously-skip-permissions）

```bash
# 列出所有 claude 实例和它们的 PID
ps aux | grep "\bclaude\b" | grep -v grep | awk '{print $2, $11, $12}'
# 检查哪个是当前会话（当前 pts/X），哪个是后台实例
```

### 场景 3：不确定该不该杀

- 询问用户："PID xxx 是 `java mix2api.jar`，启动于 16:28，确认终止吗？"
- **永远不要静默终止用户可能关心的服务**

## 操作约束（必须遵守）

1. **只读扫描**：识别阶段只用 `ps`、`pstree`，不做任何写操作
2. **必须确认**：终止进程前必须向用户展示进程信息并获得确认
3. **不终止父 claude**：只清理 claude 发起的**子服务进程**，绝不 kill claude 主进程
4. **SIGTERM 优先**：先尝试优雅关闭，2 秒内不响应再用 SIGKILL

## 常见错误

| 错误 | 原因 | 修正 |
|------|------|------|
| kill 后进程仍存在 | Java/某些服务忽略 SIGTERM | 用 `kill -9` |
| 误杀在用服务 | 未确认是否仍在使用 | 终止前询问用户 |
| 找不到游离进程 | claude 父进程已退出，孤儿被 init 接管 | `ps aux | grep "shell-snapshots"` |
| PPID 对不上 | 多层进程嵌套 | 用 `pstree` 追溯根节点 |
