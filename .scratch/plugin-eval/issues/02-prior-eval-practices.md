# 02: 仓内历史评测实践盘点

Type: research
Status: resolved
Blocked by: 无

## Question

本仓过去做过哪些插件效果评测？各自评什么、怎么评、判分方式、规模、结论落在哪、哪里费劲？

## Answer

详见 [research/prior-eval-practices.md](../research/prior-eval-practices.md)。

要点：

- 手工搭过三套：working-discipline 注入压缩 A/B（装置已删）、wenyan 三组对照（仍在仓内）、ask-format-eval（另一会话在迭代）。
- 共有手工环节：每次手工做旧版快照；每次手写 `--settings` 关掉已装同名插件；评分口径一案一议，原始数据不入库。
- 已验证可复用的做法：`claude -p` 的 cwd 放仓库外；用 stream-json 里 hook 的 `output` 字段做注入生效证明。
- 成本参照：wenyan 两组 60 轮约 38.77 美元。
- hook 拦截逻辑已有十来套确定性单测，但无统一入口、无自动触发。

## Comments
