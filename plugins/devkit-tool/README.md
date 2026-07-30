# DevKit-Tool

**版本**: 6.2.2
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

- `init-architect` — 初始化项目、生成 `CLAUDE.md` 与 `.claude/rules/`。6.2.0 起产物分三层：根级 `CLAUDE.md`（全局必知，守 200 行）／`.claude/rules/{topic}.md`（跨模块横切规则）／模块级 `CLAUDE.md`（该模块是什么）。

  `.claude/rules/**` 由 Claude Code 自动加载、与 `CLAUDE.md` 并列，**不要**在 `CLAUDE.md` 里 `@import` 它们或加链接引用（前者会让同一份内容注入两次，后者纯冗余）。拆分的核心收益是 `paths` frontmatter 条件加载——只在改动命中这些路径时才进上下文。三个必须避开的边界：不写 `paths` 字段等于无条件加载（省不下任何上下文）；`paths` 只写 `**` 会被判定为全通配而**退化成无条件加载**；尾部 `/**` 会被自动剥掉，`src/**` 与 `src` 等价。模式是 gitignore 风格。
- `key-module-analysis`
- `deps-investigator`

### 协作与辅助

- `orphan-process-cleaner`
- `marketplace-cache-sync` — 市场源 + 已启用插件缓存两层同步，含缓存清理。6.2.1 起修正了「让新版本生效」的判据：默认 `/reload-plugins` 即可（实测能热载 skill / agent / hook 脚本与新增的 `PreToolUse` / `PostToolUse` / `UserPromptSubmit` 挂载点），**只有** `SessionStart` / `SessionEnd` / `PreCompact` 这类生命周期挂载点变动才必须重启会话——`/reload-plugins` 不重放生命周期事件，否则会出现「每轮注入已是新版指针、它引用的静态主体却从未投放」的割裂状态。6.2.2 起补上 project/local scope 插件的刷新：常规刷新循环默认只处理 `user` scope，只装在项目目录下（`project`/`local` scope）的插件会静默刷新失败且无任何报错提示；新增按 (id, projectPath) 逐条 `cd` 进目标项目再刷新的写法，并记录了 `--scope project` 靠 cwd 隐式定位、cwd 不匹配时静默假成功的陷阱。

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
