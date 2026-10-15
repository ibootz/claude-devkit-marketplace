# 仓内历史评测实践盘点

盘点时间：2026-10-13。只读，追到各装置的入口文件、规则文件、评分汇总和报告为止；未逐条读 judge 原始 JSON、replies 原文与 task-keeper 的 24 个 hook 用例。

## 一、working-discipline 注入压缩 A/B（2026-09-30，装置已删）

- **对象**：working-discipline 3.33.0 → 3.34.0，三层注入去重压缩并新增「先上图」。
- **方法**：old 臂加载 3.33.0 快照、new 臂加载工作树，两臂都用 `--settings` 关掉已装同名插件、`--plugin-dir` 加载各自目录；判分 = 脚本读 `transcript.jsonl` 做机械断言 + LLM 评分员按 rubric 判语义。
- **硬坑**：`claude -p` 的 cwd 必须放仓库外，否则仓根 `CLAUDE.md` 与 `.claude/rules` 会被自动加载，两臂都叠上无关指令。
- **规模**：6 场景 × 2 臂 × 2 次，fixture 是自造的 `mini-shop`。
- **结论落点**：只在提交 a1fef3c 的信息里：「通过率 93% 对 74%，压缩相关场景持平」。装置 46 个文件在 98e90b1 删除，`runs/` 原始数据从未入库，分母无从核对。
- **手工环节**：手写 `PREMISE.md` 前提并手跑探针；手工拷整份旧版插件做快照；手写 `rewrite.py` 替换注入常量。

## 二、wenyan 篇章连贯三组对照（2026-09-23，仍在仓内）

- **装置**：[eval/README.md](../../wenyan-discourse-coherence/eval/README.md)，三组 baseline（1.7.0 快照）/ no-style（风格插件全关）/ new（工作区快照）。
- **注入生效证明**：在 stream-json 里对每个 SessionStart / UserPromptSubmit 的 `output` 字段做子串匹配，每轮留痕在 raw 记录的 `injectionProof`。
- **判分**：被评模型 sonnet-4-5，评委 opus-5-5，每条评两遍；八项回忆指标 1–5 分 + 五项硬负例 pass/fail/na；通过线事先登记在 `pass-bar.md`。
- **规模与成本**：10 场景，核心 6 个每组 3 次；baseline + no-style 两组 60 轮约 **38.77 美元**。
- **结论**：[report.md](../../wenyan-discourse-coherence/eval/report.md) 给 no-go（4/6 核心场景达标，要求 5/6）。
- **痛点**：
  - 人工盲评没做（[06 号票](../../wenyan-discourse-coherence/issues/06-human-blind-review.md) wontfix），盲评材料备好无人读。
  - 样本小，组内标准差最大 0.60，多数差值落在噪声内。
  - 评委两遍逐项平均绝对差 0.20，硬负例两遍判定不一致 29 处；单一评委、无人工校准。
  - 长对话场景没真正触发 auto-compact（阈值约 32 万 token，成本过高）。
  - 子代理回执里「baseline 三次都直接执行删除」与原文不符（实为两次），靠人逐条读原文才发现。

## 三、ask-format-eval（未入库，另一会话在迭代）

读者子代理答题 + 盲评，3 案例 × 改前改后 × 2 读者。硬指标全部持平无区分度，唯一差异来自读者自评费力分。该会话定下：**易读性结论必须由用户本人看过再下，不靠 AI 读者打分。**

## 四、skill-creator 格式的 evals.json

全仓仅 [zh-disambiguate/evals/evals.json](../../../plugins/devkit-discipline/skills/zh-disambiguate/evals/evals.json) 一份，3 条用例，无任何运行记录。

## 五、现存确定性测试（均需手动运行，无统一入口）

| 插件 | 文件 |
|---|---|
| devkit-discipline | `test/guard-verify.js`、`test/probe-throttle-verify.js` |
| devkit-cd-blocker | `tests/cd-guard.test.js` |
| devkit-worktree-flow | `tests/main-branch-guard.test.js`、`tests/round-approval.test.js` |
| devkit-clickable-paths | `hooks/tests/clickable-paths.test.js` |
| devkit-readable-citations | `hooks/tests/readable-citations.test.js` |
| devkit-style-wenyan | `hooks/tests/wenyan-output-style.test.js`（含 golden 快照） |
| devkit-task-keeper | `hooks/tests/run-tests.sh`（24 个用例） |
| devkit-tool | `tests/probe-refresh-url-criterion.test.py`、`hooks/tests/*` |

唯一自动触发点是 `.githooks/pre-commit`，只跑 `scripts/check-versions.js`。

## 六、三次评测共有的手工环节

1. 每次手工做旧版快照。
2. 每次手写 `--settings` 关掉本机已装的同名插件。
3. 评分口径一案一议，结论落点不固定、原始数据不入库。
