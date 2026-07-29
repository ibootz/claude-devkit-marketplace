---
name: marketplace-cache-sync
description: 拉取 Claude Code 已配置的插件市场(marketplace)最新代码，刷新已启用插件(enabled plugin)的本地缓存版本，并在刷新后回收缓存磁盘占用。Use when：用户说"更新一下插件市场"、"拉取 marketplace 最新代码"、"刷新插件缓存"、"plugin 装的新版本怎么不生效"、"skill 改了但没同步过来"、"市场 lastUpdated 变了/没变是不是真的更新了"、"marketplace update 之后要不要重启"、"插件缓存占了多少空间"、"清理插件缓存"、"cache 目录太大"、"temp_git_ 开头的目录能删吗"、"历史版本缓存能不能删"。内容基于两次真实全量执行(17 个 marketplace + 25 个 enabled plugin，2026-07-29 复跑)验证过，覆盖两层模型(marketplace 源 vs 已启用插件缓存)、批量刷新写法、缓存清理的白名单差集算法，以及非纯 git 市场/lastUpdated 语义不可作判据/zsh 分词导致循环失效等已复现的坑。
---

# Marketplace Cache Sync（插件市场与插件缓存刷新）

把"更新插件市场"这件事拆成两层动作依次执行，并在核实每一层是否真的生效时避开已知的误判坑。

## 背景：两层状态，容易只做一半

Claude Code 的插件系统有两层独立状态，都在 `~/.claude/plugins/` 下：

1. **Marketplace（插件市场，"源"）**：`known_marketplaces.json` 登记每个市场的 git/github 源地址与 `installLocation`，实际内容克隆在 `marketplaces/<name>/`。`claude plugin marketplace update [name]` 拉取的是这一层——市场仓库本身的最新代码，相当于所有插件定义的"上游"。
2. **Installed/enabled plugin（已启用插件，"缓存"）**：`installed_plugins.json` 登记每个 `<plugin>@<marketplace>` 具体钉住的版本号/commit sha，实际内容缓存在 `cache/<marketplace>/<plugin>/<version>/`。`claude plugin update <plugin>@<marketplace>` 刷新的才是这一层——把某个已启用插件的缓存副本，从（已经更新过的）市场源里重新拉一份下来。

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

**必须串行执行，不能并发派发**：`claude plugin update` 会读改写共享的单个文件 `~/.claude/plugins/installed_plugins.json`，多个进程同时跑存在写竞态——后写完的会覆盖先写完的那条记录，可能导致某些插件的刷新结果丢失。`claude plugin update` 没有 `--all`/批量参数，一次只能指定一个 `<plugin>@<marketplace>`，只能像上面这样自己拼循环。

插件数量多（25 个左右）时整个循环耗时数分钟，同样用 `run_in_background` 起后台任务。

### 第四步：告知需要重启才生效

刷新缓存只影响**下次启动**加载的版本；当前运行中的会话仍然使用旧版本插件内容（无论是 hook 逻辑、SKILL.md 文本还是 command 定义）。`claude plugin update` 的输出会明确提示 `Restart to apply changes.`——刷新完不重启等于白刷，必须显式告知用户这一点，不要让用户误以为当前会话已经在用新版本。

### 第五步：清理缓存，回收磁盘占用

**执行顺序是硬约束：必须在第三步刷新完成之后才能清理，不能先清后刷。** 第三步会写入新版本目录，并让旧版本从"被引用"变成"未被引用"——先清理等于按刷新前的旧白名单判断，会把刚要用的版本算成垃圾，同时漏掉真正该删的旧版本。

清理对象分**两类**，判定方式完全不同，不要合并成一条命令处理。

#### (a) `temp_git_*` 临时克隆残留——优先清，收益最大且判定最简单

`cache/` 下会出现形如 `temp_git_<13 位毫秒时间戳>_<6 位随机后缀>` 的顶层目录（例如 `temp_git_1784510740316_ohwupx`），是插件安装/更新过程中的临时 git 克隆，正常流程结束后本应自行删除，实测会大量残留。

实测规模（2026-07-29，一台日常使用的 mac）：`cache/` 总占用 **2.9G**，其中 **13 个** `temp_git_*` 目录合计 **1.8G**——占了将近一半，比历史版本堆积严重得多。

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

实测该差集为 **58 个目录 / 704M**（白名单 48 条、磁盘 106 个三级目录）。

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
| `claude plugin update <plugin>` 找不到批量刷新的写法 | CLI 本身没有 `--all` 之类的参数，设计上一次只处理一个 `<plugin>@<marketplace>` | 只能枚举 `claude plugin list --json` 里 `enabled: true` 的 id 后自己拼循环（见第三步） |
| 同一插件在 `installed_plugins.json` 里出现好几条记录，`version`/`installPath` 都相同 | 同一个插件在不同项目目录分别 `enable` 过，每次 enable 会在对应 `scope`（`project`/`user`）各记一条，但共用同一份缓存目录 | 只需对这个 `<plugin>@<marketplace>` id 跑一次 `claude plugin update`，不用按出现的项目数重复刷 |
| 刷新了缓存，当前会话里 skill/hook 行为却没有变化 | 忘了重启——缓存刷新不会热更新到正在运行的进程里 | 结束当前会话重新打开，或明确提醒用户手动重启后再验证 |
| 第三步的循环只跑了一次就整体失败，报 `Plugin "<第一个插件名>" not found`，可那个插件明明装着 | 用了 `for p in $plugins` 这种依赖单词分割的写法。macOS 上 Claude Code 的 Bash 工具走 zsh，zsh 默认**不对未加引号的变量做单词分割**，25 行的插件清单被当成一个 token 传给 CLI | 改成落地临时文件后 `while IFS= read -r p` 逐行读（见第三步）。这类失败**无副作用**——CLI 在 id 校验阶段就退出，没有写 `installed_plugins.json`、没有刷新任何插件，修好写法直接重跑即可 |
| `cache/` 目录体积远大于所有已启用插件之和（实测 2.9G） | 存在 `temp_git_<毫秒时间戳>_<随机后缀>` 形态的临时克隆残留目录，是安装/更新过程的中间产物没被清掉。实测 13 个占 1.8G，接近总量一半；它们在 `known_marketplaces.json` 与 `installed_plugins.json` 里都是 0 处引用 | `grep -c 'temp_git' ~/.claude/plugins/known_marketplaces.json ~/.claude/plugins/installed_plugins.json` 两处都为 0 即确认孤立，可整批删除（见第五步 (a)） |
| 清理历史版本缓存后，某个项目下的插件失效或被迫重新下载 | 按"每个插件只保留最新版本"删了。同一插件在不同项目目录（`scope: project`）会各自钉不同版本——实测 `sdlc@ai-sdlc` 有 12 条 project 记录横跨 4 个版本（`3.3.0`/`3.3.3`/`3.3.18`/`3.7.3`），"最新"只对当前项目成立 | 必须以 `installed_plugins.json` 里 `.plugins[][].installPath` 的**全集**为白名单做差集（见第五步 (b)）。jq 要展开两层 `.plugins[][]`，`.plugins` 的每个值是数组、每个 scope 一条记录，只取第一条会把在用版本误判成垃圾 |

## 验证清单

- [ ] 判断市场是否真的拉到新代码时用的是 HEAD 对比，**没有**拿 `lastUpdated` 当判据（它变了 / 没变都不能证明任何一个方向）
- [ ] `claude plugin list --json` 筛出的全部 `enabled: true` 插件 id 都刷新过一次（按 id 去重后的数量，不是原始条目数）
- [ ] 第三步用的是 `while IFS= read -r` 逐行读，不是 `for p in $plugins`（zsh 下后者必坏）
- [ ] 每条 `claude plugin update` 的输出都在预期的三种正常结束态之一：`already at the latest version`、`updated from X to Y`、`refreshed from source`
- [ ] 关键插件已走**写后回读**核实：`installed_plugins.json` 的 `installPath`、磁盘上该缓存目录、目录内 `.claude-plugin/plugin.json` 的 `version` 三处一致（只看 CLI 回执不足以证明落盘）
- [ ] 若执行了第五步清理：确认在第三步刷新**之后**做的；`temp_git_*` 零引用已 grep 核实；历史版本走的是 `.plugins[][].installPath` 白名单差集；反向检查（配置引用但磁盘缺失）输出为空；删除清单已出示给用户并获得同意
- [ ] 已明确告知用户：需要重启 Claude Code 会话，新版本插件才会真正生效
