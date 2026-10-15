# 02 — 单测声明与本仓 pre-commit 单测

Status: ready-for-agent

**What to build:**

插件作者在插件根放一份 `unit-tests.json`（单测声明），写明自己的确定性单测怎么跑。本票做两件事：

1. 本仓 `.githooks/pre-commit` 调起一个本仓 JS 脚本（node 调起，不依赖 `devkit-plugin-eval` 已安装）：按暂存路径命中 `plugins/<name>/**` 选出被改插件，读工作区里的声明、在工作区跑，任一条失败或超时即拦。
2. 给本仓已有确定性单测的插件写上声明；另备一组共用的声明样例（合法、不合法、平台跳过、解释器缺失、超时），供本票的 JS 实现与 14 的 Python 实现各跑一遍对齐。

声明格式：顶层只有 `tests` 数组；每条只有 `run`（argv 数组，不经 shell，cwd 固定插件根）、`timeout_sec`（缺省 120）、`platforms`（`darwin` / `linux` / `win32`，缺省全部）。

**Blocked by:** None — can start immediately


- [ ] 改某插件的文件并提交时，该插件声明里的单测被执行；单测失败或超时，提交被拦下，输出指明是哪条
- [ ] 未声明单测的插件静默放行；声明不是合法 JSON 或含约定外字段时拦下并指明原因
- [ ] 当前平台不在 `platforms` 里的条目跳过并提示；解释器解析不到时跳过并警告；`python3` 按 `python3` → `python` → `py -3` 实际执行 `--version` 解析
- [ ] 只改 `plugin-evals/<name>/` 下的文件不触发该插件单测；插件目录已删则跳过
- [ ] 本仓现有确定性单测都已登记进各自插件的 `unit-tests.json`，`claude plugin validate` 对这些插件无新增 warning
- [ ] 共用声明样例集已就位，本票 JS 实现对每个样例的判定结果写进样例旁的期望文件
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.7 确定性单测」；[16](../../plugin-eval/issues/16-existing-deterministic-tests.md)、[18](../../plugin-eval/issues/18-unit-test-declaration.md)

## Comments
