# demo-integ-C：C 批（13 / 16）集成后的真实验证摘要

**本目录记录的裁定都是 AI 代给的演示，不是用户审阅。** 具体是：

- 复盘待审页的三次回复码 `6A`、`6A 8A`、`1A 8A`：AI 为演示挑候选选「转草稿」。
- 草稿待审页的 `1A`：AI 代选「通过」，用来验证通过后 `.gitignore` 不随搬。

所有命令都在临时克隆和临时数据目录里跑。命令行用本 worktree 的 `plugins/devkit-plugin-eval/scripts/plugin_eval.py`（0.5.0）。跑完后临时克隆、数据目录、eval 沙箱都已删除。真实会话改写出来的东西不入库。

环境：Claude Code 2.1.300。PATH 去掉了 `~/.asdf/shims`，直接命中真实的 node。

## 1. 触发测试补例（票 16）

- 新增两个用例，放在 [../demo-16/trigger-cases/](../demo-16/trigger-cases/)：
  - `r5-session-review`：扫本机会话记录，看某插件实际触发、拦截与 hook 报错的情况。属于「跑会话复盘」类，提问里没出现「复盘」二字。
  - `r6-draft-cases`：条款清单已确认、还没有用例，让 AI 起草用例草稿。属于「起草用例」类。
- 跑法同 demo-16 第二轮：把插件拷到临时目录，`evals/` 换成这两例，跑 `claude plugin eval <临时插件目录> --ablation none --runs 3 -j 4 --no-publish --trust-plugin --keep-temp --json <out.json>`，`max_turns: 10`。
- 结果：6 次 run 全部有效，`run-eval-used` 与 `handle-pending-unused` 都通过。从 trace 核对，每次实际加载的都是 `devkit-plugin-eval:run-eval`。
- 花费（eval 报的标价估算）：$1.2906，耗时 88 秒。

## 2. `drafts from-review` 隐私防护（票 13，C 批定稿 1、2）

步骤：

1. 克隆本 worktree，放入 demo-10 的条款清单，登记 devkit-discipline。
2. `review --days 3`：devkit-discipline 有复盘候选 18 个。
3. 出复盘待审页，AI 代选候选转草稿。
4. 环境变量与 `private-terms.txt` 都不设，跑 `drafts from-review devkit-discipline`。

逐项确认：

- **私有词为空时有提示**：每次运行 stderr 都有一行 `[from-review] ！！未配置私有词，只能靠会话推断与形态检测（…）`；摘要也有一行 `！！未配置私有词，只能靠会话推断与形态检测。可设环境变量 PLUGIN_EVAL_PRIVATE_TERMS（逗号分隔），或在数据目录下建 …/private-terms.txt（每行一个）`。
- **草稿目录带 `.gitignore`**：写成的草稿 `review-agent-name-model-prefix-after-compact` 目录下有 `.gitignore`，内容是 2 字节的 `*\n`。摘要打出 `！！这些草稿由本机真实会话改写，通过前逐字审隐私。草稿目录里有内容为 * 的 .gitignore…`。
- **git 看不到草稿**：临时克隆里跑 `git status --porcelain --untracked-files=all`，草稿目录下的文件一个都没列出。列出的只有复盘结果、条款清单和 drafts 运行目录的 `run.json` / `report.md`；这两个文件只记草稿目录名，不含草稿正文。
- **待审页有隐私行**：草稿页该项的事实栏有「隐私：由本机真实会话改写，通过前逐字审隐私（prompt、历史、grader、文件桩都要看）」。
- **通过后标记不随搬**：AI 代选 `1A` 通过后，`plugins/devkit-discipline/evals/<草稿名>/` 里没有 `.gitignore` 和 `draft.json`。写回把草稿目录里的这两个文件列为删除；剩下的空目录在下次生成草稿页时清掉，这是原有行为。
- **隐私检索**：对写成的草稿目录检索派发简报规定的词，另加家目录用户名、仓名、worktree 分支前缀和邮箱形态，结果 0 命中。检索用 `/usr/bin/grep`，先用确定存在的 `schema_version` 验证过能搜到 2 个文件。
  - 注意：本机 shell 里的 `grep` 是个函数，会遵守 `.gitignore`。草稿目录的 `*` 会让它静默零命中，复核这类目录要用 `/usr/bin/grep`。

结果分布：AI 共调用 13 次，覆盖 5 个候选；被拒的候选下次运行会重试，所以有的候选被调用了不止一次。

| 结果 | 次数 | 说明 |
|---|---|---|
| 写成草稿 | 1 | `c-a3c987f89a77` |
| AI 判为写不成（`needs-write-tools`） | 2 | 两个拦截类候选 |
| 结构不合格（`invalid spec`） | 2 | 同一候选，两次都不合格。conversion 只记问题个数，看不到是哪条 |
| 隐私自检拒写 | 8 | 每次都有逐字重合，其中 2 次另带 path 命中 |

逐字重合的来源按片段类型排查过，排查脚本只打印片段类型、命中窗口数和少量 24 字窗口：

- 工具输出里的 eval 用例 frontmatter（如 `timeout_seconds` / `allowed_tools` 一行）被照抄：B1 修复后按设计拒写。
- 合成 compact 摘要照着 Claude Code 摘要的固定开头写（`This session is being continued from a previous conversation…`）：误拒。
- hook 报错里的被测插件脚本路径（`hooks/guards/bash-guard.js`）：误拒。

因此集成时追加了一项暂定口径（见票 13「C 批集成」一节）：重合窗口出现在 Claude Code 固定文案或被测插件自己的文本文件里时，不算逐字重合。补了单测 `test_public_text_exempt_from_overlap`。这项改动之后没有再真跑 from-review，避免再次读取真实会话。

花费（标价估算）：13 次 AI 调用合计 $3.5710。

## 3. compare 收尾的下一步命令（票 16 CLI 缺口 1）

- 用例：克隆里只把 `compact-dispatch-with-model` 放进 `plugins/devkit-discipline/evals/`（去掉 `draft.json`），跑 `compare devkit-discipline --runs 1`。
- run_id：`20261015T181548Z-4.1.0-compare`。
  - 规则分：不装 0.33 / 上一版 4.0.0 1.00 / 当前版 1.00。
  - 完整：是。AI 评委样本 3 个，分歧 0。
  - 花费 $0.7102。
- 终端最后一行：

  ```
  下一步：生成待审页 → "<sys.executable>" "<worktree>/plugins/devkit-plugin-eval/scripts/plugin_eval.py" --data-dir "<临时数据目录>" pending devkit-discipline --run 20261015T181548Z-4.1.0-compare
  ```

- 把这一行原样复制执行，生成了这次对照的待审页（本页 5 项，共 5 项待判）。
- 三臂日志都有「回放用例的子会话转录 2 项移出组装目录」。注入核验仍报「找不到子会话转录」，这是票 13 已知缺口 1。

## 合计花费

$1.2906 + $3.5710 + $0.7102 = **$5.5718**（标价估算，走订阅）。
