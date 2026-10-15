# 03 — 插件骨架、登记与最小离线对照（主链路打通）

Status: ready-for-agent

**What to build:**

新建本仓插件 `devkit-plugin-eval`，交付一个 Python 命令行，打通离线对照的最短完整链路：

- **登记**：用户登记一个被测插件（插件名 + 所在仓路径），写入用户级 `registry.json`。登记即信任声明：之后跑 eval 自动加 `--trust-plugin`；未登记的插件拒绝跑。
- **最小对照**：对已登记插件现有的 `evals/` 用例，按 01 定下的跑法组装「不装」与「当前版」两个臂（各一个临时组装目录，用例一律拷当前版），每臂跑 eval（`--keep-temp`、每例 3 次），只用规则判分，脚本自算两臂之差。
- **落盘**：在被测插件所在仓的 `plugin-evals/<plugin>/runs/<时间>-<版本>-compare/` 下写 `run.json`（唯一真源）、各臂 `aggregate-result.json`、`report.md`；状态为「待审」；eval 写进 `<plugin>/evals/results/` 的产物搬走，该目录进 `.gitignore`；全量 trace 移到用户级 `traces/`；跑完清理臂组装目录与回放转录。

本票只做两臂、只做规则判分；前置检查、上一版臂、注入核验、AI 评委、待审页都在后续票。

**Blocked by:** 01


- [ ] 插件以 `devkit-` 前缀命名，两份市场清单都已登记，`node scripts/check-versions.js` 通过，`claude plugin validate` 通过
- [ ] 对一个带现成用例的插件（如 plugin-eval probe 里的 devkit-discipline 三例）跑一次对照，得到含两臂分数与差的 `report.md`
- [ ] `run.json` 含 spec「四、目录布局与状态文件」列出的字段中本票已能填的部分（插件名、版本、插件内容指纹、各臂、Claude Code 版本、主力模型、token 与标价估算、`kind=compare`、是否完整、是否通过、审阅状态=待审）；其余字段留键位
- [ ] 未登记插件跑对照被拒，并提示先登记
- [ ] 调 `claude` 前先解析出可执行文件路径；stdout 设为 UTF-8
- [ ] 改插件文件前按仓根 CLAUDE.md 先读规定的技能

**参考：** [spec](../../plugin-eval/spec.md) 的spec「2.1 交付形态」「2.2 离线对照（compare）」第 3、4、8 步、「四、目录布局与状态文件」；[09](../../plugin-eval/issues/09-build-vs-extend.md)、[13](../../plugin-eval/issues/13-result-layout.md)

## Comments
