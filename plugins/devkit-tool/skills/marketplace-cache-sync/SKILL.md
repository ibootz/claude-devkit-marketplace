---
name: marketplace-cache-sync
description: 拉取 Claude Code 已配置的插件市场(marketplace)最新代码，刷新已启用插件(enabled plugin)的本地缓存版本(含 user scope 与 project/local scope 两种安装范围)，并在刷新后回收缓存磁盘占用。
when_to_use: |
  用户说"更新一下插件市场"、"拉取 marketplace 最新代码"、"刷新插件缓存"、"plugin 装的新版本怎么不生效"、"skill 改了但没同步过来"、"市场 lastUpdated 变了/没变是不是真的更新了"、"marketplace update 之后要不要重启"、"插件缓存占了多少空间"、"清理插件缓存"、"cache 目录太大"、"temp_git_ 开头的目录能删吗"、"历史版本缓存能不能删"、"reload-plugins 够不够还是必须重启"、"reload 完 hook 还是旧的"、"某个项目里装的插件版本没跟着更新"、"project scope 的插件怎么刷新"、"这个插件只在某个项目里装了，全局刷新覆盖不到"。
---

# Marketplace Cache Sync（插件市场与插件缓存刷新）

把"更新插件市场"这件事拆成两层动作依次执行，并在核实每一层是否真的生效时避开已知的误判坑。

**验证基础**：内容来自两次真实全量执行（17 个 marketplace + 25 个 enabled plugin，2026-07-29 复跑）+ 一次 project/local scope 专项验证（2026-07-30，8 个仅装在 project/local scope、从未装过 user scope 的插件 id），覆盖两层模型（marketplace 源 vs 已启用插件缓存）、批量刷新写法、project/local scope 按 (id, projectPath) 逐条刷新、缓存清理白名单差集算法，以及下方「已验证的坑」列出的各条已复现问题。

## 背景：两层状态，容易只做一半

Claude Code 的插件系统有两层独立状态，都在 `~/.claude/plugins/` 下：

1. **Marketplace（插件市场，"源"）**：`known_marketplaces.json` 登记每个市场的 git/github 源地址与 `installLocation`，实际内容克隆在 `marketplaces/<name>/`。`claude plugin marketplace update [name]` 拉取的是这一层——市场仓库本身的最新代码，相当于所有插件定义的"上游"。
2. **Installed/enabled plugin（已启用插件，"缓存"）**：`installed_plugins.json` 登记每个 `<plugin>@<marketplace>` 具体钉住的版本号/commit sha，实际内容缓存在 `cache/<marketplace>/<plugin>/<version>/`。`claude plugin update <plugin>@<marketplace>` 刷新的才是这一层——把某个已启用插件的缓存副本，从（已经更新过的）市场源里重新拉一份下来。

第 2 层内部还分**两种互相独立的安装范围（scope）**，`installed_plugins.json` 里同一个 `<plugin>@<marketplace>` id 下的 `plugins[id]` 是一个**数组**，每个元素各带一个 `scope` 字段（`user` / `project` / `local`）：`user` scope 是当前用户全局共用的一份钉版，跨项目共享；`project` / `local` scope 是**某一个具体项目目录**（`projectPath` 字段）单独钉住的版本，同一个 id 在不同项目目录下可以各自钉着不同版本号——例如 `sdlc@ai-sdlc` 在 12 个不同项目目录下横跨 `3.3.0`/`3.3.3`/`3.3.18`/`3.8.0` 四个版本互不影响。**第二步 `claude plugin list --json` 里 `enabled` 字段也是按 (id, projectPath) 各自独立的**——同一个 id 在 A 项目可能 `enabled: true`、在 B 项目 `enabled: false`，不是插件级的单一开关。第三步的常规刷新流程默认只处理 `user` scope（原因见下面的补充小节），`project`/`local` scope 需要单独一轮，见「第三步补充」。

**第 1 层更新了不代表第 2 层跟着更新**：市场仓库拉到最新 commit 后，已启用插件的缓存副本仍然钉在旧版本号/旧 commit，除非显式对每个启用中的插件跑一次 `claude plugin update`。两层都做才算一次完整同步，只做第 1 层是最常见的"以为更新了其实没生效"的原因。

## 执行工作流

### 第一步：全量拉取所有 marketplace

```bash
claude plugin marketplace update
```

不带参数即为对 `known_marketplaces.json` 里登记的**全部**市场执行更新；只想更新单个市场传 `claude plugin marketplace update <name>`。市场数量多（例如 15+ 个，尤其含公司内网 git 源）时，这一步可能耗时数分钟，用 `run_in_background` 起后台任务，不要按固定秒数轮询等待。

### 第二步：枚举当前"已启用"的插件

```bash
claude plugin list --json
```

从结果里筛 `"enabled": true` 的条目，按 `id`（形如 `<plugin>@<marketplace>`）去重——**同一个 id 可能因为在多个项目目录里分别 enable 过而重复出现多条记录**（`scope` 分别是 `project`/`user`），但它们的 `installPath` 指向同一份缓存，只需刷新一次，不用按项目数重复刷。

### 第三步：逐个刷新已启用插件的缓存

```bash
claude plugin list --json | jq -r '.[] | select(.enabled==true) | .id' | sort -u > /tmp/enabled_plugins.txt
echo "待刷新插件数: $(wc -l < /tmp/enabled_plugins.txt | tr -d ' ')"
while IFS= read -r p; do
  [ -z "$p" ] && continue
  echo "=== $p ==="
  claude plugin update "$p" 2>&1
done < /tmp/enabled_plugins.txt
```

**必须用 `while IFS= read -r` 逐行读，不要写 `for p in $plugins`。** Claude Code 的 Bash 工具在 macOS 上走 zsh，而 zsh 默认**不对未加引号的变量做单词分割**（bash 会）——`for p in $plugins` 会把整个多行字符串当成**一个** token 传给 CLI，报 `Plugin "<第一个插件名>" not found` 后整个循环失败。落地成临时文件再逐行读，不依赖任何 shell 的分词行为。

**循环变量禁止命名为 `path`（以及 `fpath` / `cdpath` / `manpath` / `fignore` / `mailpath` / `module_path`）。** zsh 用 `typeset -T PATH path` 把这些小写名与同名大写环境变量**双向绑定**——写 `path` 就是写 `PATH`。所以 `while IFS= read -r path ver` 会在第一次迭代把 `$PATH` 覆盖成一个目录字符串，之后循环体内所有外部命令（`jq` / `sort` / `wc` / `comm` / `du`）全部 `command not found`。**这个故障极易误判**：循环**之前**的同名命令已经跑成功了，报错看起来像"jq 没装好 / 环境坏了"，而真正的原因是自己把 PATH 写没了。本步与第五步的核验循环都要读 `installPath`，是最容易踩的位置——统一用带语义前缀的名字（`ipath` / `_p` / `orphan_dir`）。判据：**任何出现在 shell 片段里的小写变量名，若其大写形式是常见环境变量，就换名。**

```bash
echo a | while IFS= read -r path;  do jq --version; done   # command not found: jq
echo a | while IFS= read -r ipath; do jq --version; done   # jq-1.7.1
```

**必须串行执行，不能并发派发**：`claude plugin update` 会读改写共享的单个文件 `~/.claude/plugins/installed_plugins.json`，多个进程同时跑存在写竞态——后写完的会覆盖先写完的那条记录，可能导致某些插件的刷新结果丢失。

（`claude plugin update` 没有 `--all`/批量参数，一次只能指定一个 `<plugin>@<marketplace>`，只能像上面这样自己拼循环。）

插件数量多（25 个左右）时整个循环耗时数分钟，同样用 `run_in_background` 起后台任务。

### 第三步补充：project/local scope 插件的刷新——常规流程覆盖不到的缺口

**这是一个第三步天然会漏掉、且漏掉时完全没有任何报错提示的缺口，必须单独跑一轮。**

第三步的循环对 `claude plugin list --json` 里 `enabled==true` 的条目按 `.id` 去重后，逐个执行 `claude plugin update "$p"`（不带 `--scope` 参数）。查 `claude plugin update --help` 可知这个参数有默认值——`-s, --scope <scope>  Installation scope: user, project, local, managed (default: user)`——所以第三步等价于对每个 id 只尝试刷新它的 `user` scope 记录。**如果某个 id 从来没有 `user` scope 记录、只在一个或多个项目目录下以 `project`/`local` scope 装过**，这条命令会报错退出（`exit=1`）：

```
$ claude plugin update cskl-dev@curatedskills-dev
Checking for updates for plugin "cskl-dev@curatedskills-dev" at user scope…
✘ Failed to update plugin "cskl-dev@curatedskills-dev": Plugin "cskl-dev" is not installed at scope user
```

第三步给出的循环写法本身不检查每条命令的退出码，这类失败会和其它插件的成功回执一起滚屏而过，**看起来像是流程正常跑完了，实际上这个插件从未被刷新过**。2026-07-30 在本机实测复现了 8 个这样的 id：`aisdlc-cust-extension@aisdlc-cust-extension`、`aisdlc-saas-extension@aisdlc-saas-extension`、`cctx-dev-xxv2-base@codifiedcontext-dev`、`cskl-dev@curatedskills-dev`、`dc@curatedskills-dev`、`fusion@aisdlc-fusion`、`prod@xxstar-prod-ai`、`sdlc@ai-sdlc`——判定方法是 `jq -r '.plugins | to_entries[] | select(.value | map(.scope) | index("user") | not) | .key' ~/.claude/plugins/installed_plugins.json`，凡是数组里所有元素的 `scope` 都不含 `"user"` 的 id 就属于这一类。

#### 枚举需要刷新的 (id, projectPath, scope) 组合

不能按 id 去重后刷一次就完事——同一个 id 在不同项目目录可能各自钉着不同版本，且 `enabled` 状态也是按项目各自独立的（见上一节）。直接用 `claude plugin list --json` 现成算好的 `enabled` 字段筛，不要回退去读 `installed_plugins.json` 原始数组自己判断：

```bash
claude plugin list --json | jq -r '.[] | select((.scope=="project" or .scope=="local") and .enabled==true) | "\(.id)|\(.projectPath)|\(.scope)"' | sort -u > /tmp/project_scope_plugins.txt
echo "待刷新的项目级组合数: $(wc -l < /tmp/project_scope_plugins.txt | tr -d ' ')"
```

#### 逐条 cd 进目标项目目录再刷新

```bash
while IFS='|' read -r pid ppath pscope; do
  [ -z "$pid" ] && continue
  if [ ! -d "$ppath" ]; then
    echo "跳过（目录已不存在）: $pid @ $ppath"
    continue
  fi
  echo "=== $pid @ $ppath (scope=$pscope) ==="
  (cd "$ppath" && claude plugin update --scope "$pscope" "$pid") 2>&1
done < /tmp/project_scope_plugins.txt
```

用子 shell `(cd "$ppath" && ...)` 而不是裸 `cd`，避免污染当前 Bash 调用之后的 cwd（同一坑见本仓 `.claude/rules/` 里 bash-guard 的判定）。和第三步一样必须**串行**执行——`claude plugin update` 无论哪个 scope 都在读改写同一个共享文件 `~/.claude/plugins/installed_plugins.json`，并发跑仍然存在后写覆盖先写的竞态。目录缺失（项目已删除但配置残留）不算错误，跳过并报告即可，不要让整批失败。

**关键陷阱：`--scope project` / `--scope local` 靠当前工作目录隐式定位目标项目，不接受任何显式路径参数；且 cwd 不匹配时不会报错，而是打印看似成功的回执、对配置零改动。** 2026-07-30 实测：在与 `cskl-dev@curatedskills-dev` 完全无关的目录（本仓 `claude-devkit-marketplace`，从未装过这个插件的任何 project scope 记录）下执行 `claude plugin update --scope project cskl-dev@curatedskills-dev`，回执是 `✔ cskl-dev is already at the latest version (1.5.1)`，但更新前后 `diff <(jq -S . 快照) <(jq -S . ~/.claude/plugins/installed_plugins.json)` 是 **0 行差异**——这句"已是最新"完全没有对应到任何真实的项目记录，纯粹是误导性的假成功。所以上面的循环必须先 `cd` 进 `/tmp/project_scope_plugins.txt` 里那条记录**自己的** `projectPath`，不能图省事随便挑一个当前目录跑；核实同样要靠**写后回读**——刷新前后各存一份 `installed_plugins.json` 快照，diff 应显示该 (id, projectPath) 对应记录的 `version`/`gitCommitSha`/`lastUpdated` 三者都变了，而不是只看命令回执的文字。

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

核实方式不要只看 reload 回执的数量，**看行为**：下一轮里 hook 注入的文本是否已经是新版内容（例如长度、章节结构变了），这才证明加载的是新代码。

### 第五步：清理缓存，回收磁盘占用

**执行顺序是硬约束：必须在第三步刷新完成之后才能清理，不能先清后刷。** 第三步会写入新版本目录，并让旧版本从"被引用"变成"未被引用"——先清理等于按刷新前的旧白名单判断，会把刚要用的版本算成垃圾，同时漏掉真正该删的旧版本。

清理对象分**两类**，判定方式完全不同，不要合并成一条命令处理。

#### (a) `temp_git_*` 临时克隆残留——优先清，收益最大且判定最简单

`cache/` 下会出现形如 `temp_git_<13 位毫秒时间戳>_<6 位随机后缀>` 的顶层目录（例如 `temp_git_1784510740316_ohwupx`），是插件安装/更新过程中的临时 git 克隆，正常流程结束后本应自行删除，实测会大量残留。

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
| 跑完 `/reload-plugins` 后，每轮 hook 注入已经是新版的"指针"文本，但它引用的那份静态主体内容压根不在上下文里 | 新版本把内容下沉到了 `SessionStart`，而 reload **不重放**生命周期事件（见第四步）。实测 `working-discipline` 3.0.0 → 3.2.0：reload 后本会话里那句"一～六章已在会话开始注入"**不成立** | 涉及 `SessionStart` 类挂载点变动必须重启会话，或等一次 auto-compact 补上；判据看新版 `plugin.json` 的 `hooks` 字段，不看 reload 回执 |
| 核验循环里所有 `jq` / `sort` / `wc` / `comm` 突然 `command not found`，但循环之前同样的命令刚跑成功过 | 循环变量名撞上 zsh 的 `typeset -T PATH path` 绑定（见第三步「循环变量禁止命名为 `path`」） | 改用带语义前缀的变量名（`ipath` / `_p` / `orphan_dir`）改名重跑即可；PATH 只在该次 Bash 调用的子 shell 内被破坏，**不影响后续调用** |
| 第三步的循环只跑了一次就整体失败，报 `Plugin "<第一个插件名>" not found`，可那个插件明明装着 | 用了 `for p in $plugins` 依赖单词分割的写法，zsh 默认不做单词分割（见第三步） | 改成 `while IFS= read -r p` 逐行读；这类失败**无副作用**——CLI 在 id 校验阶段就退出，没有写 `installed_plugins.json`、没有刷新任何插件，改好写法直接重跑即可 |
| 第三步的循环整体跑完、回执看着都正常滚过去了，但某个只在项目目录里装过的插件（从未在 `user` scope 装过）实际上完全没被刷新 | `claude plugin update "$p"` 默认 `--scope user`，无 `user` scope 记录的 id 会 `exit=1` 但循环不检查退出码（机制与 8 个实测复现 id 见「第三步补充」） | 同一条 jq 判定式（见「第三步补充」），命中的 id 都要走 project/local scope 专项刷新，不能指望第三步的常规循环覆盖到 |
| 对某个 project scope 插件跑 `claude plugin update --scope project <id>`，回执 `already at the latest version`，但其实完全没有更新到真正需要的那个项目 | `--scope project`/`--scope local` 靠 cwd 隐式定位、不接受路径参数，cwd 不匹配时不报错、只打印假成功回执（机制与 2026-07-30 实测 demo 见「第三步补充」） | 必须先 `cd` 进该记录**自己的** `projectPath` 再执行；核实靠写后回读 diff，确认 `version`/`gitCommitSha`/`lastUpdated` 三者都变了，而不是只信"already at the latest version"这句回执文字 |
| `cache/` 目录体积远大于所有已启用插件之和（实测 2.9G） | `temp_git_*` 临时克隆残留没被清掉，13 个占 1.8G，在两份配置里都是 0 引用（见第五步 (a)） | `grep -c 'temp_git' ~/.claude/plugins/known_marketplaces.json ~/.claude/plugins/installed_plugins.json` 两处都为 0 即确认孤立，可整批删除 |
| 清理历史版本缓存后，某个项目下的插件失效或被迫重新下载 | 按"每个插件只保留最新版本"删了。实测 `sdlc@ai-sdlc` 有 12 条 project 记录横跨 4 个版本（`3.3.0`/`3.3.3`/`3.3.18`/`3.7.3`），"最新"只对当前项目成立（见第五步 (b)） | 必须以 `.plugins[][].installPath` 的全集为白名单做差集，`.plugins[][]` 要展开两层，只取第一条会把在用版本误判成垃圾 |

## 验证清单

- [ ] 判断市场是否真的拉到新代码时用的是 HEAD 对比，**没有**拿 `lastUpdated` 当判据（它变了 / 没变都不能证明任何一个方向）
- [ ] `claude plugin list --json` 筛出的全部 `enabled: true` 插件 id 都刷新过一次（按 id 去重后的数量，不是原始条目数）
- [ ] 第三步用的是 `while IFS= read -r` 逐行读，不是 `for p in $plugins`（zsh 下后者必坏）
- [ ] 已单独跑过「第三步补充」：`jq` 判定式找出所有数组里不含 `"user"` scope 的 id，逐个确认它们在本轮的 project/local scope 循环里被刷新过，不是只看第三步的常规回执滚屏正常就当作已覆盖
- [ ] project/local scope 的刷新循环里，每条命令执行前都真的 `cd` 进了该记录**自己的** `projectPath`（不是随手挑的当前目录），且刷新后用快照 diff 核实了该记录的 `version`/`gitCommitSha`/`lastUpdated` 确实变化，而不是只信"already at the latest version"这句回执文字
- [ ] 所有循环 / 临时变量都**没有**取名 `path` / `fpath` / `cdpath` / `manpath` 等 zsh 绑定变量名（会静默覆写 `$PATH`，表象是"jq 没装"）
- [ ] 每条 `claude plugin update` 的输出都在预期的三种正常结束态之一：`already at the latest version`、`updated from X to Y`、`refreshed from source`
- [ ] 关键插件已走**写后回读**核实：`installed_plugins.json` 的 `installPath`、磁盘上该缓存目录、目录内 `.claude-plugin/plugin.json` 的 `version` 三处一致（只看 CLI 回执不足以证明落盘）
- [ ] 若执行了第五步清理：确认在第三步刷新**之后**做的；`temp_git_*` 零引用已 grep 核实；历史版本走的是 `.plugins[][].installPath` 白名单差集；反向检查（配置引用但磁盘缺失）输出为空；删除清单已出示给用户并获得同意
- [ ] 已明确告知用户让新版本生效的**最小动作**：默认建议 `/reload-plugins`；仅当新版本改动了 `SessionStart` / `SessionEnd` / `PreCompact` 挂载点时才说"必须重启"（判断依据是新版 `plugin.json` 的 `hooks` 字段，见第四步表格）
- [ ] 生效后的核实看的是**行为**（下一轮 hook 注入文本 / skill 内容确实变了），不是 reload 回执里的插件数量
