---
name: key-module-analysis
description: "对关键模块进行深度分析并生成结构化文档。Use when: 用户需要\"分析核心模块\"、\"梳理模块架构\"、\"生成模块文档\"、\"理解模块边界\"、\"评估模块风险\"、\"制定变更影响清单\"、\"输出模块档案\"。适用于重要模块的架构梳理、重构规划、故障预防和 AI 辅助变更安全。"
---

# Key Module Analysis Skill（关键模块分析）

## 你要做什么

为指定的关键模块创建可重复、基于证据的模块档案，产出紧凑的文档包，帮助开发者和 LLM 快速理解模块意图、边界、流程、决策、风险和变更影响。

## 快速开始

1. 明确一个目标模块和一个代码路径范围（目录/包/服务）
2. 运行脚手架脚本生成模块文档包
3. 基于代码证据和提交历史填充各文档
4. 明确标记未知项并附上待解决问题

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/key-module-analysis/scripts/scaffold_module_docs.sh" \
  --module "订单结算" \
  --path "backend/services/settlement" \
  --owner "payments-team" \
  --out "docs/key-modules"
```

## 执行工作流

### 第一阶段：确定范围和目标

- 锁定模块名称和模块路径
- 说明该模块为何关键：收入、安全、可靠性或高频变更
- 定义分析目标：入职培训、重构规划、故障减少或 AI 辅助变更安全

### 第二阶段：收集证据

- 阅读代码入口点、公共接口、测试、配置和最近提交
- 优先使用直接证据而非假设；引用文件路径和符号
- 将未解决的行为记录为 `Unknown` 而非猜测

推荐命令模式：

```bash
rg --files <module-path>
rg "TODO|FIXME|HACK|deprecated" <module-path>
rg "interface|class|type|handler|controller|service|repo" <module-path>
```

### 第三阶段：构建模块档案

按以下顺序填充生成的文件以获得最佳信号密度：

1. `00-module-card.md` - 模块卡片
2. `01-context-and-boundaries.md` - 上下文与边界
3. `02-runtime-flows.md` - 运行时流程
4. `03-dependencies-and-contracts.md` - 依赖与契约
5. `04-quality-attributes.md` - 质量属性
6. `05-risk-and-hotspots.md` - 风险与热点
7. `06-adr-index.md` - ADR 索引
8. `07-operations-runbook.md` - 运维手册
9. `08-change-impact-checklist.md` - 变更影响检查清单

### 第四阶段：正确应用方法论

- 使用 C4 描述结构视图（上下文/容器/组件）
- 使用 arc42 风格章节确保架构关注点完整
- 使用 ADR 跟踪非显而易见的设计决策和备选方案
- 使用 Diataxis 分离解释与操作/参考指南
- 使用 ISO 42010 概念：将利益相关者关注点与选定视图关联

加载 `references/methodology.md` 以决定文档内容和深度。

### 第五阶段：创建关键业务与技术流程图

在 `09-key-process-diagrams.md` 中至少输出以下图种（按模块复杂度裁剪）：

- 业务流程图（BPMN）：描述跨角色、跨系统的业务编排与异常分支
- 技术流程图（UML 活动图或 Mermaid flowchart）：描述模块内控制流、状态与失败处理
- 时序图（UML Sequence 或 Mermaid sequenceDiagram）：描述服务/组件之间消息时序与并发
- 动态架构图（C4 Dynamic）：描述单一用例在静态关系上的“运行时实例化路径”
- 数据/安全流程图（DFD + trust boundary）：描述敏感数据流向、信任边界与威胁建模输入

执行要求：

- 每张图必须绑定一个场景 ID（如 `S1 下单支付成功`），并在文本中给出触发条件和完成判定
- 每张图必须包含主路径 + 至少一条失败/补偿路径
- 图中节点命名与代码术语保持一致（聚合根、服务名、topic、API、表名）
- 优先使用文本化图定义（Mermaid/Structurizr DSL）以便版本管理、审查和 LLM 消费
- 图后追加“证据映射”：列出路径 + 符号（函数/类/接口/配置）+ 契约（API/schema/topic）

### 第六阶段：质量门禁

仅在以下条件满足时接受档案：

- 每个声明映射到代码证据（路径 + 符号或行为）
- 运行时流程包含触发器、主路径和失败路径
- 依赖列表包含入站和出站契约
- 风险有具体信号和可操作的缓解措施
- 变更检查清单覆盖 schema/API/状态/可观测性/回滚
- 关键流程图覆盖业务视角、技术视角和数据/安全视角，并与代码证据一致

## 输出契约

输出目录结构：

```
docs/key-modules/<module-slug>/
├── INDEX.md
├── 00-module-card.md
├── 01-context-and-boundaries.md
├── 02-runtime-flows.md
├── 03-dependencies-and-contracts.md
├── 04-quality-attributes.md
├── 05-risk-and-hotspots.md
├── 06-adr-index.md
├── 07-operations-runbook.md
├── 08-change-impact-checklist.md
└── 09-key-process-diagrams.md
```

## 深度规则

根据模块影响范围和变更频率选择深度：

| 深度 | 适用场景 | 必需文件 |
|---|---|---|
| Level 1 (快速) | 低风险模块 | 模块卡片 + 上下文 + 检查清单 |
| Level 2 (标准) | 常规模块 | 完整档案 + 至少一个运行时流程 + 至少 2 张关键流程图 |
| Level 3 (深度) | 核心模块 | 包含边缘情况流程、失败模式、ADR 链接 + 至少 4 张关键流程图（含 DFD/trust boundary） |

## 资源

### scripts/

- `scripts/scaffold_module_docs.sh` - 从模板创建档案文件夹和 markdown 文件

### references/

- `references/methodology.md` - C4、arc42、ADR、Diataxis 和 ISO 42010 最佳实践映射

### assets/templates/

- `assets/templates/*.md.tpl` - 脚本使用的可复用模块档案模板

## 响应前自检

在最终响应前，请验证：

1. ✅ 是否明确了一个目标模块和一个代码路径？
2. ✅ 每个声明是否有代码证据支撑？
3. ✅ 运行时流程是否包含触发器、主路径和失败路径？
4. ✅ 风险项是否有具体信号和可操作的缓解措施？
5. ✅ 是否已产出 `09-key-process-diagrams.md` 且图与代码证据可追溯？
6. ✅ 输出结构是否符合规范？
