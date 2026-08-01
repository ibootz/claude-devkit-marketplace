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
#   （cases/01-... 到 cases/14-...）、最后汇总 pass/fail。可移植性约束
#   （mktemp 模板、不用 sed -i、python3 写死路径、日期不写字面量）随 helper
#   实现一起搬进了 lib/harness.sh，此处不再重复。14 个用例文件与下面
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
# 【测试用真实进程跑，不 mock】直接把 JSON 喂给 hook 脚本的 stdin、断言 stdout，
#   与 harness 的调用方式完全一致，因此能覆盖 bash 外壳、python 定位、编码等
#   全链路，而不只是 python 函数。

set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$HOOK_DIR/user-prompt-submit-debug-queue.sh"
HOOK_CHORE="$HOOK_DIR/user-prompt-submit-chore-queue.sh"
ROUTING="$HOOK_DIR/session-start-keeper-routing.sh"
TRIAGE_HOOK="$HOOK_DIR/user-prompt-submit-keeper-routing.sh"
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

echo
printf '通过 %d / 失败 %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
