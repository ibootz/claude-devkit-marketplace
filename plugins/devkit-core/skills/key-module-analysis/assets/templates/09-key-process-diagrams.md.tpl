# 关键流程图集：__MODULE_NAME__

## 使用说明

- 本文件用于汇总关键业务与技术流程图，支持开发者与 LLM 统一理解模块行为。
- 建议每张图都使用场景 ID（`S1`/`S2`...）并附“代码证据映射”。
- 默认优先使用文本化定义（Mermaid 或 Structurizr DSL），避免图片孤岛。

## S1 业务流程图（BPMN 视角）

### 场景定义

- 场景 ID：
- 目标结果：
- 触发条件：
- 结束判定：

### 图定义（可用 Mermaid flowchart 近似 BPMN）

```mermaid
flowchart TD
    A[开始事件] --> B[业务活动]
    B --> C{网关判断}
    C -->|主路径| D[业务活动]
    C -->|异常路径| E[补偿/回滚]
    D --> F[结束事件]
    E --> F
```

### 代码证据映射

| 图节点 | 文件路径 | 符号（函数/类/接口） | 契约（API/schema/topic） |
|---|---|---|---|
| | | | |

## S2 技术流程图（控制流/状态流）

### 场景定义

- 场景 ID：
- 技术目标：
- 前置条件：
- 失败条件：

### 图定义（UML Activity 或 Mermaid flowchart）

```mermaid
flowchart LR
    A[接收请求] --> B[参数校验]
    B --> C{校验通过?}
    C -->|是| D[执行业务逻辑]
    C -->|否| E[返回错误]
    D --> F[持久化/发布事件]
    F --> G[返回成功]
```

### 非功能标注

- 超时：
- 重试：
- 幂等：
- 一致性模型：

## S3 交互时序图（服务协作）

### 图定义（UML Sequence 或 Mermaid sequenceDiagram）

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Service
    participant DB

    Client->>API: 请求
    API->>Service: 调用
    Service->>DB: 读写
    DB-->>Service: 结果
    Service-->>API: 响应
    API-->>Client: 结果
```

### 异常/补偿

- 超时处理：
- 重试策略：
- 失败补偿：

## S4 数据与安全流程图（DFD + 信任边界）

### 数据流与边界

- 敏感数据类型：
- 数据来源：
- 存储位置：
- 信任边界：

### 图定义

```mermaid
flowchart TB
    subgraph TrustBoundaryA[信任边界 A]
      U[用户]
      APP[应用服务]
    end

    subgraph TrustBoundaryB[信任边界 B]
      DB[(数据库)]
      MQ[(消息队列)]
    end

    U --> APP
    APP --> DB
    APP --> MQ
```

### 威胁建模输入

| 数据流 | 威胁类型 | 现有控制 | 待补强项 |
|---|---|---|---|
| | | | |

## 一致性检查清单

- [ ] 每张图有场景 ID、触发条件、结束判定
- [ ] 每张图覆盖主路径 + 失败/补偿路径
- [ ] 图中术语与代码/契约一致
- [ ] 每张图可映射到代码证据（路径 + 符号 + 契约）
- [ ] 高风险场景已补充 DFD 和信任边界
