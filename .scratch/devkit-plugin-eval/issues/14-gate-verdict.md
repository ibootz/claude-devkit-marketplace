# 14 — 闸门判定

Status: ready-for-agent

**What to build:**

`gate` 子命令（入参为插件目录）判当前版本能否发布：

- **插件内容指纹**：算整个插件目录、排除 `evals/`。
- **判据**：扫 `runs/*/run.json`；过闸 = 存在同版本、指纹一致、不是 dirty / 不完整的记录，且为二者之一：已审的离线对照，或通过的规则子集。major 升版与提交信息 trailer 写了 `eval-required:` 的版本只认前者。指纹不一致视为未过闸。
- **单测声明**：Python 实现读 `unit-tests.json` 逐条跑，任一失败判失败；未声明只提示「未声明单测」；声明不合法判失败；解释器解析不到判失败。用 02 的共用样例集与 JS 实现对齐。
- **跳过与漏检**：`eval-skip:` 的版本放行并列出全部跳过记录；闸门内版本推到 main 时既无已审报告、也无 `eval-skip:` 的，列为漏检。
- 本仓不接 git hook，用户发版前手动跑。

**Blocked by:** 02, 03


- [ ] 对一个有已审对照、指纹一致的版本，`gate` 判通过
- [ ] 审后改一个文件（`evals/` 外）不升版，`gate` 判未过闸；只补 `evals/` 用例不影响判定
- [ ] dirty 或不完整的 `run.json` 不被采信
- [ ] 提交信息带 `eval-skip:` 时放行，并在输出里列出全部跳过版本
- [ ] 构造一个闸门内版本无报告、无跳过标记地出现在 main，输出列为漏检
- [ ] 02 的共用声明样例在本票 Python 实现下判定结果与 JS 实现一致
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的「2.8 发版闸门（gate）」「2.7 确定性单测」；[12](../../plugin-eval/issues/12-release-gate-coverage.md)、[13](../../plugin-eval/issues/13-result-layout.md) 第 7 条、[18](../../plugin-eval/issues/18-unit-test-declaration.md)

## Comments

- 2026-10-15，票 03 审查遗留（主会话定、jev 同意）：run.json 的 `dirty` 现按插件目录 `git status` 计，含 `evals/`，也含 compare 自己往插件目录写的那行 `.gitignore`（仓根插件首次对照必为 dirty）。本票实现闸门时统一 dirty 口径：dirty 排除 `evals/`（与插件内容指纹的排除范围一致），并排除 compare 自写的 `.gitignore` 行。票 03 不改。
- 2026-10-15，票 04 集成口径②（主会话定）：插件不在 git 仓、取不到 git 状态时 run.json 记 `dirty=null`。闸门判据必须写成 `dirty is False`；写成 `not dirty` 会把 null 放行。上一版臂的 `head_sha` / `dirty` 恒为 null（快照来自 git 历史，没有 dirty 一说），不能拿它套这条判据。
- 2026-10-15，集成审查 N4（未修，待本票定）：续跑过的运行，dirty 有两个来源。run.json 的 `preflight.dirty` 取自最后一次续跑时，`arms.current.dirty` 沿用首跑。两者可能不一致，闸门判据须写明读哪一个；也可以要求两者都是 `False`。见票 07 Comments「集成审查修订」一节。
- 2026-10-15，用户拍板 05-1（原话「按照推荐来」）：新插件首评或从未升过版本号时，上一版臂仍标退化（`previous_arm.degraded=true`、`reason_kind=no-different-version`），不新设状态。闸门按 `reason_kind` 区别对待：`no-different-version` 的退化报告是「按基线规则比不装」，与 `not-git` / `no-history` / `snapshot-failed` 这类取不到上一版的退化分开处理，具体放行规则本票定。
- 2026-10-15，用户拍板 06-3.2：注入未到达不改 `complete`。闸门读 run.json 的 `injection_check.ok`，为 false 时拒绝把这次运行作依据。
- 2026-10-15，用户拍板 07-1：续跑时 Claude Code 版本不同照常合并。闸门须检查 run.json 顶层的 `claude_code_versions`：多于一个即版本混用（续跑时版本变了，或各臂不同），按混用处理。主力模型不同已在运行侧判为不完整（`complete=false`），闸门照「不完整不作依据」排除即可。
