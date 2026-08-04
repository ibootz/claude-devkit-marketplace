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

约 600 字符，要点四条：

1. 形态 `[<文件名>:<行号>](file:///<绝对路径>#<行号>)`；
2. 行号写 `#` 后而非 `:` 后（iTerm2 只认这个位置），**没有具体行号补 `#1`**；
3. href 必须绝对路径（`file://` + `/` = 三条斜杠）；
4. **只对确认存在的文件套链接**（判据见下一节）；
5. 其余不适用场景：代码块与命令行内部、commit message、写进文件的 md 与代码、派给子代理的
   prompt、提交给外部系统的内容、不在本机的路径（他人仓库 / 报错原文 / 纯举例）。

**为什么第 2 条要补 `#1`**：无片段时 `\2` 会替换成空串，命令变成 `code --goto "/abs/path:"`，
是否可用取决于编辑器对尾随冒号的容忍度。一律带片段就不必依赖这个未定行为。

## 已存在 vs 尚未创建（1.1.0 补的判据）

**只对确认存在的文件套链接。** 判据取 AI 自己的状态，不需要猜语义：

| 情形 | 怎么写 |
|------|--------|
| Read / Edit / Grep / `ls` 见过，或工具结果里出现过 | 套链接 |
| 正在提议新建、落点还没定 | 裸 inline code，如 `plugins/foo/bar.js` |
| 同一轮里 `Write` 已建好，之后再提它 | 按已存在处理，套链接 |
| 拿不准 | 不套 |

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

## 关闭

```bash
export CLICKABLE_PATHS=off     # 或 0 / false
```

纯注入类 hook，不拦截任何工具调用，失败模式只是「多占了约 600 字符上下文预算」。

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
