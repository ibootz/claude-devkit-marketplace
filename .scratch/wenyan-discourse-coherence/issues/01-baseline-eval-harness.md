# 01: 搭建评测装置并采集基线

Status: done
Type: task
Blocked by: 无

## What to build

在任何规则改动落地之前，搭好三组对照的行为评测装置，并跑完两组基线：

- **baseline 组**：wenyan 1.7.0，取自 git commit `303e719` 的快照（用 `git worktree` 或 `git archive` 导出到仓库外的临时目录），通过 `--plugin-dir` 加载。
- **no-style 组**：wenyan 和其他所有 output-style 插件（`plain-talk-output-style`、`adhd-output-style`）全部停用。
- **new 组**：只搭好装置，本票不跑；由 05 号票运行。

每组都作为独立的 headless `claude -p` 主会话运行，插件启停通过 `--plugin-dir` / `--settings` 控制。**不得用子代理作为评测载体**：wenyan 只通过主会话的 SessionStart 与 UserPromptSubmit 注入，子代理两者都收不到，两组会在毫无报错的情况下都不带插件运行。

交付物：

- 场景集：spec 测试决策第 7 条列出的全部十个场景，每个场景给出 prompt 与所需的固定文件。其中六个核心场景：跨文件根因、陌生组件介绍、方案比较、正文决策包、答后闭环、不可逆确认。
- 评分标准（rubric）：spec 测试决策第 8 条列出的各项回忆指标，外加第 13 条的硬负例。
- 通过线：原样照抄 spec 测试决策 6c。
- 一个脚本（Python 或 JS，按全局 macOS/Windows 双通约定），输入组名与场景，输出原始记录。
- baseline 组与 no-style 组的原始输出：六个核心场景 × 每组 3 次运行，另外四个场景每组各 1 次。

## Scope boundaries

本票只做测量，不改 `plugins/**` 下的任何文件。原始输出存放在 `.scratch/wenyan-discourse-coherence/eval/` 下。不发布到外部 tracker，不使用浏览器，不做部署。

## Acceptance criteria

- [ ] 每组在采集任何输出之前，都已证明注入状态符合预期：baseline 组能看到 wenyan 的 SessionStart 头部文字，no-style 组看不到任何风格注入。证明方法和证据写入评测 README。
- [ ] 运行全部走 headless 主会话；脚本里没有任何通过子代理生成评测输出的路径。
- [ ] 三组之间只有启用的插件集合不同，模型、入口、prompt、固定文件、会话隔离方式和 rubric 完全一致。
- [ ] 十个场景的 prompt 与固定文件、rubric、通过线全部落盘。
- [ ] baseline 与 no-style 两组的原始输出落盘，每条记录带上模型 ID 与版本、运行序号、时间戳。
- [ ] 脚本跑两次得到的记录结构一致；new 组在 04 号票完成后能用同一条命令跑起来。

## Comments

### 2026-09-23 · 已完成

- 装置在 `eval/`：`harness.mjs`、`rubric.md`、`pass-bar.md`、`settings/disable-styles.settings.json`、10 个场景、共用夹具 `fixtures/mini-project/`。
- baseline（1.7.0 = `303e719` 快照）与 no-style 两组各 22 次运行、30 轮，零失败、零重试。模型 `claude-sonnet-4-5`，CLI 2.1.280，两组合计约 38.77 美元。
- 注入证明：每轮从 stream-json 的 hook 事件里数风格 header。baseline 30 轮每轮 wenyan 各 1 次，no-style 30 轮三个风格插件全为 0。
- 已知局限：08 场景是 6 轮 `--resume`，但没有真正撑到自动压缩的阈值；Windows 上没有验证过。
- 父代理复核时发现一处与原文不符：回执说 06 场景 baseline「三次都直接执行删除」，实际是两次（run-3 先停下来问了）。已在 05 号票的报告里更正。
