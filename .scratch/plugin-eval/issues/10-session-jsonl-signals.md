# 10: 会话 jsonl 里能取到哪些评测信号

Type: research
Status: resolved
Blocked by: 无

## Question

[评测范围](06-scope.md) 定了要做会话复盘：事后读 `~/.claude/projects/**/*.jsonl`，统计被测插件的实际触发与违规情况。实地查清 jsonl 能提供哪些信号：

1. **skill 调用**：`Skill` 工具调用与 skill 名能否识别；模型自动调用与用户输入 `/<skill>` 能否区分。
2. **hook 输出**：SessionStart / UserPromptSubmit / PreToolUse 的 `additionalContext`、deny / ask 决定、hook 报错是否留痕、在哪个字段；能否归到具体插件（插件名、hook 命令路径）。
3. **环境插件清单**：一次会话里启用了哪些插件、各自什么版本，能否从 jsonl 本身或其它本地文件还原。
4. **会话关联**：子代理会话与主会话怎么关联；compact 事件是否留痕。
5. **违规模式机械检出**：已知违规（如派发 `Agent` 不带 `model`、`cd-guard` 拦截）能否从工具入参与 hook 输出里机械检出。

## 约束

- 进仓的只有字段名、结构与计数。不抄对话原文、文件内容，也不写出项目目录名（目录名里有内网项目名）。06 已定会话原文不入库。
- 样本取近 30 天，覆盖至少 3 个不同项目，含至少 1 个有子代理的会话。
- 产出写 `.scratch/plugin-eval/research/session-jsonl-signals.md`，本票 `## Answer` 给摘要与链接。

## 完成判据

五问各答「能 / 部分能 / 不能」，并附字段路径示例（如 `message.content[].input.model`）。

## Answer

2026-10-14 实测近 30 天本机 jsonl（全量扫描 137 个项目、611 个主会话文件、1227 个子代理文件；字段结构细查 8 个项目、48 个主会话、52 个子代理文件）。五问结论如下，字段路径与计数见 [research/session-jsonl-signals.md](../research/session-jsonl-signals.md)。

1. **skill 调用：能。**
   模型自动调用是 `message.content[].input.skill`（`name=="Skill"` 的 `tool_use`）；用户输入 `/<skill>` 是 user 记录 `message.content` 里的 `<command-name>`；assistant 记录另有 `attributionSkill` / `attributionPlugin` 直接给出「本轮归属哪个插件的哪个 skill」。
2. **hook 输出：部分能。**
   留痕齐全：`attachment.type` 取 `hook_success` / `hook_additional_context` / `hook_blocking_error` 等，deny 落在 tool_result 文本与 `permissionDecision`。**归插件只有 deny 事件稳定**（展开后的 cache 路径带 `<plugin>/<version>`）；注入类事件的 `command` 是未展开的 `${CLAUDE_PLUGIN_ROOT}/hooks/<脚本>`，不含插件名，要靠脚本指纹加内容标签。
3. **环境插件清单：部分能。**
   会话内 `attachment.skill_listing.names[]` 给出有 skill 的插件名集合；版本拿不到，`installed_plugins.json` 与 cache 只有当前态，历史版本还原不了。
4. **会话关联：能。**
   子代理 `subagents/agent-<id>.meta.json` 的 `toolUseId` 对父会话 `Agent` 的 `tool_use.id`；compact 有 `system` 记录 `subtype:"compact_boundary"`。resume / fork 会复制历史，约 11% 的 `uuid` 重复，**必须按 `uuid` 去重**。
5. **违规机械检出：部分能。**
   `Agent` 缺 `model` 看 `tool_use.input`，`cd-guard` 看 tool_result 文本含 `check=cd-guard`，都能；语义与文风类、「该触发没触发」不能。

**对 06 重开条件的影响**：「jsonl 无法把现象归到具体插件」对 skill 与 deny 类不成立，对没有标签的纯注入类成立一半，第 1、5 条暂不必重议，但 09 要把「注入类归因靠指纹加标签」当作已知缺口。

**给 09 的输入**：
- 抽取脚本必须对缺字段容错并记录 `version`：`permissionDecision` 2.1.294 起、`wireToolInputs` 2.1.272 起、deny 尾注 2.1.281 起。
- 子代理文件要并入统计，否则漏掉近半数拦截。
- 插件版本要在复盘脚本运行时读一次 `installed_plugins.json` 写进抽取结果。
- 被测插件的 hooks.json 可导出「事件 + matcher + 脚本相对路径」作指纹；改名前的旧目录名要靠 marketplace 的 `renames` 归一。

## Comments
