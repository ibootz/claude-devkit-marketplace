---
name: restore-subscription
description: 把因自定义模型配置（第三方 API 中转 / 本地 LLM）而回不到 Claude 订阅鉴权的会话切回订阅。定位三层污染源（shell 环境变量 / settings 文件的 env 段 / daemon 进程继承），用 `--settings` 空串覆盖起新会话替换旧会话，并自动沿用旧会话的显示名，全程保住对话历史。判据落在 transcript 的实际应答模型上，不信"看起来切过去了"。仅 macOS 实证。
when_to_use: |
  用户说"切回订阅"、"不想用 apikey 了"、"改回官方模型"、"会话里改了不生效"、"还是走的第三方"、"base_url 怎么还是旧的"、"/login 了没用"、"提示 Invalid API key"、"提示 Both claude.ai and ANTHROPIC_API_KEY set"、"agent 全在报 429 但我订阅还有额度"、"横幅显示 API Usage Billing 不是我的订阅"、"用了 GLM/DeepSeek/Kimi/本地 LM Studio 之后回不去了"。
  **核心触发判据**：当前或某些会话正在用非 Anthropic 官方的鉴权（`ANTHROPIC_BASE_URL` 指向第三方、或 `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` 是中转 key），而用户想让它们改用自己的 Claude 订阅账号，且**不想丢失这些会话已有的对话历史**。
  **另一类触发是诊断性的，不要漏**：用户并没有说"切回订阅"，而是报告一个看起来无关的现象——某几个后台 agent 全部卡在同样的 429 限流、且重置时间逐秒相同；或者新起的会话莫名其妙报 Invalid API key。这类现象的根因常常就是本 skill 处理的污染，先按"症状与判据"一节确诊再说。
  **不适用**：用户本来就想用第三方模型、只是想换一个 key 或换个中转商（那是改配置，不是切回订阅）；用户问的是订阅额度本身用完了怎么办（那是等窗口重置或升级套餐，本 skill 帮不上）。
---

# Restore Subscription（切回订阅鉴权）

## 你要做什么

有会话在用第三方 API 中转（或本地 LLM）跑，用户想让它改用 Claude 订阅账号，且不想丢历史。你要做的不是"在会话里改个设置"——那条路走不通，原因见下一节。你要做的是：**定位污染源 → 起一个干净的新会话去接管旧会话的历史与显示名 → 用 transcript 里的实际应答模型证明切成功了**。

> **平台边界**：本 skill 的所有命令与结论均在 macOS 上实证（Darwin 25.5.0，Claude Code 2.1.233）。其中 `ps eww -o command= -p <pid>` 是 BSD `ps` 读取进程环境变量的写法；Linux 上应改用 `tr '\0' '\n' < /proc/<pid>/environ`，且 `/proc` 方式更可靠。判据逻辑跨平台通用，命令形态需按平台替换。

## 为什么会话内改不掉

`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` 都是**进程启动时读取一次**的环境变量，官方文档原话是 "Shell environment variables are read at startup, so changes take effect on the next launch of `claude`"。而在鉴权优先级链上，它们排在订阅 OAuth 之上：

```
云厂商凭据（Bedrock/Vertex/Foundry）
  > ANTHROPIC_AUTH_TOKEN
  > ANTHROPIC_API_KEY
  > apiKeyHelper
  > CLAUDE_CODE_OAUTH_TOKEN
  > /login 写入的订阅 OAuth 凭据        ← 排最后
```

所以 `/login` 会正常完成、也会正常写入新凭据，但只要那两个环境变量还在，鉴权仍然用它们。官方文档对这个场景有直接的一句话："If you have an active Claude subscription but also have `ANTHROPIC_API_KEY` set in your environment, the API key takes precedence once approved."

**推论**：想切回订阅，只能换一个进程；能省下的只是"会话历史"，省不了"重启进程"这件事。

## 三层污染源（先定位，别急着改）

变量可能从三个地方来。**按顺序排查，不要在第一层查不到就下结论**——最容易漏的是第三层，而它恰恰最常见。

| 层 | 排查命令 | 说明 |
|---|---|---|
| ① shell 环境 | `env \| grep ANTHROPIC` + 翻 `~/.zshrc` `~/.zshenv` `~/.zprofile` `~/.bash_profile` | 最直观，但**查不到不代表没被污染** |
| ② settings 文件的 `env` 段 | `grep -rl ANTHROPIC ~/.claude/*.json <项目>/.claude/settings*.json` | 两类都要查：**默认加载的 `~/.claude/settings.json`**（模型切换工具如 `cc-switch` 直接改它），以及非默认文件名（如 `settings.glm.json`，靠 `--settings <file>` 加载）。**两者的 `env` 段都会被注入 `process.env`** |
| ③ daemon 进程继承 | `ps -eo pid,command \| grep 'claude daemon run'` 拿到 pid 后 `ps eww -o command= -p <pid> \| tr ' ' '\n' \| grep '^ANTHROPIC'` | **最隐蔽也最关键**：daemon 由某个加载过第②层配置的 `claude` 拉起，此后**一切由它承载的后台会话都继承这套变量**，与你当前 shell 干不干净无关 |

第③层的存在导致一个反直觉现象，必须记住：

> **后台会话中不中毒，取决于 daemon 的环境，不取决于你敲命令那个终端的环境。**
> 交互式会话（终端里直接敲 `claude`）环境来自你那个 shell，所以它可能是干净的，而同一台机器上的后台会话全是脏的。

### 会话形态是可变的：进 agents 视图就换阵营

**不要把"交互式会话"当成一个稳定属性。** 实测：把一个走订阅的交互式会话切进 `claude agents` 管理视图再切回来，它会被转成后台（bg）形态、改由 daemon 承载，于是当场继承带毒环境、下一个请求 401。

判据在 transcript 里，每条消息都带 `sessionKind` 字段：

```json
{"isApiErrorMessage":true,"apiErrorStatus":401,"sessionKind":"bg",
 "sessionId":"54ff7d6d-...","text":"Invalid API key · Fix external API key"}
```

这条 401 属于一个用户以为是 interactive 的会话，而出错那一刻 `sessionKind` 是 `bg`。伴随现象是 session id 与承载进程双双变更（形态转换伴随进程重建，不是原地改状态）。

**推论**：daemon 带毒期间，agents 视图是个传染入口——每进去一次，当前会话就被污染一次。这比"只有后台会话受影响"严重得多，因为 agents 视图是日常入口。查会话是否被污染时，**查 transcript 的 `sessionKind` 与应答模型，不要查进程 env**——后者在形态可变时会给出错误的安心。

## 症状与判据

**唯一自证的判据是 transcript 里的实际应答模型**，其余都是旁证：

```bash
grep -o '"model":"[^"]*"' ~/.claude/projects/<项目目录名>/<session-id>.jsonl | sort | uniq -c
```

出现 `glm-*` / `qwen/*` / 其它非官方模型名 = 仍在走第三方；出现 `claude-opus-*` / `claude-sonnet-*` = 已在订阅上。

辅助信号（用于快速判断，不作最终结论）：

| 信号 | 含义 |
|---|---|
| 启动横幅 `· API Usage Billing` | 在用 API key 计费 |
| 启动横幅 `· Claude Team` / `Claude Max` / `Claude Pro` | 在用订阅 |
| `⚠ Both claude.ai and ANTHROPIC_API_KEY set · auth may not work as expected` | 两套凭据并存，API key 会赢 |
| `Invalid API key · Fix external API key` | 有 key 但打到了官方端点（`BASE_URL` 没跟着一起传） |
| 多个会话同时 429 且**重置时刻逐秒相同** | 共用同一个上游配额 → 大概率同一个第三方 key |

**不要用这些当判据**：`/login` 是否成功（成功了也可能被 env 压过）；进程 env 是否干净（第③层污染在进程 env 里看不出来）；`claude agents` 面板显示什么（那是账本，不是实时鉴权状态）。

## 执行工作流

### 第一阶段：清点要救的会话

```bash
claude agents --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  for (const x of JSON.parse(s)) console.log(x.kind, x.status, x.sessionId, x.pid, JSON.stringify(x.name), x.cwd)})'
```

`claude agents --json` 不需要 TTY，是脚本化的唯一入口。**承载显示名的字段是 `name`，不是 `title`**（对象的完整 key 列表是 `pid,id,cwd,kind,startedAt,sessionId,name,status,state`）——按 `title` 取会全是 `undefined`，据此得出"这些会话没有名字"是错的。

把每个会话的 `sessionId`、`cwd`、`pid`、`name` 四项**成组记下来**，后面三步都要按组取用。

### 第二阶段：对照实验（一次调用的成本，不要跳过）

在动任何现存会话之前，先起一个一次性会话验证解法在这台机器上真的有效：

```bash
claude --bg --settings '{"env":{"ANTHROPIC_API_KEY":"","ANTHROPIC_AUTH_TOKEN":"","ANTHROPIC_BASE_URL":""}}' \
  "Reply with exactly one word: PING"
```

等十几秒后看它的应答模型（用第一阶段的命令拿到它的 sessionId，再用"症状与判据"一节的 grep）。出现 `claude-*` 才继续往下走；仍是第三方模型名说明这台机器上还有本 skill 没覆盖的第四层来源，停下来重新排查，**不要带着未验证的解法去动用户的真实会话**。

验完记得停掉它：`claude stop <返回的短 job id>`。

### 第三阶段：抽取旧会话的显示名（自动化，不要问用户）

**这一步不能省，也不该让用户手打名字。** 名字必须在停掉旧会话**之前**抽出来存好——一旦进程终止，`~/.claude/jobs/` 下的状态文件可能被清理，届时只剩 transcript 这一条退路。

名字有两个来源，按顺序取，取到即止：

```bash
# 来源 A（首选）：会话还活着时，直接从 agents 账本取 name —— 与面板显示逐字一致
claude agents --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  for (const x of JSON.parse(s)) if (x.name) console.log(x.sessionId + "\t" + x.name)})' > /tmp/session-names.tsv

# 来源 B（退路）：进程已死时，从 transcript 里抽最后一条标题记录
grep -o '"customTitle":"[^"]*"' ~/.claude/projects/<项目目录名>/<session-id>.jsonl | tail -1
grep -o '"aiTitle":"[^"]*"'     ~/.claude/projects/<项目目录名>/<session-id>.jsonl | tail -1
```

`customTitle` 是用户手动设的（`/rename`、agent-view 里 `Ctrl+R`、启动时 `--name`），`aiTitle` 是模型自动摘要的；两者都可能有多条记录，**取最后一条**。有 `customTitle` 就用它，没有才退回 `aiTitle`。

**为什么必须显式传名字、不能指望 `--resume` 自动带过来**：一个会话的显示名可能被用户中途手动改过，也可能是模型自动摘要的，这两者在磁盘上落在不同字段、由不同机制维护。与其判断"这次会不会继承"，不如**一律显式传 `--name`**——这是确定性做法，成本只是多一个参数。

### 第四阶段：停掉旧会话

```bash
claude stop <短 job id>        # 首选：既停进程，也清 agents 账本条目
kill -TERM <pid> [<pid>...]    # 退路：claude stop 报 "No job matching" 时用
sleep 4 && ps -p <pid>,... -o pid=   # 核验，期望无输出
```

**`claude stop` 只认当前 daemon 自己派发的 job（那个 8 位短 id），不认更早的 daemon 起的会话**——对后者会报 `No job matching '<session-id>'`，此时只能用 `kill`。

**但要清楚 `kill` 清不掉什么**：它只终结进程，`claude agents` 的账本条目会留下来变成状态为 `undefined` 的僵尸行，用户在面板上仍然看得见。这不是没杀掉，是两套状态。僵尸条目需要用户在 agent-view TUI 里 `Ctrl+X` 移除。**收尾时要主动向用户说明这一点**，否则用户看到面板上还有就会认为你没做成。

### 第五阶段：带干净 settings + 原标题恢复

按第三阶段存下的名字，逐个会话恢复：

```bash
S='{"env":{"ANTHROPIC_API_KEY":"","ANTHROPIC_AUTH_TOKEN":"","ANTHROPIC_BASE_URL":"","ANTHROPIC_DEFAULT_OPUS_MODEL":"","ANTHROPIC_DEFAULT_SONNET_MODEL":"","ANTHROPIC_DEFAULT_HAIKU_MODEL":""}}'
(cd <旧会话的 cwd> && claude --resume <session-id> --bg --settings "$S" --name "<第三阶段抽到的名字>" --model 'opus[1m]')
```

四个参数缺一不可，逐个说明为什么：

- **`--settings` 传空串**：这是本 skill 的核心手法。settings 的 `env` 段能覆盖同名变量，空字符串会让 Claude Code 判定为未设置，从而落回订阅 OAuth。把 `ANTHROPIC_DEFAULT_*_MODEL` 一并清掉，否则模型别名仍指向第三方模型 id。
- **`--name`**：锁死显示名。若这台机器上已有活跃会话同名，Claude Code 会自动追加两词后缀（如 `-sequential-rabbit`），这是正常行为不是失败；想避免就先确认旧会话已经停干净。
- **`--model`**：**必须显式给**。不给则延续原会话记录的模型（可能是 `glm-5.3` 这种订阅下不存在的 id）。
- **`cd` 到原 cwd**：会话与项目目录绑定，起错目录会读到错的 CLAUDE.md 与项目设置。

**不要加 `--allow-dangerously-skip-permissions` 或 `--permission-mode bypassPermissions`**：这两个标志会被 auto mode classifier 拦下、整条命令被拒。去掉即通过。代价是恢复出来的会话在需要权限时会停下等确认——若用户原本就是无人值守跑的，把这个代价明确告诉他，由他决定是否自己在终端里带上这些标志重开。

### 第六阶段：写后回读

恢复出来的会话默认是 `idle`（等 prompt），此时还没发过真实请求，**拿不到 transcript 级证据**。必须等它真跑过一轮再验：

```bash
# 1. 确认 session id 未变、历史在续写（不是新建了一个空会话）
ls -lt ~/.claude/projects/<项目目录名>/<session-id>.jsonl     # mtime 应更新到刚才
ps -eo command= | grep -- '--resume'                          # 命令行应指向原 jsonl 路径

# 2. 名字是否落对
claude agents --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  for (const x of JSON.parse(s)) console.log(x.sessionId.slice(0,8), JSON.stringify(x.name))})'

# 3. 跑过一轮后，验实际应答模型
grep -o '"model":"[^"]*"' ~/.claude/projects/<项目目录名>/<session-id>.jsonl | sort | uniq -c | tail -3
```

第 3 项出现 `claude-*` 才算成。**在拿到这条证据之前，不要向用户报告"已切回订阅"**——只能报告"已恢复，鉴权待首轮请求后验证"。

## 快速诊断命令（一键扫描）

```bash
echo "=== ① shell ==="; env | grep ANTHROPIC | sed -E 's/=(.{0,8}).*/=\1…/' || echo "(clean)"
echo "=== ② settings 文件 ==="; grep -rl ANTHROPIC ~/.claude/*.json 2>/dev/null || echo "(none)"
echo "=== ③ daemon ==="; for p in $(pgrep -f 'claude [d]aemon run'); do
  echo "daemon pid=$p"; ps eww -o command= -p $p | tr ' ' '\n' | grep -E '^ANTHROPIC' | sed -E 's/=(.{0,8}).*/=\1…/'
done
echo "=== 活跃会话 ==="; claude agents --json | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  for (const x of JSON.parse(s)) console.log(" ", x.kind, x.status, x.sessionId.slice(0,8), JSON.stringify(x.name))})'
```

## 根治：换掉带毒 daemon（可由 AI 全自动完成，已实证）

上面的流程每次都要传 `--settings` 覆盖。换掉 daemon 本身可一劳永逸——**换完之后新起的后台会话默认就走订阅，不必再传 `--settings`**。

**AI 能不能自己做**：能，但有一个硬前提——**AI 当前会话的进程链必须是干净的**。先验证再动手：沿 `$$` 逐级取 `ppid`，对链上每个进程跑 `ps eww -o command= -p <pid>` 并数 `^ANTHROPIC` 的行数，全为 `0` 才能继续。不为 `0` 说明 AI 自己就在带毒环境里，它触发生成的新 daemon 同样带毒，此时必须交给用户从干净终端做。

### 前置认知

daemon 是 `claude daemon run --origin transient`，`ppid=1`，**不受 launchd 托管**（`launchctl list | grep -i claude` 只有桌面版更新服务 `com.anthropic.claudefordesktop.ShipIt`）。所以终止它不会被自动拉起，而是**下次有人需要时按需新建一个，继承那个发起者的环境**——这正是自动化可行的原因：AI 自己的 Bash 环境干净，由它触发的新建就产出干净 daemon。

**终止 daemon 不会丢会话**（已实证）：pty-host 子进程会被 init 收养、`ppid` 变 `1` 后继续运行，会话照常服务。会话内容也不在进程里——transcript 实时写在 `~/.claude/projects/<项目>/<session-id>.jsonl`。

### 步骤

1. **存盘会话名单**（含 `name`，后面要靠它恢复）：用第一阶段那条 `claude agents --json` 命令，输出重定向到一个临时 tsv 文件。

2. **终止 daemon 进程**：`pgrep -f 'claude [d]aemon run'` 取到 pid，然后 `kill -9 <那个 pid>`。**SIGTERM 对它无效**（见下面坑一），直接用 `-9`。等 3 秒后再 `pgrep` 一次确认已消失。

3. **触发新建 daemon**：起一个一次性探针，它既触发新建又兼作验证——
   ```bash
   claude --bg "Reply with exactly one word: PONG"
   ```

4. **验新 daemon 干净**（成败判据）：`pgrep -f 'claude [d]aemon run'` 取新 pid，`ps eww -o command= -p <新pid> | tr ' ' '\n' | grep -cE '^ANTHROPIC'` 必须输出 `0`。

5. **验探针真走了订阅**：
   ```bash
   claude logs <探针短 id> | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' \
     | grep -aoE 'Claude Team|Claude Max|Claude Pro|API Usage Billing|Invalid API key' | sort -u
   ```
   只出现 `Claude Team`/`Max`/`Pro`、且无 `API Usage Billing` 与 `Invalid API key` 即成功。验完 `claude stop <探针短 id>`。

### 两个实测坑

**坑一：SIGTERM 对 claude 进程无效。** 这些进程装了 term handler，`kill -TERM` 之后实测 14 个目标全数存活。按常规纪律仍应先 TERM、核验、再升级 KILL，但要预期 TERM 这一轮必然不生效，不要因此以为"信号没送达"而跑去查权限或属主。

**坑二：部分 pty-host / bg-spare 连 `kill -9` 都杀不掉。** 实测 daemon 本体与一部分子进程能终止，另一些 `kill` 返回 `exit=0`（信号已送达）但进程状态始终是 `S`（正常睡眠、非僵尸态 `Z`），反复终止无效。**撞到就停手，不要试第四种杀法**——旧 daemon 已死、新 daemon 已干净，这些残留只影响挂在它们下面的旧会话，不影响新会话。把它们交给用户在 agents 视图里 `Ctrl+X` 清理，然后再按存盘名单 resume。

### 换完之后

新 daemon 干净后，第五阶段的 `--settings` 覆盖参数**可以不传了**（传了也无害）。但 `--name` 与 `--model` 仍要传，理由不变。

### 换 daemon 治标不治源：决定性的是「谁第一个拉起 daemon」

**daemon 按需新建、之后常驻。第一个触发它诞生的进程的环境，就是它此后一直带着的环境。** 推论有二，都反直觉：

- 某次用第三方配置（如 `claude --settings ~/.claude/settings.glm.json`）起过一次 claude → daemon 诞生即带毒 → 此后**所有**后台会话都脏；
- 之后再用干净配置起 claude → **daemon 已经在了、不会重建** → 照样脏。

这解释了最常见的困惑："我明明没设任何环境变量，为什么会中毒"——中毒发生在很久以前那一次启动，而 daemon 一直没换过。

所以换掉 daemon 只清掉当前实例，**不阻止下次复发**。复发条件很明确：在带那套变量的环境里再启动一次 claude，且当时没有活着的 daemon。

### 典型成因：模型切换工具改了配置，但不管已在跑的 daemon

这是最常见的一条完整链路（实测复盘，用户自述 + 时间戳互证）：

1. 用 `cc-switch` 之类的模型切换工具，往**默认加载的** `~/.claude/settings.json` 的 `env` 段写入第三方配置；
2. 此时启动一次 `claude`（该实测中是 `claude agents`）——这个进程读 settings.json、把 `env` 注入自身 `process.env`，并**顺手 spawn 出 daemon**，daemon 就此带毒；
3. 后来用同一个工具切回订阅，settings.json 的 `env` 段被清干净；
4. **但没有任何工具会去管那个已经在跑的 daemon**，它继续带着第 2 步那一刻的环境快照，服务此后所有后台会话。

时间戳可以直接验证这条链路是否发生过——比较 daemon 的启动时刻与 settings.json 的 mtime：

```bash
ps -o lstart= -p $(pgrep -f 'claude [d]aemon run' | head -1)   # daemon 诞生时刻
stat -f "%Sm" ~/.claude/settings.json                          # 配置最后修改时刻
```

**配置的修改时刻晚于 daemon 诞生时刻**，就说明二者已经分叉：daemon 停留在旧配置上，而你看到的配置文件是新的。该实测中两者相差 54 分钟。

这条也解释了排查时最容易卡住的地方：**`settings.json` 是干净的，daemon 却是脏的**。因为进程环境是启动那一刻的快照、配置文件是当下的状态，**两者会分叉且分叉不留任何痕迹**——没有报错、没有警告，只有那个查不出来源的鉴权失败。

同类工具（`claude-swap`/`cswap` 等）读过源码确认同样**不含任何 kill/restart daemon 的逻辑**，只管改凭据与配置文件。所以这不是某一个工具的缺陷，而是这类工具的共性：**它们管配置，不管进程**。

**预防判据（一句话）**：**用这类工具切换过配置之后，把换 daemon 当作切换动作的一部分**；或者反过来——切换之前先确认没有活着的 daemon。

### 日常自检（比事后排查便宜得多）

用第三方模型跑完、要切回订阅干活之前，先验一句：

```bash
ps eww -o command= -p $(pgrep -f 'claude [d]aemon run' | head -1) | tr ' ' '\n' | grep -cE '^ANTHROPIC'
```

`0` 即干净，直接用；非 `0` 就走上面的「步骤」换 daemon。事前一条命令，事后要面对的是一堆已经跑脏、还得逐个 resume 的会话。

**另外注意**：换完 daemon 后不必急着杀旧 agent。新起的会话自动干净，旧会话只在你还要继续用它们时才需要 resume 替换；否则让它们自己跑完即可。

## 常见场景

### 场景 1：只有一个会话要救
跳过第一阶段的清点，直接三→四→五→六。

### 场景 2：用户说"面板上还能看到旧的，你没杀掉"
先复查进程（`ps -p <pid> -o pid=`），全为空即进程已死。那么用户看到的是账本僵尸条目，告诉他按 `Ctrl+X` 移除，并解释这是两套状态。**不要因为用户说"没杀掉"就再杀一遍或改用 `kill -9`**——先分清他看的是哪一层。

### 场景 3：验证发现仍走第三方
说明存在本 skill 三层之外的来源。此时**不要反复重试同一条命令**，回到第二阶段的对照实验，用一个全新会话隔离变量，把 `claude logs <job>` 的启动横幅原文（`sed 's/\x1b\[[0-9;]*[a-zA-Z]//g'` 清掉 ANSI 转义后）交给用户判断。

### 场景 4：恢复出来的会话自己跑起来了
`--resume` 出来的会话可能不是停在 idle，而是接着原会话最后的待办继续执行（`state` 字段为 `working`）。若用户的订阅额度紧张，**主动提示他**，由他决定是否让它们先停手。

## 操作约束（必须遵守）

1. **停会话前先确认 pid 与 sessionId 的对应关系**，用 `cwd` 交叉核对。杀错会话是不可逆的（历史还在，但在跑的工具调用会断）。
2. **名字必须在停掉旧会话之前抽出来**。顺序反了就只剩 transcript 一条退路，且可能已经取不到。
3. **不替用户杀 daemon**。影响面超出单个会话，且需要用户提供干净终端，见"根治"一节。
4. **不回显 key 的实际值**。所有涉及 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 的输出一律截断脱敏（`sed -E 's/=(.{0,8}).*/=\1…/'`）。
5. **`--settings` 里只清鉴权相关变量**，不要顺手清 `CLAUDE_CODE_*` 那些（它们控制上下文窗口、effort 等，清掉会改变用户原有的运行参数）。
6. **拿到 transcript 级证据前不报成功**，见第六阶段。
7. **额度提醒**：切回订阅意味着开始消耗订阅额度。恢复多个会话前，先看一眼启动横幅里的用量提示（形如 `You've used 86% of your weekly limit · resets ...`）并转告用户。

## 常见错误

| 错误 | 原因 | 修正 |
|---|---|---|
| 查了 shell 和 settings 都干净，就断定"没被污染" | 漏掉第③层 daemon 继承 | 三层都查完再下结论 |
| 查进程 env 干净，就断定该会话没被污染 | 会话形态可变，进 agents 视图会转 bg 归 daemon 管 | 查 transcript 的 `sessionKind` 与应答模型 |
| `kill -TERM` 后进程还在，就去查权限 / 属主 | claude 进程装了 term handler，忽略 SIGTERM | 预期 TERM 不生效，核验后直接升 `kill -9` |
| 按 `title` 字段读会话显示名，得到全空 | 字段实际叫 `name` | 用 `name` |
| `kill` 之后看 `ps` 为空就报"已全部终止" | 用户看的是 `claude agents` 账本，不是 `ps` | 复查用户看得到的那一层，并说明僵尸条目需 `Ctrl+X` |
| `claude stop <session-id>` 报 No job matching 就以为会话不存在 | `stop` 只认当前 daemon 的短 job id | 改用 `kill <pid>` |
| 先停会话再想起要取名字 | jobs 状态文件可能已被清理 | 停之前先抽名字存盘 |
| `--resume` 不传 `--model` | 延续原会话记录的第三方模型 id，订阅下不存在 | 显式传 `--model` |
| `--resume` 不传 `--name`，指望它自动继承 | 显示名由多套机制维护，继承与否不确定 | 一律显式传 `--name` |
| 命令里带 `--allow-dangerously-skip-permissions` | 被 auto mode classifier 拒绝，整条命令不执行 | 去掉；需要免权限时让用户自己在终端加 |
| 用 `timeout` 给命令加超时 | macOS 无此命令 | 不加，或用 `gtimeout`（需 coreutils） |
| 直接改 `~/.claude/jobs/<short>/state.json` 的 `name` | 该文件由 daemon 周期性写入，手改可能被覆盖 | 走 `--name` 参数或会话内 `/rename <新名>` |
