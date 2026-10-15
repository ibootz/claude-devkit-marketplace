# `claude plugin eval` 与 `/skill-doctor` 能力调研

调研时间：2026-10-13，本机 Claude Code 2.1.296（eval 门槛 2.1.269，`/skill-doctor` 门槛 2.1.252）。
出处：官方文档 [plugin-evals](https://code.claude.com/docs/en/plugin-evals)、[plugins/measure](https://code.claude.com/docs/en/plugins/measure)、[skills](https://code.claude.com/docs/en/skills) 的「Find unused skills」节，以及本机 `claude plugin eval --help`。
标「未查到」的是文档与 `--help` 都没写的，未臆测。

## 一、和 skill-creator 是两套东西

官方原文：skill-creator 的 `evals/evals.json` 与本格式 "neither tool reads the other's case files"。

## 二、用例格式

- 一个用例是 `evals/<case>/` 目录：`prompt.md`（frontmatter 是字段，正文是 prompt）和/或 `case.yaml`。
- 每个用例至少一个 `graders/<name>.md`，否则加载失败。
- frontmatter 字段：`name` `tags` `plugins` `runs`（1–50，默认 3）`model` `max_turns`（默认 10，上限 200）`timeout_seconds` `allowed_tools` `append_system_prompt` `env`（key 必须 `EVAL_*`）。未知 key 报错。
- `case.yaml` 独有：`context.scaffold_script`、`context.history_file`、`context.add_dirs`、`graders`。
- 生成：`claude plugin eval init`（访谈式）或 `init --bare <name>`。

## 三、能评什么

| 对象 | 支持情况 |
|---|---|
| skill 触发 | 支持。`tool_used` grader 配 `tool: Skill` + `input_match` |
| 单轮输出 | 支持 |
| 多轮对话 | 半支持。只能用 `context.history_file` 回放一份 jsonl，评下一轮 |
| hook 行为 | 无专门支持。run 会加载插件的 hooks，但 hook 跑在沙箱外；注入的 `additionalContext` 是否出现在 `trace` 里：**未查到** |
| output style | 未查到 |
| MCP | 支持，`mocks/<server>/<tool>.md` 打桩 |
| 多插件同时加载 | `plugins` 字段是复数，但文档无多插件示例：**未明确** |

## 四、判分

- 6 种 grader，原文 "There are no custom-code graders"：
  - 免费：`regex`（contains / not_contains / `count:N`）、`tool_used`（`min` `max`）、`tool_order`、`file_exists`
  - 调模型：`llm`（3 票 ≥2 PASS）、`baseline`（与参考 transcript 比）
- grader 可读：`last_message`（默认）、`trace`（`llm` 评委只看前 12 条与后 12 条）、`files`（只有路径）、`{source: file, path}`、`mock_calls`。
- 分数 = 通过的 grader 占比（可加权），用例分 = 各 run 均值，默认阈值 1.0。
- 对照：`--ablation with-without` 输出 `WITH` `W/OUT` `Δ`。
- 方差 / 置信区间字段：未查到。
- 评委默认 haiku，可 `--judge-model` 改；文档提醒小评委会误判长输出。

## 五、隔离

- 每个 run 是独立 `claude -p` 子进程，临时 home、临时工作目录、临时配置。原文："Your user settings, hooks, `CLAUDE.md` files, MCP servers, other installed plugins, memory, and skills are absent."
- 工作区里的 `.claude/` `CLAUDE.md` `.mcp.json` 一律不加载。
- 默认只给只读工具；`Bash` `Write` `Edit` `WebFetch` 要 `--allow-tools`。
- 对照组是「什么都不装」，不是「装了用户其它插件」。

## 六、输出、CI、成本

- `<eval dir>/results/<时间戳>/aggregate-result.json`（`schemaVersion: 1`）+ `report.html`；`--no-publish` 不发到 claude.ai。
- 退出码：0 全达标；1 低于阈值或加载失败；2 部分完成（成本上限 / 凭证）；130 中断；143 被终止。Δ 不影响退出码。
- 成本控制：`--max-cost-usd`、`--runs`、`--ablation none`、`-j`（1–8）、`--judge-model`、`--case` / `--tag`。
- 成本是按标价估算，不是实际账单。

## 七、已知局限（文档原载）

- 含自有 hook 的插件，分数只能作参考：hook 跑在沙箱外，可能改动 grader 读的文件。
- 配额或限流中途触发时后续 run 记 0，但套件不标 `partial`，易误读为回归。
- 双臂模式下插件自带 agent 在对照臂报 `Agent type ... not found`，属预期。

## 八、`/skill-doctor`

列各 skill 的上下文成本与调用频率，标出从未被调用的 skill 与近期没用过的插件。是**用量报告，不评行为**。具体列与阈值文档未写。
