# DevKit-Core

**版本**: 4.0.0
**作者**: zhangq
**许可证**: MIT

核心开发工具套件，当前聚焦 7 个 Skills，覆盖代码库分析、依赖排查、缺陷修复、多模型协作与辅助工具。

---

## 插件定位

- 聚焦高复用的分析、排障与协作能力
- 吸收原 `devkit-issue` 的缺陷处理能力，并收敛为统一的 `bugfix`
- 保留原 `devkit-core` 的基础能力与多模型协作能力
- 不再内置原 `devkit-dev` 的开发工作流技能，避免与当前市场定位重叠
- 不再内置原 `devkit-git` 的独立 Git 技能，避免与更成熟的外部插件重复

## Skills 分组

### 分析与诊断

- `init-architect`
- `key-module-analysis`
- `deps-investigator`
- `bugfix`

### 协作与辅助

- `orphan-process-cleaner`
- `using-codex`
- `using-gemini`

## 典型用法

```bash
# 架构初始化
请帮我分析代码库并生成 CLAUDE.md

# 统一缺陷修复
/bugfix #123 用户反馈登录失败

# 分析关键模块
请帮我梳理认证模块的边界和风险
```

## 目录结构

```text
plugins/devkit-core/
├── .claude-plugin/plugin.json
└── skills/
    ├── bugfix/
    ├── deps-investigator/
    ├── init-architect/
    ├── key-module-analysis/
    ├── orphan-process-cleaner/
    ├── using-codex/
    └── using-gemini/
```

## 维护说明

- 技能清单以 `.claude-plugin/plugin.json` 为准
- 每个 skill 的具体流程以对应目录下的 `SKILL.md` 为准
- `bugfix` 已替代原 `issue-debug` 与 `issue-fix`
- `dev-feature`、`dev-review`、`dev-test`、`init`、`planner`、`ui-ux-designer`、`get-current-datetime` 已从当前插件中移除
- 该插件不再声明独立 Git 技能，相关能力建议交由专门插件提供
- 自 5.1.0 起不再内置任何 hook：`guard-full-read.js`（大文件全文读取拦截）已删除；`block-cd.js`（污染 cwd 的独立 `cd` 拦截）已迁至 `working-discipline` 插件
