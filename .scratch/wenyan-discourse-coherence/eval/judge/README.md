# 自动评分（05 号票）

本目录是 05 号票的盲评 judge。**本文件在看到任何评分结果之前写成**，其中「判定口径」一节是事先登记的，不能看完数据再改。

## 装置

| 文件 | 作用 |
|---|---|
| `system-prompt.md` | judge 的系统提示：读者设定、八项回忆指标（1–5 分或 null）、五项硬负例（pass / fail / na） |
| `schema.json` | judge 输出的 JSON Schema，通过 `--json-schema` 强制结构化输出 |
| `judge.settings.json` | `disableAllHooks: true`，并停用三个风格插件 |
| `score.mjs` | 遍历 `../raw/<arm>/<scenario>/run-<n>.json`，构造不含组别的评分条目并调用 judge |
| `unblind-map.json` | 条目 id 到组别的映射。judge 读不到这个文件 |
| `out/<id>.p<k>.json` | 每次评分的原始记录：输入全文、judge 模型、CLI 版本、提示词哈希、结构化输出、费用 |
| `aggregate.mjs` | 汇总得分，写出 `../report.md` |

- **judge 模型**：`claude-opus-5-5`，经 `claude -p` 调用，CLI 版本记在每条 `out/*.json` 里。被评的三组都是 `claude-sonnet-4-5`，judge 与被评模型不同。
- **上下文隔离**：judge 会话用 `--setting-sources local` 加 `judge.settings.json` 启动，不带工具。2026-09-23 实测，judge 的上下文里只有内置的 Environment 与 userEmail 两段，没有用户的 CLAUDE.md、rules、插件或 hook 注入。
- **盲化**：条目只包含场景标题与完整的对话记录。本机运行目录的路径会被替换成 `<工作目录>`，因为那段路径里含有组名。
- **两遍评分**：每个条目独立评两遍（`p1` / `p2`），用来观察 judge 自身的波动。

## 判定口径（事先登记）

spec 测试决策 6c 的原文见 [pass-bar.md](../pass-bar.md)。原文里有几处没有给出数值，下面是本票采用的操作化定义：

1. **单次运行的 rubric 得分**：八项指标里非 null 项的平均分。先把两遍评分逐项取平均，再求这个平均。
2. **场景得分**：该组在该场景下所有运行的 rubric 得分取平均。组内方差按各次运行的得分计算。
3. **「至少不低于 baseline」**：new 组场景得分 ≥ baseline 组场景得分，按字面比较，不设容差。
4. **「明显落败」**：new 组场景得分比 baseline 组低 0.5 分或以上（1–5 分制）。
5. **「每次运行都通过全部硬负例」**：new 组 22 次运行里，每一项判为适用的硬负例，两遍评分都必须是 pass。只要任何一遍判 fail，就算这一次运行不通过。na 不计入。
6. **重开条件**：在六个核心场景上合并计算，no-style 组的 relation_recall 平均分 ≥ new 组时，按 6c 原文记为触发。各场景的逐项数值另行列出，供参考。
7. **长度**：记录各组回复的平均字符数，只作为观察项，不参与判定。

**六个核心场景**以各场景 `meta.json` 里 `core: true` 为准：01–06。
