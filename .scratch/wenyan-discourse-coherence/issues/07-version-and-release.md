# 07: 版本同步与交付收口

Status: done
Type: task
Blocked by: 06

## What to build

前提：06 号票的结论是「发布」。满足前提后：

1. 按仓库版本规则递增 `wenyan-output-style` 的版本号。
2. 同步插件的 `plugin.json` 与两份 marketplace 清单：`.claude-plugin/marketplace.json` 和 `.agents/plugins/marketplace.json`。
3. 运行 `node scripts/check-versions.js`，以及 wenyan 的 hook 测试。
4. 合并之前先检查 `origin/main..main`，防止并行会话撞上同一个版本号。
5. 核对全部 diff：没有改动 `worktree-flow`，没有改动 `plain-talk-output-style`，没有新建 Codex manifest，没有敏感值，没有写外部系统。

如果 06 号票的结论是「不发布」或「返工」：本票改为 `wontfix`，或回到对应的票补做，并在本票 Comments 写明去向。

## Scope boundaries

不推送、不发布，除非用户当轮明确授权。根 README 的统计数字另立文档任务处理。

## Acceptance criteria

- [ ] 三处版本号一致，`check-versions.js` 通过。
- [ ] hook 测试全部通过，运行命令与结果写入本票 Comments。
- [ ] `origin/main..main` 已检查，没有版本号冲突。
- [ ] diff 范围核对无越界。
- [ ] 交付报告列出改动文件、验证命令、评测结论与残余风险。

## Comments

### 2026-09-23 · 收口完成（未提交、未推送）

**前提变更**：06 号票没有给出「发布」结论，按用户当轮指示改为收口（见 06 号票 Comments）。同一条指示还要求把停用 wenyan 后会失效的纪律迁进 `working-discipline`，这部分也在本轮做完，超出本票原定范围，下面单列。

**版本**：`wenyan-output-style` 1.7.0 → 1.8.0，`working-discipline` 3.31.0 → 3.32.0。两者各自的 `plugin.json` 与两份 marketplace 清单都已同步，用的是 `node scripts/check-versions.js --fix`。

**验证**（从仓库根执行，结果都是本轮实跑的）：

- `node scripts/check-versions.js --quiet` → 退出码 0，「23 个插件的版本登记四方一致」
- `node plugins/wenyan-output-style/hooks/tests/wenyan-output-style.test.js` → 18/18 passed（改规则后按其 README 刷新了 golden）
- `node plugins/working-discipline/test/guard-verify.js` → 160/160
- `node plugins/working-discipline/test/probe-throttle-verify.js < /dev/null` → 45 passed, 0 failed。不加 `< /dev/null` 时，在后台 shell 里挂了 10 分钟没有返回；加上后正常结束。原因未查。
- working-discipline 各层注入长度（仓库路径下测）：SessionStart 4976，UserPromptSubmit 3352，SubagentStart 4943 / 4027（Explore·Plan），都在 5000 自律线以内。装进插件缓存目录后，SessionStart 约为 4988。

**`origin/main..main`**：空，没有未推送的提交，不存在并行会话抢版本号的问题。

**diff 范围**：没有改 `worktree-flow`、`plain-talk-output-style`，没有新建 Codex manifest；扫过敏感值，无命中；没有写外部系统。`working-discipline` 的改动来自用户同一条指示，不算越界。仓根 `CLAUDE.md` 的「Agent skills」一节是之前 setup 时写入的，与本票无关，一直未提交。

**迁移内容**（`working-discipline` 3.32.0，理由见该插件 README「3.32.0」一节）：

- 新增 3.8 答后闭环：回收选定项等、决定同轮落盘；正文答复不是机械授权。
- 新增 3.9 不点链接也读得懂：承重概念、链接信息气味。
- 3.4 并入五类断言分层，子代理层也注入。
- wenyan 那边相应条目改成指针，判据只在一处。

**残余风险**：

- 05 号票结论是 no-go，wenyan 1.8.0 的篇章规则没有证明能改善关系回忆。
- `inference_not_fact` 在三组里都大量不过；3.4 只是把判据摆明，不能期望它单独解决。
- SessionStart 余量只剩十来个字符。

**未做**：没有提交，没有推送，没有发布。
