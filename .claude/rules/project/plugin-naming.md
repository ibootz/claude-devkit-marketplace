# 插件命名：一律 `devkit-` 前缀

本仓每个插件的名字都是 `devkit-<kebab-case 名>`，如 `devkit-tool`、`devkit-spec`。名字登记在
五处，五处必须逐字一致：

1. 目录名 `plugins/<name>/`
2. `plugins/<name>/.claude-plugin/plugin.json` 的 `name`
3. `plugins/<name>/.codex-plugin/plugin.json` 的 `name`（有这个文件时）
4. `.claude-plugin/marketplace.json` 的 `plugins[].name`
5. `.agents/plugins/marketplace.json` 的 `plugins[].name`

机械兜底：`scripts/check-versions.js` 校验前缀、五处同名、两份清单的 source 路径是否指向
`./plugins/<name>`；`.githooks/pre-commit` 在暂存了 `plugins/` 或市场清单时自动跑，不过即拦。
命名问题 `--fix` 不修，按下面「改名」一节人工处理。

前缀只加一层：`devkit-` 后面接插件本身的名字，不写成 `devkit-devkit-xxx`，也不换成
`dk-` 等缩写。

## 新建插件

起名时直接带前缀。`plugin-dev:create-plugin` 等外部技能给出的示例名不带前缀，照本规则改。

## 改名（含把不合规的旧名纠正过来）

插件名同时是 skill 命名空间（`<plugin>:<skill>`）与缓存路径段
（`~/.claude/plugins/cache/claude-devkit-marketplace/<plugin>/<version>/`），改名不是只改上面五处：

- 在 `.claude-plugin/marketplace.json` 的 `renames` 里追加 `"旧名": "新名"`。这张表只追加
  不删除：Claude Code 加载插件找不到旧名时按它跳转，并把用户 settings 里的 `enabledPlugins`
  迁到新名；删掉条目，老用户的插件就静默停用。删除插件时同样追加一条，值写 `null`
  （`"旧名": null`），表示该插件已移除（schema 原文：`old plugin name → current name (or null
  when removed)`），同样只追加不删除。
- 全仓替换 `旧名:<skill>` 形态的命名空间引用、拼缓存路径的字符串、按插件名做判断的 hook 代码。
- 升该插件的 major 版本号（命名空间变了，引用它的外部文字全部失效，是破坏性变更）。
- 跑 `node scripts/check-versions.js` 确认四处版本一致。

### 改名时保留不动的标识

下面这些长得像插件名、实际是独立的契约，改插件名时**原样保留**（2026-10-13 用户拍板）。改了要
跨仓同步、迁移用户侧已有文件或 shell 配置，收益为零：

- 项目级配置文件名，如 `.claude/task-keeper.local.md`——radnove 仓的 `keeper-local-config.sh`
  写死了这个文件名，已有项目里也存着这个文件。
- hook 内部的来源标记，如 worktree-flow 的 `APPROVAL_SOURCE = 'worktree-flow'`。
- 用户在 shell 里设置的环境变量开关，如 `TOKEN_SAVER`、`CLICKABLE_PATHS`、`OMP_PROTOCOL_ENABLED`。
- 脚本与测试的文件名，如 `hooks/working-discipline.js`、`hooks/readable-citations.js`——它们登记在
  hooks.json / plugin.json 的 command 里，改文件名是另一项改动。
- 写进用户仓或被字节比对的输出串：guard 输出的 `check=worktree-flow`（SKILL.md 的触发短语绑定它）、
  task-keeper 写进 `index.md` frontmatter 的 `generated_by="task-keeper hook"`、task-keeper 维护的
  `.gitignore` 块注释（逐字写死，改一个字会让所有已有仓出现假 diff 或冲突）。
- `.codex-plugin/plugin.json` 的 `displayName`：展示标签，不是插件 id。

批量替换旧名时只替换四种形态：`旧名:<skill>`、`plugins/旧名`、`旧名@claude-devkit-marketplace`、
缓存路径里的 `/旧名/`。裸词替换会误伤同名 CLI、子代理名与上面这些标识（`omp`、`agent-browser`、
`heal` 最容易出事）。
