# demo-11：票 11 用例草稿流的演示摘要

**本目录的裁定是 AI 演示，不是用户审阅。**

演示里的勾选与回复码（第一页 `1A 2B 3A 5A 6B 7A`）是 AI 代给的，用来演示写回流程。
`runs/*-drafts/run.json` 里的 `pending.decisions`、各项 `decision`，以及「已通过」「已打回」的状态，都来自这次 AI 代给的回复码。
`evals-approved/` 只是演示目录名，里面的 4 个用例没有经过用户审阅，也没有进仓内任何插件的 `evals/`。

- `runs/`：两次草稿批次（`-drafts`）、一次基线判定（`-baseline`）、一次离线对照（`-compare`），每次只留 run.json 与 report.md，转录、trace、report.html 不入库。
- `drafts-after/`：写回后留在草稿区的草稿（含被打回的）。
- `baseline.json`、`clause-rehang.json`、`draft-skips.json`：演示结束时这三份状态文件的样子。
- 过程、花费与验收证据见票 11 的「验收证据」一节：[../issues/11-case-drafts-flow.md](../issues/11-case-drafts-flow.md)。
