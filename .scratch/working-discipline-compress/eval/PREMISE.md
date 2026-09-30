# 评测装置前提（派发给子代理的硬约束，动手前必读，中途有疑问重新 Read 本文件）

## 目标

为 working-discipline 插件的「注入文本压缩 + 新增 mermaid 图示规则」做 A/B 行为评测。
两组（arm）唯一差异是加载的 working-discipline 插件目录：

| arm | 插件目录 |
|---|---|
| `old` | `/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/working-discipline-compress/snapshot/working-discipline`（3.33.0 快照，只读，不许改） |
| `new` | `/Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/working-discipline`（主会话正在改，评测装置不许改它） |

## 已核实的事实（直接当前提用）

- `claude -p` 支持 `--plugin-dir <path>`（从目录加载插件）、`--settings <file-or-json>`、
  `--output-format stream-json --verbose`、`--append-system-prompt`。已由 `claude --help` 核实。
- `--bare` 不能用：它只认 `ANTHROPIC_API_KEY`，本机走 OAuth。
- 用户 user-scope 已安装并启用 `working-discipline@claude-devkit-marketplace`（3.33.0）。
  两组都必须用 `--settings` 把它显式关掉（`"enabledPlugins": {"working-discipline@claude-devkit-marketplace": false}`），
  再用 `--plugin-dir` 加载各自的目录。否则两组都会叠加已安装版本，评测失去区分度。
- 其余已装插件（wenyan-output-style 文言风格、radnove-core、clickable-paths 等）两组都保持启用，不动——这是用户真实环境。
- 可参考的旧装置：`/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/wenyan-discourse-coherence/eval/harness.mjs`
  （413 行，Node，已在本机跑通过 `claude -p` 批量调用）。优先复用它的调用、并发、落盘、失败重试写法，不要从零写。

## 待验证（你自己先验一遍再用）

- 同时 `--settings` 关掉已装版 + `--plugin-dir` 加载同名插件时，实际生效的是哪一份：
  跑一次最小调用，prompt 让模型原样复述它上下文里「# AI 工作纪律」段落第一行和「3.7」那一条的标题，
  两组各跑一次，确认 old 组看到的是 `3.7 裸值带含义`（3.33.0 快照内容），new 组看到的是 new 目录当前内容。
  这是装置有效性的证据，写进回执。new 目录当前内容可能与 old 相同（主会话还没改完），只要机制对即可。

## 落点

- 一切产物放 `/Users/zhangq/Workspace/mine/claude-devkit-marketplace/.scratch/working-discipline-compress/eval/` 下。
- 不许写 `plugins/**`、不许写 `~/.claude/`、不许 git commit。
- 每次 `claude -p` 的 cwd 用 fixture 项目目录的**副本**（每个 run 一份独立副本，放 `eval/runs/<arm>/<eval-name>/run-<n>/project/`），
  因为有的场景会让模型写文件，共用一份会互相污染。

## 脚本约束

- 用 Node（.mjs），macOS / Windows 双通，不写 shell 脚本。
- 并发上限 4 个 `claude -p` 同时跑。单次超时 600 秒。失败（非 0 退出 / 超时）重试 1 次，仍失败则记录并继续。
- `claude -p` 的权限：加 `--permission-mode bypassPermissions` 或等价参数，让模型能 Read/Write/Agent 而不卡审批；
  若该参数不可用，改用 `--allowedTools` 列出 Read,Grep,Glob,Bash,Write,Edit,Agent。
- 每个 run 落盘：`transcript.jsonl`（stream-json 原样）、`final.md`（最终 assistant 文本）、`meta.json`（arm、eval、run 序号、耗时、退出码）。
- 装置本身要能单独跑一个 arm / 一个 eval（命令行参数），便于主会话在 new 版改完后再跑 new 组。
</content>
</invoke>
