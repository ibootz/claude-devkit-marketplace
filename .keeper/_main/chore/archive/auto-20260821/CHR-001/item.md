---
id: CHR-001
summary: marketplace-cache-sync url源剪枝判据错误已修复补台账
status: done
kind: ledger
external_write: false
reported_at: '2026-08-21'
external_ref: null
---

## 用户原话

标题：marketplace-cache-sync 探测器的 url 源剪枝判据错误（已修）

问题：plugins/devkit-tool/skills/marketplace-cache-sync/scripts/probe-refresh.py 对 url 独立仓源插件判断「要不要刷」时，比的是 installed_plugins.json 里该记录的 gitCommitSha。而 `claude plugin update` 判定 `already at the latest version` 的真实条件（claude 2.1.237 二进制里的函数 yJT）是：该记录的 `version` 字段等于 CLI 从远端解析出的版本号，gitCommitSha 从不参与这个比较。版本号解析函数 S1e 的优先级依次是：远端仓根 .claude-plugin/plugin.json 的 version → marketplace.json 条目的 version → gitCommitSha 前 12 位 → 字面量 "unknown"。

后果（2026-08-20 实测）：--stage plugin 判出 73 条待刷，其中 54 条是 url 源，真跑一遍全部回执 `already at the latest version`，误判率 100%。每条 update 固定 25 秒，白付约 22.5 分钟。成因是同一个插件 id 的多条安装记录共享同一 version 却带不同 sha（cctx-dev-yxt-design-system 14 条记录里有 3 个不同 sha、version 全是 1.9.12），于是恒判「独立仓有新提交」。

同时发现两个附带缺陷：
1. 分桶时只读 src.get("ref")，完全忽略 src.get("sha")。对「钉了 sha、没有 ref」形态的源（mattpocock-skills）会去探该仓 HEAD，拿到的必然不是钉住的那个提交，是结构性必然误判。
2. 远端 manifest 取不到时一律当探测失败走保守侧。但「候选端点全部 404」是个确定答案（仓里压根没有 manifest），CLI 此时会回落到 gitCommitSha 前 12 位，探测器也应该跟着回落去比 sha。本机 cctx-dev-fecenter 与 cctx-dev-agent-cli 正是这一类，它们的记录 version 就等于 sha 前 12 位。

修法与结果：改为按 (url, revision) 去重后并发取远端仓根 .claude-plugin/plugin.json 的 version（一次 HTTP GET，不 clone；GitHub 走 raw.githubusercontent，自建 GitLab 走 api/v4 的 files/:path/raw）。本机 110 条 url 源记录去重成 15 个远端仓、并发耗时 0.8 秒。同一批数据从 73 条待刷降到 4 条，与真跑一遍的回执分布 100% 吻合。剩下那 4 条正是 version 为字面量 "unknown" 的记录（CLI 恒重装）。

落点：devkit-tool 6.17.0。提交 cf4fc50，合并提交 0140482，已推送到 origin/main。新增回归用例 plugins/devkit-tool/tests/probe-refresh-url-criterion.test.py（27 条断言、纯离线不发网络请求，覆盖判据两侧）。SKILL.md 与 references/verification-log.md 里「url 源比 sha」的错误结论已改写。

未追的边界（如实记下，不要写成已知）：
- yJT 里还有一条更早的分支——当有别的插件对本插件声明版本约束时走 tag 解析，判据变成 re.version===v.resolvedVersion && re.sha===v.gitCommitSha，回执文案带 satisfying。本机 221 条安装记录没有任何 resolvedVersion 字段，54 条回执也都不带 satisfying，所以这支当前不生效。只读了代码、未构造样本实测。
- archive / npm / command / git-subdir / github 这几种 source 形态的判据路径完全没追（本机零样本）。探测器会把它们丢进 unknown 桶无条件列入待刷，保守但不精确。
- 「那 15 条 updated 是市场仓内源」这条身份由 lastUpdated 时间窗反推（already 路径对配置零写入，只有 updated/refreshed 才写回配置），属强证据、非代码级证实。

## 处置方案

这是补台账记录，不是待修 bug——代码已修完并推送验证，无需派 fixer。登记即执行归档。

## 执行记录

- 复核确认：`cf4fc5039f3e1e86549dba7f24dc9c6568ededa0` 与合并提交
  `014048251614d61f93678b3b45b221dbe38ee6fc` 均在本地 `main` 历史上，且本地
  `main` 与 `origin/main` 指向同一 commit（已推送，见下方核验命令）。
- 新增回归用例路径确认存在：
  `plugins/devkit-tool/tests/probe-refresh-url-criterion.test.py`。
- 核验命令与结果：
  ```
  git log --oneline -3 -- plugins/devkit-tool/skills/marketplace-cache-sync/scripts/probe-refresh.py
  → cf4fc50 fix(devkit-tool): url 源剪枝判据改比远端 manifest 的 version
  git show --stat 0140482 | head -3
  → Merge: ec8dddf cf4fc50，9 files changed, 481 insertions(+), 43 deletions(-)
  git log main -1 --oneline / git log origin/main -1 --oneline
  → 两者一致，均为 0140482
  ```

## 结局

已核实修复内容与提交历史一致，落点 devkit-tool 6.17.0，已推送 origin/main。台账登记完毕，本条直接归档，不派 fixer。
