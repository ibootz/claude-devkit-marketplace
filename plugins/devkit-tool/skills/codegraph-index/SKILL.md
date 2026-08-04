---
name: codegraph-index
description: "判断一个仓库该不该建 codegraph 代码知识图谱、什么时候建、worktree 要不要各自建，以及建完怎么用（含实测的体积/耗时/内存阈值与已验证的坑）。codegraph 是 tree-sitter 抽符号 + 调用边存本地 SQLite 的代码图，不是文档知识图谱。本 skill 只用 CLI，明令禁止接 MCP。"
when_to_use: |
  用户说"给这个项目建知识图谱"、"装/部署 codegraph"、"索引这个仓"、"用图谱省 token"、"这个仓值不值得建图"、"worktree 要不要单独建图"、"codegraph 查不到东西"、"codegraph db 太大/索引太慢/内存占太多"、"卸掉 codegraph"、"codegraph 图过期了"、"explore 返回一大坨"、"codegraph 要不要接 MCP"。
---

# CodeGraph Index（代码知识图谱建图决策与运维 · CLI-only）

**验证基础**：2026-08-01/02 在 `xxstar-ai-spsd-work`（3.0G 聚合仓、22 个 submodule、Java + Vue/JS/TS 混合）与其 D-001 worktree 上各完整跑通一次 `codegraph@1.5.0` 全量建图，并对 MCP 服务端做过 JSON-RPC 直连探测与一次完整卸载核验。下方所有阈值、耗时、体积、坑均来自该次实测，非推断。

## 你要做什么

先判「该不该建」，再判「什么时候建」，最后才动手。**默认不建是零成本的**——这不是保守表述，是实测：未索引项目里 codegraph 完全不参与任何环节，不留常驻进程、不占上下文。

**红线：禁止执行 `codegraph install`，也禁止任何插件/脚本自动执行它。**本 skill 只走 CLI，理由与实测见 § 五。

## 一、该不该建（判据，逐条对照）

**建**——同时满足：
1. 可解析语言源文件 **≥ 800 个**（Java / TS / JS / Vue / Python / Go / Rust / C# / PHP / Ruby / Kotlin / Swift 等）；
2. 日常检索对象是**跨文件的调用关系**（谁调了这个方法、改它炸哪、Controller 到 Mapper 的链路），而不是单文件内改字符串。

**不建**——命中任一：
- **文档仓 / 文档为主的仓**。实测 `Files by Language` 统计里**没有 markdown 这一项**：codegraph 不给 md 产任何节点。9061 个 md 的 `ontologies/` + `sdlc/` 建图收益严格为 0，只白花扫描时间。
- 源文件 < 200：`Grep` + `Read` 本来就够快，建图的 db 与常驻 watcher 不划算。
- 一次性 clone、马上要删的临时目录。
- 磁盘紧张且仓很大：db 体积按 **每 1000 个源文件 ≈ 37 MB** 估（实测 9,810 文件 → 365 MB）。

## 二、什么时候建（时机，别抢跑）

- **禁止挂 `SessionStart` 之类的钩子自动建图**。首次全量是重活：实测 9,810 文件 **57.2s**、索引期峰值 RSS **4.2 GB**。让它在会话启动时抢资源，等于每次开会话先卡一分钟。
- **主仓**：确认这个仓要进入长期开发时，手工 `codegraph init` 一次。之后靠 FSEvents watcher 增量同步，不用管。
- **worktree**：**必须各自 init，不能共用父仓的图**。实测证据——分支新增类 `SeqModel4Create` 在 worktree 图里查得到（`src/sptalentsdapi/.../seqmodel/SeqModel4Create.java:19`），在主仓图里查不到（只返回一个同名前缀的无关 method `getModel4Create`）。所以拿父仓的图查分支代码，会静默拿到旧分支的符号。
  - 长命 feature worktree（跨天、要反复读跨层链路）→ 建。
  - 短命 fix / DBG-* worktree（一两个小时、改动集中在一两个文件）→ **不建**，直接 Grep；建一次要 55s + 330 MB。
- **重建**（`codegraph index`，不是 `sync`）：切了大分支、submodule gitlink 大跨度更新、或 `codegraph status` 的文件数与实际明显对不上时。

## 三、动手步骤

```bash
# 1. 装 CLI（本机 node >= 20 时用 npm；要免 node 版本漂移就用官方 install.sh 自带运行时）
npm i -g @colbymchenry/codegraph

# 2. 【跳过】codegraph install —— 禁止执行，见 § 五

# 3. 内网/公司代码仓先关遥测
codegraph telemetry off

# 4. 排除纯文档树 —— 写 <repo>/codegraph.json（必须在 init 之前，配置只在 init/index 时读取）
{
  "exclude": ["ontologies/**", "sdlc/**", "docs/**", "tests/**"]
}

# 5. .gitignore 追两行
.codegraph/
codegraph.json      # 若决定不入库，则每个 worktree 手工复制一份

# 6. 建图（大仓走后台任务，别前台阻塞）
codegraph init /abs/path/to/repo

# 7. 核验：看 Files by Language 是不是只剩你想要的语言
codegraph status /abs/path/to/repo
```

`node_modules` / `dist` / `build` / `target` / `vendor` / `.venv` / `.next`、>1MB 的文件、以及所有 `.gitignore` 命中的路径都是**内置排除**，不用自己写。这条顺带解决了 worktree 去重——只要 worktree 目录本身被 gitignore（例如 `.sdlc/` `.keeper/`），父仓建图就不会把 worktree 全量副本重复索引进去。

## 四、怎么用（全部走 Bash 调 CLI）

| 命令 | 用途 | 实测成本 |
|---|---|---|
| `codegraph query <符号>` | 找定义位置——**日常最高频，优先用它** | 极小，几百字节 |
| `codegraph callers <符号>` / `callees` | 单向调用关系 | 小 |
| `codegraph impact <符号>` | 改它的影响面 | 中 |
| `codegraph affected [files...]` | 改了源文件 → 哪些测试要跑 | 小 |
| `codegraph node <符号\|文件>` | 带行号读源码 + 依赖者 | 视文件大小 |
| `codegraph files` | 索引里的项目结构 | 中 |
| `codegraph explore "<问题>"` | 符号源码 + 调用链 + 影响面一次到位 | **单次约 25 KB ≈ 6.5k token** |

`explore` 不是廉价操作，它是「用一次 6.5k token 换掉十来次 Read」。**查单个符号在哪就用 `query`，别用 `explore`。**

**提问必须带英文标识符。** 实测 `explore "岗位序列模型的保存接口在哪"` 返回 `No relevant code found`；把英文类名塞进同一句中文里（`explore "BelloController 的接口方法调用了哪些 service"`）就正常返回 27 个符号，且与纯英文提问输出几乎逐字节相同（25,856 vs 25,836 字节）。匹配靠 query 里的标识符 token，不靠自然语言语义。

**不接 MCP 会少掉服务端自动下发的使用引导**——本插件用一个纯注入 hook 补上：`hooks/codegraph-hint.js` 在 cwd 归属的仓**已建图**时注入两行（强化用 codegraph、抑制拿 `Grep`/`Glob` 全仓搜符号），未建图的仓输出 0 字节。它**双挂 `UserPromptSubmit` + `SubagentStart`**（6.5.0 起）：前者覆盖主会话每轮，后者覆盖每个子代理启动时——`UserPromptSubmit` 的语义是「用户在交互界面提交了一次 prompt」，而子代理由 `Agent`/`Task` 工具编程派发，**该事件的注入到不了子代理**。实证：某会话主会话收到注入 20 次、该项目 23 份 transcript 里 codegraph 实调为 0，因为真正做符号检索的是 keeper / fixer 子代理，它们一次都没收到过。它向上找 `.codegraph/` 时**不越过 worktree 边界**（读 `.git` 文件的 gitdir 区分：`/modules/` 穿过、`/worktrees/` 停），避免未建图的 worktree 认领父仓那份属于另一分支的图。关掉：`CODEGRAPH_HINT=off`。回归用例见 `hooks/tests/codegraph-hint-gating.sh`。

没装本插件、或想让规则进仓库的，在**已建图**项目的 `CLAUDE.md` 里补一行等效内容（未建图项目不要写）：

```markdown
本仓已建 codegraph 图（`.codegraph/`）。定位符号/调用方/影响面优先跑
`codegraph query|callers|impact <符号>`，比 Grep 全仓快且带跨文件调用边；
查不到或需要跨层链路时再 `codegraph explore "<含英文类名的问题>"`。
结果可直接用于定位，但作为结论证据引用前仍需 Read 原文核对行号。
```

最后那句是刻意的：codegraph 官方引导主张「信任结果、不要再核」，与本地核实纪律相反（见 § 五第 4 条），这里显式压过它。

## 五、为什么只用 CLI、不接 MCP

`codegraph install` 会把 MCP 接线写进 **4 处全局文件**：`~/.claude.json` 的 `mcpServers.codegraph`、`~/.claude/settings.json` 两处（`permissions` 加 `mcp__codegraph__*`、**无 matcher 的 `hooks.UserPromptSubmit` → `codegraph prompt-hook`**，所有项目每轮都触发）、`~/.claude/CLAUDE.md` 追加 `<!-- CODEGRAPH_START -->` marker 段。**禁止执行**，四条实测理由：

1. **MCP 面只有 1 个工具**。`tools/list` 返回 `codegraph_explore(query, maxFiles, projectPath)` 一个。README 声称其余工具 "remain functional but unlisted"——实测按名 `tools/call` 调 `codegraph_node`，**无任何响应、连 error 都没有**（同一连接的 `initialize` / `tools/list` 均正常应答，排除协议问题）。也就是说 CLI 的 `query` / `callers` / `callees` / `impact` / `affected` / `files` 在 MCP 侧**全部拿不到**。
2. **成本方向是反的**。MCP 只剩 explore，单次约 25 KB ≈ 6.5k token；CLI `query` 定位一个符号几百字节。用 MCP 查「这个类在哪」要多付 20–50 倍。
3. **每会话固定入场费 ≈ 1.2k token**。MCP `initialize` 响应携带 **4597 字符** instructions，每个会话、每个 subagent 各吃一次，无论那个仓有没有建图。
4. **它的 instructions 与核实纪律冲突且改不掉**（服务端下发）。原文：`Trust codegraph's results — don't re-verify them with grep.` 与 `Don't grep or Read first`。

已经跑过 `install` 的机器这样拆（实测 4 处全清、CLI 保留、`~/.claude/CLAUDE.md` 与安装前逐字节一致）：

```bash
codegraph uninstall -t claude -l global -y --keep-cli
```

## 已验证的坑

1. **纯中文自然语言查询命中率为 0**（证据见 § 四）。提问必须带类名/方法名。
2. **worktree 图不可共用**（证据见 § 二）。给 worktree 建图时记得把 `codegraph.json` 也复制进去——它若未入库，worktree 靠 `git checkout` 拿不到。
3. **`init` 前没写 `codegraph.json` 等于白扫一遍**：配置只在 `init` / `index` 时读取，漏了要 `codegraph index` 重建，`sync` 不行。
4. **每个已索引项目常驻 watcher 进程，会叠加**。实测索引期 11 进程 / 4.2 GB RSS，空闲后 7 进程 / 680 MB。数进程用 `pgrep -f codegraph | wc -l`；**`codegraph daemon` 是交互式菜单（"pick one and press enter"），禁止在脚本或非交互 Bash 里调用**。要彻底关后台同步用 `CODEGRAPH_NO_DAEMON=1` + 手工 `codegraph sync`。
5. **遥测默认开**。公司内网代码仓建图前先 `codegraph telemetry off`。
6. **`codegraph.json` 要不要入库是个决策点**，别默认替人决定：入库则所有 worktree 与同事自动继承排除规则，代价是业务仓多一个工具配置文件；不入库则每个 worktree 要手工复制。
7. **md 零节点**：文档仓建图纯亏，别为了「知识图谱」四个字给文档仓建。

## 拆除

```bash
codegraph uninit /abs/path/to/repo   # 只删该项目 .codegraph/
codegraph uninstall -t claude -l global -y --keep-cli   # 摘 MCP 接线，留 CLI
npm rm -g @colbymchenry/codegraph    # 连 CLI 一起卸
```
