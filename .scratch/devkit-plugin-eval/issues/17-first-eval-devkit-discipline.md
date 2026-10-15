# 17 — 首次真评 devkit-discipline（验收）

Status: ready-for-agent

**What to build:**

以 devkit-discipline 为第一个被测插件，按 skill 引导完整走一遍：登记 → 抽条款清单并确认 → 起草与审第一批草稿 → 跑改版对照（上一版、当前版，必要时加不装）→ 处理待审（分歧样本、抽检、报告）→ 会话复盘 → 闸门检查。用户在每个待审页的实际耗时记下来，对照每页 ≤ 10 分钟、每月 ≤ 1 小时。

跑完把发现写成本目录的验收记录：哪些环节顺、哪些卡、spec 里哪些「实施待定」与「残余风险」被这次运行回答了；需要改的开新票。「回放与真实 compact 的等价性」是实施后验证项，不在本票验收内，但本次复盘若已产出 compact 前后违规率，记下数据供后续验证。

**Blocked by:** 13, 15, 16


- [ ] devkit-discipline 有一份已审的离线对照报告，`gate` 对当前版本判过闸
- [ ] 每个待审页的用户实际耗时已记录，超出上限的环节有说明
- [ ] 会话复盘结果已写进本仓 `plugin-evals/devkit-discipline/reviews/`
- [ ] 验收记录落盘，列出被回答的实施待定项与新开的票
- [ ] 入库内容经全文检索确认不含账号邮箱等个人信息与会话原文

**参考：** [spec](../../plugin-eval/spec.md) 的spec 全文，尤其「残余风险与实施后验证项」；[map.md](../../plugin-eval/map.md)

## Comments
