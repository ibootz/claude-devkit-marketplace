# DBG-001 回执

## 实现

- 新增 `task-keeper:debug-fixer-easy`、`medium`、`hard` 三个第二层 fixer，固定映射为 easy/sonnet、medium/opus、hard/fable；三者均明确禁止再派 subagent。
- 保持第一层 `task-keeper:debug-keeper` 的 `opus`、`opus-debugger-<4位>` 与 `debug 队列` 描述前缀不变。
- `agent-dispatch.js` 仅按精确 `subagent_type`、`model`、`name`、`description` 和长度校验第二层 fixer；不扫描 prompt。缺 name 时按精确 type 自动补 `<model>-debug-<4位>`。
- 补入 `traditional-simplified-forms.js`：从 OpenCC `TSCharacters.txt` 固定出 3203 个明确简繁差异的传统单字形，仅对精确第二层 fixer description 拒绝；普通 Agent、第一层 keeper 与简繁共用字不受影响。
- 同步 debug keeper、队列派发模板、task-keeper README、working-discipline 注入与 README；模板保留 worktree、提交、禁止启动服务、禁止 push、headless 浏览器等既有约束。
- 版本登记：task-keeper `4.5.0`；working-discipline `3.29.0`；已同步 Claude Code 与 Codex 两份 marketplace 清单。

## 验证

- `node plugins/working-discipline/test/guard-verify.js`：`✓ guard 回归 160/160 全部通过`。
- `node --check plugins/working-discipline/hooks/guards/agent-dispatch.js`、`node --check plugins/working-discipline/hooks/guards/traditional-simplified-forms.js` 与 `node --check plugins/working-discipline/hooks/working-discipline.js`：通过。
- Python YAML/load 校验：三个 `agents/debug-fixer-*.md` frontmatter 均解析成功，名称与模型分别为 easy/sonnet、medium/opus、hard/fable。
- `node scripts/check-versions.js`：`✓ 22 个插件的版本登记四方一致`。
- OpenCC 来源回读：commit `3acca9851846cee58b0be32f2618d8f675935a19` 的 `TSCharacters.txt` SHA-256 与记录值一致；按记录生成规则重算为 3203 个单字形，且与 vendored 表一致。
- marketplace description 长度：task-keeper 55、working-discipline 50；plugin manifest description 长度：84、112；均在各自上限内。
- 注入长度：SessionStart 8209；UserPromptSubmit 4514；SubagentStart 9874，均不超过 10000。
- `git diff --check`：通过。

## 覆盖边界

第二层 description 使用 `\p{Script=Han}`、字符白名单及 OpenCC `TSCharacters.txt` 的固定单字表校验：表中仅含「传统源字不属于简体目标字列表」的 3203 个明确简繁差异字形，逐 code point 机械拒绝。因此 `修復登入` 被拒绝、`修复登入` 放行；共享汉字（例如 `乾`、`著`）不拒绝。静态 vendored 表从 BYVoid/OpenCC `data/dictionary/TSCharacters.txt` 的 commit `3acca9851846cee58b0be32f2618d8f675935a19` 生成，源文件 SHA-256 为 `737c21c66f55a419dd6956cb3089476cdefc5a36877452631617696df1e5d925`；生成时仅保留源字不在简体目标列表的单字行，运行时不下载或调用 OpenCC。它不试图判断词级语境或区域用字偏好；普通 Agent 与第一层 keeper 不走此表。
