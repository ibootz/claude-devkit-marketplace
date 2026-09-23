# 02: 把 hook 迁到 Node.js 并补协议回归测试

Status: done
Type: task
Blocked by: 无

## What to build

把 `wenyan-output-style` 的两个 hook（SessionStart 注入、每轮 UserPromptSubmit 短锚）从 bash + 内联 Python heredoc 迁移成 Node.js，注入的文本逐字节不变。这是纯重构：本票不改任何规则文字。

现状的几个缺陷见 spec 实施决策第 20 条：

- 事件名写死，不回显入参的 `hook_event_name`。
- heredoc 占用了 stdin，hook 读不到自己的输入。
- 用 `command -v python3` 解析解释器，会被 Windows Store 的零字节桩骗过。
- 出错时静默输出空内容。
- 没有环境变量开关。

目标形态参照 `clickable-paths` 的 hook 与它的 `hooks/tests/clickable-paths.test.js`：

- 通过 `node ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.js` 调用。
- 回显 stdin 里的 `hook_event_name`。
- stdin 为空或 JSON 格式错误时，照样输出注入内容。
- 删掉旧的 `.sh` 文件，同步更新 `plugin.json` 的 `command`。
- 不新增环境开关，启停仍只通过 `/plugin`。

## Scope boundaries

规则文字不动，版本号不动（07 号票统一收口）。改动 `plugins/**` 之前，按仓库 `CLAUDE.md` 的要求，先用两次真实的 `Skill` 调用读完 `mattpocock-skills:writing-for-agents` 和 `skill-creator:skill-creator`。

## Acceptance criteria

- [ ] **删除 bash 版之前**，先把两个 bash hook 的 stdout 抓下来存成 golden 文件；Node 版的注入文本与 golden 逐字节一致。
- [ ] 测试以子进程方式运行真实的 Node hook，沿用 `spawnSync` + `cases` 模式，失败时非零退出。
- [ ] 用例覆盖：合法 JSON 输出；`hookEventName` 回显；stdin 为空；stdin 为错误 JSON；与 golden 逐字节一致。
- [ ] 用例写死注入预算：SessionStart 正文 ≤ 6400 字符，每轮短锚 ≤ 300 字符。
- [ ] `plugin.json` 不再引用任何 `.sh`；hook 目录里没有残留的 bash 脚本。
- [ ] `node scripts/check-versions.js` 与新测试均通过。

## Comments

### 2026-09-23 · 已完成

- `session-start.sh` / `user-prompt-submit.sh` 已移植为 `session-start.js` / `user-prompt-submit.js`；`plugin.json` 改为 `node ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.js`；两个 `.sh` 已 `git rm`。
- 删除 bash 版之前，先把两个 hook 的 stdout 抓成 `hooks/tests/golden/*.json`；移植后首次运行与 golden 逐字节一致，12/12 通过。
- 新增 `hooks/tests/wenyan-output-style.test.js`：覆盖事件回声、空 stdin、畸形 JSON、外来事件静默退出、两条注入预算、`plugin.json` 的 command、无残留 `.sh`。
- README 已更新：文件表、预算说明、「改规则后刷新 golden」命令。
- 版本号未改，留给 07 号票。
