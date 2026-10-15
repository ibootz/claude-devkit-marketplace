# 插件评测体系 · 地图

Label: wayfinder:map

## Destination

一份可以交给实施的 spec，描述一套**通用的 Claude Code 插件评测机制**：任给一个用户自己写的插件（一次评一个，即**被测插件**），都能用它评。`devkit-*` 是第一批使用者，不是机制的边界（2026-10-14 用户在 [评测范围](issues/06-scope.md) 中补充）。spec 要回答：

- 哪些部分直接用 Claude Code 内置的 `claude plugin eval`；
- 哪些要自建，自建到什么程度；
- 谁、在什么时候跑，每次花多少钱。

**2026-10-15 已到达**：spec 落在 [spec.md](spec.md)（2026-10-15 用户审过，Status: ready-for-agent）。

## Notes

- **领域**：本仓插件市场。被评对象按作用方式分五类：skill、agent、注入（纪律 / 文风）、拦截、副作用，见 [07](issues/07-questions-eval-must-answer.md) 与 `CONTEXT.md`。注入与拦截是本仓主体。
- **每个会话先调用的技能**：`mattpocock-skills:grilling` 与 `mattpocock-skills:domain-modeling`；research 票派子代理调用 `mattpocock-skills:research`。
- **三样东西别混**：
  - skill-creator 的评测——用户嫌「傻」的那套，只能评 skill；
  - `claude plugin eval`——Claude Code 官方 CLI，见 [01](issues/01-claude-plugin-eval-capabilities.md)；
  - `.scratch/` 下过去 AI 现写的 wenyan、注入压缩两套装置，见 [02](issues/02-prior-eval-practices.md)。
- **常设偏好**：
  - 实测优先于凭文档推断。
  - 「人读着累不累」这类易读性指标，终裁归用户本人，AI 评委只做初筛。
  - 原始运行数据与结论都要入库、可复核——历史上两次评测的结论最后只剩一句提交信息。例外：会话复盘的原始会话 jsonl 不入库也不另存，只入库抽取结果（见 [评测范围](issues/06-scope.md)）。离线对照的全量 trace 只在本机留 90 天，入库的是结构化结果与用户看过的样本 trace（见 [评测产物与状态落在哪、什么格式](issues/13-result-layout.md)）。
  - 用例与结果放在被测插件自己所在的仓；本仓公开，radnove 等内网插件的评测产物不进本仓。
  - 给用户的说明与提问：句号后换行、选项之间空一行、关键处加粗。
- **工单格式**：见 [issue-tracker.md](../../docs/agents/issue-tracker.md) 的「Wayfinding operations」节（地图、工单、阻塞与认领的本地写法）。没有 `Status:` 行或 `Status: open` 的票视为未认领。

## Decisions so far

- [claude plugin eval 能评什么](issues/01-claude-plugin-eval-capabilities.md) — 官方 CLI，沙箱干净、有确定性判分与有无插件对照；hook 注入、output style、多插件干扰、真实会话分析都没有一等支持。
- [仓内历史评测实践盘点](issues/02-prior-eval-practices.md) — 手工搭过三套，每次重写装置、手工做旧版快照和关插件配置，结论不入库。
- [先验证还是先设计](issues/03-verify-before-design.md) — 先花一小步实测 `claude plugin eval` 能撑到哪，再定自建多少。
- [已有散装评测怎么处理](issues/04-existing-eval-artifacts.md) — wenyan 装置作原型参考；ask-format-eval 不归本图。
- [实测 claude plugin eval 能否评出 hook 注入的效果](issues/05-probe-plugin-eval-on-hook-injection.md) — 部分能：SessionStart 注入与工具入参类纪律评得出；UserPromptSubmit 注入进不了 trace，`AskUserQuestion` 在 headless 里不存在；多插件可同载；3 例 × 3 次 × 双臂约 $2.5。
- [评测范围](issues/06-scope.md) — 通用机制，一次评一个被测插件；离线对照与会话复盘两条都做；用例与结果跟被测插件所在仓走；会话原文不入库；干扰靠会话复盘发现，离线对照只留手动加环境插件的口子。
- [会话 jsonl 里能取到哪些评测信号](issues/10-session-jsonl-signals.md) — skill 调用、子代理与 compact 关联、`Agent` 缺 `model` 与 `cd-guard` 这类入参或拦截违规都能机械检出；hook 归因只有 deny 事件稳定（路径带插件名与版本），注入类要靠脚本指纹加内容标签；插件历史版本还原不了；按 `uuid` 去重。
- [评测要回答哪些问题](issues/07-questions-eval-must-answer.md) — 按作用方式分五类（skill、agent、注入〔纪律 / 文风〕、拦截、副作用），每类有必答 / 可选 / 不答清单；注入逐条款、含 compact 后；基线新插件比不装、改版比上一版；干扰只答有无迹象；人工要在判分、用例、结论、选题四处介入。
- [判分分工与人工介入点](issues/11-judging-and-human-checkpoints.md) — 规则能判的不交 AI；AI 评委判两遍、用金标样本校准，分歧样本全给用户看并随机抽 3 条；用例与复盘选题由用户勾选，报告落盘标「待审」、未审不得据此改插件；四环节集中在一个本地 HTML 待审页，每次 ≤ 10 分钟 ≤ 10 项。
- [谁跑、何时跑、花多少](issues/08-cadence-and-budget.md) — 用户采纳 Jev 的判断：对照手动触发（相关升版提示、Claude Code 升级或换模型时也跑）；复盘每周、本机定时任务（已被 09 覆盖：改手动触发、超 7 天提醒）；要做发版闸门；用户每月 ≤ 1 小时（单次 $10、每月 $50 与「评委先便宜档」已于 10-15 撤销：订阅不设美元上限，评委默认最贵档如 Fable）。
- [发版闸门覆盖哪些版本](issues/12-release-gate-coverage.md) — 用户采纳 Jev：major 与用户声明的版本须有已审报告；其余版本须过规则判分子集（子集取全部能用规则判分的用例，原 $50 约束 10-15 撤销）；通用检查命令、本仓不接 hook 手动跑；`eval-skip:` 标记绕过，由闸门检查命令收口（原为每周复盘，09 改）。
- [缺口里哪些自建、以什么形态](issues/09-build-vs-extend.md) — 不建独立 harness，eval 是唯一离线运行器；臂编排、AI 评委、注入到达核验、静态 token、记账、待审页由外围脚本做；compact 后、`AskUserQuestion` 类、hook 时延、版本变化归会话复盘；复盘手动触发、超 7 天提醒；交付为新插件 `devkit-plugin-eval`（Python 命令行 + 两个 skill）。
- [「上一版」臂的插件目录怎么产出](issues/14-previous-version-arm.md) — 上一版取 git 历史里与当前版本号不同的最近一个版本的引入提交（`--base` 可覆盖），`git archive` 解到臂组装目录、用例一律取当前版；环境插件收 `插件名@市场` 或路径；取不到上一版就只跑不装与当前版并在报告写明；跨改名快照原样、标注不可比用例。
- [跑评测前检查哪些前置条件](issues/15-preflight-checks.md) — 硬项（hook 冒烟：临时空 HOME 真执行每条 command、eval 参数特性探测、登录、`plugin validate`、已登记（余额项 10-15 撤销））失败即中止不可绕过，软项（dirty 工作区、版本或模型变化、保留期短于复盘间隔）照跑并标注；dirty 结果不计入闸门；登记即信任、自动加 `--trust-plugin`；平台差异靠冒烟吸收；各动作自动查，另有 `check` 子命令。
- [现有确定性单测是否并入同一入口](issues/16-existing-deterministic-tests.md) — 闸门检查命令跑被测插件「单测声明」里的命令，未声明只提示不拦；本仓单测接 pre-commit、按暂存路径只跑被改插件，与评测闸门不接 hook 不冲突（单测零花费）。
- [评测产物与状态落在哪、什么格式](issues/13-result-layout.md) — 通过的用例放 `<plugin>/evals/`（eval 原生、随插件分发），草稿与运行结果、复盘抽取、金标放仓内插件目录外的 `plugin-evals/<plugin>/`；每次运行一个目录，`run.json` 是唯一真源（含审阅状态与插件内容指纹）；全量 trace 本机留 90 天、只入库用户看过的样本；用户级 `~/.claude/plugins/data/` 只放登记清单与 trace 缓存（账本 10-15 撤销）；闸门认同版本且指纹一致的已审对照或规则子集，声明与跳过用提交信息 trailer。
- [单测声明放哪、长什么样](issues/18-unit-test-declaration.md) — 放在被测插件根下的 `unit-tests.json`、随插件分发；每条只有 `run`（argv 数组、不经 shell、工作目录固定为插件根）、`timeout_sec`（缺省 120）、`platforms` 三个字段；只收离线确定性单测；解释器找不到时闸门判失败、pre-commit 跳过并警告；pre-commit 按 `plugins/<name>/**` 选插件、未声明静默、声明不合法即拦。
- [离线对照的用例从哪来、怎么构造](issues/17-case-sourcing.md) — 冷启动 AI 按条款清单起草、复盘候选逐步替换，一律先进草稿待勾选；复盘候选只存指针、转草稿时现读改写去内网内容；compact 后用合成 `history_file` 回放，前提交 [实测 history_file 回放](issues/19-probe-history-file-replay.md)；基线已满足的只作回归守护、量差另写诱导用例；每条款 1 例（诱导另 2），每次全量跑所有已通过用例（原「只跑改动触及 + 轮换」10-15 撤销），每例每臂 3 次；首批草稿每批 ≤ 10 分批审。
- [实测 history_file 回放能否测出「长历史之后」的遵守差](issues/19-probe-history-file-replay.md) — 能：`history_file` 即会话转录 jsonl、可含 compact 摘要，回放后两层注入照常到达，约 20k token 历史后派发带 `model` 的 Δ 仍为 +0.67；回放用例须显式 `--ablation with-without`，子会话转录写进用例目录需清理，合成历史不放注入文本。
- [条款清单的生命周期](issues/20-clause-list-lifecycle.md) — 清单记抽取时的注入文本指纹（真实 HOME、空 cwd 执行注入 hook 取输出），跑对照第一步发现变了就 AI 增量重抽、变更进待审页算 1 项、未确认照跑并标注；id 绑判定标准、永不复用，退役条款的用例退回草稿附改挂建议、金标停用不删；闸门只出一条「建议跑对照（会先更新条款清单）」。

## Not yet specified

（暂无。）

## Out of scope

- **ask-format-eval**（`.scratch/ask-format-eval/`）——另一会话正在迭代，见 [已有散装评测怎么处理](issues/04-existing-eval-artifacts.md)。
- **hook 拦截逻辑本身的正确性**——已有 `guard-verify.js` 等确定性单测覆盖，评测体系不重做；它们经单测声明接入闸门检查命令与本仓 pre-commit，见 [现有确定性单测是否并入同一入口](issues/16-existing-deterministic-tests.md)。
- **回放与真实 compact 的等价性**（2026-10-15 用户选 a 划出）——要等机制跑起来、会话复盘产出「compact 前后违规率」才能验证，写 spec 前答不了；作为**实施后验证项**并以残余风险写进 spec。原文：19 所测条款在长历史下没退化，回放能否复现真实会话里 compact 后的退化仍未验证。要等会话复盘产出「compact 前后违规率」，挑一条真实会话里 compact 后变差的条款再跑回放；真实有退化而回放 with 臂仍满分，才触发 [缺口里哪些自建、以什么形态](issues/09-build-vs-extend.md) 的重开条件。来自 [19](issues/19-probe-history-file-replay.md)。
