# dws — 钉钉全产品能力集成

通过 `dws` CLI 在 Claude Code / Codex 中管理钉钉全产品能力。基于钉钉内部产品文档封装为一个可复用的 skill 插件。

## 能力范围

| 产品 | 用途 |
|------|------|
| `aisearch` | AI 搜问（找人首选）：按姓名/部门/职位/职责/上下级/手机号/工号找人，"谁负责 XX" |
| `aitable` | AI 表格：Base/数据表/字段/记录/视图/附件/图表/仪表盘/导入导出 |
| `attendance` | 考勤：考勤组规则/打卡详情/班次/统计摘要 |
| `calendar` | 日历：日历/日程/参与者/会议室/闲忙查询/时间建议 |
| `chat` | 群聊与机器人：建群/成员管理/消息收发/@我/机器人群发/单聊/撤回 |
| `contact` | 通讯录：用户/花名册/离职员工/部门查询 |
| `dev` / `devdoc` | 开放平台开发者与文档搜索（建号、联调、应用生命周期、API 文档 RAG） |
| `ding` | DING 消息：应用内/短信/电话发送与撤回 |
| `doc` | 钉钉文档：搜索/读写/块级编辑/评论/复制移动/导出/权限/媒体上传下载 |
| `drive` | 钉钉云盘：文件列表/元数据/上传下载 |
| `minutes` | AI 听记：摘要/关键词/转写/待办/思维导图/发言人分析 |
| `oa` | OA 审批：待处理/详情/同意拒绝/撤销/转交/评论/抄送 |
| `report` | 日志：按模版创建/收件箱/已发送/已读统计 |
| `mail` | 邮箱：地址查询/KQL 搜索/详情/发送 |
| `sheet` | 在线电子表格（axls）：读写/样式/筛选/条件格式 |
| `wiki` + `doc` | 知识库：空间/成员管理 + 库内文档处理 |

## 前置要求

- 已安装并登录 `dws` CLI（`cli_version >= 1.0.15`）。
- 所有操作只经 `dws` 命令完成，不使用 curl / HTTP API / 浏览器。

## 安装

- **Claude Code**：通过本 marketplace 安装 `dws` 插件，skill 自动加载。
- **Codex**：运行仓库根目录的 `node scripts/install-codex.js`，会将 `skills/dws` 复制到 `~/.agents/skills/`。

## 结构

```
plugins/dws/
├── .claude-plugin/plugin.json   # Claude Code manifest
├── .codex-plugin/plugin.json    # Codex manifest（skills + interface）
└── skills/dws/                  # skill 内容（SKILL.md + references/ + scripts/）
```
