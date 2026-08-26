# ponytail 项目重点与融入当前插件的分析

**研究对象**：<https://github.com/DietrichGebert/ponytail>

**研究结论**：`ponytail` 的核心价值不是“少写代码”本身，而是把“先证明必要性、优先复用已有能力、最后才写最小实现”固化为 agent 工作规则，并辅以 `lite/full/ultra/off` 模式、`ponytail-review` 等按需入口，以及生命周期 hook。当前仓库已有 `simplify` 类能力的需求基础、`token-saver` 的轻量注入机制、`working-discipline` 的分层注入与机械 guard，因此不宜直接引入一个同质的完整插件；宜吸收其决策顺序与审查入口，形成一个轻量的“复杂度预算 / 反过度工程”能力。

## 1. `ponytail` 的核心机制

### 1.1 最小化不是目标，避免非必要复杂度才是目标

项目 README 以 “The best code is the code you never wrote.” 概括方向，但同时明确：规则不是追求最少 token 或最少代码；信任边界校验、数据丢失处理、安全、错误处理和无障碍不能因“简化”而删除。

来源：

- [README.md](https://github.com/DietrichGebert/ponytail/blob/main/README.md)
- [README.md#the-rule-was-never-fewest-tokens](https://github.com/DietrichGebert/ponytail#the-rule-was-never-fewest-tokens)

### 1.2 实现决策按固定优先级收敛

README 的 `How it works` 给出以下顺序：

1. 先判断需求是否真的需要新增实现；
2. 优先复用当前代码库；
3. 优先使用标准库；
4. 优先使用平台原生能力；
5. 再考虑已有依赖；
6. 能用一行解决时不扩展；
7. 最后才写最小实现。

这不是代码风格偏好，而是一个可复用的决策顺序：先压缩问题空间，再选择技术方案。

来源：[README.md · How it works](https://github.com/DietrichGebert/ponytail#how-it-works)

### 1.3 同一规则适配多个宿主

项目同时提供：

- `AGENTS.md`：无插件宿主的规则回退；
- `.claude-plugin/`、`.codex-plugin/` 等宿主入口；
- `.cursor/rules/`、`.windsurf/rules/`、`.clinerules/` 等常驻规则目录；
- `skills/`：按需技能；
- `hooks/`：生命周期自动化；
- `benchmarks/`、`tests/`、`scripts/`：验证、基准与维护工具。

其关键设计不是“所有宿主都拥有同样能力”，而是把核心规则与宿主适配层拆开：能力完整的宿主提供命令和 hook，能力较弱的宿主退化为常驻规则。

来源：

- [仓库根目录](https://github.com/DietrichGebert/ponytail/tree/main)
- [README.md · Compatibility](https://github.com/DietrichGebert/ponytail#compatibility)
- [docs/agent-portability.md](https://github.com/DietrichGebert/ponytail/blob/main/docs/agent-portability.md)

### 1.4 模式化控制注入强度

项目支持：

```text
/ponytail [lite | full | ultra | off]
```

并可通过 `PONYTAIL_DEFAULT_MODE` 或 `~/.config/ponytail/config.json` 设置默认模式。规则默认也可注入子代理，并可用 `PONYTAIL_SUBAGENT_MATCHER` 按代理类型筛选。

这说明它把“规则是否存在”与“规则注入多少”分开处理，而不是所有规则永远全量常驻。

来源：[README.md · Modes and configuration](https://github.com/DietrichGebert/ponytail#configuration)

### 1.5 命令入口覆盖不同决策时刻

README 列出的能力包括：

- `ponytail`：切换或查看模式；
- `ponytail-review`：审查当前 diff；
- `ponytail-audit`：审计仓库；
- `ponytail-debt`：收集被延期的复杂度问题；
- `ponytail-gain`：查看节省或收益；
- `ponytail-help`：查看帮助。

其中最值得借鉴的不是命令名，而是把“写代码前的约束”“改完后的 review”“暂不处理的债务记录”“收益度量”拆成不同决策时刻。

来源：[README.md · Commands](https://github.com/DietrichGebert/ponytail#commands)

## 2. 与当前仓库的对应关系

| `ponytail` 能力 | 当前仓库已有对应物 | 差距 | 判断 |
|---|---|---|---|
| 先复用、后新增、最小实现 | `token-saver` 与 `working-discipline` 已强调节省上下文、先定位、避免无谓操作 | 尚无一条集中描述“实现方案复杂度优先级”的规则 | 值得吸收 |
| 改完审查复杂度 | `working-discipline` 有多类事后提醒；仓库也有代码 review 类能力 | 缺少专门针对过度工程、重复抽象、无必要依赖的审查清单 | 值得补充 |
| `lite/full/ultra/off` | `token-saver` 支持 `TOKEN_SAVER=off`；部分规则有独立开关 | 缺少跨插件统一的强度模式 | 可借鉴，但不宜立即做全局模式 |
| 子代理规则下传 | `working-discipline` 已有 `SubagentStart` 分层注入 | 已有较复杂的注入预算与分层策略 | 不应重复实现 |
| 生命周期 hook | `working-discipline` 已有 `SessionStart`、`UserPromptSubmit`、`SubagentStart` 与多个 guard | 机制成熟，但新增 guard 需严格证明判据机械 | 只加注入或低风险提醒 |
| `ponytail-review` / `audit` | 当前仓库已有 review、简化类技能基础 | 需要确认实际技能清单后再决定复用入口 | 优先复用现有入口 |
| `debt` / `gain` 记录 | 当前仓库有研究文档与 task-keeper 队列 | 没有专门的复杂度债务与收益账本 | 可作为后续能力 |
| 多宿主适配 | 当前仓库面向 Claude Code / Codex 插件市场 | 仓库自身已强调两套 manifest 与插件可移植性 | 直接沿用当前规范，不照搬其目录 |

当前仓库的一手依据：

- [`plugins/token-saver/README.md`](../../plugins/token-saver/README.md)：仅做轻量注入和大文件软提醒，明确避免高频、猜语义的 hook。
- [`plugins/working-discipline/README.md`](../../plugins/working-discipline/README.md)：已有分层注入、机械判据优先、误杀复盘与 hook 克制原则。
- [`Agents.md`](../../Agents.md)：规定插件目录、skills、hooks、版本同步与可移植性。

## 3. 推荐融入方案

### 3.1 MVP：先补一条独立、轻量的“复杂度决策规则”

推荐新增一个短 skill，而不是复制 `ponytail` 的完整插件结构。技能触发词可围绕：

- “是否需要新增依赖”；
- “这个抽象是否过度”；
- “能否复用现有实现”；
- “简化这段代码”；
- “审查过度工程”；
- “减少不必要代码”。

技能正文只保留以下流程：

1. 写代码前列出需求中必须保留的行为与不可删边界；
2. 搜索当前仓库是否已有实现、抽象、依赖或平台能力；
3. 按“现有代码库 → 标准库 → 平台原生 → 已有依赖 → 最小新增实现”顺序比较；
4. 明确拒绝了哪些更复杂方案，以及拒绝理由；
5. 改完只做一次针对复杂度的 review，确认没有删除安全、错误处理、数据完整性和无障碍要求。

这条路径可获得 `ponytail` 的核心收益，同时不增加常驻 token 成本，也不与 `working-discipline` 的 hook 重叠。

### 3.2 第二阶段：复用现有 review 入口，增加“复杂度”维度

若仓库已有通用 review skill，优先给它增加一个可选维度，而非新增平行命令。审查项建议为：

- 是否重复实现仓库已有能力；
- 是否新增了本可由标准库或平台完成的依赖；
- 抽象层级是否高于调用复杂度；
- 是否引入只服务一次调用的通用框架；
- 是否把本可局部解决的问题扩展成跨模块改动；
- 简化是否误删了安全、数据完整性、错误处理、权限和无障碍边界。

输出应按“发现 / 证据 / 影响 / 建议”组织，避免把主观“看起来复杂”直接当问题。

### 3.3 第三阶段：建立复杂度债务记录，但不要另造账本

可把 `ponytail-debt` 的思想接到已有 task-keeper 或研究文档体系：

- 只记录明确延期、且有证据的复杂度问题；
- 条目写明现状、期望、影响范围、触发条件和后续处理入口；
- 不把“我个人不喜欢这种写法”登记为债务；
- 债务条目必须区分缺陷、技术债和规格空白，避免把未定义的设计偏好伪装成 bug。

“收益”先不做自动数值化。若未来要做，可记录删除的依赖、减少的代码路径、减少的 hook 注入字符或减少的运行时步骤，但必须以可复核事实为依据。

## 4. 不建议照搬之处

### 4.1 不建议直接引入完整 `ponytail` 插件

当前仓库已有较强的 `working-discipline`、`token-saver` 与插件目录规范。直接安装或复制完整 `ponytail`，容易造成：

- 同一条“少写代码”规则多份注入；
- `SessionStart` / `SubagentStart` token 预算重复消耗；
- 多套模式开关互相覆盖；
- 多个 review 入口对同一 diff 重复审查；
- hook 拓扑重复，增加误拦与排障成本。

### 4.2 不建议把“复杂”做成硬拦截

当前仓库已经记录：只有能机械判定的字段存在性、格式或纯计数，才适合 `deny`；“这段实现是否过度工程”需要理解上下文，不适合靠正则拦截。

故不建议新增以下 guard：

- 扫 prompt 中的 `class`、`factory`、`adapter`、`framework` 等词后阻断；
- 看到新增依赖就阻断；
- 按文件行数或函数长度推断实现一定过度；
- 读取 transcript 后判断 agent 是否做了“足够简化”。

复杂度判断应落在 skill、review 提示或人工可审计报告，不应伪装成确定性门禁。

### 4.3 不建议照搬其基准结论

README 的数字来自特定仓库、特定模型、有限任务数与样本量。它能支持“规则可能带来收益”的假设，不能直接证明在当前插件市场、当前模型和当前用户工作流中同样节省成本或时间。

若要验证，应在当前仓库选取有代表性的任务，比较：

- 是否减少无必要依赖与文件改动；
- 是否减少返工；
- 是否增加漏实现边界的风险；
- 总 token、工具调用数与完成时延；
- review 发现的真实问题比例。

来源：[README.md · Numbers / Benchmarks](https://github.com/DietrichGebert/ponytail#numbers)

### 4.4 不建议照搬其多宿主目录

`ponytail` 的多宿主适配值得参考，但当前仓库已有自己的 `.claude-plugin/marketplace.json`、插件 `plugin.json` 与 Codex 清单约定。直接复制目录会造成第二套事实来源。应复用“核心规则 + 宿主适配层”的思想，具体路径仍以当前仓库 `Agents.md` 为准。

## 5. 验证计划

### 阶段 A：静态验证

- 选 5 个近期真实改动，分别执行“普通实现”和“复杂度审查”流程；
- 记录是否发现重复实现、无必要依赖、过度抽象或不必要跨模块改动；
- 检查审查建议是否有源码证据，是否误把规格空白当缺陷。

### 阶段 B：行为验证

- 对同一需求做 A/B：不开复杂度 skill 与开启复杂度 skill；
- 比较文件改动数、依赖变更数、工具调用数、总 token、返工次数；
- 单独统计错误处理、安全、权限、数据完整性和无障碍回归，不以“代码更少”抵消这些回归。

### 阶段 C：注入与 hook 验证

- 新能力默认不进常驻注入；
- 若确需注入，先测字符预算与 auto-compact 后是否重新出现；
- 不新增语义猜测 guard；
- 若未来新增机械 guard，必须同时提供误杀样例、漏报样例、fail-open 行为与回归测试。

## 6. 最终建议

**建议吸收思想，不直接引入项目。**

优先级如下：

1. 新增或补强一个按需 skill：固化“先证明必要性，再复用，最后最小实现”的决策顺序；
2. 在现有 review 能力中增加可选的复杂度审查维度；
3. 视真实使用数据，再把复杂度债务接入现有 task-keeper 记录；
4. 暂不新增全局 `lite/full/ultra` 模式，也不新增语义型硬拦截；
5. 完成 A/B 验证后，再决定是否需要独立插件名、配置项或收益统计。

一句话概括：`ponytail` 最适合成为当前插件体系中的一套**按需决策方法与 review 维度**，不适合原样成为又一个常驻规则集。
