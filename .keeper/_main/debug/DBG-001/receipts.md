# DBG-001 回执

## 实现

- 新增 `task-keeper:debug-fixer-easy`、`medium`、`hard` 三个第二层 fixer，固定映射为 easy/sonnet、medium/opus、hard/fable；三者均明确禁止再派 subagent。
- 保持第一层 `task-keeper:debug-keeper` 的 `opus`、`opus-debugger-<4位>` 与 `debug 队列` 描述前缀不变。
- `agent-dispatch.js` 仅按精确 `subagent_type`、`model`、`name`、`description` 和长度校验第二层 fixer；不扫描 prompt。缺 name 时按精确 type 自动补 `<model>-debug-<4位>`。
- 同步 debug keeper、队列派发模板、task-keeper README、working-discipline 注入与 README；模板保留 worktree、提交、禁止启动服务、禁止 push、headless 浏览器等既有约束。
- 版本登记：task-keeper `4.5.0`；working-discipline `3.28.0`；已同步 Claude Code 与 Codex 两份 marketplace 清单。

## 验证

- `node plugins/working-discipline/test/guard-verify.js`：`✓ guard 回归 157/157 全部通过`。
- `node --check plugins/working-discipline/hooks/guards/agent-dispatch.js` 与 `node --check plugins/working-discipline/hooks/working-discipline.js`：通过。
- Python YAML/load 校验：三个 `agents/debug-fixer-*.md` frontmatter 均解析成功，名称与模型分别为 easy/sonnet、medium/opus、hard/fable。
- `node scripts/check-versions.js`：`✓ 22 个插件的版本登记四方一致`。
- marketplace description 长度：task-keeper 55、working-discipline 50；plugin manifest description 长度：84、112；均在各自上限内。
- 注入长度：SessionStart 8209；UserPromptSubmit 4514；SubagentStart 9874，均不超过 10000。
- `git diff --check`：通过。

## 覆盖边界

第二层 description 使用 `\p{Script=Han}` 与字符白名单，能机械拒绝纯英文、模型标签、队列前缀及超 15 code point；JavaScript 标准正则不能可靠区分简体与繁体，未将简繁判别伪装为已覆盖。
