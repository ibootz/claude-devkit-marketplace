#!/usr/bin/env bash
#
# task-keeper · hook 回归测试（Debug/Chore 双队列 schema v4 · worktree 供给 ·
# 截图证据守卫 · push/destroy 守卫 · 归档 · 决策信箱 · 主会话路由注入）
#
# 用法： bash plugins/task-keeper/hooks/tests/run-tests.sh
# 退出码：0 全过 / 1 有失败
#
# 【文件结构】本文件是入口，只负责：算路径变量、source 共享 helper
#   （lib/harness.sh）、按固定顺序 source 每个 H 节的用例文件
#   （cases/01-... 到 cases/21-...）、最后汇总 pass/fail。可移植性约束
#   （mktemp 模板、不用 sed -i、python3 写死路径、日期不写字面量）随 helper
#   实现一起搬进了 lib/harness.sh，此处不再重复。21 个用例文件与下面
#   source 列表逐一对应，新增/调整用例节时两处要一起改。
#
# 【来源】本文件搬迁自 radnove-core 插件的
#   plugins/radnove-core/hooks/tests/run-tests.sh（922 行，schema v3 版本）。
#   task-keeper 是 radnove debug 体系的通用化搬迁版：产物布局从 `.debug/` 改成
#   `.keeper/`；存储层从 `issue_files.py` 单队列实现改成 `queue_files.py` 的
#   QueueSpec 参数化实现，一份代码同时伺候 debug（DBG-）与 chore（CHR-）两个
#   队列；skill 目录从 `debug-triage/` / `worktree-supply/` 改名 `tk-debug/` /
#   `tk-worktree/`；hook_counter 的临时状态文件前缀从 `rn-` 改成 `tk-`。
#
#   本文件之后又经历一轮 v3 → v4 迁移（队列跟随交付 worktree）：布局从
#   `.keeper/debug/issues/<id>.md`（一 issue 一文件，`worktree/` 与 `debug/`、
#   `chore/` 平级挂在 `.keeper/` 下）改成 `.keeper/<交付id>/debug/<id>/issue.md`
#   （一交付一目录、一条目一目录，`receipts.md`/截图/`worktree/` 都收进条目
#   自己的目录里）；交付 id 取 worktree 根 basename（`D-\d+-*` / `hotfix-*`
#   前缀），非交付 worktree 落固定兜底桶 `_main`。成因见
#   `hooks/lib/keeper_paths.py` 与 `hooks/lib/queue_files.py` 的模块头注释。
#   下面每一节的用例编号、断言意图与迁移前逐条对应，只按布局差异改写了路径
#   字面量与部分断言文案，判断逻辑本身未改动。
#
# 【搬了旧版哪 8 节，为什么另外两节不搬】
#   搬：H1（1-8，debug 队列快照）/ H1b（9-13，index.md）/ H7（25-30，截图证据
#   守卫）/ H8（31-39，wt_supply.py）/ H9（40-42，push 守卫）/ H10（43-45，
#   destroy 守卫）/ H11（46-48，归档）/ H12（49-52，merge-back 源侧判据）。
#   不搬：H5（tf 发布守卫）与 H13/[53]-[56]（dbops 提单守卫）——这两节测的是
#   `ymcas` / `fe_deploy.py` / `dbops` 这类云学堂内部工具链，是 radnove-core
#   插件的公司专属能力，task-keeper 里既没有对应的被测脚本，也不该有；这两节
#   继续留在 radnove-core 仓自己的回归测试里。
#
# 【编号沿用旧坐标、故意留空档】
#   旧文件本身的用例编号就不连续（[17] 跳到 [25]，是 v3 摘除派发/回执对账/前端
#   组件溯源三节后留下的空档，旧文件头注释解释过原因）。本文件继续沿用这个
#   历史坐标：H1/H1b 用 [1]-[13]，跳过 H5 原占的 [13]-[17]（旧 tf 守卫用例，
#   本文件不搬），H7-H12 用 [25]-[52]（与旧文件完全一致的编号），跳过 H13 原占
#   的 [53]-[56]（旧 dbops 用例，本文件不搬），新增的 5 节从 [57] 起接着编号。
#   编号是历史坐标而不是行号——保持它不变，是为了让「第 N 个用例」这种指代在
#   跨文件/跨版本的讨论里仍然对得上。
#
# 【新增 5 节，编号 [57]-[66]】
#   H14（[57]-[58]，chore 快照）/ H15（[59]，决策信箱计数与 debug↔chore 去重）/
#   H16（[60]-[61]，双队列互不串号）/ H17（[62]-[64]，archive_done.py --auto
#   自动归档）/ H18（[65]-[66]，SessionStart 路由注入分档）。这 5 节测的是
#   task-keeper 相对 radnove-core 新增的能力（chore 队列、决策信箱、主会话
#   路由注入、自动归档），radnove-core 里没有对应实现，故不是「搬迁」而是
#   新写。
#
# 【2026-08-03 补一节，编号 [67]-[68] 之后接 [69]-[73]】
#   H19（[67]-[68]，UserPromptSubmit 三岔口分诊注入）已是当时最后一节；随后
#   `find_queue` 加了「`.keeper/<交付id>/` 已存在但 debug/chore 子目录缺失时
#   自动补建」的行为（修一个自锁死循环，见 queue_snapshot.py 的 find_queue
#   docstring），为它单独补一节 H20（[69]-[73]），接着编号，不复用空档。
#
# 【2026-08-04 补一节 H21，编号 [74]-[80]】
#   keeper 的 name 改为强制带 4 位随机短哈希，主会话唤醒前需要落盘登记来查真实
#   name——新增 `pre-tool-use-keeper-instance.sh`（`PreToolUse(Agent)`）承担这个
#   登记动作。H21 覆盖它命中/不命中两侧、name 缺失时放弃、目录不存在时能建出来、
#   写一档不覆盖另一档。
#
# 【2026-08-05 补会话隔离，H21 追加 [81]-[86]，新增 H22 编号 [87]-[92]】
#   登记文件跨会话存活，但派出去的 subagent 只活在派出它的那次会话里——新会话
#   读到上一个会话的死 name、唤醒失败后误判成"重派"，两个实例抢同一个目录的独占
#   写权限。修法是登记里多写 `session_id`（`keeper_paths.write_keeper_instance`
#   新增同名参数、`read_keeper_instance_name` 新增 `current_session_id` 参数做
#   比对），真正的三选一判断现算在 `keeper_routing.py` 的 `triage_wake_line` 里、
#   直接注进每轮的三岔口文案。H21 追加的 [81]-[86] 测 `keeper_paths.py` 函数级的
#   写入/比对/旧格式陈旧判据；新增 H22（[87]-[92]）测 `triage_wake_line` 三选一
#   在真实 hook 外壳下的注入文案（无登记 / session 匹配直接带出 name / session
#   不匹配或旧格式当陈旧 / 两档同时匹配 / payload 缺 session_id 时的安全降级）。
#
# 【2026-08-12 sdlc-writer 整体迁出 radnove-sdlc】原 H23（sdlc-routing，[93]-[98]）与
#   H30（sdlc-writer-guard，[135]-[141]）两节随 sdlc-writer 全套（agent + tk-sdlc skill +
#   guard + keeper_routing 第 4 支路）迁到 radnove 市场的 radnove-sdlc 插件（1.0.0）。
#   本文件 source 列表已摘除这两条，编号留 gap 不复用（同 H5/H13 留空档的先例）。
#   三岔口 build_triage 回到纯三 keeper（去掉 sdlc_line 形参），H19/H22 等既有断言
#   不受影响（314 用例全过）。
#
# 【2026-08-10 新增 H26，编号 [112]-[113]】
#   DEBUG 这个 QueueSpec 新增 frontmatter 字段 spec_status（fm_order 在 "type" 与
#   "reported_at" 之间插入、index_cols 追加 ("spec_status", "规格")）。H26 锁两件事：
#   render_frontmatter 按 fm_order 固定位置渲染它（不是被当未知键排到末尾）、
#   index.md 的 open 表格新增「规格」列且取值取自 issue 的 spec_status。
#
# 【2026-08-10 新增 H27，编号 [114]-[120]】
#   第三条队列 context（上下文收集包）接线：queue_files 新增 CONTEXT spec、
#   新增 lib/context_snapshot.py 与 user-prompt-submit-context-queue.sh。H27 锁
#   fm_order 键位与 index_cols 三列（失效形态同 H26）、`ledger_progress` 的两侧
#   （数得对 + 格式一变就 fail-soft 返回 None 而不是谎报「0 行已填」）、以及
#   端到端注入里三方降级标记与「销账表无人填」告警的两侧。
#
# 【2026-08-10 新增 H28，编号 [121]-[127]】
#   入库策略 v5 → v6 反转（队列正文与附件入库，只精确排除 worktree/instance.json/
#   keeper-active 三类）。**此前 v4→v5→v6 三次反转都改同一组常量与同一段冷启动
#   bash，却一条测试都没有**——改错的表现是「队列悄悄没进版本库」或「本机状态文件
#   天天产生 diff」，两者都不报错。H28 锁三处文案逐字同步（分支各自追加不同注释会
#   产生合并冲突，实测过）、四行 pattern 的写法坑（两条要 `**`、`.keeper-active`
#   不能带 `**`）、以及 gitignore_findings 的五种配置。
#
# 【测试用真实进程跑，不 mock】直接把 JSON 喂给 hook 脚本的 stdin、断言 stdout，
#   与 harness 的调用方式完全一致，因此能覆盖 bash 外壳、python 定位、编码等
#   全链路，而不只是 python 函数。

set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$HOOK_DIR/user-prompt-submit-debug-queue.sh"
HOOK_CHORE="$HOOK_DIR/user-prompt-submit-chore-queue.sh"
ROUTING="$HOOK_DIR/session-start-keeper-routing.sh"
TRIAGE_HOOK="$HOOK_DIR/user-prompt-submit-keeper-routing.sh"
KEEPER_INSTANCE_HOOK="$HOOK_DIR/pre-tool-use-keeper-instance.sh"
SUBAGENT_START_HOOK="$HOOK_DIR/subagent-start-debug-keeper.sh"
LIBDIR="$HOOK_DIR/lib"

# 本文件自己所在目录（.../hooks/tests），用来定位 lib/harness.sh 与
# cases/*.sh——与上面 HOOK_DIR（.../hooks）是两层不同的目录，不要混用。
TESTS_DIR="$HOOK_DIR/tests"

source "$TESTS_DIR/lib/harness.sh"

# 【顺序硬编码，不用通配符遍历】cases/*.sh 的加载顺序必须与旧文件（拆分前
# 单文件版 run-tests.sh）的用例编号顺序完全一致——通配符遍历的顺序依赖
# locale 与文件系统，而这套测试的输出顺序本身就是可读性的一部分；硬编码
# 列表还能让「新增 case 文件忘了挂进去」变成显式的遗漏（不 source 就不会
# 跑，容易在本地测出来），而不是被 for 循环静默吞掉。
#
# 【节间变量/函数耦合，务必保持这个顺序】01→02 共享 01 建的 $T/$Q（01 结尾
# 故意不清理，留给 02 继续用，02 清理）；04→08 共享 04 定义的
# run_supply()/mksmrepo()/mkmainwithsm()/$WT_SUPPLY（08 的 mkmbfixture 直接
# 调用它们）；07→11、07→12 共享 07 定义的 $ARCH（11/12 直接引用它跑
# archive_done.py），07→12 还共享 07 的 py_nextid() 函数（12 用它取归档
# 前后的 next_id）。详见各对应 case 文件顶部的注释。
source "$TESTS_DIR/cases/01-h1-debug-snapshot.sh"
source "$TESTS_DIR/cases/02-h1b-index.sh"
source "$TESTS_DIR/cases/03-h7-evidence-guard.sh"
source "$TESTS_DIR/cases/04-h8-wt-supply.sh"
source "$TESTS_DIR/cases/05-h9-push-guard.sh"
source "$TESTS_DIR/cases/06-h10-destroy-guard.sh"
source "$TESTS_DIR/cases/07-h11-archive.sh"
source "$TESTS_DIR/cases/08-h12-mergeback.sh"
source "$TESTS_DIR/cases/09-h14-chore-snapshot.sh"
source "$TESTS_DIR/cases/10-h15-decision-inbox.sh"
source "$TESTS_DIR/cases/11-h16-dual-queue-ids.sh"
source "$TESTS_DIR/cases/12-h17-auto-archive.sh"
source "$TESTS_DIR/cases/13-h18-session-start-routing.sh"
source "$TESTS_DIR/cases/14-h19-userprompt-triage.sh"
source "$TESTS_DIR/cases/15-h20-queue-autocreate.sh"
source "$TESTS_DIR/cases/16-h21-keeper-instance-registry.sh"
source "$TESTS_DIR/cases/17-h22-keeper-routing-session.sh"
source "$TESTS_DIR/cases/19-h24-board-report.sh"
source "$TESTS_DIR/cases/20-h25-subagent-start-inject.sh"
source "$TESTS_DIR/cases/21-h26-spec-status.sh"
source "$TESTS_DIR/cases/22-h27-context-queue.sh"
source "$TESTS_DIR/cases/23-h28-gitignore-v6.sh"
source "$TESTS_DIR/cases/24-h29-keeper-generation.sh"

echo
printf '通过 %d / 失败 %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
