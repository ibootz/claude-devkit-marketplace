---
name: marketplace-cache-sync
description: 拉取 Claude Code 已配置的插件市场(marketplace)最新代码，刷新已启用插件(enabled plugin)的本地缓存版本(含 user scope 与 project/local scope 两种安装范围)，并在刷新后回收缓存磁盘占用。先探测再刷新，只动真有变化的那几个。
when_to_use: |
  用户说"更新一下插件市场"、"拉取 marketplace 最新代码"、"刷新插件缓存"、"plugin 装的新版本怎么不生效"、"skill 改了但没同步过来"、"刷新插件太慢了"、"marketplace update 要跑十几分钟"、"市场 lastUpdated 变了/没变是不是真的更新了"、"marketplace update 之后要不要重启"、"插件缓存占了多少空间"、"清理插件缓存"、"cache 目录太大"、"temp_git_ 开头的目录能删吗"、"历史版本缓存能不能删"、"reload-plugins 够不够还是必须重启"、"reload 完 hook 还是旧的"、"某个项目里装的插件版本没跟着更新"、"project scope 的插件怎么刷新"、"这个插件只在某个项目里装了，全局刷新覆盖不到"。
  **另一类触发是主动的，不要漏**——上面那些措辞全是「发现没生效之后」的补救语气，但更常见的场景是**改完当场就该刷**：
  你（或用户）刚改完自己维护的某个插件的 SKILL.md / hook / plugin.json 并提交推送，此时**当前会话读到的仍是旧版缓存**。
  判据很机械：**本轮是否写过 `<某个 marketplace 仓>/plugins/**` 下的文件**。写过就该在收尾时刷一次，而不是只丢下一句「记得刷新缓存」让用户自己去跑。
---

# Marketplace Cache Sync（插件市场与插件缓存刷新）

把"更新插件市场"这件事拆成两层动作依次执行，**先用本地/并发探测算出「哪几个真的需要动」，再只对那几个调 CLI**，并在核实每一层是否真的生效时避开已知的误判坑。

**验证基础**：内容来自两次真实全量执行（17 个 marketplace + 25 个 enabled plugin，2026-07-29 复跑）+ 一次 project/local scope 专项验证（2026-07-30，8 个仅装在 project/local scope、从未装过 user scope 的插件 id）+ 一次 hook 定义方式双检测验证（2026-08-01，发现目录式 hook 会让”只读 `plugin.json` 判生命周期”漏判）+ **一次性能专项实测（2026-08-06，逐条计时定位固定开销、验证"跳过 no-op 等价"、验证两类插件源的探测判据）**，覆盖两层模型（marketplace 源 vs 已启用插件缓存）、探测优先的执行顺序、project/local scope 按 (id, projectPath) 逐条刷新、缓存清理白名单差集算法，以及下方「已验证的坑」列出的各条已复现问题。

## 背景：两层状态，容易只做一半

Claude Code 的插件系统有两层独立状态，都在 `~/.claude/plugins/` 下：

1. **Marketplace（插件市场，"源"）**：`known_marketplaces.json` 登记每个市场的 git/github 源地址与 `installLocation`，实际内容克隆在 `marketplaces/<name>/`。`claude plugin marketplace update [name]` 拉取的是这一层——市场仓库本身的最新代码，相当于所有插件定义的"上游"。
2. **Installed/enabled plugin（已启用插件，"缓存"）**：`installed_plugins.json` 登记每个 `<plugin>@<marketplace>` 具体钉住的版本号/commit sha，实际内容缓存在 `cache/<marketplace>/<plugin>/<version>/`。`claude plugin update <plugin>@<marketplace>` 刷新的才是这一层——把某个已启用插件的缓存副本，从（已经更新过的）市场源里重新拉一份下来。

第 2 层内部还分**两种互相独立的安装范围（scope）**，`installed_plugins.json` 里同一个 `<plugin>@<marketplace>` id 下的 `plugins[id]` 是一个**数组**，每个元素各带一个 `scope` 字段（`user` / `project` / `local`）：`user` scope 是当前用户全局共用的一份钉版，跨项目共享；`project` / `local` scope 是**某一个具体项目目录**（`projectPath` 字段）单独钉住的版本，同一个 id 在不同项目目录下可以各自钉着不同版本号——例如 `sdlc@ai-sdlc` 在 12 个不同项目目录下横跨 `3.3.0`/`3.3.3`/`3.8.0`/`3.9.0`/`3.3.18` 五个版本互不影响。**enabled 状态也是按 (id, projectPath) 各自独立的**——同一个 id 在 A 项目可能启用、在 B 项目未启用，不是插件级的单一开关。所以**待刷清单必须按 (id, scope, projectPath) 逐条算**，按 id 去重会漏掉其余项目目录下那些各自钉版的记录。

**第 1 层更新了不代表第 2 层跟着更新**：市场仓库拉到最新 commit 后，已启用插件的缓存副本仍然钉在旧版本号/旧 commit，除非显式对每个启用中的插件跑一次 `claude plugin update`。两层都做才算一次完整同步，只做第 1 层是最常见的"以为更新了其实没生效"的原因。

## 慢在哪：先读这段，否则会照旧全量刷一遍

2026-08-06 本机逐条计时（`claude` 2.1.220，17 市场 / 128 条安装记录）：

| 动作 | 实测耗时 | 说明 |
|---|---|---|
| `claude --version` | 0.05s | CLI 启动开销可忽略，慢的不是启动 |
| `claude plugin update <不存在的 id>` | 0.24s | 校验阶段就早退，证明固定开销**不在**加载市场清单 |
| **`claude plugin update <一个已是最新的插件>`** | **24.8s** | **即使回执是 `already at the latest version`、对配置零改动，也照付这 25 秒** |
| `claude plugin list --json` | 23.2s | 同一类固定开销 |
| `claude plugin marketplace update <单个 git 市场>` | 3.9s | 市场层反而便宜 |
| `claude plugin marketplace update`（不带参数，全量 17 个） | **14~16 分钟** | 逐市场**串行** clone，期间不流式打印进度；其中一个 SSH 源曾单独卡 1.5 分钟 |
| 并发 `git ls-remote` 探测全部 17 个市场 | **4.5s** | 替代上面那 14~16 分钟的探测手段 |
| 并发 `git ls-remote` 探测全部 53 条 url 源插件记录 | **2.9s** | 替代逐个 `plugin update` 的探测手段 |

两个结论直接决定执行顺序：

1. **每次 `claude plugin update` 都是 25 秒起步，与它是否真的有活干无关。** 本机 113 条已启用记录全刷一遍 ≈ 47 分钟。所以优化的唯一有效方向是**减少调用次数**，不是并行（并行不安全，原因见第三步）。
2. **跳过一次必然 no-op 的 update，与跑它完全等价。** 实测：`claude plugin update insight-addon@claude-devkit-marketplace` 回执 `already at the latest version (1.1.0)`，前后 `diff <(jq -S . 快照) <(jq -S . installed_plugins.json)` 是 **0 行**。既然零改动，跳过就不丢任何东西——这是本 skill 全部剪枝的合法性基础。

### 两类插件源：判据不同，别混用

`marketplace.json` 里每个插件条目的 `source` 字段有两种形态，决定了「怎么判断它需不需要刷」：

- **(a) 市场仓内源**（`"source": "./plugins/<name>"`）：插件内容就在市场仓里。判据是**版本号**——条目里的 `version`（缺失时回落读该目录的 `plugin.json`）与 `installed_plugins.json` 里该记录的 `version` 比，相等即跳过。这正是 CLI 判 `already at the latest version` 的依据，纯本地读、毫秒级。
- **(b) url 独立仓源**（`"source": {"source": "url", "url": "http://…git", "ref": "master"}`）：**插件内容根本不在市场仓里**，在一个独立 git 仓中。判据是 **commit sha**——`installed_plugins.json` 里该记录的 `gitCommitSha` 就是那个独立仓的 sha（2026-08-06 对 13 个 url 源逐个 `git ls-remote` 比对确认），并发探测全部只需 2.9 秒。

**(b) 类正是最慢的那一类**：CLI 每次都要重新 clone 那个独立仓，实测一次 `plugin update` 期间峰值并发起 **4 个** `temp_git_*` 克隆，且会顺带 fetch 非目标市场——这同时解释了第五步要清的 `temp_git_*` 残留是怎么来的。

**注意 `gitCommitSha` 对 (a) 类不是这个语义**，它记的是上次刷新时市场仓的某个 commit，与「该插件目录最后改动的 commit」在实测里大面积不相等（14 个样本只有 1 个吻合）。所以 (a) 类**只能比版本号，不要拿 sha 去比**。

## 执行工作流

探测器脚本随本 skill 提供，两个阶段各跑一次（**顺序不能颠倒**，插件层的版本比对必须读到已更新的市场清单）：

```bash
# 从配置里取本插件缓存目录，避免把版本号写死在路径里
PROBE="$(jq -r '.plugins | to_entries[] | select(.key | startswith("devkit-tool@")) | .value[0].installPath' ~/.claude/plugins/installed_plugins.json | head -1)/skills/marketplace-cache-sync/scripts/probe-refresh.py"
ls -l "$PROBE"   # 必须存在再往下走
```

拿不到时改用 `$CLAUDE_PLUGIN_ROOT/skills/marketplace-cache-sync/scripts/probe-refresh.py`，或直接在 devkit-tool 的源仓里跑那份脚本——它只读 `~/.claude/plugins/` 下的配置，不依赖自己所在的位置。

### 第一步：探测哪些市场真有新提交，只更新那几个

```bash
python3 "$PROBE" --stage market      # 本机实测 4.5s
```

它对每个 `marketplaces/<name>/` 并发跑 `git ls-remote origin HEAD` 与本地 `rev-parse HEAD` 比对，把结果分成四类，并把需要更新的市场名写进 `/tmp/mkt_to_update.txt`：

| 判定 | 含义 | 处置 |
|---|---|---|
| `SAME` | 远端 HEAD == 本地 HEAD | **跳过**，`marketplace update` 必然无事可做 |
| `STALE` | 远端有新提交 | 列入待更新 |
| `NO_GIT` | 目录里没有 `.git`（如官方市场，只有 `.gcs-sha`，按内容哈希整体快照同步） | 无法探测，列入待更新，事后比对 `.gcs-sha` 是否变化 |
| `PROBE_FAIL` | ls-remote 失败（网络/凭证） | 保守列入待更新，别当成"已是最新" |

然后**只**更新命中的市场，一个一个来：

```bash
while IFS= read -r mkt; do
  [ -z "$mkt" ] && continue
  echo "=== marketplace update $mkt ==="
  claude plugin marketplace update "$mkt" 2>&1
done < /tmp/mkt_to_update.txt
```

**不要再跑不带参数的 `claude plugin marketplace update`。** 它对全部市场串行 clone，本机实测 14~16 分钟；而 2026-08-06 那次探测的结论是 17 个市场里只有 1 个真有新提交（另 1 个是无法探测的官方市场），实际要跑的只有 2 次 × 4s。历史上那 14 分钟里绝大部分是在重新 clone 已经最新的仓。

命中数量多（比如超过 5 个）时才需要 `run_in_background`，否则前台跑完更省事。

### 第二步：算出真正需要刷新的插件清单

```bash
python3 "$PROBE" --stage plugin      # 本机实测 4.0s（含 53 条 url 源并发探测 2.9s）
```

输出写进 `/tmp/plugins_to_refresh.txt`，每行形如 `<id>|<scope>|<projectPath>`（user scope 的 projectPath 为空）。它做四件事：

1. 遍历 `installed_plugins.json` 的**全部** `plugins[id][]` 数组元素——每个元素是一条独立的 (id, scope, projectPath) 记录，同一个 id 在不同项目目录可以各自钉着不同版本。
2. 按 enabled 过滤。**不调 `claude plugin list --json`**（那条命令本机 23.2s），改为直读 `~/.claude/settings.json` 的 `enabledPlugins[<id>]`（user scope）与 `<projectPath>/.claude/settings.json` / `settings.local.json`（project/local scope）——2026-08-06 实测三条 project 记录，直读值与 `plugin list` 的 `enabled` 字段一致。要连未启用的一起刷时加 `--include-disabled`。
3. 按上面「两类插件源」的判据分别剪枝：(a) 市场仓内源比版本号，(b) url 独立仓源并发 ls-remote 比 `gitCommitSha`。
4. 三种情况一律**列入待刷**，不做剪枝：`installPath` 指向的缓存目录不存在、市场源没声明版本号（判不了）、远端探测失败。剪枝只在能确证"必然 no-op"时才生效。

本机 2026-08-06 实测结果：113 条已启用记录里 **82 条可跳过、31 条需刷**，光这一步就省下 82 × 25s ≈ **34 分钟**。

**这个剪枝不改变结果，也不修 CLI 自身的漏刷面。** 它做的只是"预测 CLI 会不会 no-op，会就别调"。若某插件的版本号没升但内容改了，CLI 自己也会说 `already at the latest version` 而不刷——那是 CLI 的行为，剪枝既不引入也不放大它。

### 第三步：串行刷新清单里的每条记录

一个循环同时覆盖 user 与 project/local 两种 scope——清单每行都自带 `scope` 与 `projectPath`，不需要分两轮：

```bash
cp ~/.claude/plugins/installed_plugins.json /tmp/ip_before.json   # 写后回读用的基线快照
total=$(wc -l < /tmp/plugins_to_refresh.txt | tr -d ' ')
echo "待刷新记录数: $total（预计 $((total * 25 / 60)) 分钟左右）"
while IFS='|' read -r pid pscope ppath; do
  [ -z "$pid" ] && continue
  if [ "$pscope" = "user" ]; then
    echo "=== $pid [user] ==="
    claude plugin update --scope user "$pid" 2>&1
  else
    if [ ! -d "$ppath" ]; then
      echo "跳过（项目目录已不存在）: $pid @ $ppath"
      continue
    fi
    echo "=== $pid [$pscope] @ $ppath ==="
    (cd "$ppath" && claude plugin update --scope "$pscope" "$pid") 2>&1
  fi
done < /tmp/plugins_to_refresh.txt
```

**必须用 `while IFS= read -r` 逐行读，不要写 `for p in $plugins`。** Claude Code 的 Bash 工具在 macOS 上走 zsh，而 zsh 默认**不对未加引号的变量做单词分割**（bash 会）——`for p in $plugins` 会把整个多行字符串当成**一个** token 传给 CLI，报 `Plugin "<第一个插件名>" not found` 后整个循环失败。落地成临时文件再逐行读，不依赖任何 shell 的分词行为。

**`--scope` 必须显式传。** `claude plugin update` 的 scope 默认值是 `user`（见 `--help`：`-s, --scope <scope>  Installation scope: user, project, local, managed (default: user)`）。某个 id 若从来没有 `user` scope 记录、只在项目目录下装过，不带 `--scope` 跑就会 `exit=1` 报 `Plugin "<name>" is not installed at scope user`，而循环不检查退出码，这类失败会和成功回执一起滚屏而过——**看起来流程正常跑完了，实际上那个插件从未被刷新**。2026-07-30 实测本机有 8 个这样的 id（判定式：`jq -r '.plugins | to_entries[] | select(.value | map(.scope) | index("user") | not) | .key' ~/.claude/plugins/installed_plugins.json`）。上面的清单驱动写法从源头绕开了这个坑——每条记录的 scope 都来自 `installed_plugins.json` 本身。

**project/local scope 靠 cwd 隐式定位目标项目，不接受任何显式路径参数；且 cwd 不匹配时不报错，而是打印看似成功的回执、对配置零改动。** 2026-07-30 实测：在与 `cskl-dev@curatedskills-dev` 完全无关的目录下执行 `claude plugin update --scope project cskl-dev@curatedskills-dev`，回执是 `✔ cskl-dev is already at the latest version (1.5.1)`，但前后 `diff <(jq -S . 快照) <(jq -S . installed_plugins.json)` 是 **0 行差异**——这句"已是最新"没有对应到任何真实记录，是误导性的假成功。所以必须 `cd` 进该条记录**自己的** `projectPath`；用子 shell `(cd "$ppath" && ...)` 而不是裸 `cd`，避免污染后续 Bash 调用的 cwd。目录缺失（项目已删但配置残留）不算错误，跳过并报告即可。

**循环变量禁止命名为 `path`（以及 `fpath` / `cdpath` / `manpath` / `fignore` / `mailpath` / `module_path`）。** zsh 用 `typeset -T PATH path` 把这些小写名与同名大写环境变量**双向绑定**——写 `path` 就是写 `PATH`。所以 `while IFS= read -r path ver` 会在第一次迭代把 `$PATH` 覆盖成一个目录字符串，之后循环体内所有外部命令（`jq` / `sort` / `wc` / `comm` / `du`）全部 `command not found`。**这个故障极易误判**：循环**之前**的同名命令已经跑成功了，报错看起来像"jq 没装好 / 环境坏了"，而真正的原因是自己把 PATH 写没了。本步与第五步的核验循环都要读 `installPath`，是最容易踩的位置——统一用带语义前缀的名字（`ipath` / `_p` / `orphan_dir`）。判据：**任何出现在 shell 片段里的小写变量名，若其大写形式是常见环境变量，就换名。**

```bash
echo a | while IFS= read -r path;  do jq --version; done   # command not found: jq
echo a | while IFS= read -r ipath; do jq --version; done   # jq-1.7.1
```

**必须串行执行，不能并发派发**：`claude plugin update` 会读改写共享的单个文件 `~/.claude/plugins/installed_plugins.json`，多个进程同时跑存在写竞态——后写完的会覆盖先写完的那条记录，可能导致某些插件的刷新结果丢失。用 `flock` 包住每个调用也换不来加速：一次 update 的 25 秒里网络检查与配置写入是同一个不可分割的进程，锁会让所有调用在锁处排队，等价于串行。

**所以加速只能靠前两步减少调用次数，不能靠这一步并行。** 这也是为什么探测阶段值得花那 8.5 秒。

（`claude plugin update` 没有 `--all`/批量参数，一次只能指定一个 `<plugin>@<marketplace>`，只能像上面这样自己拼循环。）

剩余记录数乘 25 秒就是这一步的预计耗时；超过 2 分钟（即 5 条以上）时用 `run_in_background` 起后台任务，不要按固定秒数轮询等待。

刷完做一次**写后回读**核验，不要只信回执文字：

```bash
diff <(jq -S . /tmp/ip_before.json) <(jq -S . ~/.claude/plugins/installed_plugins.json) | head -40
```

每条真被刷新的记录应能看到 `version` / `gitCommitSha` / `lastUpdated` 的变化。清单里某条记录在 diff 中完全没出现，说明它那次 update 是假成功（最常见成因是 project scope 的 cwd 没进对，见下），要单独复查。

### 第三步补充：project scope 版本落后很多时先问用户，别默认拉平

探测输出里若出现同一个 id 在多个项目目录下**版本号落后好几个大版本**，不要当成"欠账"直接全刷。2026-08-06 本机实测：`sdlc@ai-sdlc` 在 12 个项目目录下横跨 `3.3.0` / `3.3.3` / `3.8.0` / `3.9.0` / `3.3.18` 五个版本，而市场源已到 `3.12.2`。这有两种完全不同的成因，处置相反：

- **有意钉版**——某个项目正依赖旧版行为，升级会改掉它的 skill / hook 行为。此时应保持不动。
- **确实漏刷**——那些项目只是很久没打开过。此时该刷。

**从配置里区分不出这两者**，所以把清单出示给用户、由用户拍板刷哪些。别用"版本号落后"当作可以自主升级的理由——升级 project scope 插件会改变**别的项目**下一次启动时加载的代码。

### 第四步：告知如何让新版本生效（`/reload-plugins` 通常够用，但有一类注入不会追补）

刷新缓存**不会**热更新到正在运行的会话里：`claude plugin update` 的输出会提示 `Restart to apply changes.`，刷新完什么都不做等于白刷。必须显式告知用户这一点，不要让用户误以为当前会话已经在用新版本。

但**"必须完整重启"是过强的说法**，`/reload-plugins` 这个内置命令通常就够：它重载插件清单、skill、agent 与 hook（回执形如 `Reloaded: 25 plugins · 4 skills · 11 agents · 17 hooks`），**包括本次刷新新增的 hook 挂载点**。2026-07-29 实测：`working-discipline` 从 3.0.0 刷到 3.2.0（3.2.0 新增了 `SessionStart` 挂载点、并把每轮注入从 6717 字符压到 1163），跑完 `/reload-plugins` 后**下一轮**的 `UserPromptSubmit` 注入内容立刻变成 3.2.0 的短版，无需退出会话。

**唯一不会追补的是会话生命周期类事件的注入**，`SessionStart` 是典型：它只在 `startup` / `resume` / `clear` / `compact` 时触发，`/reload-plugins` **不会重放**它。后果是——如果新版本把内容下沉到了 `SessionStart`（而旧版本没有这个挂载点），reload 之后会进入一个**割裂状态**：每轮注入已经是新版的"指针 + 增量"，但它所引用的那份静态主体在本会话**从未注入过**，主体里的判据实际不在上下文里。同一现象也适用于 `SessionEnd` / `PreCompact` 等生命周期钩子。

所以按新版本改动了什么来给结论：

| 本次刷新改动了什么 | 让它生效的最小动作 |
|---|---|
| 只改 skill / agent / command 文本，或改已有 hook 的脚本逻辑 | `/reload-plugins` 即可 |
| 新增或改动 `PreToolUse` / `PostToolUse` / `UserPromptSubmit` 挂载点 | `/reload-plugins` 即可（实测新挂载点会生效） |
| 新增或改动 `SessionStart` / `SessionEnd` / `PreCompact` 挂载点 | **必须重启会话**（或等一次 auto-compact 触发 `SessionStart:compact` 把它补上），否则该份注入在本会话缺失 |

**怎么判断新版本是否含生命周期挂载点——必须同时查两处，漏一处会误判"无需重启"。** Claude Code 的插件有两种互相独立的 hook 定义方式，2026-08-01 实测各踩一种：

1. **字段式**：hook 在 `.claude-plugin/plugin.json` 的 `hooks` 字段里以 `hooks.SessionStart` / `hooks.PreCompact` 等 key 声明。例如 `working-discipline` 3.7.0 的 `hooks` 字段含 `SessionStart`。
2. **目录式**：hook 以 `hooks/` 目录下的脚本文件名约定挂载，`plugin.json` 里**没有** `hooks` 字段（可能配一份 `hooks/hooks.json` 登记事件绑定），`hooks/session-start.sh` / `hooks/pre-compact.sh` 等文件名直接对应生命周期事件。例如 `radnove-core` 4.5.1 的 `plugin.json` 无 `hooks` 字段，但 `hooks/` 下有 `session-start.sh`——只读 `plugin.json` 会判成"无 SessionStart"，实际它正是会话开头注入的那段内容。

检测命令（对某插件的 installPath 同时查两处，变量名避开 `path` 等 zsh 绑定名）：

```bash
ipath=<插件 installPath>
cfg="$ipath/.claude-plugin/plugin.json"; [ ! -f "$cfg" ] && cfg="$ipath/plugin.json"
jq -r '.hooks // {} | keys[]' "$cfg" 2>/dev/null | grep -iE 'SessionStart|SessionEnd|PreCompact'   # ① 字段式
ls "$ipath/hooks/" 2>/dev/null | grep -iE 'session-start|session-end|pre-compact'                   # ② 目录式
# 两条任一命中 → 该插件含生命周期挂载点 → 涉及其改动时必须重启会话
```

核实方式不要只看 reload 回执的数量，**看行为**：下一轮里 hook 注入的文本是否已经是新版内容（例如长度、章节结构变了），这才证明加载的是新代码。

### 第五步：清理缓存，回收磁盘占用

**执行顺序是硬约束：必须在第三步刷新完成之后才能清理，不能先清后刷。** 第三步会写入新版本目录，并让旧版本从"被引用"变成"未被引用"——先清理等于按刷新前的旧白名单判断，会把刚要用的版本算成垃圾，同时漏掉真正该删的旧版本。

清理对象分**两类**，判定方式完全不同，不要合并成一条命令处理。

#### (a) `temp_git_*` 临时克隆残留——优先清，收益最大且判定最简单

`cache/` 下会出现形如 `temp_git_<13 位毫秒时间戳>_<6 位随机后缀>` 的顶层目录（例如 `temp_git_1784510740316_ohwupx`），是插件安装/更新过程中的临时 git 克隆，正常流程结束后本应自行删除，实测会大量残留。

**成因 2026-08-06 已实测查明**：一次 `claude plugin update` 期间会**并发**起多个这样的克隆（该次观测峰值 4 个），且会顺带 fetch 非目标市场。这是 url 独立仓源插件（见「两类插件源」(b)）的必然代价——它的内容不在市场仓里，只能现拉。所以残留量与「本轮跑了多少次 update」正相关：按第一二步剪枝后调用次数大降，这类残留也跟着少了。

**残留数量在两次观测间波动极大，不要把具体数字当预期值，每次都实际 `ls` 一遍。** 观测一（2026-07-29 首次）：`cache/` 总占用 **2.9G**，其中 **13 个** `temp_git_*` 合计 **1.8G**，占了将近一半，比历史版本堆积严重得多。观测二（同日晚，清掉观测一的残留、又完整跑了一轮 17 市场 + 25 插件刷新之后）：`temp_git_*` **0 个**——说明这类残留不是每次刷新都必然产生，它取决于中途是否有克隆被打断。所以本小节可能直接命中"无残留"，这是正常结果，不要以为是命令写错了。

判定依据是"两份配置里零引用即孤立"：

```bash
grep -c 'temp_git' ~/.claude/plugins/known_marketplaces.json ~/.claude/plugins/installed_plugins.json
du -sch ~/.claude/plugins/cache/temp_git_*/ | tail -1
```

两个文件的计数都是 `0` 才说明这些目录没有任何配置指向它们，可以整批删除。若非 0，先查清是哪条配置在引用，不要删。

#### (b) 未被引用的历史版本目录——必须用白名单差集判定

**绝对不要按"每个插件保留最新版本、删掉其余"来清理。** 同一插件在不同项目目录下（`scope` 为 `project`）会各自钉住不同版本，"最新"只对当前项目成立。实测反例：`sdlc@ai-sdlc` 在 `installed_plugins.json` 里有 12 条 `project` 记录，横跨 `3.3.0` / `3.3.3` / `3.3.18` / `3.7.3` 四个版本；`aisdlc-saas-extension` 有 `0.4.2` / `0.4.1` 两个。按"保留最新"会删掉其他项目正在使用的缓存，那些项目下次启动会加载失败或被迫重新下载。

唯一正确的判据是：把 `installed_plugins.json` 里 `.plugins[][].installPath` 的**全集**作为白名单，白名单之外的三级目录才是候选。注意 `.plugins` 的每个值是**数组**（每个 scope 一条记录，各有自己的 `installPath` / `version`），所以 jq 必须写 `.plugins[][]` 展开两层，只取第一条会把绝大多数在用版本误判成垃圾。

先跑 dry-run，只统计不删除：

```bash
# 白名单：所有 scope 引用到的 installPath
jq -r '[.plugins[][] | .installPath] | unique | .[]' ~/.claude/plugins/installed_plugins.json | sort > /tmp/cache_whitelist.txt
# 磁盘实际：cache/<marketplace>/<plugin>/<version> 恰好是第 3 层，temp_git_* 已在 (a) 单独处理故排除
find ~/.claude/plugins/cache -mindepth 3 -maxdepth 3 -type d -not -path '*/temp_git_*' | sort > /tmp/cache_actual.txt
# 差集：磁盘有、配置未引用 = 可删候选
comm -13 /tmp/cache_whitelist.txt /tmp/cache_actual.txt > /tmp/cache_orphan.txt
echo "白名单 $(wc -l < /tmp/cache_whitelist.txt) / 磁盘 $(wc -l < /tmp/cache_actual.txt) / 可删 $(wc -l < /tmp/cache_orphan.txt)"
[ -s /tmp/cache_orphan.txt ] && du -sch $(cat /tmp/cache_orphan.txt) | tail -1
# 反向检查（必须为空）：配置引用了但磁盘不存在
comm -23 /tmp/cache_whitelist.txt /tmp/cache_actual.txt
```

两次实测的差集规模（同样只作量级参考，不是预期值）：观测一 **58 个目录 / 704M**（白名单 48 条、磁盘 106 个）；观测二在清掉观测一之后 **14 个 / 25M**（白名单 48 条、磁盘 62 个），其中最大一块是单个 `sdlc/3.7.16` 占 16M。清理收益随执行频率快速衰减——第二次只回收了 25M（`cache/` 408M → 383M，约 6%），大头始终在白名单内的在用版本里。如实告知用户这个量级，不要暗示清理能显著省空间。

**反向检查那一行必须输出为空**。若非空，说明有插件的配置指向了磁盘上不存在的缓存目录，缓存状态本身已异常——此时不要删任何东西，先回到第三步重新刷新把实体补齐，再重跑 dry-run。

确认无误、并已把候选清单出示给用户获得同意后再删除：

```bash
xargs rm -rf < /tmp/cache_orphan.txt
```

删除的代价要如实告知用户：被删版本在需要降级/回滚时要重新从市场源下载，属于可恢复但需要网络。如果用户明确有回滚预期，保守做法是从 `/tmp/cache_orphan.txt` 里手动剔除每个插件最近的 1-2 个版本再删。

## 已验证的坑

| 现象 | 真实原因 | 怎么核实 |
|------|----------|----------|
| 想用 `known_marketplaces.json` 里的 `lastUpdated` 判断某个市场是否真的拉到了新代码 | **`lastUpdated` 两个变化方向都已观测到反例，不可作为判据。** 方向一（首次执行时记录）：回执 `✔ Successfully updated N marketplace(s)` 但某市场 `lastUpdated` 没变，当时结论是"该市场已是最新，字段语义为上次真正拉到新内容的时间"，在两个纯 GitHub 源市场稳定复现。方向二（2026-07-29 复跑时观测）：17 个市场的 `lastUpdated` **全部**前移到同一分钟区间（`01:21`~`01:23`），无一例外，但其中 `karpathy-skills` 的本地 HEAD 仍是 `2c60614`、提交日期 `2026-04-20`（三个月前），且前一天已经更新过一轮、本地早该到位——时间戳前移并未对应任何新内容。两次观测互相矛盾，最可能的解释是 CLI 版本之间改过写入语义（从"拉到新内容才写"变成"每次成功检查都写"），也不排除与市场源类型有关 | 只信 HEAD，不信时间戳。更新**前**先存一份快照：`git -C ~/.claude/plugins/marketplaces/<name> rev-parse HEAD`，更新后再取一次对比；或用 `git -C 同目录 ls-remote origin <branch>` 与本地 HEAD 比对。**既不要**因为 `lastUpdated` 变了就判定"拉到了新代码"，**也不要**因为它没变就判定失败——两种推断都已被实测推翻 |
| 想用 `git -C ~/.claude/plugins/marketplaces/<name> log` 核实某市场是否最新，报错 `fatal: not a git repository` | 不是所有市场都是纯 git clone。例如官方 `claude-plugins-official`：即使 `known_marketplaces.json` 里登记的 `source` 字段写的是 `github`，其本地目录下实际没有 `.git`，只有一个 `.gcs-sha` 文件——它按内容哈希做整体快照同步，不是逐 commit 拉取 | 先 `ls -la ~/.claude/plugins/marketplaces/<name>` 看有没有 `.git` 目录；没有就别拿 git 命令去验真伪，直接看 CLI 回执，或对比 `installed_plugins.json` 里该市场旗下插件的 `gitCommitSha`/`lastUpdated` 字段变化 |
| `claude plugin update <plugin>` 找不到批量刷新的写法 | CLI 没有 `--all` 之类的参数（见 `--help`），设计上一次只处理一个 `<plugin>@<marketplace>` | 只能枚举 `enabled: true` 的 id 后自己拼循环（见第三步） |
| 同一插件在 `installed_plugins.json` 里出现好几条记录，`version`/`installPath` 都相同 | 不同项目目录各 `enable` 过一次，各记一条 `scope` 记录，但共用同一份缓存目录（见第二步） | 只需跑一次 `claude plugin update`，不按项目数重复刷 |
| 刷新了缓存，当前会话里 skill/hook 行为却没有变化 | 缓存刷新不热更新到运行中的进程里（见第四步） | 跑 `/reload-plugins`；只有涉及 `SessionStart` / `SessionEnd` / `PreCompact` 这类生命周期挂载点时才必须重启 |
| 跑完 `/reload-plugins` 后，每轮 hook 注入已经是新版的"指针"文本，但它引用的那份静态主体内容压根不在上下文里 | 新版本把内容下沉到了 `SessionStart`，而 reload **不重放**生命周期事件（见第四步）。实测 `working-discipline` 3.0.0 → 3.2.0：reload 后本会话里那句"一～六章已在会话开始注入"**不成立** | 涉及 `SessionStart` 类挂载点变动必须重启会话，或等一次 auto-compact 补上；判据是**同时查两处**（`plugin.json` 的 `hooks` 字段 + `hooks/` 目录下的脚本文件名约定，见第四步检测命令），只读 `plugin.json` 会漏掉目录式定义的插件——2026-08-01 实测 `radnove-core` 4.5.1 就是目录式（`plugin.json` 无 `hooks` 字段、`hooks/session-start.sh` 存在），只读 `plugin.json` 误判为无 SessionStart |
| 核验循环里所有 `jq` / `sort` / `wc` / `comm` 突然 `command not found`，但循环之前同样的命令刚跑成功过 | 循环变量名撞上 zsh 的 `typeset -T PATH path` 绑定（见第三步「循环变量禁止命名为 `path`」） | 改用带语义前缀的变量名（`ipath` / `_p` / `orphan_dir`）改名重跑即可；PATH 只在该次 Bash 调用的子 shell 内被破坏，**不影响后续调用** |
| 第三步的循环只跑了一次就整体失败，报 `Plugin "<第一个插件名>" not found`，可那个插件明明装着 | 用了 `for p in $plugins` 依赖单词分割的写法，zsh 默认不做单词分割（见第三步） | 改成 `while IFS= read -r p` 逐行读；这类失败**无副作用**——CLI 在 id 校验阶段就退出，没有写 `installed_plugins.json`、没有刷新任何插件，改好写法直接重跑即可 |
| 第三步的循环整体跑完、回执看着都正常滚过去了，但某个只在项目目录里装过的插件（从未在 `user` scope 装过）实际上完全没被刷新 | `claude plugin update "$p"` 默认 `--scope user`，无 `user` scope 记录的 id 会 `exit=1` 但循环不检查退出码（机制与 8 个实测复现 id 见「第三步」） | 同一条 jq 判定式（见「第三步」），命中的 id 都要走 project/local scope 专项刷新，不能指望第三步的常规循环覆盖到 |
| 对某个 project scope 插件跑 `claude plugin update --scope project <id>`，回执 `already at the latest version`，但其实完全没有更新到真正需要的那个项目 | `--scope project`/`--scope local` 靠 cwd 隐式定位、不接受路径参数，cwd 不匹配时不报错、只打印假成功回执（机制与 2026-07-30 实测 demo 见「第三步」） | 必须先 `cd` 进该记录**自己的** `projectPath` 再执行；核实靠写后回读 diff，确认 `version`/`gitCommitSha`/`lastUpdated` 三者都变了，而不是只信"already at the latest version"这句回执文字 |
| `cache/` 目录体积远大于所有已启用插件之和（实测 2.9G） | `temp_git_*` 临时克隆残留没被清掉，13 个占 1.8G，在两份配置里都是 0 引用（见第五步 (a)） | `grep -c 'temp_git' ~/.claude/plugins/known_marketplaces.json ~/.claude/plugins/installed_plugins.json` 两处都为 0 即确认孤立，可整批删除 |
| 清理历史版本缓存后，某个项目下的插件失效或被迫重新下载 | 按"每个插件只保留最新版本"删了。实测 `sdlc@ai-sdlc` 有 12 条 project 记录横跨 4 个版本（`3.3.0`/`3.3.3`/`3.3.18`/`3.7.3`），"最新"只对当前项目成立（见第五步 (b)） | 必须以 `.plugins[][].installPath` 的全集为白名单做差集，`.plugins[][]` 要展开两层，只取第一条会把在用版本误判成垃圾 |
| 一次完整刷新要跑 30~50 分钟（2026-08-06 之前那轮实测从 01:55 跑到 02:47） | 没做探测剪枝，把两类固定开销全付了一遍：不带参数的 `marketplace update` 串行 clone 全部 17 个市场（14~16 分钟），加上对每条已启用记录都调一次 `plugin update`（**每次 25 秒起步，与它有没有活干无关**，113 条 ≈ 47 分钟） | 先跑 `probe-refresh.py --stage market` / `--stage plugin`（合计约 8.5 秒），只对判定为 STALE / 版本或 sha 不一致的目标调 CLI。本机实测 82 / 113 条可直接跳过 |
| 想靠并发跑多个 `claude plugin update` 来加速 | 它们读改写同一个 `installed_plugins.json` 且 CLI 内部无文件锁，后写覆盖先写会丢记录；用 `flock` 包住调用则全部在锁处排队，退化成串行、零加速 | 加速只能靠减少调用次数（第一、二步的探测剪枝），这一步保持串行 |
| 在 shell 里用 `timeout 20 git ls-remote …` 做探测，结果所有市场瞬间全部"探测失败"（总耗时只几十毫秒） | **macOS 默认没有 `timeout` 这个二进制**（GNU coreutils 才有，Homebrew 装的叫 `gtimeout`），命令整体 `command not found`，输出为空被误判成远端不可达 | `command -v timeout gtimeout` 先确认；没有就别包，或改用 python 的 `subprocess.run(..., timeout=)`（探测器脚本走的就是后者） |
| 拿 `installed_plugins.json` 里的 `gitCommitSha` 去和市场仓 HEAD 比，判断插件要不要刷，结果几乎全判成"要刷" | 这个字段的语义**按插件源类型不同**：url 独立仓源的插件，它就是那个独立仓的 commit sha（可直接比）；市场仓内源的插件，它记的是上次刷新时市场仓的某个 commit，与该插件目录最后改动的 commit 大面积不相等（2026-08-06 抽 14 个样本只 1 个吻合） | 市场仓内源**只比版本号**（marketplace.json 条目的 `version`，缺失时回落读该目录 `plugin.json`）；url 源才比 sha（`git ls-remote <url> <ref>`）。见「两类插件源」 |
| 为了拿 enabled 状态而跑 `claude plugin list --json`，一条命令等 23 秒 | 该命令与 `plugin update` 共享同一类固定开销 | enabled 状态可直读：user scope 看 `~/.claude/settings.json` 的 `enabledPlugins[<id>]`，project/local scope 看 `<projectPath>/.claude/settings.json` 或 `settings.local.json`（2026-08-06 三条 project 记录实测与 `plugin list` 一致）。探测器脚本已内置，key 缺失按未启用处理 |

## 验证清单

- [ ] **没有**跑不带参数的 `claude plugin marketplace update`，也**没有**对每个已启用插件都调一次 `plugin update`；两层都先跑过探测（`--stage market` / `--stage plugin`），只对判定需要动的目标调 CLI
- [ ] 两个探测阶段的**顺序**是 market 在前、plugin 在后（插件层的版本比对必须读到已更新的市场清单）
- [ ] 探测结果里的 `PROBE_FAIL` / `NO_GIT` / 「判不了」项都被**列入了待刷**，没有被当成"已是最新"跳过
- [ ] 判断市场是否真的拉到新代码时用的是 HEAD 对比，**没有**拿 `lastUpdated` 当判据（它变了 / 没变都不能证明任何一个方向）
- [ ] 待刷清单里的每条记录都刷过一次，且清单是按 (id, scope, projectPath) **逐条**算的，不是按 id 去重后的数量
- [ ] 第三步用的是 `while IFS= read -r` 逐行读，不是 `for p in $plugins`（zsh 下后者必坏）
- [ ] 每条 `claude plugin update` 都**显式传了 `--scope`**（默认值是 `user`，只在项目里装过的 id 会静默 `exit=1` 滚屏而过）
- [ ] project/local scope 的刷新里，每条命令执行前都真的 `cd` 进了该记录**自己的** `projectPath`（不是随手挑的当前目录），且刷新后用快照 diff 核实了该记录的 `version`/`gitCommitSha`/`lastUpdated` 确实变化，而不是只信"already at the latest version"这句回执文字
- [ ] project scope 出现跨大版本落后（如 `3.3.0` vs 市场 `3.12.2`）时，清单已出示给用户并由用户拍板刷哪些，**没有**自主拉平（可能是有意钉版，升级会改掉别的项目的行为）
- [ ] 所有循环 / 临时变量都**没有**取名 `path` / `fpath` / `cdpath` / `manpath` 等 zsh 绑定变量名（会静默覆写 `$PATH`，表象是"jq 没装"）
- [ ] 每条 `claude plugin update` 的输出都在预期的三种正常结束态之一：`already at the latest version`、`updated from X to Y`、`refreshed from source`
- [ ] 关键插件已走**写后回读**核实：`installed_plugins.json` 的 `installPath`、磁盘上该缓存目录、目录内 `.claude-plugin/plugin.json` 的 `version` 三处一致（只看 CLI 回执不足以证明落盘）
- [ ] 若执行了第五步清理：确认在第三步刷新**之后**做的；`temp_git_*` 零引用已 grep 核实；历史版本走的是 `.plugins[][].installPath` 白名单差集；反向检查（配置引用但磁盘缺失）输出为空；删除清单已出示给用户并获得同意
- [ ] 已明确告知用户让新版本生效的**最小动作**：默认建议 `/reload-plugins`；仅当新版本改动了 `SessionStart` / `SessionEnd` / `PreCompact` 挂载点时才说”必须重启”（判断依据是**同时查两处**：`plugin.json` 的 `hooks` 字段 + `hooks/` 目录下的脚本文件名约定，见第四步检测命令；只查 `plugin.json` 会漏掉目录式 hook，误判”无需重启”）
- [ ] 生效后的核实看的是**行为**（下一轮 hook 注入文本 / skill 内容确实变了），不是 reload 回执里的插件数量
