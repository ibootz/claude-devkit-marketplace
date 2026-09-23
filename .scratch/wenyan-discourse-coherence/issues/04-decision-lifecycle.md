# 04: 正文决策生命周期与答后闭环

Status: done
Type: task
Blocked by: 03

## What to build

覆盖 spec「Solution」第 6–7 条，以及实施决策第 15、15a、16、17、17a、18 条。

**决策请求的写法：**
- 在正文里依次给出四个具名部分：起源 / 差距 / 影响范围 / 现场证据。
- 一次只问一个决策边界。
- 选项用唯一的小写字母编号，写代价而不是写做法；推荐项同时给出依据和代价。
- 状态、编号、计数、时序类断言，必须在当轮读取真源后再写；读不到就标为「未核实」。

**删除旧指令：**
- 删掉回复结构一节里「或 `AskUserQuestion`」这一分支。
- 删掉 project overrides 里「AskUserQuestion 与声明句用白话」这一节中与 `AskUserQuestion` 相关的内容。
- 保留 md 受众判定声明那部分。

**单一来源：** 四要素的定义不重抄，只写 wenyan 版的呈现形状，并注明归属 `working-discipline` 3.3。

**答后闭环：**
- 用户作答后，回收：选定项、适用范围、未选项、下一步、残余不确定性、重开条件。
- 决策影响到文件、spec、票或范围时，同一轮就把记录落进受影响文件的 `## Comments`，或写入 `docs/adr/`。
- 用户的回答越界或无法映射到选项时，回头确认，不替用户挑一个。

**授权边界：**
- 自然语言回答不构成任何机械授权。
- 撞到 `worktree-flow` 主分支拦截时（spec 17a）：在正文里说明情况，默认引导进入 worktree。
- 不得声称正文回答等于直写授权；如果用户规则禁用 `AskUserQuestion`，也不得指示去调用它。
- 不可逆操作用现代白话，写清目标、后果、范围、前置条件和授权边界。

## Scope boundaries

不改 `worktree-flow`，不新增授权关键词或解析器，不编辑用户的私有全局规则文件。改动 `plugins/**` 之前，按仓库 `CLAUDE.md` 的要求先读两个 skill。

## Acceptance criteria

- [ ] 两份样式文件里，除了「不调用它」这类否定性提及，不再有任何指示调用 `AskUserQuestion` 的文字。
- [ ] 四要素的定义没有被复制，只保留呈现形状，并指向 `working-discipline` 3.3。
- [ ] 规则要求落盘记录，并写明落点：`## Comments` 或 `docs/adr/`。
- [ ] 规则写明 `worktree-flow` 拦截时的处置，且没有暗示正文回答能解锁直写。
- [ ] 注入预算仍满足两条上限。
- [ ] 测试新增断言：没有调用 `AskUserQuestion` 的指示；自然语言没有被描述为授权；存在落盘记录的要求。全部用例通过。

## Comments

### 2026-09-23 · 已完成

- 回复结构第 3 条原为「或 `AskUserQuestion`」，改为指向「正文拍板与答后闭环」。
- `project-overrides.md` 中「拍板材料四要素不因压缩豁免」「AskUserQuestion 与声明句用白话」两节，合并改写为「## 正文拍板与答后闭环」：四要素只写形状并指向 `working-discipline` 3.3；问句形态；小写字母选项；当轮读真源；要信息与要授权分开问；答后闭环及落盘（`## Comments` / `docs/adr/`）；非机械授权及 `worktree-flow` 拦截处置（默认引导进 worktree，弹框与否按用户规则办）；不可逆操作用白话。md 受众判定声明保留。
- 新增 2 条断言：`AskUserQuestion` 只允许出现在否定或限定语境；正文拍板流程的关键词齐全。18/18 通过。
- README「与 working-discipline 的接缝」一节同步改写。
