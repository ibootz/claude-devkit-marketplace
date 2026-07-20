# 关键模块档案方法论映射

## 为什么选择这个组合

采用分层方法，使输出同时满足：

- 架构完整性
- 工程工作的可操作性
- LLM 下游辅助的可读性

组合以下框架：

1. **C4 模型**：系统上下文、容器和组件的结构视图
2. **arc42**：章节纪律，避免遗漏关注点
3. **ADR**：明确的决策、备选方案和后果
4. **Diataxis**：分离解释与操作/参考
5. **ISO/IEC/IEEE 42010**：关注点驱动的视图选择

## 实践映射到输出文件

| 文件 | 方法论映射 | 核心内容 |
|---|---|---|
| `00-module-card.md` | arc42 简介 | 模块身份和关键性概述 |
| `01-context-and-boundaries.md` | C4 上下文/组件 + ISO 42010 | 边界、利益相关者、上下文 |
| `02-runtime-flows.md` | arc42 运行时视图 | 正常和失败条件下的行为 |
| `03-dependencies-and-contracts.md` | arc42 构建视图 | 入站/出站契约和耦合 |
| `04-quality-attributes.md` | arc42 质量需求 | 性能/可靠性/安全/可运维权衡 |
| `05-risk-and-hotspots.md` | ISO 42010 关注点 | 缺陷高发区和脆弱性指标 |
| `06-adr-index.md` | ADR | 设计决策索引和决策债务 |
| `07-operations-runbook.md` | Diataxis 操作指南 | 面向事故的操作流程 |
| `08-change-impact-checklist.md` | arc42 变更视图 | 实施前的安全变更门禁 |
| `09-key-process-diagrams.md` | BPMN/UML/C4 Dynamic/DFD | 跨业务-技术-数据安全的关键流程图集 |

## 关键流程图方法论与选型

### 图种与用途矩阵

| 图种 | 推荐方法 | 主要回答的问题 | 输出粒度 |
|---|---|---|---|
| 业务流程图 | BPMN 2.0 | 业务角色如何协作？网关分支与补偿如何发生？ | 跨团队/跨系统 |
| 技术流程图 | UML Activity 或 Mermaid Flowchart | 模块内部控制流、状态流转和失败处理是什么？ | 模块/子系统 |
| 交互时序图 | UML Sequence 或 Mermaid sequenceDiagram | 谁在何时调用谁？超时、重试、并发如何体现？ | 组件/服务 |
| 动态架构图 | C4 Dynamic | 单一用例在运行时如何经过容器/组件？ | 用例级 |
| 数据与安全流程图 | DFD + Trust Boundary | 敏感数据如何流动？跨信任域位置在哪里？ | 数据通路级 |
| 价值流图（可选） | Value Stream Mapping | 从需求到交付的等待/瓶颈在哪里？ | 端到端业务链路 |

### 组合策略（建议默认）

1. 先画 BPMN：对齐业务语义、边界和异常策略。
2. 再画 Sequence/Activity：把业务步骤映射到代码执行链路。
3. 补一张 C4 Dynamic：把关键用例放回架构关系中，减少“流程图脱离结构图”问题。
4. 对高风险模块补 DFD：明确数据分类、信任边界和威胁建模输入。
5. 交付时统一使用文本化图定义（Mermaid/Structurizr DSL），确保可版本化、可审查、可被 LLM 精确读取。

### 最小质量标准（每张图）

- 必须有场景 ID（如 `S1`）和目标结果。
- 必须包含主成功路径与失败/补偿路径。
- 必须映射到代码证据（路径 + 符号 + 契约）。
- 必须标注关键非功能约束（超时、重试、幂等、一致性）。

## 深度规则详解

### Level 1（快速）- 适用于低风险模块

**范围**：单页模块卡片 + 上下文 + 检查清单

**适用场景**：
- 变更频率低
- 业务影响有限
- 团队熟悉度高

**时间投入**：1-2 小时

### Level 2（标准）- 适用于常规模块

**范围**：完整档案文件 + 至少一个运行时流程

**适用场景**：
- 中等变更频率
- 有一定业务影响
- 需要知识传承

**时间投入**：半天

### Level 3（深度）- 适用于核心模块

**范围**：包含边缘情况流程、失败模式、ADR 链接

**适用场景**：
- 高频变更或高业务风险
- 关键收入/安全/可靠性影响
- 新团队接手或重构规划

**时间投入**：1-2 天

## 选择深度的决策矩阵

| 影响范围 \ 变更频率 | 低频 | 中频 | 高频 |
|---|---|---|---|
| 低影响 | Level 1 | Level 1 | Level 2 |
| 中影响 | Level 1 | Level 2 | Level 2 |
| 高影响 | Level 2 | Level 2 | Level 3 |

## 各方法论核心要点

### C4 模型

- **上下文图**：系统与外部参与者关系
- **容器图**：系统内部部署单元
- **组件图**：容器内部组件结构
- **代码图**：组件内部实现细节（可选）

### arc42 章节

1. 引言和目标
2. 约束条件
3. 上下文和范围
4. 解决方案策略
5. 构建视图
6. 运行时视图
7. 部署视图
8. 跨切概念
9. 架构决策
10. 质量需求
11. 风险和技术债务
12. 术语表

### ADR 结构

- 标题
- 状态（提议/已接受/已废弃/已替代）
- 背景
- 决策
- 后果
- 备选方案

### Diataxis 四象限

| | 面向学习 | 面向工作 |
|---|---|---|
| **面向实践** | 教程 | 操作指南 |
| **面向理解** | 解释 | 参考 |

## 参考链接

- C4 模型（官方）：https://c4model.com/
- arc42（官方文档）：https://arc42.org/overview
- ADR 项目模板：https://adr.github.io/
- Diataxis 框架：https://diataxis.fr/
- ISO/IEC/IEEE 42010 概览：https://www.iso.org/obp/ui/#iso:std:iso-iec-ieee:42010:ed-2:v1:en
- BPMN 规范（OMG）：https://www.omg.org/spec/BPMN
- UML 规范（OMG）：https://www.omg.org/spec/UML
- C4 动态图说明（Simon Brown）：https://c4model.com/diagrams/dynamic
- Structurizr DSL 动态视图（官方）：https://docs.structurizr.com/dsl/cookbook/dynamic-view
- Mermaid 流程图语法（官方）：https://mermaid.js.org/syntax/flowchart.html
- Mermaid 时序图语法（官方）：https://mermaid.js.org/syntax/sequenceDiagram.html
- DFD 与 trust boundary（Microsoft）：https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-data-flow-diagrams
- Event Storming（Martin Fowler）：https://martinfowler.com/articles/201701-event-driven.html
- Value Stream Mapping（Lean Enterprise Institute）：https://www.lean.org/lexicon-terms/value-stream-mapping/
