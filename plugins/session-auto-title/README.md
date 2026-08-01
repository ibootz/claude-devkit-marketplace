# session-auto-title

会话标题自动跟随话题：第 2 轮起后台生成标题，之后每 10 轮重算一次。

## 它补的是什么缺口

Claude Code 2.1.220 自己有一套自动命名（写进会话 jsonl 的 `ai-title` 行），但它**只生成一次**——触发条件是「本进程内第一条通过筛选的真人 prompt」，生成后有两道短路挡着：一是「已有 ai-title 就跳过」，二是一个 `useRef` 闸门，它在 `--resume` / `--continue` 拉起的进程里初值就是 true。所以聊到后面话题全变了，标题还停在第一句话上。

唯一的例外是退出 plan mode 时会用 plan 文本重算一次（生成的是 kebab-case 短名），除此之外没有任何路径会更新，也**没有任何 settings key 或环境变量能打开重算**。

这个插件用 hook 接管标题，按轮数周期性重算。

## 工作原理

hook 挂在 `UserPromptSubmit`，每轮只做三件不联网的快事：

1. **回填**：读缓存，如果有上一轮后台生成好的新标题，通过 `hookSpecificOutput.sessionTitle` 交给 Claude Code
2. **计数**：扫 transcript 数真人轮数（排除 `tool_result`、meta 行、斜杠命令、XML 包封）
3. **决定**：够轮数且没有生成在跑，就 detached spawn 一个后台进程去生成

标题生成在 `hooks/generate-title.js` 里，它拿最近 6 条 prompt 调一次 Haiku 4.5，结果写进 `$TMPDIR/claude-auto-title/<sessionId>.json`。

**标题永远慢一轮**——第 N 轮触发生成，第 N+1 轮才显示出来。这是刻意的：`UserPromptSubmit` 是阻塞 hook，跑多久用户就等多久，而调模型要几秒。把生成放后台是唯一能做到零卡顿的方式。

## 参数

都在 `hooks/lib/shared.js` 顶部：

| 常量 | 默认 | 含义 |
|---|---|---|
| `FIRST_TURN` | 2 | 第几轮首次生成 |
| `REGEN_INTERVAL` | 10 | 之后每隔多少轮重算 |
| `MODEL` | `claude-haiku-4-5-20251001` | 与 Claude Code 内建自动命名同一档 |
| `LOCK_STALE_MS` | 120000 | 锁超时，超过认为那次生成已死 |
| `RECENT_PROMPTS` | 6 | 喂给模型的最近几条 prompt |

成本：单次约 400-600 输入 token，1e-4 美元量级。按默认参数一个 50 轮的会话生成约 5-6 次。

## 标题显示在哪

装了之后这四处能看到（与 `/rename` 完全一致，因为走同一条 `r7e` 落地路径）：

1. **输入框顶部边框上的彩色徽章** —— 常驻，最显眼
2. **终端标签页/窗口标题栏** —— 通过 OSC 0 转义序列写出，可用 `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` 关掉
3. **`/status` 面板的 "Session name" 行** —— 按需打开
4. **`/resume` 会话列表每行** —— 以及 `/resume <关键词>` 的补全项

看不到的地方：对话滚动区没有常驻标题；内置 footer（模型名、上下文百分比那行）不含标题——它只把标题作为 `session_name` 字段传给自定义 statusLine 脚本。

## 三个必须知道的约束

**它会永久接管标题。** hook 写的是 `custom-title`，而 custom-title 一旦存在，内建自动命名的门禁就恒为真，从此内建机制完全不工作。这不是「双保险」而是「取代」——关掉本插件后，已有 custom-title 的老会话也不会恢复自动命名。

**必须挂 `UserPromptSubmit`，不能改挂 `SessionStart`。** 两个事件的 schema 都有 `sessionTitle` 字段，但落地函数不同：`UserPromptSubmit` 写 jsonl，`SessionStart` 只改内存——终端标题和徽章会变，但 `/resume` 列表里永远看不到。

**agent-team 模式下整体不生效。** 开了 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` 时，teammate 会话被 Claude Code 硬拒改名（`/rename` 也会明说 `Teammate names are set by the team leader`）。这一点从代码逻辑确认，未实测。

## 防递归

后台起的 `claude -p` 自身也是一个 Claude Code 会话，也会触发本 hook。不拦就是每个生成进程再生成一个。两道防护：

- 子进程带 `CLAUDE_AUTO_TITLE_CHILD=1` 环境变量，hook 第一件事就是检查它并直接退出
- 每会话一个带时间戳的锁文件，`LOCK_STALE_MS` 内不重复发起；进程被 `kill -9` 留下的孤儿锁会按 mtime 自动失效，不需要清理进程

## 维护约定

- 改判据前先跑回归。测试用 `spawnSync` 喂 JSON 到 stdin、**不经过 shell**（经过 shell 的测试脚本一旦引号失衡，会把测试数据当成真命令）。
- 端到端验证生成器：`TMPDIR=<沙箱> node hooks/generate-title.js <sessionId> <transcript.jsonl> <turn>`，然后看 `$TMPDIR/claude-auto-title/<sessionId>.json`。
- 本插件的 hook 不做任何拦截（不输出 `permissionDecision`），只输出 `sessionTitle`，因此不受 `.claude/rules/hook-restraint.md` 的判据要求约束——但它**确实会改变可见状态**，比纯注入类 hook 责任重，改判据仍需谨慎。
- 版本登记三处：本目录 `plugin.json` + 仓库两份 marketplace 清单，改完跑 `node scripts/check-versions.js`。
