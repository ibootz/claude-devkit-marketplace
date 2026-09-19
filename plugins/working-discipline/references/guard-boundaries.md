# hook 边界：四道闸各自拦什么

这份是 working-discipline 四道 guard 的**真源**。注入文本里只留一句「闸存在、撞到照 finding 改一次、改完仍拦就报告用户」，各闸的判据、误杀面与自解除方式在这里。

每道闸命中时自己会给完整 finding 与 hint，所以这份主要供两种场合：撞闸后想知道判据边界、以及改 guard 前对照它原本承诺了什么。

<!-- SEC:guards -->

## 六、hook 在时机点强制的规则（撞到时会给出完整细则）

hook 按**拦截对象**收敛：一个对象一道闸，多条违规**一次报清**，撞到照 finding 一次改全。**判据是文本形态匹配或纯计数，而非语义判定**，每道闸都有实测过或已声明的误杀面：finding 明显对不上你的真实意图时按 hint 改一次，改完仍被拦而你确信无害就**报告用户拍板**，不要多轮试探正则边界。

- **`Bash`**（`guards/bash-guard.js`）只查 `agent-browser` 启动类子命令（`open` / `connect` / 带 URL 的 `chat`）：默认 headless、人类无法中途登录，故启动前必须已备好登录态（`--profile` / `--headers` / `--state` / `--restore` 任一），且先 `agent-browser session list` 数活动实例、≥4 时先 `close` 再开；另建议带 `--allowed-domains` + `--content-boundaries`（缺失仅提醒不阻断）。完整工作流见 `agent-browser` 插件 SKILL.md。**cwd 纪律独立于这道闸**：写 Bash 一律用 `(cd /abs/path && cmd)` / `git -C <path> <cmd>` / 全绝对路径，别发裸 `cd`——`pushd`、`source` 含 cd 的脚本、`eval "cd …"` 同样污染会话 cwd。裸 `cd` 由独立插件 `cd-blocker` 硬拦（3.26.0 从本插件拆出，可按项目单独停用；它只认「裸 `cd` 开头」一种形态）
- **`Agent`**（`guards/agent-dispatch.js`）校验 `model` / `name` / `description` 的结构。第一层 keeper 仍按 kind 固定档、4 位短哈希与 `debug 队列` / `chore 队列` 前缀。第二层仅精确 `task-keeper:debug-fixer-easy` / `medium` / `hard` 受 `easy=sonnet` / `medium=opus` / `hard=fable`、`<model>-debug-xxxx` 与全串简体中文 ≤15 code point description 约束；普通 Agent 不受此例外，`fable` 仍须 `opus` 两轮无进展。所有判据只读取本次 Agent input，不扫描 prompt。
- **`Read` / `Grep` / `Glob` / `Bash` 的节奏**（`guards/probe-throttle.js`，唯一不按对象、按**行为节奏**拦的一道，故 `Bash` 会过两道闸）：自上次 `Agent` 派发以来**逐个**发起的只读检索满 4 次起实时报数、满 6 次 deny 一次，把检查点②的决定点摆到你面前。**它是减速带不是墙**——deny 后同一段内不会再拦第二次，确认无 ≥2 个互不依赖待查项时**原样重发那次调用即放行**，不必改写命令、更不要为过闸凑一个假派发。**同一条消息里并发发出的调用判为同批、一次不计**，所以合并调用既是正解也天然不撞闸
- **`Write` / `Edit`**（`guards/write-guard.js`）：单一源码文件 >1000 行、当前项目内 `CLAUDE.md` >200 行会给提示。**它挂 `PostToolUse`，触发时文件已经写完了**——不回滚这次写入、也不停住本轮，指望不上它兜底，动笔前就要判断该不该拆（`CLAUDE.md` 拆到 `.claude/rules/{topic}.md`，不要靠压缩正文过闸——那会丢约束）

<!-- /SEC -->
