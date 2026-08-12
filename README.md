# Claude DevKit Marketplace

Claude Code / Codex 插件市场，提供精选的开发工具集与生产力插件。

## 概述

本市场包含 **21 个插件**（以两份市场清单为准），覆盖核心开发、规范驱动工作流、技能生态、多模型协作、AI 工作纪律、浏览器自动化、协作方法论、输出风格等场景。下面的编号清单只有 20 节——`clickable-paths` 至今只登记在市场清单与目录树里，没有单独的介绍段落，属于既有遗漏。

原 `devkit-git`、`devkit-dev`、`devkit-issue` 已从市场移除，不再作为独立插件提供。

## 可用插件

### 1. devkit-tool

工具技能集（原 `devkit-core`），覆盖代码库分析、依赖排查、多模型协作与 Claude Code 自身运维辅助工具。

**Skills**:
- `deps-investigator` - 依赖源码读取
- `init-architect` - 架构初始化，生成 CLAUDE.md
- `key-module-analysis` - 关键模块分析
- `codegraph-index` - codegraph 代码知识图谱建图决策与使用
- `orphan-process-cleaner` - 孤儿进程清理
- `marketplace-cache-sync` - 插件市场拉取 + 已启用插件缓存刷新
- `cascade-pull` - 带 submodule 的仓库同步拉取（只处理直接声明的一层，不递归）
- `cascade-push` - 嵌套 submodule 由内向外逐层提交推送（递归全嵌套树）

### 2. devkit-spec

规范驱动开发工具集，支持完整的 Spec 工作流。

**Skills**:
- `spec-analyze` - 需求分析并生成 spec
- `spec-bugfix` - 缺陷修复流程
- `spec-tasks` - 将 spec 拆解为任务清单
- `spec-impl` - 按任务清单实施
- `spec-review` - 审查 spec 与实现一致性

### 3. heal

技能修复工具，在技能执行过程中发现问题时更新 SKILL.md 及相关文件。

- 自动检测正在运行的技能
- 反思出错原因并提出修复方案
- 审批工作流，获得用户批准后应用更改
- 支持可选的 Git 提交

### 4. prompt-engineering

提示词工程专家，优化 LLM 提示词、设计命令/钩子/技能。

- Few-Shot Learning（少样本学习）
- Chain-of-Thought（思维链推理）
- 提示词优化与模板系统
- 系统提示设计
- 基于 Anthropic 官方最佳实践

### 5. content-research-writer

内容研究写作助手，协助研究、写作和内容创作。

- 协作大纲与研究协助
- 钩子改进与分节反馈
- 声音保留与引用管理
- 支持 Web 搜索与内容获取
- 多种写作工作流程（博客、新闻通讯、教程等）

### 6. omp (Oh My Pi)

CLI 工具集成，在 Claude Code/Codex 中调用 omp 实现编码、审查、搜索等任务。

**Skills**:
- `using-omp` - OMP 基础使用
- `omp-search` - 代码搜索
- `omp-review` - 代码审查
- `omp-subagent` - 子代理任务

### 7. find-skills

帮助发现和安装 agent 技能 - 基于 skills.sh 生态系统，使用 npx skills CLI 搜索和安装技能。

- 搜索技能库
- 安装指定技能
- 列出已安装技能
- 基于 vercel-labs/skills 生态

### 8. working-discipline

AI 工作纪律注入 + 拦截：`UserPromptSubmit` 每轮注入主会话、`SubagentStart` 注入子代理、`PreToolUse` 硬拦截缺鉴权或实例超限的 `agent-browser` 启动、派发 `Agent` 的结构字段不合规、串行只读检索过线。零 skill、零命令，适合作为全局基线长期开启。（3.26.0 起「污染 cwd 的独立 `cd`」拆给下面第 19 个插件 `cd-blocker`。）

- 上下文纪律：精确读取、子代理优先、bash 输出限流、macOS 中文路径防漏检（NFC/NFD）
- 子代理协作：在飞≤16 动态上限、嵌套≤2 软约束、team 模式下 teammate 不能派下级、共享骨架文件
- 表达约束：不自造术语（8 类权威来源清单）、关键对象点名、引用自带信息、四要素待确认、行号引用、求真、简体中文
- 思维模式：写 md 前判受众 / 搬迁重命名验实体到位 / 阻塞面先判必经入口，按需触发（3.22.0 删掉了原先六条无事故支撑的通用思维法）
- Agent 工具派发：subagent_type × model 三档路由表（sonnet/opus/fable，**无 haiku 档**）、显式 model 指定、`Explore`/`Plan` 按 `agent_type` 跳过派发规范
- 外部写操作授权：dws 钉钉 CLI 默认只读，写操作须逐批出示清单获用户当次许可

### 9. discover-unknowns（发现你的未知）

与 Claude 协作挖掘未知的方法论：把提示词/上下文当"地图"、真实代码库/约束当"疆域"，两者差距即"未知"，动手前暴露未知、合并前确认理解。源自 Anthropic 官方博客 [*A field guide to Claude Fable 5: Finding your unknowns*](https://claude.com/blog/a-field-guide-to-claude-fable-finding-your-unknowns)（Thariq Shihipar）。

**组成**（3 个 Skill + 1 个 Hook，按"探索/收敛/合并"三个决策时刻拆分）：
- `discover-unknowns` - 统领：心智模型 + 路由，内嵌盲点扫描与参考两个手法
- `/brainstorm` - 头脑风暴与访谈：发散（多方向假数据原型）+ 收敛（一次一问，优先会改架构的问题）※
- `/quiz` - 测验：报告 + 必须通过的测验，通过才 merge
- `unknowns-radar` hook - UserPromptSubmit 每轮注入 4 条路标级提醒（`DISCOVER_UNKNOWNS_RADAR=off` 可关闭）

> ※ `brainstorm` 在本地已安装 superpowers 插件时优先委派 `superpowers:brainstorming`，未安装时用内置指令。实施规划与执行不属于本插件，交给 devkit-spec。Claude Code 与 Codex 两侧能力一致。

### 10. portable-shell（跨平台 shell lint）

强制 AI 生成的 shell 脚本同时兼容 Linux 与 macOS。一个 `PostToolUse` hook（matcher `Write|Edit|MultiEdit`），零 skill、零命令。

- 触发时机：当 Write/Edit/MultiEdit 写出 shell 脚本（`.sh/.bash/.zsh/.ksh` 或含 shell shebang）时自动扫描
- 检测：GNU(Linux) 与 BSD(macOS) 之间 13 类不可移植写法——`sed -i` / `readlink -f` / `date -d` / `find -printf` / `grep -P` / `stat -c` / `declare -A` / `mapfile` / `${var^^}` / `mktemp` 无模板 / `realpath` / `echo -e` / `xargs -r`
- 机理：命中即通过 stderr + `exit 2` 把「违规点 + 可移植改法」回灌给 Claude 促其修正（文件已写入，不回滚）
- 关闭：`PORTABLE_SHELL_LINT=off`
- Hook 为 Claude Code 专有机制，Codex 侧不生效

### 11. agent-browser（浏览器自动化最佳实践）

基于 [Vercel agent-browser](https://github.com/vercel-labs/agent-browser)（headless 浏览器自动化 CLI，Rust + CDP 直连 Chrome-for-Testing）的使用指令。**默认 headless 运行**，用四道机制替代"看到浏览器窗口"的监督。1 个 Skill（`agent-browser`），零 hook——硬护栏由 `working-discipline` 的 `bash-guard` 承担（避免两插件抢同一道 Bash 闸）。

- **鉴权前置**：首次 open 目标站点前必须先向用户索取账密/token/cookie 并注入（`--headers` / `--profile` / `--state` / `auth save`）；headless 下人类无法中途登录授权
- **实例上限 4**：全局最多 4 个并发实例（agent-browser 无内置并发上限，guard 查 `session list` 强制）
- **登录态复用**：持久化 `--profile`，跨会话不重登；推荐独立 AI Testing profile 防抢 SingletonLock
- **snapshot + 标注截图**：headless 下靠 `snapshot -i`（拿 `@eN` refs）+ `screenshot --annotate` 回看每步，不靠肉眼盯窗口
- **安全边界**：headless 必带 `--allowed-domains`（限域 + 禁 WebRTC）、`--content-boundaries`（防 prompt 注入）、`--max-output`（防上下文洪泛）

### 12. task-keeper（常驻 keeper 托管任务队列）

主会话只做「分类分派 + 需要人拍板时集中问一次」，debug 队列与杂务队列由常驻 keeper 子代理在独立上下文跑全流程。4 个 Skill（`tk-debug` / `tk-chore` / `tk-decisions` / `tk-worktree`）+ 2 个 Agent（debug-keeper / chore-keeper）+ 6 个 hook。

- **产物统一 `.keeper/`**：整树 gitignore，keeper 冷启动自动写入项目 `.gitignore` 并回读验证，工作区永远干净
- **自动归档**：done ≥10 条或最早 done 超 14 天即归档到 `archive/auto-<日期>/`，编号不回收
- **决策打包 HITL**：subagent 拿不到 AskUserQuestion，keeper 写 `.keeper/decisions/` 信箱、主会话攒批一次问完
- **外部工单适配器**：三层发现（项目配置 → skill 探测 → 如实报未回写），公司系统能力接线不进插件本体
- 源自 radnove-core（云学堂内部插件）debug-triage 体系的通用化搬迁，与 radnove-core ≤4.5.1 不可同装，详见插件 README

### 13. plain-talk-output-style（说人话输出风格）

可切换的输出风格插件：一个 SessionStart 注入 hook，要求 AI 一语中的、几句话讲明白、能表格就表格、不专业化/不掉书袋/不自造词（新词一律取自权威来源）。零 skill、零命令。

- 与 working-discipline（≥3.10.0）分工：纪律条款（拍板四要素 / 求真 / 简体中文）留在 working-discipline，行文风格归本插件
- 第 10 条承接拍板材料：四要素（起源 / 差距 / 影响范围 / 带行号的现场证据）在本风格下用完整段落承载，详尽优先于简短
- 切换方式：`/plugin` 里启停本插件即可换风格（原生 output style 机制已废弃，官方 explanatory 风格同为插件实现）

### 14. adhd-output-style（ADHD 友好输出风格）

复刻自 [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)（MIT）的可切换风格插件：首行给可执行动作、多步骤编号、每轮重述进度、给具体时间估算、错误用陈述句。规则原文逐字保留在 `style/upstream-rules.md`。

- 与上游差异一：拉平成纯 SessionStart 注入，不保留「skill 手动触发 + `~/.claude/.i-have-adhd-always` 标记文件」双通道，开关只有 `/plugin` 一处
- 与上游差异二：追加 `style/project-overrides.md`，解决上游 Rule 9（列表封顶 5 条）与 working-discipline 拍板四要素的冲突——四要素约束的是信息不是形状，本风格用「推荐项在前 + 选项排序 + 每项一行代价」承载
- 注入约 8500 字符，低于 hook 输出上限（10000）

### 15. wenyan-output-style（文言极简输出风格）

取自 caveman 插件 `wenyan-ultra` 档位的可切换风格插件：以文言语法压缩对话回复，**字形一律简体**；代码、命令、报错、行号原样不动；安全告警与不可逆操作确认逐段退回白话。

- 与上游差异一：繁体改简体——上游例句 `新參照則重繪` 全繁，与 working-discipline 3.5「禁止繁体中文」正面冲突，本插件保留文言语法与虚词、字形逐句改简
- 与上游差异二：上游 `wenyan-ultra` 只有 1 行档位定义 + 2 个例句，这里补齐成 8 条压缩法 + 4 条禁忌（含**禁伪古**，防「回调」写成「反召之术」）+ 产出物边界（commit message、md 文档、子代理 prompt 一律白话）
- 唯一结构差异：**两层注入**——SessionStart 注规则全文（2912 字符），UserPromptSubmit 每轮注 102 字符短锚。文言与模型默认语体正面对抗，只放 SessionStart 会在长对话里漂回白话

### 16. insight-addon（教学洞察附加件）

**不是风格，是附加件**：只加一条「何时给 ★ Insight 框」的规则，不规定句子长短和段落形态，因此可与 plain-talk / adhd 等任意风格插件**同时开启**。

- 与官方 explanatory-output-style 的区别：后者是一整套风格（含「可超出通常长度限制」的授权），跟简短类风格互斥；本插件把「给洞察」单独摘出来
- 触发条件比官方更严：要求本轮真做了非平凡技术判断，且门道是**本代码库特有**的。官方原文写的是 `always provide`，在问答轮次会塞出无意义的洞察框

### 17. session-auto-title（会话标题跟随话题）

补 Claude Code 内建自动命名的缺口：内建的 `ai-title` **只在第一条真人 prompt 时生成一次**，之后有两道短路挡着（已有标题就跳过 + resume 进程的闸门初值为 true），话题漂移后永不更新，且没有任何 settings key 能打开重算。本插件用 `UserPromptSubmit` hook 接管，第 2 轮起后台生成、之后每 10 轮重算。

- **异步不卡顿**：hook 只做回填/计数/决定三件不联网的事，生成在 detached 子进程里调 Haiku 4.5，标题慢一轮显示
- **防递归两道**：子进程带 `CLAUDE_AUTO_TITLE_CHILD` 环境变量 + 带时间戳的锁文件（孤儿锁按 mtime 自动失效）
- **显示位置与 `/rename` 完全一致**：输入框顶部边框徽章、终端标签页标题、`/status` 面板、`/resume` 列表
- 三个约束：会永久接管标题（内建从此不工作）、必须挂 `UserPromptSubmit`（挂 `SessionStart` 只改内存不落盘）、agent-team 模式下不生效
- 成本约 1e-4 美元/次，50 轮会话约 5-6 次

### 18. worktree-flow（主分支保护）

`main` / `master` 上禁止直接改代码：这两个分支上的 `Write` / `Edit` / `MultiEdit` /
`NotebookEdit` 与 `git commit` 被 `PreToolUse` **硬拦**。改动一律走「`EnterWorktree` 开临时
分支 → 在里面改并提交 → `git merge --no-ff` 合回 → `worktree remove` + `branch -d` 清理」，
**临时分支不 push remote**。

- **为什么是 deny 不是 ask**：本机 `defaultMode` 为 `bypassPermissions`，`ask` 档实测全部
  失效，可用强度只剩「注入提醒」与「硬拒」两档。故配 `WORKTREE_GUARD=off` 逃生阀
- **Bash 侧只认 `git commit` 一种形态**：`sed -i` / 重定向 / heredoc 写文件算不算写操作要
  猜语义，仓内 hook 克制原则明令这类判据不得做成 deny，故有意收窄；漏报面在插件 README 里
  逐条列明，靠注入的软约束兜
- **豁免**：非 git 目录、detached HEAD、`.claude/` `.keeper/` `.git/` 下的文件、仓正处于
  merge/rebase/cherry-pick 进行中（解决冲突按设计就在主分支上做）
- 26 条回归用例两侧都覆盖：`node plugins/worktree-flow/tests/main-branch-guard.test.js`

### 19. cd-blocker（独立 cd 拦截）

顶层片段以裸 `cd` 开头、目标不是 no-op 时 `PreToolUse` **硬拦**，finding 里回灌可照抄的两个
改法（`(cd /abs/path && cmd)` 子 shell、`git -C <path> <cmd>`）。Bash 工具的 cwd 在多次调用
之间持久保留，中途一次 `cd /tmp` 会让后续所有相对路径操作失准。

- **为什么独立成插件**：1.0.0 从 `working-discipline` 3.25.0 拆出。这条约束会与写侧约束顶死
  ——从 worktree 会话改主仓常驻产物时，写侧要求先 `cd` 到主仓，而它给的两种改法在定义上都
  不改变会话 cwd。合并在一个 hook 里时想关掉 cd 就得连 `agent-browser` 四护栏一起关；拆出来
  之后按项目停用即可。代价是 `Bash` 变成两道闸，两类违规不再一次报清
- **放行**：子 shell、命令替换、字符串内的 `cd`、heredoc 正文、`&` 后台化片段、no-op cd
  （含符号链接等价与 APFS 大小写等价）
- **判据是文本形态匹配，不是"cwd 是否被污染"这个语义**：只拦得住裸 `cd` 开头一族，`pushd` /
  `source` / `eval 'cd'` 等 19 类真污染写法实测放行，按用户拍板不补，清单在插件 README
- 逃生阀 `CD_GUARD=off`（单次）；35 条回归用例两侧都覆盖：
  `node plugins/cd-blocker/tests/cd-guard.test.js`

### 20. readable-citations（自足引用）

把「见 X 文档 §5.2」这类引用改造成读者不点也读得懂的形态：编号后带**标题原文**（编号会漂、
标题可搜）、括注 **20 字提要**（当场判断值不值得点）、**写明引用关系**（前置条件 / 反例 /
详细版 / 相反做法）、被引结论只有一句时**直接内联**。纯注入，不拦截任何调用。

- **链接按落点分两轨**：对话正文用 `file:///绝对路径#行号`（iTerm2 cmd+click 直达编辑器）；
  落盘 md 用相对路径 + 标题锚点（文档 commit 后在别人机器与 GitLab 网页上仍可跳，绝对路径
  在那里是死链且不报错）
- **双挂 `UserPromptSubmit` + `SubagentStart`**：落盘文档大量由子代理写，而
  `UserPromptSubmit` 只触达主会话，只挂它会漏掉产出文档的主力且毫无报错
- **与 `clickable-paths` 互补不重叠**：那个管「提到文件时的路径」且明文排除落盘 md，
  这个管「引用 md 文档的章节」
- 逃生阀 `READABLE_CITATIONS=off`；7 条回归用例：
  `node plugins/readable-citations/hooks/tests/readable-citations.test.js`

## 安装

### Claude Code

#### 添加此市场

```bash
/plugin marketplace add ibootz/claude-devkit-marketplace
```

#### 安装插件

添加市场后，可以安装市场中的任意插件：

```bash
# 工具技能集
/plugin install devkit-tool@claude-devkit-marketplace

# 规范驱动开发
/plugin install devkit-spec@claude-devkit-marketplace

# 技能自修复
/plugin install heal@claude-devkit-marketplace

# 提示词工程
/plugin install prompt-engineering@claude-devkit-marketplace

# 内容研究写作
/plugin install content-research-writer@claude-devkit-marketplace

# OMP 工具集成
/plugin install omp@claude-devkit-marketplace

# 技能发现与安装
/plugin install find-skills@claude-devkit-marketplace

# AI 工作纪律（推荐全局开启）
/plugin install working-discipline@claude-devkit-marketplace

# 发现你的未知（协作方法论）
/plugin install discover-unknowns@claude-devkit-marketplace

# 跨平台 shell lint（生成脚本兼容 Linux 与 macOS）
/plugin install portable-shell@claude-devkit-marketplace

# 常驻 keeper 托管 debug/杂务队列
/plugin install task-keeper@claude-devkit-marketplace

# 说人话输出风格（可切换）
/plugin install plain-talk-output-style@claude-devkit-marketplace

# ADHD 友好输出风格（可切换，三个风格插件只开一个）
/plugin install adhd-output-style@claude-devkit-marketplace

# 文言极简输出风格（可切换，三个风格插件只开一个）
/plugin install wenyan-output-style@claude-devkit-marketplace

# 教学洞察附加件（可与任意风格叠加）
/plugin install insight-addon@claude-devkit-marketplace

# 会话标题自动跟随话题
/plugin install session-auto-title@claude-devkit-marketplace

# 主分支保护（改动一律走 worktree 临时分支）
/plugin install worktree-flow@claude-devkit-marketplace
```

### Codex CLI

#### 添加此市场

```bash
codex plugin marketplace add ibootz/claude-devkit-marketplace
```

#### 通过插件目录安装

在 Codex CLI 中打开插件目录，浏览并安装：

```
codex                          # 启动 Codex CLI
/plugins                       # 打开插件目录
```

在插件目录中：
1. 切换到 "claude-devkit-marketplace" 市场标签
2. 浏览或搜索插件
3. 选择插件并点击安装

#### 通过脚本安装（推荐 — 含 hooks/agents 自动注入）

Codex CLI 通过插件目录安装时，skills 能正常加载，但 hooks 和 agents 不会自动注入到活跃配置。
本市场提供安装脚本解决这个问题，同时安装 skills、hooks 和 agents 到 Codex 的目标路径。

**前提条件**：Node.js >= 14

```bash
# 进入市场目录
cd path/to/claude-devkit-marketplace

# 安装所有插件到当前项目（项目级）
node scripts/install-codex.js --all

# 安装所有插件到用户目录（用户级，全局生效）
node scripts/install-codex.js --all --scope=user

# 交互式选择要安装的插件
node scripts/install-codex.js

# 只安装指定插件
node scripts/install-codex.js --plugins=devkit-tool,omp

# 预览模式（不实际修改文件）
node scripts/install-codex.js --all --dry-run
```

**安装范围**：
- 项目级（默认）：写入当前项目目录的 `.codex/`、`.agents/skills/`
- 用户级（`--scope=user`）：写入用户主目录的 `~/.codex/`、`~/.agents/skills/`

**安装内容**：
- **Skills**：所有 9 个插件的技能目录
- **Hooks**：omp 的 SessionStart/UserPromptSubmit 钩子、working-discipline 与 discover-unknowns 的 UserPromptSubmit 注入钩子（portable-shell 的 PostToolUse lint 钩子为 Claude Code 专有，Codex 侧不生效；devkit-tool 自 5.1.0 起不再内置任何 hook）
- **Agents**：omp 的 3 个子代理（omp-explore、omp-plan、omp-task）

#### 卸载

```bash
# 卸载所有已安装的插件
node scripts/uninstall-codex.js --all

# 卸载指定插件
node scripts/uninstall-codex.js --plugins=omp

# 预览卸载内容
node scripts/uninstall-codex.js --all --dry-run
```

### 版本一致性检查

同一个插件的版本号登记在**四处**，改了插件却漏改其中某处是本仓库反复发生的遗漏：`plugins/<dir>/.claude-plugin/plugin.json`（真相源）、`plugins/<dir>/.codex-plugin/plugin.json`（Codex 侧插件声明，只有发布到 Codex 的插件有）、`.claude-plugin/marketplace.json`（Claude Code 市场清单）、`.agents/plugins/marketplace.json`（Codex 市场清单）。真实案例：`working-discipline` 连续两次 bump（1.8.0 / 1.9.0）都只改了 `plugin.json`，两份市场清单一直卡在 1.7.1；`omp` 升到 2.3.0 后 Codex 清单仍是 2.2.0。后果是用户按市场清单看到的版本号与描述都是过期的。

**第 2 路（`.codex-plugin/plugin.json`）是 2026-08-04 才补进检查范围的**，补之前脚本对它没有任何分支。审计结果：22 个插件里 8 个在这一路上漂移，且每个插件的 `.codex-plugin/plugin.json` 都**只有创建那一次提交**——`devkit-tool` 的 `.claude-plugin` 侧已迭代五次以上到 6.5.0，`.codex-plugin` 侧原地停在 6.0.0。这条通道上从来没有会响的警报，所以漂移是必然而非疏忽。**防护的覆盖面小于问题面时，它给出的「全部通过」是假的。**

```bash
# 检查（有问题 exit 1）
node scripts/check-versions.js

# 把四处 version 对齐 plugin.json（真相源）
node scripts/check-versions.js --fix

# 只输出问题行，通过时不打表（pre-commit hook 用的就是这个）
node scripts/check-versions.js --quiet
```

**已挂 pre-commit 强制执行**（`.githooks/pre-commit`）：提交涉及 `plugins/` 或任一份市场清单时自动跑一次校验，不一致就拦下并给出修复命令。靠 `core.hooksPath` 生效，而 `git config` 不随仓库同步，**clone 之后要各自设一次**：

```bash
git config core.hooksPath .githooks
```

确有正当理由要带着不一致提交（例如拆成两次提交）：`git commit --no-verify`。改 README、改 `.claude/rules/`、改 `scripts/` 自身不触发这道校验（判据是暂存文件的路径前缀）。

**为什么必须挂成 hook**：这个脚本和上面这段说明早就存在，下方「添加新插件」第 5 步也写着「跑一下」，但那 8 处漂移证明靠文档提醒的实际执行率是零。防护要生效，必须挂在会响的时机点上。

检查项包括版本四方不一致、市场清单漏登记、清单里有条目但 `plugins/` 下无对应目录（幽灵条目）。远程源插件（`source` 为 `{"source":"github",...}`）自动豁免——它们没有本地 `plugin.json`，且 `install-codex.js` 只从本地 `plugins/<name>/` 目录安装，所以不登记到 Codex 清单是有意设计而非遗漏。本市场目前没有远程源插件（`mattpocock-skills` 已于 2026-08-01 移除），这条豁免逻辑保留待用。

`--fix` **只对齐 `version` 字段，不动 `description`**：描述该写什么需要人工判断，机器对齐只会把陈旧描述固化下来，修完仍需自行确认市场清单里的描述是否同步。

## 关键 Skills 快速参考

- `/init-architect` - 分析代码库并生成 `CLAUDE.md`
- `/key-module-analysis` - 梳理关键模块边界、依赖与风险
- `/spec-analyze` - 需求分析并生成 `spec.md`
- `/spec-tasks` - 将 `spec.md` 拆解为任务清单
- `/spec-impl` - 按任务清单实施改动
- `/spec-review` - 审查规范或实现一致性
- `/diagnose` - 系统化诊断问题
- `/tdd` - 测试驱动开发

详细参数与流程见各插件目录下的 `SKILL.md`。

## 市场结构

```
claude-devkit-marketplace/
├── .claude-plugin/
│   └── marketplace.json       # 市场配置文件
├── .agents/plugins/
│   └── marketplace.json       # Codex 市场配置文件（install-codex.js 读这一份）
├── plugins/
│   ├── devkit-tool/
│   ├── devkit-spec/
│   ├── heal/
│   ├── prompt-engineering/
│   ├── content-research-writer/
│   ├── omp/
│   ├── find-skills/
│   ├── working-discipline/
│   ├── discover-unknowns/
│   ├── portable-shell/
│   ├── agent-browser/
│   ├── task-keeper/
│   ├── plain-talk-output-style/
│   ├── adhd-output-style/
│   ├── wenyan-output-style/
│   ├── insight-addon/
│   ├── session-auto-title/
│   ├── clickable-paths/
│   ├── worktree-flow/
│   ├── cd-blocker/
│   └── readable-citations/
├── .githooks/
│   └── pre-commit             # 提交前强制跑版本四方校验（需 git config core.hooksPath .githooks）
├── scripts/
│   ├── install-codex.js       # 安装插件到 Codex CLI
│   ├── uninstall-codex.js     # 从 Codex CLI 卸载插件
│   └── check-versions.js      # 版本四方一致性检查
├── README.md
└── AGENTS.md
```

## 开发

### 添加新插件

1. 在 `plugins/` 目录下创建新的插件目录
2. 按照插件规范创建必要的配置文件
   - 对于普通插件：`.claude-plugin/plugin.json`、`skills/`、`commands/` 等
   - 对于 MCP 插件：`.mcp.json`（或 `.claude-plugin/plugin.json` + `.mcp.json`）
3. 在 `.claude-plugin/marketplace.json` 中添加插件条目（Claude Code 市场清单）
4. **同时**在 `.agents/plugins/marketplace.json` 中添加对应条目（Codex 市场清单，`scripts/install-codex.js` 读的是这一份）——只有远程源插件（`source` 为 `{"source":"github",...}`）可以不登记，因为 `install-codex.js` 只从本地 `plugins/<name>/` 目录安装
5. 若该插件也发布到 Codex，建 `plugins/<名>/.codex-plugin/plugin.json`，**版本号与 `.claude-plugin` 侧保持一致**
6. 跑 `node scripts/check-versions.js` 确认四处版本登记一致（漏改是本仓库反复出现的遗漏，见下方「版本一致性检查」）。设过 `git config core.hooksPath .githooks` 的话，提交时会自动跑这一步并在不一致时拦下

### 本地测试

```bash
# 测试 devkit-tool
claude --plugin-dir ./plugins/devkit-tool

# 测试其他插件
claude --plugin-dir ./plugins/<plugin-name>
```

## 要求

- Claude Code CLI
- Git（建议安装，用于仓库协作、差异审查与可选的 worktree 隔离修复）

## 许可证

MIT

## 作者

zhangq
