# clickable-paths — 文件路径写成可点击链接

在 iTerm2 里跑 Claude Code CLI 时，AI 输出的文件路径默认只是一段普通文本，看到了也得自己
复制、切窗口、粘贴、翻行号。这个插件每轮注入一段极短的输出格式规约，让 AI 把路径写成
markdown 链接——终端里只显示 `文件名:行号` 一小段带下划线的文本，**cmd+click 直接跳到
VS Code 的对应行**。

GUI 版 Claude 与 VS Code 插件里本来就有这个体验，本插件把它补回终端。

## 效果

AI 输出这样一行 markdown：

```
[agent-dispatch.js:414](file:///Users/you/repo/plugins/x/hooks/guards/agent-dispatch.js#414)
```

iTerm2 里渲染成一个可点击的 `agent-dispatch.js:414`（蓝色带下划线），完整路径藏在链接里
不占屏。

## 三段机制（都已实测，2026-08-04 · CC 2.1.220 + iTerm2 3.6.11）

| 环节 | 行为 |
|------|------|
| Claude Code 渲染器 | markdown link 对 `file:` scheme 有专用处理：解析成绝对路径、**保留 `#片段`**、显示文本取方括号标签；终端支持超链接时发 OSC 8 序列，不支持则退化成 `标签 (file:///…)` 纯文本 |
| iTerm2 3.4+ | OSC 8 链接若为 `file` scheme **且带 `#` 片段**，套用 Semantic History 规则打开（官方 escape codes 文档明文）。所以行号必须写在 `#` 后面 |
| Semantic History | 把点击动作交给你配的命令，`\1` = 文件名、`\2` = 行号 |

## 安装后必须配这一步（不配就只是一个打不开的链接）

iTerm2 → Preferences（⌘,）→ **Profiles** → 选中你在用的 profile → **Advanced** →
下拉找到 **Semantic History** → 选 `Run command...` → 填：

```
/opt/homebrew/bin/code --goto "\1:\2"
```

**必须写 `code` 的绝对路径。** iTerm2 执行这条命令不经登录 shell，继承的是 launchd 环境，
`launchctl getenv PATH` 常常是空的——填成 `code --goto "\1:\2"` 会**静默失败**。
`code` 的实际位置用 `which code` 查（Homebrew 装的通常是 `/opt/homebrew/bin/code`，
Intel 机器或官方安装脚本可能是 `/usr/local/bin/code`）。

**排查失败**：iTerm2 会往 `~/Library/Preferences/com.googlecode.iterm2.plist` 写一条
`NoSyncSemanticHistoryCommandFailed_<完整命令>` = true 的 key，里面是 `\1`/`\2` 替换后的
真实命令，grep 它比猜快得多。

用别的编辑器就换命令，例如：

```
/usr/local/bin/subl "\1:\2"                      # Sublime Text
/opt/homebrew/bin/idea --line "\2" "\1"          # IntelliJ IDEA
```

## 注入了什么

约 930 字符（450 → 730 → 930，两次扩容多出来的全是判据），要点七条：

1. 形态 `[<文件名>:<行号>](file:///<绝对路径>#<行号>)`，**对话正文里每提到一个本机文件就给
   一个链接**；
2. **三种漏套形态点名写出来**：只写文件名（`decisions.md`）、写成裸 `path/to/file.ext:130`、
   用反引号包成 inline code；
3. 行号写 `#` 后而非 `:` 后（iTerm2 只认这个位置），**没有具体行号补 `#1`**；
4. href 必须绝对路径（`file://` + `/` = 三条斜杠）；
5. **适用面显式圈定**：表格单元格、列表项、四要素的「现场证据」段、转述子代理回执的那几行，
   都算对话正文；
6. 不适用场景：代码块与命令行内部、commit message、写进文件的 md 与代码、派给子代理的
   prompt、提交给外部系统的内容、不在本机的路径（他人仓库 / 报错原文 / 纯举例）；
7. **队列编号 `DBG-NNN` / `CHR-NNN` 同样算文件**（1.5.0 加），并要求链接后紧跟括号写
   ≤20 字问题简述——见下一节。

**为什么第 3 条要补 `#1`**：无片段时 `\2` 会替换成空串，命令变成 `code --goto "/abs/path:"`，
是否可用取决于编辑器对尾随冒号的容忍度。一律带片段就不必依赖这个未定行为。

## 1.5.0 把 task-keeper 的队列编号也算作文件

`DBG-140` / `CHR-014` 在对话里被反复提到，但**通篇零链接**——与 1.4.0 那次实测同一个病，
成因不同：规约的判据是「提到一个本机**文件**」，而编号在 AI 眼里是一条 issue 的**标识符**，
不是文件，规约看着根本不适用。所以 1.5.0 在判据里直接写死「编号是队列条目的别名，说到编号
就是说到那条条目文件」，堵掉这层语义落差。

链接目标按队列分，两个文件名**不可互换**：

| 编号 | 条目文件 |
|---|---|
| `DBG-NNN` | `.keeper/<交付id>/debug/DBG-NNN/issue.md` |
| `CHR-NNN` | `.keeper/<交付id>/chore/CHR-NNN/item.md` |

`<交付id>` 是 hook 无法用模板表达的那一段——写死占位符会产出 `<` `>`，那是非法 URL 字符，
链接会**静默失效**（渲染成普通文本，看不出坏）。所以 hook 改为**从磁盘现探**：从 `cwd` 向上
最多 8 层找 `.keeper/`，把实际存在的 debug / chore 目录各铺一行完整样例进注入，AI 逐字照抄
形状即可。没有 `.keeper/` 的项目不铺这一段，注入回到原来的六条。

编号后要紧跟 ≤20 字问题简述（`[DBG-140](file://…#1)（导出接口 500）`），因为编号本身零语义，
只看编号无法判断值不值得点进去。

## 1.4.0 为什么要收紧措辞（一次通篇零链接的实测）

2026-08-18 的一轮真实输出里，`gates.g3` / `decisions.md` / `contracts.md` / `tasks.md` /
`_index.md` **全部写成了 inline code**，四要素的「现场证据」段写成裸
`sdlc/deliveries/…/decisions.md:130`，通篇零链接——规约在场、每轮注入、退出码 0，
只是没被执行。三个成因各自对应 1.4.0 的一处改动：

| 成因 | 1.3.0 的写法 | 1.4.0 的改法 |
|---|---|---|
| **替代形态比目标形态更容易触达** | 「不套链接就改用 inline code」——而 inline code 恰好是模型提到文件名时的默认写法，等于给了一条随时可走的退路；「拿不准按不存在处理」进一步把它变成安全默认 | 把三种漏套形态**点名**写出来，并把 inline code 收窄成「只留给落点还没定的新文件」；拿不准时改成**先 `ls` / `Grep` 确认再写** |
| **只写文件名不像「路径」** | 规约通篇说「路径」，而 `decisions.md` 这种裸文件名读起来不是路径，规约看着不适用 | 首句改成「每提到一个本机文件」，并把 `decisions.md` 作为反例直接写进去 |
| **裸 `path:行号` 已被别的规约要求** | 没提 `working-discipline` 3.3 与 `readable-citations`，而那两份每轮注入的正文里就摆着 `path/to/file.ext:行号` 的模板——模型满足了 3.3 就以为交付完了 | 写明「3.3 要的信息由链接标签与 `#行号` 一并承载，套成链接同时满足两边；写成裸路径只满足它们、漏了本条」 |

判据都落在**文本形态**上（哪三种形态算漏、哪四类场合算对话正文），不留「视情况」这类无判准
表述——这是注入类 hook 唯一能提高遵循度的地方，它没有拦截能力，写不清就等于没写。

## 已存在 vs 尚未创建（1.1.0 补的判据）

**只对确认存在的文件套链接。** 判据取 AI 自己的状态，不需要猜语义：

| 情形 | 怎么写 |
|------|--------|
| Read / Edit / Grep / `ls` 见过，或工具结果里出现过 | 套链接 |
| 正在提议新建、落点还没定 | 裸 inline code，如 `plugins/foo/bar.js` |
| 同一轮里 `Write` 已建好，之后再提它 | 按已存在处理，套链接 |
| 拿不准 | 先 `ls` / `Grep` 确认存在性再写；确认不到才退回 inline code，不编造绝对路径 |

三个理由，第二个最要紧：

1. 点开一个不存在的路径，VS Code 会开一个**空白未保存 buffer**——不报错，但会让人怀疑
   整套机制不可靠，比"不可点击"更糟。
2. **为凑格式而编造绝对路径**是信息失真。目录结构还没定就被迫写出一个看似确定的路径，
   比路径不可点击的代价大得多。规约明确要求：落点待定就如实写待定。
3. 反向失效：若不给这条判据，AI 可能因拿不准存在性而索性都不套，已有文件也点不动。

1.0.0 的不适用清单里只有一条「不存在于本机的路径」，举的三个例子（他人仓库 / 报错原文 /
纯举例）都不含「打算新建」这种情形，AI 大概率不会归类进去——1.1.0 把它单列成独立判据。

## 与 working-discipline 3.3 四要素的关系

那条要求「引用类与方法一律带 `path/to/file.ext:行号`」，目的是让人不打开文件就能判断。
本插件的形态**满足它且更强**：完整绝对路径在 href 里、点开即到。标签默认只写
`<文件名>:<行号>` 保持简短，同名文件在一轮里出现多处时才换成相对仓库根的路径。

## 主会话与子代理都注入（1.3.0 补的）

1.2.0 及之前只挂 `UserPromptSubmit`，于是**子代理回执里的文件路径从来不可点**。

原因是 `UserPromptSubmit` 只触达主会话——它的语义是「用户在交互界面提交了一次 prompt」，
而子代理由 `Agent` / `Task` 工具编程派发任务字符串，不存在这个动作。这类落点错误**没有
任何报错**：hook 正常执行、正常输出、退出码 0，只是那段文本永远不出现在子代理的上下文里。
本仓有同型实测记录（codegraph 引导注入主会话 20 次，而真正做检索的子代理 23 份 transcript
里零调用），判据见 `.claude/rules/project/hook-restraint.md` 的「注入类 hook 的事件落点」一节。

1.3.0 起双挂 `UserPromptSubmit` + `SubagentStart`，共用同一个脚本，输出的
`hookSpecificOutput.hookEventName` **按入参回声**——写死任一个会让另一路静默失效。

回归用例：

```bash
node plugins/clickable-paths/hooks/tests/clickable-paths.test.js
```

11 条：前 7 条覆盖两个事件各自的回声正确性、两路注入内容一致、白名单外事件不回声、关闭开关、
空 stdin、畸形 JSON；1.4.0 加的 4 条守注入正文的判据不被日后精简掉——三种漏套形态点名在场、
四类适用场合在场、与 `working-discipline` 3.3 的关系在场、`#1` 兜底与三斜杠 href 在场。

## 与 readable-citations 的分工

两个插件都在让引用可跳转，管的东西不重叠，同时装不冲突：

| | clickable-paths（本插件） | readable-citations |
|---|---|---|
| 管什么 | 提到**文件**时的路径 | 引用 **md 文档的章节** |
| 作用范围 | 只管对话正文，明文把「写进文件的 md」排除在外 | 对话正文与落盘 md 都管 |
| 形态 | `[文件名:行号](file:///绝对路径#行号)` | 对话正文同左；落盘 md 走相对路径 + 标题锚点 |

判据：**引用的是一份 md 文档里的某一节** → 那个插件；**提到一个源码文件的某一行** →
本插件，锚点对 `.js` / `.py` 这类文件无效。

## 关闭

```bash
export CLICKABLE_PATHS=off     # 或 0 / false
```

纯注入类 hook，不拦截任何工具调用，失败模式只是「多占了约 730 字符上下文预算」。

## 已知走不通的路

- **`vscode://file/路径:行号` 自定义 scheme**：Claude Code 只对 `file:` 做了特殊处理，
  非 http/https/file 的 scheme 不会被包成 OSC 8（anthropics/claude-code#42519）。
- **VS Code 自带集成终端**：这类链接在那里点不动，是 VS Code 侧的 bug
  （microsoft/vscode#242371），与 iTerm2 无关。
- **tmux 内**：社区报告 OSC 8 会失效，未实测。

## 渲染没生效怎么办

若看到的是 `文件名 (file:///…)` 这种纯文本，说明 Claude Code 的终端能力检测没通过。
它的二进制里有 `FORCE_HYPERLINK` 与 `supportsHyperlinks`，可试：

```bash
export FORCE_HYPERLINK=1
```
