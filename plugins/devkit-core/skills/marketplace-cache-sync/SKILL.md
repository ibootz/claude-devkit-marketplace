---
name: marketplace-cache-sync
description: 拉取 Claude Code 已配置的插件市场(marketplace)最新代码，并刷新已启用插件(enabled plugin)的本地缓存版本。Use when：用户说"更新一下插件市场"、"拉取 marketplace 最新代码"、"刷新插件缓存"、"plugin 装的新版本怎么不生效"、"skill 改了但没同步过来"、"市场 lastUpdated 没变是不是失败了"、"marketplace update 之后要不要重启"。内容基于一次真实全量执行(17 个 marketplace + 16 个 enabled plugin)验证过，覆盖两层模型(marketplace 源 vs 已启用插件缓存)、批量刷新写法，以及非纯 git 市场/lastUpdated 语义等已复现的坑。
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
for p in "plugin-a@marketplace-x" "plugin-b@marketplace-y"; do
  echo "=== $p ==="
  claude plugin update "$p"
done
```

**必须串行执行，不能并发派发**：`claude plugin update` 会读改写共享的单个文件 `~/.claude/plugins/installed_plugins.json`，多个进程同时跑存在写竞态——后写完的会覆盖先写完的那条记录，可能导致某些插件的刷新结果丢失。`claude plugin update` 没有 `--all`/批量参数，一次只能指定一个 `<plugin>@<marketplace>`，只能像上面这样自己拼循环。

### 第四步：告知需要重启才生效

刷新缓存只影响**下次启动**加载的版本；当前运行中的会话仍然使用旧版本插件内容（无论是 hook 逻辑、SKILL.md 文本还是 command 定义）。`claude plugin update` 的输出会明确提示 `Restart to apply changes.`——刷新完不重启等于白刷，必须显式告知用户这一点，不要让用户误以为当前会话已经在用新版本。

## 已验证的坑

| 现象 | 真实原因 | 怎么核实 |
|------|----------|----------|
| `claude plugin marketplace update` 回执 "✔ Successfully updated N marketplace(s)"，但某个市场在 `known_marketplaces.json` 里的 `lastUpdated` 时间戳没变 | **不是更新失败**——该市场本来就已经是最新（上游没有新 commit），`lastUpdated` 的语义是"上次真正拉到新内容的时间"，不是"上次执行检查的时间"。已在两个纯 GitHub 源市场上稳定复现 | `git -C ~/.claude/plugins/marketplaces/<name> rev-parse HEAD` 对比 `git -C 同目录 ls-remote origin <branch>` 的输出，两者一致即说明真的已是最新，不要仅凭时间戳没动就判定失败 |
| 想用 `git -C ~/.claude/plugins/marketplaces/<name> log` 核实某市场是否最新，报错 `fatal: not a git repository` | 不是所有市场都是纯 git clone。例如官方 `claude-plugins-official`：即使 `known_marketplaces.json` 里登记的 `source` 字段写的是 `github`，其本地目录下实际没有 `.git`，只有一个 `.gcs-sha` 文件——它按内容哈希做整体快照同步，不是逐 commit 拉取 | 先 `ls -la ~/.claude/plugins/marketplaces/<name>` 看有没有 `.git` 目录；没有就别拿 git 命令去验真伪，直接看 CLI 回执，或对比 `installed_plugins.json` 里该市场旗下插件的 `gitCommitSha`/`lastUpdated` 字段变化 |
| `claude plugin update <plugin>` 找不到批量刷新的写法 | CLI 本身没有 `--all` 之类的参数，设计上一次只处理一个 `<plugin>@<marketplace>` | 只能枚举 `claude plugin list --json` 里 `enabled: true` 的 id 后自己拼循环（见第三步） |
| 同一插件在 `installed_plugins.json` 里出现好几条记录，`version`/`installPath` 都相同 | 同一个插件在不同项目目录分别 `enable` 过，每次 enable 会在对应 `scope`（`project`/`user`）各记一条，但共用同一份缓存目录 | 只需对这个 `<plugin>@<marketplace>` id 跑一次 `claude plugin update`，不用按出现的项目数重复刷 |
| 刷新了缓存，当前会话里 skill/hook 行为却没有变化 | 忘了重启——缓存刷新不会热更新到正在运行的进程里 | 结束当前会话重新打开，或明确提醒用户手动重启后再验证 |

## 验证清单

- [ ] `known_marketplaces.json` 里各市场的 `lastUpdated` 已逐个核对；不动的用上表方法确认是否真的已最新，而不是直接判定失败
- [ ] `claude plugin list --json` 筛出的全部 `enabled: true` 插件 id 都刷新过一次（按 id 去重后的数量，不是原始条目数）
- [ ] 每条 `claude plugin update` 的输出都在预期的三种正常结束态之一：`already at the latest version`、`updated from X to Y`、`refreshed from source`
- [ ] 已明确告知用户：需要重启 Claude Code 会话，新版本插件才会真正生效
