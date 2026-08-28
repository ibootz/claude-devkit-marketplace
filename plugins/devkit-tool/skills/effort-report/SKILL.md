---
name: effort-report
description: 从 Claude Code 会话 transcript（~/.claude/projects 下 jsonl）复现一份「需求全流程耗时与 ROI」报告——九脚本流水线把散在多会话/多 worktree 的动作重放成统一口径的有效工时账（日历折算、subagent 并集计入、阶段由门禁事件切窗），产出交互式 HTML 时间轴（阶段两层构成/步骤证据/未具名分解）与 md 数据底稿，外加三档对比（现状/保守可达/理想上限）与裁剪面分析。当用户说"分析这个需求花了多久""AI 全流程耗时/ROI 报告""这条轨的时间都花在哪了""复现那次耗时分析"时使用。
when_to_use: |
  触发词：全流程耗时 / ROI 分析 / 时间都花在哪 / 有效工时怎么算 / 耗时报告复现 / 阶段耗时拆解。
  判据式触发：需要把一次交付（一个需求从下发改动到验收放行）在多个会话与 worktree 里的全部 AI/Human 动作，折算成可审计的工时账并出报告。
---

# Effort Report — 需求全流程耗时与 ROI 报告流水线

## 是什么

一套已在 D-003（fix-succession-map-dept-headcount，fusion 转换 08-05 14:24 → G4 08-26 18:44）上完整验证过的九脚本流水线：scan → extract_acts → add_bash → calc3 → calc4 → calc5 → build_timeline → gen_timeline（+patch_section）→ gen_md。脚本按「已验证的参考实现」原样入仓（`scripts/pipeline/`），**配置不抽参**——移植到新项目按 `scripts/pipeline/config.example.py` 逐文件改点清单改字面量，不逐文件重构。

产物两件：
- **HTML 交互时间轴**（约 1MB 单文件，无外部依赖）：四条轨、11 个阶段两层构成（具名步骤 + 本阶段其余，两层相加 = 阶段总量）、每阶段未具名动作的类别分解与二级分桶、37 个流程步骤的逐条事件证据、返工、三档对比、裁剪面（EXTRA/ROIS/CUTS）
- **md 数据底稿**（627 行）：同数据的可 diff 文本版，是回归基准的载体

## 口径（先读 references/calibers.md，再跑流水线）

最关键五条（全量见 calibers.md）：
1. **线性窗口归属**：动作落在哪个阶段窗口就归哪个阶段；只有账本明确记录的门禁回退另计返工
2. **subagent 执行时间按活跃段并集计入**所在阶段，不重复计主会话摘要时间
3. **各分项按各自活跃段并集独立计时，相加 > 阶段总量是正常的**——总量一律走并集
4. **守恒校验**：阶段合计 = 主报告总量（允许 ±0.01 舍入差）；不对就停，先找口径错
5. **红线**：G1–G5 门禁动作与本体（specs）回填永不进裁剪清单

## 流程

### 1. 定口径（先于一切脚本）
- scope 起止（如 fusion conversion 时刻 → G4 验收时刻）、会话目录白名单（主会话 + delivery worktree + fusion 侧）、日历规则（工作时段、每日封顶、周末、请假日）、阶段窗口（由 gate decided_at + git commit 时刻切）
- 口径变更必须同步改 lib.py（时间窗/日历）、phases.py（窗口）、align.py（对齐），单改一处必炸守恒

### 2. 抽取（scan → extract_acts → add_bash）
- scan 扫 `~/.claude/projects` 白名单目录 → events.jsonl
- extract_acts 产 acts.json（writes/bash/dispatch/asks/reads）；add_bash 回 raw jsonl 补全被截断的命令全文（截断字段上的归类结论不可用）

### 3. 计算（calc3 → calc4 → calc5）
- calc3：逐日有效工时（工作时段交集、封顶）；calc4：并行占用（subagent 并集）；calc5：主报告 + 三档（现状/保守可达/理想上限）
- **守恒自检点**：calc5 输出的主报告总量 vs 阶段合计，差 > 0.01h 停下查口径

### 4. 阶段归属（build_timeline）
- 输入 acts.json + steps_def.py（96 步锚点：f 文件片段 / a 文本关键词 / b 命令特征）+ phases.py（阶段窗口）
- 匹配语义（终态，勿"优化"）：ALL = domain 步骤先于 fusion 步骤；write/agent/ask/bash 匹配带 side_at(t) 侧别池（domain/fusion）；named = 本阶段 stages 的步骤；rest_none（归不到本阶段步骤）按 classify() 十四类别分解再二次分桶
- **顺序硬约束**：build_timeline 必须先跑，gen_timeline/gen_md 才能读到新 timeline.json

### 5. 生成（gen_timeline → gen_md）
- gen_timeline（内嵌 patch_section 附录模块）写 HTML；gen_md 写底稿 md
- 两者 OUT 都直写目标 docs 路径——**覆盖即生效，跑错版本会静默覆盖正式产物**（见 pitfalls.md 第 3 条）

### 6. 大头桶定性核实
未具名分解里占比大的桶，其桶名是启发式起的——建裁剪/ROI 前先过 `bucket-audit` skill 核实定性（D-003 实证：一个 3.49h 的桶名定性被全量归类推翻，下游裁剪项全部重写）

### 7. 回归门（改了任何流水线脚本后必跑）
- 冻结快照：把当时的 acts.json/.timeline.json 与产物 md 留一份只读基准（本仓附 D-003 基准：`/Users/zhangq/.claude/jobs/recovered/md_fixture.md`，627 行）
- 全链重跑后 diff 产物 md vs 基准：允许差异 = 快照时间行 + 已知残差清单（见 pitfalls.md 第 5 条）；新差异必须归因后才能收

## 移植到新项目

按 `scripts/pipeline/config.example.py` 的逐文件改点清单改（每项给文件、D-003 原值、语义）：会话目录白名单（lib.py）、时间窗（lib.py START/END）、日历（lib.py）、阶段窗口（phases.py 全重写）、步骤锚点（steps_def.py 全重写，锚点必须逐条可指到插件 SKILL/rules 的出处）、分桶关键词（build_timeline BUCKETS）、裁剪清单与折扣（gen_timeline CUTS，折扣须有实证权重）、OUT 路径（gen_timeline/gen_md/scan）。

锚点纪律：每个步骤的 src 字段（如 `skills/verify/SKILL.md:384`）必须真实可指——报告把每个步骤的耗时挂在"流程哪里规定的"上，src 不可指则整行是编的。

## 什么时候不用

- 只想问"某段代码谁改的/什么时候改的"——git log 就够，不配跑流水线
- 会话数据已漂移（相关会话经历多次 compact 重写）——先冻结可用的快照再跑，否则数字无法复现（见 pitfalls.md 第 5 条）
- 需求还在 in flight——跑到当前时刻即可，P12 类在飞阶段显示 0.00h 是预期，不是 bug
