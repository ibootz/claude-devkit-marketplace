# 验证日志（marketplace-cache-sync）

本文件收录正文里那些结论数字背后的实测场景与完整复现证据。正文每处只保留**结论**与**一句指针**，具体到日期 / CLI 版本 / 秒数 / 复现过程的细节来这查。

读者：执行刷新任务的 agent，按需检索，不必通读。

## 目录

1. [验证基础](#验证基础)——本 skill 经过哪些真实执行
2. [性能计时基准](#性能计时基准)——正文"每次 update 25s"等数字的来源
3. [探测剪枝率](#探测剪枝率)——正文"190 条中 186 跳过 4 需刷"的来源（判据修正前是 "113 中 82/31"）
4. [project/local scope 专项坑的复现](#projectlocal-scope-专项坑的复现)——`--scope` 默认值与 cwd 假成功的实测场景
5. [/reload-plugins 与生命周期挂载点](#reload-plugins-与生命周期挂载点)——`working-discipline` 3.0.0 → 3.2.0 的 reload 实测
6. [hook 定义方式双检测](#hook-定义方式双检测)——目录式 hook 的 `radnove-core` 4.5.1 案例
7. [temp_git 残留成因与两次观测](#temp_git_-残留成因与两次观测)——为什么这类残留时有时无
8. [多版本钉版反例](#多版本钉版反例)——为什么不能"只保留最新版本"
9. [缓存清理两次差集规模](#缓存清理两次差集规模)——清理收益随频率衰减
10. [已验证的坑 · 完整证据表](#已验证的坑--完整证据表)——正文坑表每条的复现过程

---

## 验证基础

本 skill 内容来自以下真实执行，覆盖两层模型（marketplace 源 vs 已启用插件缓存）、探测优先的执行顺序、project/local scope 按 (id, projectPath) 逐条刷新、缓存清理白名单差集算法：

- **两次真实全量执行**（17 个 marketplace + 25 个 enabled plugin，2026-07-29 复跑）
- **一次 project/local scope 专项验证**（2026-07-30，8 个仅装在 project/local scope、从未装过 user scope 的插件 id）
- **一次 hook 定义方式双检测验证**（2026-08-01，发现目录式 hook 会让"只读 `plugin.json` 判生命周期"漏判）
- **一次性能专项实测**（2026-08-06，逐条计时定位固定开销、验证"跳过 no-op 等价"、验证两类插件源的探测判据）
- **一次 directory 源迁移实测**（2026-09-28，`aisdlc-qa` 从 directory 源迁到 git 源：`marketplace remove` 连带卸载插件、市场名取自仓内 manifest、按原 (scope, projectPath) 逐条重装）

下方「已验证的坑 · 完整证据表」列出各条已复现问题。

## 性能计时基准

**2026-08-06 本机逐条计时**（`claude` 2.1.220，17 市场 / 128 条安装记录）：

| 动作 | 实测耗时 | 说明 |
|---|---|---|
| `claude --version` | 0.05s | CLI 启动开销可忽略，慢的不是启动 |
| `claude plugin update <不存在的 id>` | 0.24s | 校验阶段就早退，证明固定开销**不在**加载市场清单 |
| **`claude plugin update <一个已是最新的插件>`** | **24.8s** | **即使回执是 `already at the latest version`、对配置零改动，也照付这 25 秒** |
| `claude plugin list --json` | 23.2s | 同一类固定开销 |
| `claude plugin marketplace update <单个 git 市场>` | 3.9s | 市场层反而便宜 |
| `claude plugin marketplace update`（不带参数，全量 17 个） | **14~16 分钟** | 逐市场**串行** clone，期间不流式打印进度；其中一个 SSH 源曾单独卡 1.5 分钟 |
| 并发 `git ls-remote` 探测全部 17 个市场 | **4.5s** | 替代上面那 14~16 分钟的探测手段 |
| 并发 `git ls-remote` 探测全部 53 条 url 源插件记录 | **2.9s** | 已废弃的手段（判据错，见下）；替代逐个 `plugin update` |
| 并发取远端 manifest 探测全部 110 条 url 源记录（去重成 15 个远端仓） | **0.8s** | 现行手段；6 个内网 GitLab 仓并发实测 0.282s，单个 GitHub 仓 1.354s |

**"跳过 no-op 等价"的实测**：`claude plugin update insight-addon@claude-devkit-marketplace` 回执 `already at the latest version (1.1.0)`，前后 `diff <(jq -S . 快照) <(jq -S . installed_plugins.json)` 是 **0 行**。零改动意味着跳过它不丢任何东西——这是正文全部剪枝的合法性基础。

## 探测剪枝率

**2026-08-06 本机实测**：113 条已启用记录里 **82 条可跳过、31 条需刷**，光这一步就省下 82 × 25s ≈ **34 分钟**。

另一次完整刷新的历史数据：2026-08-06 之前那轮从 01:55 跑到 02:47（52 分钟），成因是没有探测剪枝，把两类固定开销全付了一遍——不带参数的 `marketplace update` 串行 clone 全部 17 个市场（14~16 分钟）+ 对每条已启用记录都调一次 `plugin update`（113 条 ≈ 47 分钟）。

## project/local scope 专项坑的复现

### `--scope` 默认值踩坑

**2026-07-30 实测本机有 8 个这样的 id**——只有 project/local scope 记录、从未在 user scope 装过。判定式：

```bash
jq -r '.plugins | to_entries[] | select(.value | map(.scope) | index("user") | not) | .key' ~/.claude/plugins/installed_plugins.json
```

对它们跑 `claude plugin update "$p"` 不带 `--scope`，会 `exit=1` 报 `Plugin "<name>" is not installed at scope user`。

### cwd 不匹配时打印假成功

**2026-07-30 实测**：在与 `cskl-dev@curatedskills-dev` 完全无关的目录下执行 `claude plugin update --scope project cskl-dev@curatedskills-dev`，回执是 `✔ cskl-dev is already at the latest version (1.5.1)`，但前后 `diff <(jq -S . 快照) <(jq -S . installed_plugins.json)` 是 **0 行差异**——这句"已是最新"没有对应到任何真实记录，是误导性的假成功。

`--help` 输出原文：`-s, --scope <scope>  Installation scope: user, project, local, managed (default: user)`。

## /reload-plugins 与生命周期挂载点

**2026-07-29 实测**：`working-discipline` 从 3.0.0 刷到 3.2.0（3.2.0 新增了 `SessionStart` 挂载点、并把每轮注入从 6717 字符压到 1163），跑完 `/reload-plugins` 后**下一轮**的 `UserPromptSubmit` 注入内容立刻变成 3.2.0 的短版，无需退出会话。

**唯一不会追补的是会话生命周期类事件的注入**：`SessionStart` 只在 `startup` / `resume` / `clear` / `compact` 时触发，`/reload-plugins` **不会重放**它。后果是——新版本把内容下沉到了 `SessionStart`（旧版本没有这个挂载点）时，reload 之后进入**割裂状态**：每轮注入已经是新版的"指针 + 增量"，但它所引用的那份静态主体在本会话**从未注入过**，主体里的判据实际不在上下文里。`SessionEnd` / `PreCompact` 同理。

## hook 定义方式双检测

Claude Code 的插件有两种互相独立的 hook 定义方式，**2026-08-01 实测各踩一种**：

1. **字段式**：hook 在 `.claude-plugin/plugin.json` 的 `hooks` 字段里以 `hooks.SessionStart` / `hooks.PreCompact` 等 key 声明。例如 `working-discipline` 3.7.0 的 `hooks` 字段含 `SessionStart`。
2. **目录式**：hook 以 `hooks/` 目录下的脚本文件名约定挂载，`plugin.json` 里**没有** `hooks` 字段（可能配一份 `hooks/hooks.json` 登记事件绑定），`hooks/session-start.sh` / `hooks/pre-compact.sh` 等文件名直接对应生命周期事件。

**目录式案例**：`radnove-core` 4.5.1 的 `plugin.json` 无 `hooks` 字段，但 `hooks/` 下有 `session-start.sh`——只读 `plugin.json` 会判成"无 SessionStart"，实际它正是会话开头注入的那段内容。

## temp_git_* 残留成因与两次观测

**成因 2026-08-06 已实测查明**：一次 `claude plugin update` 期间会**并发**起多个这样的克隆（该次观测峰值 4 个），且会顺带 fetch 非目标市场。这是 url 独立仓源插件（正文「两类插件源」(b)）的必然代价——它的内容不在市场仓里，只能现拉。所以残留量与「本轮跑了多少次 update」正相关：按第一二步剪枝后调用次数大降，这类残留也跟着少了。

**两次观测对比**（说明残留时有时无、不能把具体数字当预期值）：

| 观测 | 时机 | `cache/` 总占用 | `temp_git_*` 数量 | `temp_git_*` 占用 | 备注 |
|---|---|---|---|---|---|
| 观测一 | 2026-07-29 首次 | 2.9G | **13 个** | **1.8G** | 占了将近一半，比历史版本堆积严重得多 |
| 观测二 | 同日晚，清掉观测一之后又完整跑了一轮 17 市场 + 25 插件刷新 | — | **0 个** | — | 说明这类残留不是每次刷新都必然产生，取决于中途是否有克隆被打断 |

## 多版本钉版反例

**绝对不要按"每个插件保留最新版本、删掉其余"来清理。** 同一插件在不同项目目录下（`scope` 为 `project`）会各自钉住不同版本，"最新"只对当前项目成立。实测反例：

- `sdlc@ai-sdlc` 在 `installed_plugins.json` 里有 **12 条** `project` 记录，横跨 `3.3.0` / `3.3.3` / `3.3.18` / `3.7.3` **四个版本**
- `aisdlc-saas-extension` 有 `0.4.2` / `0.4.1` 两个版本

按"保留最新"会删掉其他项目正在使用的缓存，那些项目下次启动会加载失败或被迫重新下载。

## 缓存清理两次差集规模

**同样只作量级参考，不是预期值**：

| 观测 | 可删目录数 | 占用 | 白名单条数 | 磁盘条数 | 备注 |
|---|---|---|---|---|---|
| 观测一（2026-07-29 首次） | **58 个** | **704M** | 48 | 106 | 最大一块是单个 `sdlc/3.7.16` 占 16M |
| 观测二（同日晚，清掉观测一之后） | **14 个** | **25M** | 48 | 62 | `cache/` 408M → 383M，约 6% |

清理收益随执行频率快速衰减——第二次只回收了 25M，大头始终在白名单内的在用版本里。如实告知用户这个量级，不要暗示清理能显著省空间。

## 已验证的坑 · 完整证据表

正文「已验证的坑」的简表只列**现象 → 处置方向**；本节是每条的完整复现证据，按正文坑表同序排列。

### `lastUpdated` 两个变化方向都已观测到反例

**方向一（首次执行时记录）**：回执 `✔ Successfully updated N marketplace(s)` 但某市场 `lastUpdated` 没变，当时结论是"该市场已是最新，字段语义为上次真正拉到新内容的时间"，在两个纯 GitHub 源市场稳定复现。

**方向二（2026-07-29 复跑时观测）**：17 个市场的 `lastUpdated` **全部**前移到同一分钟区间（`01:21`~`01:23`），无一例外，但其中 `karpathy-skills` 的本地 HEAD 仍是 `2c60614`、提交日期 `2026-04-20`（三个月前），且前一天已经更新过一轮、本地早该到位——时间戳前移并未对应任何新内容。

**结论**：两次观测互相矛盾，最可能的解释是 CLI 版本之间改过写入语义（从"拉到新内容才写"变成"每次成功检查都写"），也不排除与市场源类型有关。**只信 HEAD，不信时间戳**——既不要因为 `lastUpdated` 变了就判定"拉到了新代码"，也不要因为它没变就判定失败。

### `git log` 报 `fatal: not a git repository`

不是所有市场都是纯 git clone。例如官方 `claude-plugins-official`：即使 `known_marketplaces.json` 里登记的 `source` 字段写的是 `github`，其本地目录下实际没有 `.git`，只有一个 `.gcs-sha` 文件——它按内容哈希做整体快照同步，不是逐 commit 拉取。

### `plugin update` 找不到批量刷新的写法

CLI 没有 `--all` 之类的参数（见 `--help`），设计上一次只处理一个 `<plugin>@<marketplace>`。

### 同一插件多条相同 version/installPath 记录

不同项目目录各 `enable` 过一次，各记一条 `scope` 记录，但共用同一份缓存目录。只需跑一次 `claude plugin update`，不按项目数重复刷。

### 缓存刷新后 skill/hook 行为没变

缓存刷新不热更新到运行中的进程里。跑 `/reload-plugins`；只有涉及 `SessionStart` / `SessionEnd` / `PreCompact` 这类生命周期挂载点时才必须重启。完整案例见本文件「/reload-plugins 与生命周期挂载点」。

### reload 后 hook 注入是"指针"但静态主体不在上下文

新版本把内容下沉到了 `SessionStart`，而 reload **不重放**生命周期事件。实测 `working-discipline` 3.0.0 → 3.2.0：reload 后本会话里那句"一～六章已在会话开始注入"**不成立**。完整机制与本文件上一节同源。

### zsh `path` 绑定导致循环体内 `command not found`

zsh 用 `typeset -T PATH path` 把小写 `path` 与 `$PATH` **双向绑定**——写 `path` 就是写 `PATH`。`while IFS= read -r path ver` 会在第一次迭代把 `$PATH` 覆盖成一个目录字符串，之后循环体内所有外部命令（`jq` / `sort` / `wc` / `comm` / `du`）全部 `command not found`。故障极易误判：循环**之前**的同名命令已经跑成功了，报错看起来像"jq 没装好 / 环境坏了"，而真正的原因是自己把 PATH 写没了。

最小复现与对照：

```bash
echo a | while IFS= read -r path;  do jq --version; done   # command not found: jq
echo a | while IFS= read -r ipath; do jq --version; done   # jq-1.7.1
```

PATH 只在该次 Bash 调用的子 shell 内被破坏，**不影响后续调用**。对策：改用带语义前缀的名字（`ipath` / `_p` / `orphan_dir`）改名重跑即可。正文第三步给出判据——任何 shell 片段里的小写变量名，若其大写形式是常见环境变量，就换名。

### `for p in $plugins` 在 zsh 下整体失败

用了 `for p in $plugins` 依赖单词分割的写法，zsh 默认不做单词分割。这类失败**无副作用**——CLI 在 id 校验阶段就退出，没有写 `installed_plugins.json`、没有刷新任何插件，改好写法直接重跑即可。

### 只在 project 里装过的插件静默 `exit=1`

`claude plugin update "$p"` 默认 `--scope user`，无 `user` scope 记录的 id 会 `exit=1` 但循环不检查退出码。机制与 8 个实测复现 id 见本文件「project/local scope 专项坑的复现」。

### `--scope project` 在错误 cwd 下打印假成功

`--scope project`/`--scope local` 靠 cwd 隐式定位、不接受路径参数，cwd 不匹配时不报错、只打印假成功回执。机制与 2026-07-30 实测 demo 见本文件「project/local scope 专项坑的复现」。

### `cache/` 体积远大于已启用插件之和（实测 2.9G）

`temp_git_*` 临时克隆残留没被清掉，13 个占 1.8G，在两份配置里都是 0 引用。详见本文件「temp_git_* 残留成因与两次观测」。

### 清理历史版本缓存后项目插件失效

按"每个插件只保留最新版本"删了。详见本文件「多版本钉版反例」。

### 一次完整刷新要跑 30~50 分钟

没做探测剪枝，把两类固定开销全付了一遍。详见本文件「探测剪枝率」。

### 并发跑 `plugin update` 加速

它们读改写同一个 `installed_plugins.json` 且 CLI 内部无文件锁，后写覆盖先写会丢记录；用 `flock` 包住调用则全部在锁处排队，退化成串行、零加速。

### `timeout 20 git ls-remote` 全部"探测失败"

**macOS 默认没有 `timeout` 这个二进制**（GNU coreutils 才有，Homebrew 装的叫 `gtimeout`），命令整体 `command not found`，输出为空被误判成远端不可达。对策：`command -v timeout gtimeout` 先确认；没有就别包，或改用 python 的 `subprocess.run(..., timeout=)`（探测器脚本走的就是后者）。

### url 源判据是 version 不是 sha（原「`gitCommitSha` 对市场仓内源插件语义错位」）

**2026-08-20 更正：这一节原先的结论「url 源比 sha」是错的。** 两类源的判据其实是同一个——版本号；`gitCommitSha` 从不参与 CLI 的 no-op 判断。原结论只对了一半（市场仓内源不能比 sha 那半），错的那半让 url 源的剪枝完全失效。

#### 代码级依据（claude 2.1.237）

`claude` 是 bun 单文件产物，`strings` 可取出内嵌 JS。`plugin update` 的实现函数 `yJT`（遥测事件名 `plugin_update_op`）里判 `up_to_date` 的条件是：

```js
let j=Ife(c,J),z=J==="unknown",Z=Cht(c,J),
    re=!z&&(v.version===J||v.installPath===j||v.installPath===Z);
if(re&&!Q){ ... `${s} is already at the latest version (${J}).` }
```

`v` 是 `installed_plugins.json` 里匹配出的那条记录，`J` 是 CLI 从远端解析出的版本号。`Ife(c,J)` 是 `~/.claude/plugins/cache/<市场>/<插件>/<J>`——`installPath` 末段就是 version，所以两个比较项在实际数据上等价。**`gitCommitSha` 一次都没出现在这个判断里。**

版本号解析函数 `S1e` 的优先级逐条是：

1. 远端仓根 `.claude-plugin/plugin.json` 的 `version` ← 本机绝大多数 url 源命中这一支
2. 所属 `marketplace.json` 条目上的 `version`
3. `gitCommitSha` 的前 12 位 ← 仓里没有 manifest 时落到这里
4. archive / 本地 sha / 字面量 `"unknown"`

落到第 3 支时被比较的仍是记录的 **`version`** 字段（此时它存的就是那 12 位），不是 `gitCommitSha`。本机 `cctx-dev-agent-cli` 是活样本：`version` = `02128add7690`，`gitCommitSha` = `02128add7690a86723443faf88b5d0c57371198e`，远端 `refs/heads/main` 也是后者——三者吻合。

#### 误判规模（2026-08-20 实测）

`--stage plugin` 判 73 条需刷 / 121 条跳过。那 73 条真跑一遍的回执分布：

| 回执 | 条数 | 实际身份 |
|---|---|---|
| `already at the latest version` | **54** | 全部是 url 源，**全部误判**（误判率 100%）|
| `updated from X to Y` | 15 | 市场仓内源（`sdlc@ai-sdlc` 13 条 + `fusion@aisdlc-fusion` 2 条）|
| `refreshed from source` | 4 | 记录 `version` 是字面量 `unknown`（`skill-creator` / `plugin-dev` 各 2 条）|

54 × 25s ≈ **22.5 分钟白付**。成因是判据比的是 sha：同一 id 的多条记录共享同一个 `version` 却带不同 sha（`cctx-dev-yxt-design-system` 14 条里 3 个不同 sha、`version` 全是 `1.9.12`；`cctx-dev-gpb` 是 2 sha / 1 version），于是恒判「有新提交」。

#### 修正后（2026-08-20 同一台机器实测）

190 条已启用记录 → **4 条需刷 / 186 条跳过**，url 源探测 0.8s。那 4 条正是上表里 `version` 为 `unknown` 的那批——与真跑一遍的结果 100% 吻合。回归用例见 `plugins/devkit-tool/tests/probe-refresh-url-criterion.test.py`（27 条断言，纯离线）。

#### 仍然成立的那半：市场仓内源不能比 sha

市场仓内源的 `gitCommitSha` 记的是上次刷新时市场仓的某个 commit，与该插件目录最后改动的 commit 大面积不相等——**2026-08-06 抽 14 个样本只 1 个吻合**。这一半结论不变。

#### 未追的边界

- `yJT` 里还有一条更早的分支：有别的插件对本插件声明版本约束时走 tag 解析，判据变成 `re.version===v.resolvedVersion && re.sha===v.gitCommitSha`（回执文案带 `satisfying`）。本机 221 条安装记录**没有任何 `resolvedVersion` 字段**，54 条回执也都不带 `satisfying`，所以这支当前不生效。但它是「将来有人给插件加版本约束就会换判据」的敞口。**只读代码、未构造样本实测。**
- `archive` / `npm` / `command` / `git-subdir` / `github` 这几种 source 形态的判据路径**完全没追**（本机零样本）。探测器会把它们丢进 `unknown` 桶无条件列入待刷——保守但不精确。
- 「`updated` 那 15 条是市场仓内源」这条身份由 `lastUpdated` 时间窗反推（`already` 路径对配置零写入，只有 `updated` / `refreshed` 才写回），**强证据、非代码级证实**。

### `claude plugin list --json` 一条命令等 23 秒

该命令与 `plugin update` 共享同一类固定开销。enabled 状态可直读：user scope 看 `~/.claude/settings.json` 的 `enabledPlugins[<id>]`，project/local scope 看 `<projectPath>/.claude/settings.json` 或 `settings.local.json`（**2026-08-06 三条 project 记录实测与 `plugin list` 一致**）。探测器脚本已内置，key 缺失按未启用处理。

### `marketplace remove` 连带卸载该市场的插件（2026-09-28 实测，claude 2.1.283）

把 `aisdlc-qa` 从 directory 源迁到标准 git 源时撞到。`claude plugin marketplace remove aisdlc-qa` 的完整回执：

```
✔ Successfully removed marketplace: aisdlc-qa
Also uninstalled 1 plugin from this marketplace:
  qa@aisdlc-qa
The removal also deletes their saved options, secrets and data where it can.
To use a plugin again, add the marketplace back and reinstall the plugin.
```

第二行起是**实际发生的卸载**，不是告警：`~/.claude/plugins/installed_plugins.json` 里 `qa@aisdlc-qa` 的 9 条记录全部消失（8 条装在各自项目根，1 条装在某个 `.sdlc/worktrees/<id>` 下），`known_marketplaces.json` 与 `settings.json` 的 `extraKnownMarketplaces` 条目也一并移除。

**未被删除的是各项目 `.claude/settings.json` 里的 `enabledPlugins["qa@aisdlc-qa"] = true`**——9 个项目逐条查过，全部保留。这是迁移能低代价完成的关键：启用状态不在 remove 的删除范围内。

迁移的完整序列：

```bash
# 0. 迁移前先存快照——remove 之后就查不到原来装在哪些 (scope, projectPath) 了
jq -r '.plugins["<id>"][] | "\(.scope)|\(.projectPath // "")"' \
  ~/.claude/plugins/installed_plugins.json > /tmp/records_before.txt

# 1. 移除旧市场（连带卸载）
claude plugin marketplace remove <name>

# 2. 以 git 源重注册
claude plugin marketplace add <git-url>

# 3. 按快照逐条重装
while IFS='|' read -r pid pscope ppath; do
  [ -z "$pid" ] && continue
  if [ "$pscope" = "user" ]; then
    claude plugin install "$pid" --scope user
  else
    (cd "$ppath" && claude plugin install "$pid" --scope "$pscope")
  fi
done < /tmp/records_before.txt
```

三条与之相关的实测事实：

- **市场名不由 URL 决定，取自该仓 `.claude-plugin/marketplace.json` 的 `name` 字段。** 本机该字段写着 `aisdlc-qa`，所以 `add git@…:xxstar-ai/qa/xxstar-ai-qa-plugin.git` 之后市场仍叫 `aisdlc-qa`，插件 id 仍是 `qa@aisdlc-qa`，**各项目的 `enabledPlugins` 声明一个字都不用改**。重装完 9/9 三方核验一致（`installed_plugins.json` 的 `installPath` / 磁盘目录 / 目录内 `.claude-plugin/plugin.json` 的 `version` 全为 `0.7.7`）。
- **重装装的是当前最新版，不是原版本。** 9 条原为 `0.6.15`×8 + `0.6.4`×1，重装后全部变 `0.7.7`。若原版本是有意钉的，迁移会把它顶掉——**迁移前必须先把这个后果告诉用户**（跨项目改版本，见第三步补充那条纪律）。
- **重装逐条跑，同 `plugin update` 一样串行**，每条仍是 25s 起步量级；9 条实测在后台跑完一轮。

#### 顺带查出的 directory 源根因（这条才是"为什么要迁"）

`aisdlc-qa` 原先是 `{"source": "directory", "path": "/Users/zhangq/Workspace/xx/qa/xxstar-ai-qa-plugin"}`，指向一个本机 git 工作副本。`claude plugin marketplace update` 对 directory 源**不会 pull**，于是市场版本静默冻结在那个工作副本的当前 checkout 上。

实测该副本落后 `origin/master` **57 个 commit**（local `85dfafb7752bbb74b7349aeef6421586f28d7431` / origin `7f0287a7b3163a6c3f71a9099205c63867f2df7d`），插件版本因此卡在 `0.6.15`，而上游已是 `0.7.7`——**全程无任何报错**，探测器也判不出（它读的是已安装记录的 `version`，而那个值本来就是从这份陈旧副本来的）。

判据：`marketplaces/<name>/` 下有没有 `.git`。该目录不存在、或存在但无 `.git`，即为 directory 源或非 git 快照，`marketplace update` 对它无效。迁到 git 源之后 `marketplaces/aisdlc-qa/.git` 存在，且本地 HEAD 与 `git ls-remote origin HEAD` 一致——这才是"以后能正常 pull"的凭据。

### 市场 clone 默认 120s 超时不够（2026-09-28 实测，claude 2.1.283）

`claude plugin marketplace update` 对 `open-code-review` 与 `ui-ux-pro-max-skill` 双双失败：

```
Failed to refresh marketplace 'open-code-review': Failed to clone marketplace repository:
Git clone timed out after 120s. The repository may be too large for the current timeout.
Set CLAUDE_CODE_PLUGIN_GIT_TIMEOUT_MS to increase it (e.g., 300000 for 5 minutes).

Original error: Cloning into '~/.claude/plugins/marketplaces/open-code-review..clone'...
```

带 `CLAUDE_CODE_PLUGIN_GIT_TIMEOUT_MS=300000` 重跑同一条命令，两个都成功，实测耗时 **3m45s**（open-code-review）与 **3m08s**（ui-ux-pro-max-skill）。回执里能看到这个变量确实生效：`Refreshing marketplace cache (timeout: 300s)…`。

两条要点：

- **这不是网络抖动，重试不抬超时没用**——实际耗时远超 120s，是仓库要重新 clone 的固有开销。报错原文自带这条提示，照做即可。
- **120s 只对真正要 clone 的大仓不够。** 同一轮里另外 18 个市场在探测阶段就判为 `SAME` 跳过了，`claude-plugins-official` 走 `.gcs-sha` 内容哈希同步也是秒级——只有被判 `STALE` 的那几个才真付 clone 开销。

未追的边界：失败那一次是否在 `marketplaces/` 下留了 `<name>..clone` 半成品目录，**没有在失败当场 `ls` 过**；成功重跑之后查过，当时无残留。（这条边界在下方「市场刷新还有一种非超时的失败」里被补上了。）

### 市场刷新还有一种非超时的失败（2026-09-28 实测，claude 2.1.283）

补完上面两条坑之后刷本机缓存时撞到，与上一节的超时**不是同一个成因**：

```
Updating marketplace: claude-devkit-marketplace...✘ Failed to update marketplace(s):
Failed to refresh marketplace 'claude-devkit-marketplace':
Failed to clone marketplace repository: Cloning into '…/claude-devkit-marketplace..clone'...
fatal: could not open '…/claude-devkit-marketplace..clone/.git/objects/pack/tmp_pack_t6YHza' for reading: No such file or directory
fatal: fetch-pack: invalid index-pack output
```

两者的判据相反，别混：

| | 超时那条 | 本条 |
|---|---|---|
| 报错关键词 | `Git clone timed out after 120s` | `invalid index-pack output` / `could not open …tmp_pack_*` |
| 失败前耗时 | 超 120s（成功那次 3m08s ~ 3m45s） | 1m48s，命令自行中断 |
| 加超时变量有用吗 | 有用 | **没用**——重试那次耗时 1m43s，**低于** 120s 默认值，加不加都过 |
| 处置 | 带 `CLAUDE_CODE_PLUGIN_GIT_TIMEOUT_MS=300000` 重跑 | 直接重跑即可 |

**成因未确认。** 一条间接现场证据：`pgrep -fl claude` 查到本机同时有 6 个 claude 进程在跑（其中另一个会话带 `--allow-dangerously-skip-permissions`）。若它同时在做会碰同一 `..clone` 路径的操作，就可能一个进程在读 pack、另一个在清理它。**没有构造复现，只观测到一次。**

失败后 `ls -d marketplaces/*..clone` 为**空**——这种失败不留半成品目录。这一条是在**失败当场**查的，补上了上一节那条「未追的边界」。

### 第五步清理会删掉本会话正在加载的版本目录（2026-09-28 实测）

`devkit-tool` 升 6.21.0 → 6.21.1 后重跑差集，孤儿清单第一条是：

```
700K  ~/.claude/plugins/cache/claude-devkit-marketplace/devkit-tool/6.21.0
 32K  ~/.claude/plugins/cache/claude-plugins-official/code-review/fa59bc903774
 …（共 8 条，合计 904K）
```

`devkit-tool/6.21.0` 正是**本会话启动时加载的那一份**，其 `hooks/` 下两个脚本（`codegraph-hint.js`、`worktree-cwd-recovery.js`）本轮还在每次工具调用时执行。判据来自同轮另一个插件的报错行——它把自己的运行路径打了出来，带版本号：

```
PreToolUse:Bash hook error: [node …/cd-blocker/1.0.0/hooks/guards/cd-guard.js]: [L1-BLOCKER] …
```

即 hook 命令在**会话启动时**就把 `${CLAUDE_PLUGIN_ROOT}` 展开成了带版本号的绝对路径。配置文件随后改成 6.21.1，但**正在跑的进程不会重新解析**。所以删掉 6.21.0 的后果不是「下次启动会重新下载」这种可恢复代价，而是**本会话此后每轮工具调用都撞 hook 报错**。

**这是推断，没有做删除试验。** 但代价判据足够清楚：8 个孤儿合计 904K，删掉省不到 1M；赌错则打断当前会话的 hook。故本轮**一个都没删**。

不累积：剔掉的目录下次 sync 时仍在差集里，那时会话已重启或已 reload，会被正常收走。

机械判据（已写进正文第五步 (b)）：拿第三步存的 `/tmp/ip_before.json` 对照孤儿清单——某孤儿的 `<version>` 等于**刷新前**该插件的记录版本，它极可能就是本会话启动时加载的那份。
