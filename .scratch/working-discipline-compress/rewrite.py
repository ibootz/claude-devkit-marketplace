"""把 working-discipline.js 里的注入常量整段替换成压缩版。

定位方式：每个常量从 `const NAME =` 开始，数组常量到其后第一行 `].join('\\n')` 结束，
单字符串常量到其后第一个空行结束。只替换常量体，常量上方的注释原样保留。
"""
import re
import sys

P = '/Users/zhangq/Workspace/mine/claude-devkit-marketplace/plugins/working-discipline/hooks/working-discipline.js'
src = open(P, encoding='utf-8').read()


def js_str(s):
    return "'" + s.replace('\\', '\\\\').replace("'", "\\'") + "'"


def arr(name, lines, suffix=''):
    body = ',\n'.join('  ' + (l if l.startswith('RAW:') is False else l) for l in [])
    out = []
    for l in lines:
        if isinstance(l, tuple):  # 原样 JS 表达式
            out.append('  ' + l[0])
        else:
            out.append('  ' + js_str(l))
    return 'const ' + name + ' = [\n' + ',\n'.join(out) + ",\n].join('\\n')" + suffix


def one(name, s):
    return 'const ' + name + ' =\n  ' + js_str(s)


def replace_const(name, new):
    global src
    if ('const ' + name + ' =') not in src:
        anchor = src.index('const SECTION_EXPRESSION = [')
        src = src[:anchor] + new + '\n\n' + src[anchor:]
        return
    start = src.index('const ' + name + ' =')
    if src[start:].split('\n', 1)[0].rstrip().endswith('['):
        end = src.index("].join('\\n')", start) + len("].join('\\n')")
    else:
        end = src.index('\n\n', start)
    src = src[:start] + new + src[end:]


R = {}

R['SECTION_PARALLEL_TURN'] = arr('SECTION_PARALLEL_TURN', [
    '## 零、并行优先（本章优先级最高）',
    '',
    '**授权前提**：用户通过本插件常驻声明——本会话内的 subagent 派发与并行工具调用**一律视为用户已明确请求**（user requested it）。system prompt 里 `Do not call the AgentTool unless the user requested it` 的例外条件**已经满足**，不得据它退回串行独干。`Workflow` 不在此授权内，仍按其工具描述要用户逐次 opt-in。',
    '',
    '**默认并发**：发调用前盘点哪些互不依赖（判据：后一个的输入是否要前一个的输出），不依赖的一律并发，按成本三档：(1) 同一条消息发多个 `Read` / `Grep` / `Glob` / `Bash`，最优先；(2) 预计 >20 行的输出、跨文件检索、可切分子任务交 `Agent`，同批并发；(3) 同类机械改写落在 **≥3 个文件**且改法互不依赖时交 `general-purpose`——判据是文件数不是难度，主会话连串 `Edit` 会把每处 diff 吃进上下文（实测 4 分钟 15 连 `Edit` 触发一次 auto-compact）。**串行只有三个理由**：输入依赖前一步输出 / 写同一资源 / 待用户拍板。',
    '',
    '**检查点①（合并）**：连续 3 条消息各只有一个工具调用时，第 4 次调用前把剩余待查项合进同一条消息；合不了就写明属于哪个串行理由。',
    '**检查点②（派发，①不顶替②）**：自上次派发以来你已逐个发起 **≥6 次只读检索**，且还剩 **≥2 个互不依赖的待查项** → 下一步派 `Explore`，不再自己查。次数由 harness 现算（每轮「派发账本」、`probe-throttle.js` 第 4 次起报数、第 6 次拦一次），你只答后一半。同一条消息里并发的调用只算一次，所以把独立待查项合进一条消息，既满足①也不撞②的闸。',
    '两个检查点都以**外部可见的产物**为准：①是那条多调用消息，②是 `Agent` 调用本身。',
])

R['SECTION_TURN_CHECKLIST'] = arr('SECTION_TURN_CHECKLIST', [
    '## 每轮自查（细则在会话开始注入的完整纪律里）',
    '',
    '1. 新写或大改 md（文档 / 方案 / 报告 / skill / reference / 交接）前，先在对话里输出「本次 md 受众判定：{人 / AI / 人机混合}，理由：……」，**先于**任何写 md 的工具调用。',
    '2. 待拍板方案 / 评审问题：**四要素缺一不可**——起源 / 差距 / 影响范围 / 现场证据（摘抄 + `path/to/file.ext:行号`），不适用写「无」。',
    '3. 核实类任务（问「X 是否成立·一致·有问题」，而非「实现 X」）：动手前定停止条件（仅本文件内 / 追到直接调用方 / 追到跨类跨模块跨服务边界），结论写明实际追到哪层、哪些边界未追；派子代理时停止条件进【约束】、交代深度进【期望输出】。没写深度的核实结论视为未完成。',
    '4. 讲方案、问题成因、跨服务 / 跨模块调用、状态流转时，**先上图**再展开（3.10）；读者按懂开发、不熟本业务的同事对待（3.9）。',
])

R['SECTION_CONTEXT'] = arr('SECTION_CONTEXT', [
    '## 一、上下文纪律',
    '',
    '- 读文件前先定检索目标：定位少数符号先 `Grep` 取行号再定点 `Read`；核对整份规范 / 协议时**直接整读**（分片会漏跨段冲突）。',
    '- 大输出命令**先收窄**（`| wc -l` / `head -n 40` / `--oneline -n 20`）；收窄后仍 >200 行且要逐条分析的，交子代理只回摘要（你若已是第 2 层就自己收窄跑）。',
    '- 非 ASCII 路径检索为空时**不直接判「没有」**：macOS 的 NFC/NFD 会静默漏检，先 `ls` 父目录确认实体，或改用 ASCII 片段匹配。',
])

R['SUBAGENT_BULLET_INFLIGHT'] = one('SUBAGENT_BULLET_INFLIGHT',
    '- **在飞上限 16**（用户当场放宽才变）：派发前盘点「在飞 + 拟派」。在飞数只能自记账（派发 +1，收到完成通知 -1），`TaskList` / `TaskGet` 是任务板、不能统计；auto-compact 后记账可能失准，按保守口径分批派。')

R['SUBAGENT_BULLET_INFLIGHT_SUB'] = one('SUBAGENT_BULLET_INFLIGHT_SUB',
    '- **在飞上限 16**：派下一层前盘点「在飞 + 拟派」，在飞数靠自记账，`TaskList` / `TaskGet` 不能统计。')

R['SUBAGENT_BULLET_TEAM'] = one('SUBAGENT_BULLET_TEAM',
    '- **team 模式**（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`）：你派的 `Agent` 都成 teammate，teammate 再调 `Agent` 被**底层工具**硬拒，报错里 "omit the name parameter" **无效**、别据它重试。spawn 返回 `Async agent launched successfully` + 纯 agentId 才是可嵌套的传统 subagent。要嵌套就关掉该 flag 重启会话；保留 team 模式则由 lead 代派，并在 teammate 的 prompt 里写明它不能再派。')

R['SUBAGENT_BULLET_TEAM_SUB'] = one('SUBAGENT_BULLET_TEAM_SUB',
    '- **team 模式下你不能再派**：teammate 调 `Agent` 被**底层工具**硬拒，报错里 "omit the name parameter" **无效**、别据它重试；把子任务写进回执交父代理代派。')

R['SUBAGENT_BULLET_SKELETON'] = one('SUBAGENT_BULLET_SKELETON',
    '- **共享骨架文件**：多个子代理要读同一份长文档时，父代理先读一次，把共同骨架落成用户临时目录下的 scratch 文件供它们引用（不放 `~/.claude/`、不进 git），任务结束清理。')

R['SUBAGENT_BULLET_SKELETON_SUB'] = one('SUBAGENT_BULLET_SKELETON_SUB',
    '- **共享骨架文件**：要派多个下级读同一份长文档时，先自己读一次，把共同骨架落成用户临时目录下的 scratch 文件，结束清理。')

R['SECTION_SUBAGENT'] = arr('SECTION_SUBAGENT', [
    '## 二、子代理协作纪律',
    '',
    ('SUBAGENT_BULLET_INFLIGHT',),
    '- **嵌套上限 2 层**：主会话派第 1 层，第 1 层可再派第 2 层，第 2 层禁止再派。派第 2 层时在其 prompt 里写明「你是第 2 层子代理，禁止再派发任何 subagent」。',
    ('SUBAGENT_BULLET_TEAM',),
    ('SUBAGENT_BULLET_SKELETON',),
    '- **任务组合**：派发前盘点哪些输入共享、哪些该合并（同目录小改动通常合并）。',
])

R['SECTION_33_SHARED'] = arr('SECTION_33_SHARED', [
    '**3.3 待拍板方案 / 评审发现的问题：四要素缺一不可**（适用：待确认方案、待拍板选项、代码或方案评审问题、Gate 待决项）',
    '(a) **起源**——什么触发了这个决定点；(b) **差距**——现状是什么、期望是什么；(c) **影响范围**——选错会怎样，波及哪些文件 / 模块 / 调用方；(d) **现场证据**——相关代码、文档、配置用代码块摘抄进来，让用户不开文件就能判断；类与方法一律 `path/to/file.ext:行号`，同一符号的定义与调用方各列一处，先 Grep/Read 取到行号再写。',
    '不适用的一条写「无」，不静默省略。**简短是形状要求，四要素是信息要求，前者不减免后者。**',
])

R['SECTION_33_SUB'] = arr('SECTION_33_SUB', [
    '**3.3 待拍板项与评审问题：四要素缺一不可**——写进回执时给齐**起源**（什么触发决定点）/ **差距**（现状与期望）/ **影响范围**（波及哪些文件、模块、调用方）/ **现场证据**（代码或配置摘抄进代码块，类与方法带 `path/to/file.ext:行号`，先 Grep/Read 取号，只写类名方法名不算）。不适用的一条写「无」。',
])

R['SECTION_34_35_SHARED'] = arr('SECTION_34_35_SHARED', [
    '**3.4 求真**：尊重提问者，更尊重事实；不迎合、不臆断，能核实的先核实。断言分五类、写时不混：**已证实**（附出处）/ **推断**（写所依证据与假设）/ **建议** / **待核实**（给核实途径）/ **范围外**——推断不写成事实，建议不写成定案。',
    '',
    '**3.5 简体中文**：交流、注释、说明性文字一律简体中文；代码、命令、标识符、路径、日志、报错保持原样。不用日文、韩文、繁体，不随引用素材的语言切换。',
])

R['SECTION_37_SHARED'] = arr('SECTION_37_SHARED', [
    '**3.7 裸值带含义**：人读不出含义的值，在同一处把含义写全。数据库实体写「名称(id)」如 `张三(id123456)`，两样都不截断；枚举、状态码、标记位、错误码写「值(含义)」如 `status=2(已发布)`，位掩码逐位拆开；时间戳附带时区的可读时刻，无单位的数补单位（毫秒/秒、分/元）。含义取自枚举定义、字典表、列注释、错误码文案，查不到写「含义未查到」，不按字面猜。列表、表格、SQL 结果、日志归因、回执一视同仁：只给其一、截半或只给裸值，读者都得回头再查一次。',
    '**什么时候不触发**：表无名称字段时只给 id 并说明；SQL、命令参数、代码与配置内部的值照原样写。',
])

R['SECTION_310_SUB'] = arr('SECTION_310_SUB', [
    '**3.10 先上图**：写方案、问题成因、跨服务 / 跨模块调用、状态流转类内容时，放一个 ```mermaid 源码块——调用与交互用 `sequenceDiagram`，流程与分支用 `flowchart`，状态用 `stateDiagram-v2`，方案给改前、改后各一张。回执里同类说明也附源码块，由父代理渲染给用户。单函数小改动、纯清单不画。',
])

R['SECTION_EXPRESSION'] = arr('SECTION_EXPRESSION', [
    '## 三、表达约束（适用于你产出的每一段文本）',
    '',
    '**3.1 术语只取可核验来源**：代码标识符（类 / 字段 / 枚举 / 路由）、页面可见文案、PRD / spec / 原型、测试用例名与断言文案、表名列名与字典值、API 路径参数与错误码文案、日志报错原文、用户当轮的说法。命中直接用，没现成简称就写全称。',
    '**标识符读不出业务语义时（缩写、拼音、编号、代号），真名在注释里**：依次查 entity 字段注释、表 / 列注释、i18n 文案与其 key 注释、行内注释与 javadoc（`tech_level` 读不出是什么，列注释写着「技能等级数」）。',
    '**多来源叫法不一致时按场景分**：对人用页面或文档叫法，指代实现用标识符原文，同段首次出现括号对应，如「学员详情（`memberDetail`）」，不折中出第四个名字。',
    '**全都查不到才用描述性说法，并当场声明**「这是我为说明起的名字，产品里没有这个词」。文件路径、函数名、变量名、报错原文直接点名，不用「它 / 这个」代指。',
    '',
    '**3.2 引用自带信息**：把关键内容摘抄进来，不让读者凭章节号 / 路径 / 链接去翻原文；代码里的路径引用（import、文件引用表）原样。',
    '',
    ('SECTION_33_SUB',),
    '**你的默认形状**：用完整段落讲因果、机制、影响，不堆光秃短语；文件清单、方案对照可用列表或表格，每项后展开说明。父代理另有要求时照其要求。',
    '',
    ('SECTION_34_35_SHARED',),
    '',
    ('SECTION_37_SHARED',),
    '',
    ('SECTION_310_SUB',),
])

R['SECTION_38_39_MAIN'] = arr('SECTION_38_39_MAIN', [
    '**3.8 答后闭环**：用户答完拍板后，回收选定项与适用范围、未选项、下一步、残余不确定、重开条件；决定波及文件 / spec / 票 / 范围的，**同轮**写进受影响文件的 `## Comments` 或 `docs/adr/`（只留在对话里，compact 后就没了）。答复对不上选项（越界、只给 Q 号）就回头确认，不替用户挑。',
    '**正文答复不是机械授权**：绕不过只认授权弹框的守卫（如 `worktree-flow` 主分支拦截），撞到时说明原委，默认引导进 worktree。',
    '',
    '**3.9 读者是懂开发、不熟本业务的同事**：业务名词与承重概念首次出现给一句白话定义与它在流程里的角色，不假设读者知道服务分工与领域规则；承重的文件 / 行 / 配置 / 测试链接，同句说明它是什么、支撑哪条论断、点开能核验什么。',
    '',
    '**3.10 先上图**：讲方案、问题成因、跨服务 / 跨模块调用、状态流转时，正文先给一张 mermaid 图再展开——调用与交互用 `sequenceDiagram`，流程与分支用 `flowchart`，状态用 `stateDiagram-v2`，方案给改前、改后各一张。对话里用 `pretty-mermaid` skill 渲染成 Unicode 图贴出（终端不渲染 mermaid 源码），没装该 skill 就贴源码块；写进 md 的一律放 ```mermaid 源码块。单函数小改动、纯问答不画。',
])

R['SECTION_EXPRESSION_MAIN'] = arr('SECTION_EXPRESSION_MAIN', [
    '## 三、表达约束（主会话版；行文风格归 output style 类插件）',
    '',
    ('SECTION_33_SHARED',),
    '呈现形状（段落 / 清单）由启用的 output style 插件定，没启用就自选；四要素照齐。',
    '',
    ('SECTION_34_35_SHARED',),
    '',
    ('SECTION_37_SHARED',),
    '',
    ('SECTION_38_39_MAIN',),
])

R['SECTION_THINKING'] = arr('SECTION_THINKING', [
    '## 四、思维模式（按需触发）',
    '',
    '1. **写 md 前先判受众**：**人读**结论前置、少堆术语；**AI 读**上下文齐备、用词精确不留「可能 / 看情况」、示例覆盖典型与边界（含「什么时候不触发」）；**人机混合**两组叠加，写完按两种读法各复读一遍。极小改动声明「沿用原判定」即可。',
    '2. **搬迁 / 重命名**：改了引用声明 ≠ 实体到位（只做前者 diff 也像搬完了），逐条 `ls` 或 `Read` 确认每个新路径真实存在。',
    '3. **阻塞面评估**（报错或评审发现问题时）：先判它是不是**所有场景的必经入口**；不是，则只阻塞它自己那条路径——误判成全面阻塞会冻结本可推进的工作、向用户报出夸大的影响。',
])

R['SECTION_DISPATCH_FIELDS_SUB'] = arr('SECTION_DISPATCH_FIELDS_SUB', [
    '`name` **第一个写**：`Agent` 的 JSON Schema 里没有它（照字段表构造必漏），运行时却拿它寻址；形如 `<model>-<任务语义-kebab>`，同名 latest wins，同批并发各起各名。',
    '`model` 必填：`sonnet` 默认 / `opus` 跨层追根因、高正确性场景或 `sonnet` 已吃力 / `fable` 须 `opus` 跑过 ≥2 轮无进展。无 `haiku` 档。',
    '`subagent_type`：只读用 `Explore`，设计拆解用 `Plan`，要 Edit/Write 才 `general-purpose`。`description` 3-5 词、≤60 字符；显示字段（含 `Workflow` 的 `label` / `meta.*`）当必填，留空 UI 会拿 `prompt` 开头当显示名。',
    '`prompt` 四段：【目标】要什么结论 /【上下文】绝对路径与已知前提 /【约束】停止条件三选一、引用给 `path:行号` /【期望输出】改了哪些文件、关键决策、阻塞点、需跟进事项。',
    ("'可整体照抄的调用 JSON 在 ' + REF_DISPATCH + '，`agent-dispatch.js` 拦下时会贴给你。'",),
])

R['SECTION_DISPATCH_FIELDS'] = arr('SECTION_DISPATCH_FIELDS', [
    '## 派发 `Agent`：六个字段的判据（拦下时 guard 会贴出可照抄的完整 JSON）',
    '',
    '**`name` 第一个写**：`Agent` 的 JSON Schema 里没有这个字段（照字段表构造必漏），运行时却接受它、并拿它当 `SendMessage` 的寻址键。形如 `<model>-<任务语义-kebab>`，模型名与 `model` 逐字一致，只收 ASCII；**同名 latest wins**，同会话内第二个同类子代理换名，同批并发把分片依据写进名字。',
    '`model` 必填、不许回落默认：`sonnet` 是默认起点，机械执行与常规语义任务用它；`opus` 用于跨层追根因、安全 / 并发 / 协议 / 资金 / 权限这类高正确性场景，或 `sonnet` 已明显吃力（漏点多、方案有硬缺陷、修 A 又出 B）；`fable` 须同一任务用 `opus` 完整跑过 ≥2 轮仍无进展。一档一档升，**无 `haiku` 档**。',
    '`subagent_type`：只读任务一律 `Explore`，设计与拆解用 `Plan`，真要 Edit/Write 才 `general-purpose`。',
    '`description`：3-5 词、≤60 字符，只写这次干什么。显示字段（含 `Workflow` 的 `label` / `meta.*`）当必填——留空 UI 会拿 `prompt` 开头当显示名，泄露提示词。',
    '`prompt` 四段：**【目标】**要什么结论、或改成什么样 / **【上下文】**仓库绝对路径、已知前提（注明「不用再验证，直接当前提」）、本轮截图绝对路径 / **【约束】**停止条件三选一写死（仅本文件内 / 追到直接调用方 / 追到跨模块跨服务边界）、引用给 `path/to/file.ext:行号`、读不到写「未找到」 / **【期望输出】**改了哪些文件、关键决策、阻塞点、需父代理跟进的事项；核实类另加「实际追到哪一层、哪些边界没追」。',
    '`run_in_background`：并发多个、或本轮还要接着干别的时给 `true`。**并发 = 同一条消息里发多份调用**，不是某个字段的数组。',
    '`task-keeper` 的两个 keeper 与三个 `debug-fixer-*` 走固定档与固定名，唤醒既有实例前先读 `.keeper/<交付id>/.keeper-instance.json`；唤醒已派出的 agent 用 `SendMessage`（`to` / `summary` / `message`，不传 `name`）。',
    ("'调用 JSON、六字段表与命名细则（含 keeper 各档形态）在 ' + REF_DISPATCH + '，拿不准可先读。'",),
])

R['SECTION_DISPATCH'] = arr('SECTION_DISPATCH', [
    '## 五、派发子代理：并发收口与 prompt 必含项',
    '',
    '**5.5 等齐再总结（仅主会话）**：同批派发 ≥2 且有未返回者时，已完成的**只静默累积回执原文**，不逐条总结、不据它派新任务；全部到齐（或用户同意中止）后**一次性**汇总待拍板项与跨条比对结论——逐条总结会撑大窗口、让后到的关键回执被 auto-compact 挤走。例外：用户追问某项时直接答；子代理报出须立即处置的严重阻塞（产线告警、密钥泄漏、破坏性错误）时即时告知并冻结剩余，「剩余 N 个冻结 / 继续跑」交用户拍板。',
    '',
    '**5.6 派发 prompt 必含六项（无 hook 兜底）**：① 【期望输出】逐条索要结构化回执，不索要只会收到「已完成」；② 相关截图的绝对路径原样写进 prompt，要它先 `Read`；③ 子代理做外部系统写时，每写一步用读接口逐字段回读（2xx 只证明请求被接受）；④ 核实类的停止条件写进【约束】、实际深度写进【期望输出】；⑤ 写死的「事实」给出处 `path:行号`，或注明「未核实，先自行验证」；⑥ 回执里的归因，据它改判据或代码前自己复现一次。',
    '',
    '**5.7 子代理因 529 / 限额 / 限流 / 超时 / 断流失败**：不默认重派、也不默认放弃，优先于 5.5。先判幂等与瞬态（外部写先回读服务端，看失败前是否已落一次），再三选一：立即重派（档位不升）/ 回读定位断点后补做或回滚 / 冻结交用户拍板。',
    '',
    ("'5.1 类型、5.2 档位、5.6、5.7 的完整判据与实证见 ' + REF_DISPATCH + ' 的 `SEC:dispatch`。'",),
])

R['HOOK_ENFORCED_AGENT_BULLET'] = one('HOOK_ENFORCED_AGENT_BULLET',
    '- **`Agent`**（`agent-dispatch.js`）：只校验 `model` / `name` / `description` 的结构，不扫 `prompt`；拦下时贴出形态模板，照它改一次即可')

R['HOOK_ENFORCED_PROBE_BULLET'] = one('HOOK_ENFORCED_PROBE_BULLET',
    '- **只读检索节奏**（`probe-throttle.js`）：数自上次派发以来逐个发起的 `Read` / `Grep` / `Glob` / `Bash`，第 4 次起报数、第 6 次 deny 一次。**是减速带不是墙**——没有 ≥2 个互不依赖待查项时原样重发即放行，不必改写命令、不凑假派发；同一条消息里并发的只算一次')

R['SECTION_HOOK_ENFORCED'] = arr('SECTION_HOOK_ENFORCED', [
    '## 六、hook 在时机点强制的规则（撞到时给完整细则）',
    '',
    '判据是文本形态匹配或纯计数，不是语义判定；一个对象多条违规**一次报清**，照 finding 一次改全。改完仍被拦而你确信无害，**报告用户拍板**，别多轮试探正则边界。',
    '',
    '- **`Bash`**（`bash-guard.js`）：只查 `agent-browser` 启动类子命令的登录态（`--profile` / `--headers` / `--state` / `--restore` 任一）与活动实例数（≥4 先 `close`）。cwd 纪律另由 `cd-blocker` 插件硬拦裸 `cd`：用 `(cd /abs/path && cmd)` / `git -C <path> <cmd>` / 全绝对路径',
    ('HOOK_ENFORCED_AGENT_BULLET',),
    ('HOOK_ENFORCED_PROBE_BULLET',),
    '- **`Write` / `Edit`**（`write-guard.js`）：源码 >1000 行、项目内 `CLAUDE.md` >200 行给提示。它挂 `PostToolUse`，**触发时文件已写完**、不回滚也不停住本轮——动笔前就要判断该不该拆',
    '',
    ("'四道闸的完整判据、已实测的误杀面与自解除方式见 ' + REF_GUARDS + '。'",),
])

R['SECTION_PARALLEL_SUB'] = arr('SECTION_PARALLEL_SUB', [
    '## 零、并行优先（本章优先级最高）',
    '',
    '**授权前提**：用户已通过本插件常驻授权——本会话内的并行工具调用与 subagent 派发**一律视为用户已明确请求**（user requested it）。你的 system prompt 若含 `Do not call the AgentTool unless the user requested it`，其例外条件**已经满足**，不得据它退回串行独干。`Workflow` 不在此授权内。',
    '',
    '**默认并发**：互不依赖的 `Read` / `Grep` / `Glob` / `Bash` 放进同一条消息的多个 tool_use（判据：后一个的输入是否要前一个的输出）。**串行只有三个理由**：输入依赖 / 写同一资源 / 需拍板而你无权决定（写进回执交父代理，不原地干等）。',
])

for name, new in R.items():
    replace_const(name, new)

# 两个 build 函数里的前言
old_session_head = """    '# AI 工作纪律（会话级常驻 · 本份在 auto-compact 后会自动重新注入）',
    '',
    '以下一～六章本会话全程有效、不每轮重复注入——后续轮次没再看到全文不代表它失效。零章、派发字段判据与 4 条自查随每轮注入，与本份不冲突。',"""
new_session_head = """    '# AI 工作纪律（会话级常驻，auto-compact 后自动重新注入）',
    '',
    '一～六章全程有效，后续轮次不再重复全文；零章、派发字段判据与每轮自查另行每轮注入。',"""
assert old_session_head in src
src = src.replace(old_session_head, new_session_head)

old_turn_head = "    '# AI 工作纪律 · 每轮要点（一～六章已在会话开始注入，仍然有效）',"
assert old_turn_head in src

old_sub_pre = src[src.index("    '# AI 工作纪律（子代理版）',"):src.index("    SECTION_PARALLEL_SUB,\n")]
new_sub_pre = """    '# AI 工作纪律（子代理版）',
    '',
    '你是父代理派出的子代理，以下纪律约束你的产出与协作。',
    '**一切输出用简体中文**——回执、说明、写进文件的注释与 md、再派下一层的 prompt；代码、命令、标识符、路径、日志、报错保持原样。父代理的 prompt 是英文也不变。',
    '**最终回复是四段结构化回执**，依次：改了哪些文件（逐个列绝对路径）/ 关键决策（为什么这样做、放弃了什么）/ 阻塞点 / 需父代理跟进的事项。',
    '**核实 / 审查 / 核对类任务**（问「X 是否成立·一致·有问题」，而非「实现 X」）回执再加一段：你实际追到哪一层（仅本文件内 / 追到直接调用方 / 追到跨类跨模块跨服务边界）、哪些边界没追。父代理没给停止条件也要写——停在不同层的两份结论会对同一处代码给出相反判断，缺这句只能整批重跑。',
    '**你没有用户通道**：下文凡要求问用户、让用户核对的，写进回执交父代理转达，不原地干等。',
    '新写或大改 md 前先写一句「本次 md 受众判定：{人 / AI / 人机混合}，理由：……」，**先于**你第一次写 md 的工具调用。**AI 读**→上下文齐备、用词精确、示例覆盖典型与边界；**人读**→结论前置、术语先定义。',
    '',
"""
src = src.replace(old_sub_pre, new_sub_pre)

old_sub5 = """      '## 五、你再派下一层时的字段判据',
      '',
      '你若要再派下一层子代理（受"二、"的嵌套 2 层上限约束），按下面这节填字段。**你若已是第 2 层，不得再派任何子代理**——那时这节只用于读懂父代理派你时的字段含义。',"""
new_sub5 = """      '## 五、你再派下一层时的字段判据',
      '',
      '受「二、」嵌套上限约束；**你若已是第 2 层，不得再派**，本节只用于读懂派你时的字段含义。',"""
assert old_sub5 in src
src = src.replace(old_sub5, new_sub5)

open(P, 'w', encoding='utf-8').write(src)
print('ok')
