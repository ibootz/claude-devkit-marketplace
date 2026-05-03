---
name: spec-tasks
description: 将 Spec 拆解为有向无环图（DAG）结构的任务清单，支持并行开发
tools: Read, Write, Bash
color: blue
---


## argument-hint
<spec.md 路径> 例如：docs/specs/auth-20260129-143000/spec.md

## 流程

### 阶段 1：解析 Spec

1. 读取指定的 spec.md 文件
2. 验证 spec.md 格式和必需章节
3. 提取核心实体、数据流、用户旅程

### 阶段 2：层级划分

按架构层级划分任务：
1. **数据层**：数据库表结构、类型定义
2. **核心逻辑层**：Repository、Service、业务逻辑
3. **接口/交互层**：API 端点、UI 组件、外部接口

### 阶段 3：DAG 依赖构建

1. 识别任务间依赖关系
2. 使用 `DependsOn: T{M}, T{N}` 标记前置依赖
3. 无依赖任务标记 `[Root]`，可并行执行
4. 确保依赖关系形成有向无环图（无循环依赖）

### 阶段 4：并行分组

按依赖关系分层（Wave）：
- **Wave 1**: Root Tasks（无依赖，可并行）
- **Wave 2**: 依赖 Wave 1（可并行）
- **Wave 3**: 依赖 Wave 2（可并行）
- ...以此类推

## 任务清单格式（tasks.md）

```markdown
## 任务清单

### Wave 1: Root Tasks（可并行）
- [ ] **T1** [Root] `数据库表结构设计`
    - Goal: 设计用户表结构，包含字段：id, email, password_hash, created_at, updated_at
    - Ref: Spec §2.1
    - Files: `migrations/001_create_users.sql`

- [ ] **T2** [Root] `基础类型定义`
    - Goal: 定义 User 类型和相关接口
    - Ref: Spec §2.2
    - Files: `types/user.ts`

### Wave 2: Depends on Wave 1（可并行）
- [ ] **T3** (DependsOn: T1) `Repository 实现`
    - Goal: 实现用户数据访问层
    - Files: `repository/user.ts`

- [ ] **T4** (DependsOn: T1, T2) `Service 层实现`
    - Goal: 实现用户认证业务逻辑
    - Files: `services/auth.ts`

### Wave 3: Integration
- [ ] **T5** (DependsOn: T3, T4) `API 端点实现`
    - Goal: 实现登录/注册 API
    - Files: `routes/auth.ts`
```

## 并行开发说明

- "并行"指的是**逻辑上可同时进行**，而非技术上的多线程执行
- Claude 实际执行时仍是顺序的，但同 Wave 内任务无依赖，可任意顺序执行
- 开发团队可根据 Wave 分组，多人并行开发

## 错误处理

- 若 spec.md 格式错误或缺失关键章节，列出缺失项并建议补充
- 若检测到循环依赖，报错并提示调整任务拆解
- 若任务粒度过大（单个任务涉及 5+ 文件），建议进一步拆解

## 核心原则

1. **依赖清晰**：每个任务的依赖必须明确标注
2. **粒度适中**：单个任务聚焦单一职责
3. **无循环依赖**：DAG 必须是有向无环图
4. **可追溯**：每个任务引用 Spec 相关章节

## 输出路径

`<spec_dir>/tasks.md`（与 spec.md 同目录）

## 使用示例

```
/spec-tasks docs/specs/auth-20260129-143000/spec.md
```
