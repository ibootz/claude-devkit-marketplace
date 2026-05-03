# 跨会话长久记忆插件对比报告

**报告时间**: 2026年2月1日  
**评估目标**: 为 claude-devkit-marketplace/plugins 选择合适的跨会话长久记忆方案（方案3：Worker服务 + 渐进式披露）

---

## 评估维度

基于方案3需求，评估以下5个核心维度：

1. **自然语言检索** - 是否支持语义搜索、向量检索
2. **新对话自动注入** - 是否支持 SessionStart 自动注入上下文
3. **分层分类保存** - 是否有结构化的记忆分层（Core/Episodic/Observation等）
4. **失效/防重处理** - 是否有TTL、去重、质量评分、情感元数据等治理机制
5. **渐进披露** - 是否支持 search→timeline→details 三层渐进检索

---

## 插件对比矩阵

| 需求点 | **claude-mem** | **episodic-memory** | **cipher** | **mcp-memory-service** | **Claude-Code-Workflow** | **SuperClaude** |
|--------|---------------|---------------------|------------|------------------------|--------------------------|-----------------|
| **自然语言检索** | ✅ 语义搜索 + 技能检索 | ✅ SQLite-vec + Transformers.js | ✅ 语义搜索 + 知识图谱 | ✅ SQLite-vec + MiniLM ONNX | ✅ Embedding + 语义搜索 | ❌ 关键词匹配 |
| **新对话自动注入** | ✅ SessionStart hook 自动注入 | ✅ Session-end hooks 自动索引 | ⚠️ 需手动调用 MCP tools | ✅ Automatic context capture | ✅ Resume 策略注入 | ✅ `/sc:load` 手动/自动 |
| **分层分类保存** | ✅ Observation→Cluster→Timeline | ✅ 对话归档 + 项目分组 | ✅ **双系统记忆** (System 1 + System 2) | ✅ Episodic + Knowledge Graph | ✅ Core + Session + Entity 分层 | ✅ Project + Session + Pattern |
| **失效/防重处理** | ✅ TTL + 去重 + 版本控制 | ⚠️ 归档保留，无自动TTL | ⚠️ 需配置管理 | ✅ **质量评分** + 访问计数 + 情感元数据 | ✅ 热度衰减 + 冲突标记 | ❌ 无自动治理 |
| **渐进披露** | ✅ **search→timeline→details** | ❌ 单层搜索展示 | ⚠️ 知识图谱导航，非渐进 | ⚠️ 智能检索，无分层披露 | ⚠️ 聚类后展示，非渐进 | ❌ 全量加载 |

---

## 各插件详细分析

### 1. claude-mem ⭐ 最佳匹配

**官方链接**: https://github.com/thedotmack/claude-mem  
**协议**: AGPL 3.0  
**技术栈**: Node.js + TypeScript + SQLite + ChromaDB

**核心特性**:
- **Worker 服务**: 端口 37777 HTTP API + MCP Server
- **渐进披露**: 唯一完整实现 search→timeline→details 三层检索
- **自动注入**: SessionStart hook 自动注入上下文，无需手动干预
- **隐私控制**: `<private>` 标签自动排除敏感内容
- **分层存储**: Observation → Cluster → Timeline 三级结构
- **引用系统**: 每条记忆有唯一 ID，支持精确引用

**MCP Tools**:
- `mem-search`: 语义搜索记忆
- `mem-timeline`: 获取时间线视图
- `mem-details`: 获取详细记忆内容
- `mem-store`: 存储新记忆

**优点**:
- 与 Claude Code 深度集成
- 自动运行，零配置
- Web UI 实时查看记忆流

**缺点**:
- 需要 ChromaDB（可选，可降级为 SQLite）
- 社区版功能相对聚焦

---

### 2. episodic-memory ⭐ 轻量替代

**官方链接**: https://github.com/ephemeral-labs/episodic-memory  
**协议**: MIT  
**技术栈**: TypeScript + SQLite-vec + Transformers.js（纯本地）

**核心特性**:
- **纯本地**: SQLite + Transformers.js，零外部依赖
- **对话索引**: 自动索引 `~/.claude/projects` 下的对话历史
- **语义搜索**: 基于向量相似度的对话检索
- **MCP 集成**: 提供 `episodic_memory_search` 和 `episodic_memory_show` 工具

**使用方式**:
```bash
# 作为 Claude Code 插件安装
/plugin install episodic-memory@superpowers-marketplace

# 自动索引（session-end hook）
episodic-memory sync

# 搜索
episodic-memory search "React Router authentication"
```

**优点**:
- 完全离线，隐私友好
- 轻量级，启动快速
- 自动会话归档

**缺点**:
- ❌ 无渐进披露（只有搜索→展示）
- ❌ 无自动 SessionStart 注入
- ❌ 无记忆治理（TTL、去重等）

---

### 3. cipher 🔷 双系统记忆

**官方链接**: https://github.com/campfirein/cipher  
**协议**: Elastic License 2.0（非纯开源）  
**技术栈**: Node.js + Qdrant/Milvus + PostgreSQL/SQLite

**核心特性**:
- **双系统记忆架构**:
  - System 1: 编程概念、业务逻辑、历史交互
  - System 2: 模型生成代码时的**推理步骤**（反思记忆）
- **知识图谱**: 完整的节点/边管理，支持关系查询
- **团队协作**: Workspace Memory 支持实时共享
- **多后端**: Qdrant、Milvus、内存向量库
- **MCP 模式**: `cipher --mode mcp` 作为 MCP Server 运行

**MCP Tools**:
- `cipher_memory_search`: 语义搜索
- `cipher_extract_and_operate_memory`: 提取知识并自动 ADD/UPDATE/DELETE
- `cipher_store_reasoning_memory`: 存储高质量推理轨迹
- `cipher_search_reasoning_patterns`: 搜索反思模式
- 知识图谱工具: `cipher_add_node`, `cipher_add_edge`, `cipher_search_graph`

**优点**:
- 独特的双系统记忆（尤其 System 2 反思记忆）
- 知识图谱支持复杂关系查询
- Workspace Memory 支持团队协作

**缺点**:
- Elastic License 限制商业使用
- 需要 LLM API key（OpenAI/Anthropic/Gemini等）
- ⚠️ 渐进披露需自建逻辑
- ⚠️ 自动注入需手动配置 hooks

---

### 4. mcp-memory-service 🔷 功能最全面

**官方链接**: https://github.com/doobidoo/mcp-memory-service  
**协议**: Apache 2.0  
**技术栈**: Python + SQLite-vec/Cloudflare + MiniLM-L6-v2 (ONNX)

**核心特性**:
- **质量感知记忆**:
  - `quality_score`: 记忆质量评分
  - `access_count`: 访问计数
  - `last_accessed_at`: 最后访问时间
  - 情感元数据: `emotion`, `emotional_valence`, `emotional_arousal`
- **极速检索**: 宣称 5ms 延迟
- **多后端**: SQLite（本地）、Cloudflare（云同步）、Hybrid
- **Web 仪表盘**: `http://localhost:8000` 可视化记忆 + 知识图谱
- **SHODH 生态兼容**: 统一 Memory API 规范，可与其他实现互操作

**MCP Tools**:
- `create_memory`: 创建记忆
- `search_memory`: 语义搜索（支持自然语言时间表达式）
- `get_memory`: 获取记忆详情
- `delete_memory`: 删除记忆
- `get_memory_stats`: 获取记忆统计

**情感元数据示例**:
```json
{
  "emotion": "excitement",
  "emotional_valence": 0.8,
  "emotional_arousal": 0.7
}
```

**优点**:
- 功能最完善，质量评分机制独特
- 多后端选择（本地/云端/混合）
- Web UI 可视化友好
- Apache 2.0 完全开源

**缺点**:
- ⚠️ 无渐进披露（需要自建）
- ⚠️ 自动注入需配置
- 配置相对复杂

---

### 5. Claude-Code-Workflow (CCW)

**来源**: `/home/momog/workspace/ai/coding/workflow/Claude-Code-Workflow`  
**技术栈**: TypeScript + SQLite + 自定义 Embedding Bridge

**核心特性**:
- **Resume 策略**: `native` / `prompt-concat` / `hybrid` 三种会话恢复模式
- **会话聚类**: Session Clustering Service 按意图匹配度分组
- **分层存储**: Core Memory + Session Metadata + Entity Tracking
- **Embedding Bridge**: TypeScript ↔ Python 桥接用于向量生成

**数据模型**:
- `core_memories`: 核心记忆表
- `session_clusters`: 会话簇
- `memory_blocks`: 记忆块（支持 embedding）
- `entities`: 实体追踪

**优点**:
- 与你的 workflow 代码库同源
- Resume 策略灵活
- 完整的 TypeScript 实现

**缺点**:
- ⚠️ 渐进披露不完整（聚类后直接展示）
- ⚠️ 需要自建 Worker 服务
- ⚠️ 无内置自动注入 hooks

---

### 6. SuperClaude Framework

**来源**: `/home/momog/workspace/ai/coding/workflow/SuperClaude_Framework`  
**技术栈**: Markdown-based + Serena MCP

**核心特性**:
- **Serena MCP**: 通过 MCP 实现语义代码理解和项目记忆
- **命令式管理**: `/sc:load`, `/sc:save`, `/sc:reflect` 手动管理
- **记忆类型**: Project / Session / Pattern / Progress Memories
- **ReflexionMemory**: 自动学习错误的 JSONL 存储

**生命周期管理**:
```
Session Start Protocol:
  list_memories → read_memory → 恢复上下文

Session End Protocol:
  write_memory(last_session, next_actions, pm_context)
```

**优点**:
- 与 Serena MCP 深度集成
- ReflexionMemory 专注错误学习

**缺点**:
- ❌ 无自然语言检索（关键词匹配）
- ❌ 无渐进披露
- ❌ 无自动治理
- 命令式操作，非自动

---

## 需求维度最佳匹配

| 你的需求 | **最佳匹配** | **理由** |
|----------|-------------|----------|
| **自然语言检索** | mcp-memory-service / cipher | 都有完整语义搜索 + 知识图谱 |
| **新对话自动注入** | claude-mem / mcp-memory-service | 两者都支持自动上下文捕获 |
| **分层分类保存** | **cipher** | 双系统记忆（System 1+2）是独特优势 |
| **失效/防重处理** | **mcp-memory-service** | 质量评分 + 访问计数 + 情感元数据最完善 |
| **渐进披露** | **claude-mem** | 唯一完整实现 search→timeline→details 三层 |

---

## 最终推荐

### 🥇 首选：claude-mem（单选即可满足方案3）

**推荐理由**:
- ✅ **唯一完整实现渐进披露**（你的核心需求）
- ✅ **Worker 服务**已就绪（端口 37777）
- ✅ **自动注入**通过 SessionStart hook
- ✅ **隐私控制**内置 `<private>` 标签
- ✅ **AGPL 开源**，可自由修改

**集成方式**:
```bash
# 在 devkit-core 中安装
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem

# 复用其 MCP tools
# - mem-search
# - mem-timeline
# - mem-details
# - mem-store
```

---

### 🥈 次选：mcp-memory-service（功能最全面）

**适用场景**:
- 你需要 **质量评分** 和 **情感元数据**
- 你需要 **Web 仪表盘** 可视化
- 你需要 **多后端**（本地/云端/混合）

**注意**:
- 需要自建渐进披露逻辑
- 需要配置自动注入

---

### 🥉 特定场景：cipher（双系统记忆）

**适用场景**:
- 你需要 **记录模型推理过程**（System 2 记忆）
- 你需要 **团队协作** 的 Workspace Memory
- 你需要 **知识图谱** 进行关系查询

**注意**:
- Elastic License 限制
- 需要 LLM API key

---

### 组合方案（高级）

如果你需要同时满足所有维度，考虑组合：

**方案A：claude-mem + mcp-memory-service**
- claude-mem: 渐进披露 + 自动注入
- mcp-memory-service: 质量分析（周期性导入质量评分）

**方案B：episodic-memory + 自建渐进层**
- episodic-memory: 纯本地语义搜索（MIT协议）
- 自建: search→timeline→details 逻辑

---

## 实施建议

### 最小 MVP 路线（推荐）

```
Phase 1: 直接集成 claude-mem
  - 安装 claude-mem 插件
  - 复用其 MCP tools 在 devkit-core 命令中
  - 使用其 SessionStart hook 自动注入

Phase 2: 可选补强
  - 如需要质量评分，叠加 mcp-memory-service
  - 如需要推理记录，叠加 cipher
```

### 文件变更清单

**如选择 claude-mem（零开发）**:
- ✅ 无需新增文件，直接使用插件

**如选择 episodic-memory + 自建渐进层**:
- `hooks/session-start.py`: 调用记忆检索并分层注入
- `hooks/session-end.py`: 触发 sync 索引
- `commands/mem-search.md`: 封装渐进披露逻辑
- `worker/memory_worker.py`: 轻量级检索服务

---

## 附录：技术栈对比

| 插件 | 语言 | 存储 | 向量库 | 嵌入模型 | License |
|------|------|------|--------|----------|---------|
| claude-mem | Node/TS | SQLite | ChromaDB | 可配置 | AGPL 3.0 |
| episodic-memory | Node/TS | SQLite-vec | 内置 | Transformers.js | MIT |
| cipher | Node/TS | SQLite/PG | Qdrant/Milvus | 可配置 | Elastic 2.0 |
| mcp-memory-service | Python | SQLite-vec/Cloudflare | 内置 | MiniLM-L6-v2 ONNX | Apache 2.0 |
| CCW | TypeScript | SQLite | 自定义 | 自定义 Bridge | - |
| SuperClaude | Markdown | JSONL | - | 关键词 | - |

---

*报告结束*
