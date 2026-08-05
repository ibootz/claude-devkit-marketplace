# DevKit-Tool

**版本**: 6.4.2
**作者**: zhangq
**许可证**: MIT

工具技能套件（原 `devkit-core`），当前聚焦 6 个 Skills，覆盖代码库分析、依赖排查、代码知识图谱建图决策、多模型协作与 Claude Code 自身运维辅助工具。

---

## 插件定位

- 聚焦高复用的分析、排障与协作能力，专门收纳与具体业务无关的通用工具类技能
- 不再内置原 `devkit-dev` 的开发工作流技能，避免与当前市场定位重叠
- 不再内置原 `devkit-git` 的独立 Git 技能，避免与更成熟的外部插件重复
- 不再内置缺陷修复技能，相关能力交由 `devkit-spec` 插件的 `spec-bugfix` 提供
- 新增 Claude Code 自身运维类能力：孤儿进程清理、插件市场与已启用插件缓存刷新

## Skills 分组

### 分析与诊断

- `init-architect` — 初始化项目、生成 `CLAUDE.md` 与 `.claude/rules/project/`。6.2.0 起产物分三层：根级 `CLAUDE.md`（全局必知，守 200 行）／`.claude/rules/project/{topic}.md`（跨模块横切规则）／模块级 `CLAUDE.md`（该模块是什么）。**6.7.0 起** `.claude/rules/` 下按来源分三类子目录——`radnove/`（公司内部 radnove 插件市场自带规则）、`devkit/`（通用 devkit 插件市场自带规则）、`project/`（项目自有规则，判据是"内容属于谁"而非"谁写的文件"，本 skill 生成的规则即便是插件代笔也归这里）；顶层 `.claude/rules/*.md` 不再直接放文件，本 skill 只写 `project/` 子目录。

  `.claude/rules/**`（含三类子目录，无深度限制）由 Claude Code 自动加载、与 `CLAUDE.md` 并列，**不要**在 `CLAUDE.md` 里 `@import` 它们或加链接引用（前者会让同一份内容注入两次，后者纯冗余）。拆分的核心收益是 `paths` frontmatter 条件加载——只在改动命中这些路径时才进上下文，且**匹配基准恒为项目根、不随规则文件所在子目录层级变化**，规则文件挪到 `project/` 子目录不需要改写 `paths` 的值。三个必须避开的边界：不写 `paths` 字段等于无条件加载（省不下任何上下文）；`paths` 只写 `**` 会被判定为全通配而**退化成无条件加载**；尾部 `/**` 会被自动剥掉，`src/**` 与 `src` 等价。模式是 gitignore 风格（走 npm `ignore` 包语义，不是 picomatch）。
- `key-module-analysis`
- `deps-investigator`
- `codegraph-index` — codegraph 代码知识图谱的**建图决策**技能：先判某仓该不该建（源文件 ≥ 800 且日常检索跨文件调用关系才建；文档仓一律不建——实测 codegraph 不给 md 产任何节点），再判何时建（禁止挂 `SessionStart` 自动建，实测首次全量 9,810 文件 57.2s、峰值 RSS 4.2 GB）。核心结论：**worktree 图不可共用父仓的图**（分支新增类在 worktree 图查得到、主仓图查不到，用 `projectPath` 指父仓会静默拿到旧分支符号），长命 feature worktree 才各自建、短命 fix worktree 不建。另含 7 个已验证的坑（纯中文查询命中率为 0、watcher 进程叠加、`codegraph daemon` 是交互式菜单不可脚本调用等）与拆除路径。

  **6.4.1 起明确 CLI-only：禁止执行 `codegraph install`，本插件也不会自动接任何 MCP。**四条实测理由——MCP 面 `tools/list` 只有 `codegraph_explore` 一个工具（README 声称"unlisted but functional"的 `codegraph_node` 按名调用**无任何响应、连 error 都没有**，`query`/`callers`/`impact`/`affected`/`files` 在 MCP 侧全拿不到）；explore 单次 25 KB ≈ 6.5k token，而 CLI `query` 几百字节，成本方向是反的；MCP `initialize` 每会话每 subagent 固定下发 4597 字符 ≈ 1.2k token instructions；那段 instructions 原文 `Trust codegraph's results — don't re-verify them with grep` 与本地核实纪律冲突且服务端下发改不掉。已装过的机器用 `codegraph uninstall -t claude -l global -y --keep-cli` 拆（实测 4 处全清、CLI 保留）。

  6.4.2 起配套一个**纯注入 hook** `hooks/codegraph-hint.js`：cwd 归属的仓已建图时注入两行（强化用 codegraph、抑制拿 `Grep`/`Glob` 全仓搜符号与为找代码而整读文件），未建图的仓输出 **0 字节**。6.5.0 起**双挂 `UserPromptSubmit` + `SubagentStart`**——前者只到主会话，子代理由 `Agent`/`Task` 编程派发、收不到它；实证某会话主会话收到 20 次而全项目 23 份 transcript 里 codegraph 实调为 0（真正检索的是子代理）。两路共用同一脚本，输出的 `hookEventName` 从入参回声，写死任一个都会让另一路静默失效。gating 向上找 `.codegraph/` 时读 `.git` 文件的 gitdir 区分边界——`/modules/` 穿过（父仓建图会把 submodule 源码一并索引）、`/worktrees/` 停（未建图 worktree 不得认领父仓那份属于另一分支的图）。`CODEGRAPH_HINT=off` 关闭；`bash hooks/tests/codegraph-hint-gating.sh` 跑 13 条回归。

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
├── hooks/
│   ├── codegraph-hint.js   # 纯注入（双挂 UserPromptSubmit + SubagentStart）：已建图仓才输出两行 codegraph 引导
│   └── tests/codegraph-hint-gating.sh    # gating 回归用例（13 条，判据两侧都覆盖）
└── skills/
    ├── codegraph-index/
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
- **不内置拦截类 hook**：`guard-full-read.js`（大文件全文读取拦截）自 5.1.0 删除；`block-cd.js`（污染 cwd 的独立 `cd` 拦截）已迁至 `working-discipline` 插件。6.4.2 新增的 `hooks/codegraph-hint.js` 是**纯注入类**（只输出 `additionalContext`、不阻止任何操作），按本仓 `.claude/rules/project/hook-restraint.md` 末节「这条规则自己的适用边界」不受克制原则约束
