---
name: codegraph-index
description: "判断一个仓库该不该建 codegraph 代码知识图谱、什么时候建、worktree 要不要各自建，以及建完怎么用（含实测的体积/耗时/内存阈值与 7 个已验证的坑）。codegraph 是 tree-sitter 抽符号 + 调用边存本地 SQLite 的代码图，不是文档知识图谱。"
when_to_use: |
  用户说"给这个项目建知识图谱"、"装/部署 codegraph"、"索引这个仓"、"用图谱省 token"、"这个仓值不值得建图"、"worktree 要不要单独建图"、"codegraph 查不到东西"、"codegraph db 太大/索引太慢/内存占太多"、"卸掉 codegraph"、"codegraph 图过期了"、"explore 返回一大坨"。
---

# CodeGraph Index（代码知识图谱建图决策与运维）

**验证基础**：2026-08-01 在 `xxstar-ai-spsd-work`（3.0G 聚合仓、22 个 submodule、Java + Vue/JS/TS 混合）与其 D-001 worktree 上各完整跑通一次 `codegraph@1.5.0` 全量建图，下方所有阈值、耗时、体积、坑均来自该次实测，非推断。

## 你要做什么

先判「该不该建」，再判「什么时候建」，最后才动手。**默认不建是零成本的**——这不是保守表述，是实测：未索引项目里 `codegraph prompt-hook` 输出 **0 字节**，且全局 `~/.claude/CLAUDE.md` 被注入的 marker 段自带 gating 原文 `If there is no .codegraph/ directory, skip CodeGraph entirely — indexing is the user's decision`。所以「装了但不给某个仓建图」对那个仓完全无副作用，不需要为了不用它而卸载。

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
- **worktree**：**必须各自 init，不能共用父仓的图**。实测证据——分支新增类 `SeqModel4Create` 在 worktree 图里查得到（`src/sptalentsdapi/.../seqmodel/SeqModel4Create.java:19`），在主仓图里查不到（只返回一个同名前缀的无关 method）。所以拿 `projectPath` 指父仓来查分支代码，会静默拿到旧分支的符号。
  - 长命 feature worktree（跨天、要反复读跨层链路）→ 建。
  - 短命 fix / DBG-* worktree（一两个小时、改动集中在一两个文件）→ **不建**，直接 Grep；建一次要 55s + 330 MB。
- **重建**（`codegraph index`，不是 `sync`）：切了大分支、submodule gitlink 大跨度更新、或 `codegraph status` 的文件数与实际明显对不上时。

## 三、动手步骤

```bash
# 1. 装（本机 node ≥ 20 时用 npm；要免 node 版本漂移就用官方 install.sh 自带运行时）
npm i -g @colbymchenry/codegraph

# 2. 接线（只挂 Claude Code、全局、非交互；会写 4 处文件，见坑 3）
codegraph install -t claude -l global -y

# 3. 内网/公司代码仓先关遥测
codegraph telemetry off

# 4. 排除纯文档树 —— 写 <repo>/codegraph.json（必须在 init 之前）
{
  "exclude": ["ontologies/**", "sdlc/**", "docs/**", "tests/**"]
}

# 5. .gitignore 追一行
.codegraph/

# 6. 建图（大仓走后台任务，别前台阻塞）
codegraph init /abs/path/to/repo

# 7. 核验：看 Files by Language 是不是只剩你想要的语言
codegraph status /abs/path/to/repo
```

`node_modules` / `dist` / `build` / `target` / `vendor` / `.venv` / `.next`、>1MB 的文件、以及所有 `.gitignore` 命中的路径都是**内置排除**，不用自己写。这条顺带解决了 worktree 去重——只要 worktree 目录本身被 gitignore（例如 `.sdlc/` `.keeper/`），父仓建图就不会把 worktree 全量副本重复索引进去。

## 四、怎么用（含成本认知）

| 命令 / MCP 工具 | 用途 | 实测成本 |
|---|---|---|
| `codegraph query <符号>` | 找定义位置 | 极小，几百字节 |
| `codegraph explore "<问题>"` / `codegraph_explore` | 符号源码 + 调用链 + 影响面，一次到位 | **单次约 25 KB ≈ 6.5k token** |
| `codegraph callers` / `callees` / `impact` | 单向关系 | 小到中 |
| `codegraph node <符号\|文件>` | 带行号读源码 + 依赖者 | 视文件大小 |

`explore` 不是廉价操作，它是「用一次 6.5k token 换掉十来次 Read」。查单个符号在哪，用 `query` 别用 `explore`。

## 已验证的坑

1. **纯中文自然语言查询命中率为 0**。实测 `explore "岗位序列模型的保存接口在哪"` 返回 `No relevant code found`；把英文标识符塞进同一句中文里（`explore "BelloController 的接口方法调用了哪些 service"`）就正常返回 27 个符号，且与纯英文提问的输出几乎逐字节相同（25,856 vs 25,836 字节）。**结论：匹配靠 query 里的英文标识符 token，不靠自然语言语义。提问必须带类名/方法名。**
2. **worktree 图不可共用**（证据见 § 二）。给 worktree 建图时记得把 `codegraph.json` 也复制进去——它若未入库，worktree 靠 `git checkout` 拿不到。
3. **`codegraph install` 写 4 处文件**，升级/排障前先备份：`~/.claude.json`（加 `mcpServers.codegraph`）、`~/.claude/settings.json` **两处**（`permissions` 加 `mcp__codegraph__*`；`hooks.UserPromptSubmit` 加 `codegraph prompt-hook`，**无 matcher，即所有项目每轮都触发**）、`~/.claude/CLAUDE.md`（追加 `<!-- CODEGRAPH_START -->` marker 段 11 行）。那个全局 hook 在未索引项目输出 0 字节，在已索引项目无命中时 242 字节，不构成负担，但要知道它存在。
4. **每个已索引项目常驻 watcher 进程，会叠加**。实测索引期 11 进程 / 4.2 GB RSS，空闲后 7 进程 / 680 MB。数进程用 `pgrep -f codegraph | wc -l`；**`codegraph daemon` 是交互式菜单（"pick one and press enter"），禁止在脚本或非交互 Bash 里调用**。要彻底关后台同步用 `CODEGRAPH_NO_DAEMON=1` + 手工 `codegraph sync`。
5. **遥测默认开**。公司内网代码仓建图前先 `codegraph telemetry off`（它声称不上传代码/路径/符号名，但默认开就该关）。
6. **`codegraph.json` 要不要入库是个决策点**，别默认替人决定：入库则所有 worktree 与同事自动继承排除规则，代价是仓里多一个工具配置文件；不入库则每个 worktree 要手工复制。
7. **`init` 前没写 `codegraph.json` 就等于白扫一遍**，配置是 init 时读取的；漏了要 `codegraph index` 重建，不是 `sync`。

## 拆除

```bash
codegraph uninit /abs/path/to/repo   # 只删该项目 .codegraph/，保留全局接线
codegraph uninstall                  # 摘掉全局接线（~/.claude.json / settings.json / CLAUDE.md marker 段）
npm rm -g @colbymchenry/codegraph
```
