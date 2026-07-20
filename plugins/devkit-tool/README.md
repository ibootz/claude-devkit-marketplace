# DevKit-Tool

**版本**: 6.0.0
**作者**: zhangq
**许可证**: MIT

工具技能套件（原 `devkit-core`），当前聚焦 5 个 Skills，覆盖代码库分析、依赖排查、多模型协作与 Claude Code 自身运维辅助工具。

---

## 插件定位

- 聚焦高复用的分析、排障与协作能力，专门收纳与具体业务无关的通用工具类技能
- 不再内置原 `devkit-dev` 的开发工作流技能，避免与当前市场定位重叠
- 不再内置原 `devkit-git` 的独立 Git 技能，避免与更成熟的外部插件重复
- 不再内置缺陷修复技能，相关能力交由 `devkit-spec` 插件的 `spec-bugfix` 提供
- 新增 Claude Code 自身运维类能力：孤儿进程清理、插件市场与已启用插件缓存刷新

## Skills 分组

### 分析与诊断

- `init-architect`
- `key-module-analysis`
- `deps-investigator`

### 协作与辅助

- `orphan-process-cleaner`
- `marketplace-cache-sync`

## 典型用法

```bash
# 架构初始化
请帮我分析代码库并生成 CLAUDE.md

# 分析关键模块
请帮我梳理认证模块的边界和风险

# 刷新插件市场与已启用插件缓存
帮我拉取一下最新的 marketplace 并刷新插件缓存
```

## 目录结构

```text
plugins/devkit-tool/
├── .claude-plugin/plugin.json
└── skills/
    ├── deps-investigator/
    ├── init-architect/
    ├── key-module-analysis/
    ├── marketplace-cache-sync/
    └── orphan-process-cleaner/
```

## 维护说明

- 技能清单以 `.claude-plugin/plugin.json` 为准
- 每个 skill 的具体流程以对应目录下的 `SKILL.md` 为准
- `dev-feature`、`dev-review`、`dev-test`、`init`、`planner`、`ui-ux-designer`、`get-current-datetime`、`bugfix` 已从当前插件中移除
- 该插件不再声明独立 Git 技能，相关能力建议交由专门插件提供
- 自 5.1.0 起不再内置任何 hook：`guard-full-read.js`（大文件全文读取拦截）已删除；`block-cd.js`（污染 cwd 的独立 `cd` 拦截）已迁至 `working-discipline` 插件
