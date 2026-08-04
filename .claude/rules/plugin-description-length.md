---
paths:
  - .claude-plugin/marketplace.json
  - .agents/plugins/marketplace.json
  - plugins/*/.claude-plugin/plugin.json
  - plugins/*/.codex-plugin/plugin.json
---

# 插件 description 长度上限（两处都不截断，写长了直接糊屏）

本仓每个插件的 description 登记在两处，**Claude Code 的 `/plugin` 界面把两处都原样铺开、
不截断也不折叠**。以下是 2.1.220 二进制里的渲染代码，两处都没有 `wrap:"truncate"`、没有
`slice`：

```js
// A) /plugin 主界面「已安装插件」列表 —— 读 plugins/<name>/.claude-plugin/plugin.json
D.installedPlugins.map(se => jsxs(Tb,{children:[se.name,'\n',
  jsx(Text,{dimColor:true, children: se.manifest.description})]}))

// B) marketplace 浏览详情页 —— 读 marketplace.json 的 plugins[].description
PP.entry.description && jsx(Box,{marginTop:1,
  children: jsx(Text,{children: PP.entry.description})})
```

(A) 最容易出事：列表里**每个插件**都铺完整 description，一个插件写 2782 字符就能把整份列表
撑成几十行。真实事故——`working-discipline` 的 plugin.json description 曾达 2782 字符，
`/plugin` 列表无法扫读，2026-07-29 压到 113 字符。marketplace 那份还会出现在 `/plugin`
命令的补全候选里（`{value: pluginId, description, isFinal: true}`），更需要短。

## 硬上限

| 文件 | 上限 | 显示位置 | 写什么 |
|---|---|---|---|
| `marketplace.json` 的 `plugins[].description` | **≤80 字符** | 浏览列表、命令补全候选 | 一行讲清"这插件是干什么的" |
| `plugins/<name>/.claude-plugin/plugin.json` 的 `description` | **≤120 字符** | 已安装插件列表、插件详情页 | 同上 + 关键操作信息（关闭开关的环境变量、挂载点、"零 skill"这类部署特征） |

超限时**不要靠删关键信息压行**，把细节移到 `plugins/<name>/README.md`，description 里留一句
"……见 README"。设计依据、实测数据、二进制符号名、历史事故这类内容**一律不进 description**
——它们属于 README 与源码文件头注释。

## 检查命令

```bash
python3 - <<'EOF'
import json, os
mk = json.load(open('.claude-plugin/marketplace.json'))
for p in mk['plugins']:
    lm = len(p.get('description') or ''); src = p.get('source'); lp = 0
    if isinstance(src, str):
        f = os.path.join(src, '.claude-plugin', 'plugin.json')
        if os.path.exists(f): lp = len(json.load(open(f)).get('description') or '')
    if lm > 80 or lp > 120: print('超限', p['name'], 'mk=', lm, 'pj=', lp)
EOF
```

## 连带约束：改 description 时顺手核版本号

version 登记在**四处**（`plugins/<name>/.claude-plugin/plugin.json` 是真相源 +
`plugins/<name>/.codex-plugin/plugin.json` + 两份市场清单），漏改是本仓反复发生的遗漏。
2026-08-04 起 `.githooks/pre-commit` 会在提交涉及 `plugins/` 或任一份市场清单时**强制**跑
`node scripts/check-versions.js`，不一致直接拦下（需先 `git config core.hooksPath .githooks`）。

**`--fix` 只对齐 version，`description` 不会被它同步**——必须手改。而且 description 的
登记位置比 version 少一处也少不了：两份市场清单 + `.claude-plugin/plugin.json` +
（若有）`.codex-plugin/plugin.json`，**四处的 description 各自独立、没有任何工具在同步它们**。

实测这一路已经漂了：2026-08-04 把 8 个插件的 `.codex-plugin/plugin.json` 版本对齐之后，
它们的 description 仍停在初版——`devkit-tool` 的 codex 侧写着「（5个技能）」而实际已有 6 个、
且完全没提 codegraph。**版本号有机器兜底，description 只有你自己**。改插件功能时，四处
description 要一起看一遍。

## 两份清单的格式差异（不是不一致，别"顺手统一"）

`source` 字段两边形态本就不同，**保持各自格式**：`.claude-plugin` 版用字符串简写
`"./plugins/xxx"`；`.agents` 版（Codex 安装器读）用显式对象
`{"source":"local","path":"./plugins/xxx"}`。顶层字段也不同（前者有 `renames`，后者有
`interface`）。只有 `name` / `version` / `description` 需要两边一致。
