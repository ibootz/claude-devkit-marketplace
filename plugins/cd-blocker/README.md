# cd-blocker

在命令执行前拦下会污染会话 cwd 的独立 `cd`，并把可照抄的改法回灌给 AI。

一个 hook、零 skill、零常驻注入——不装它时上下文成本为 0，装了也不占每轮预算。

## 为什么它是独立插件（1.0.0 从 working-discipline 3.25.0 拆出）

拆分动因不是"文件太大"，而是**这条约束会与写侧约束在特定项目里顶死，顶死时需要一个开关**。

实测场景：从 worktree 会话去改主仓的常驻产物。写侧约束要求先 `cd` 到主仓，而本 guard 把独立
`cd` 判为阻断——它给的两种改法（绝对路径 / 子 shell）**在定义上都不改变会话 cwd**，所以两条
约束各自都成立、交集为空。这不是判据 bug，是两条规则的适用范围真的撞上了。

拆分前 cd 检查与 `agent-browser` 四护栏合并在 `working-discipline` 的 `bash-guard.js` 里，
想关掉 cd 就只有两条路：连 `agent-browser` 护栏一起关，或者停掉整个纪律注入插件。两者代价都
远大于"这个项目里允许改会话 cwd"。独立成插件后，`/plugin` 里停用本插件即可，其余约束不受影响。

**代价要如实知道**：`Bash` 现在有两道闸（本插件 + `working-discipline` 的 `bash-guard.js`）。
两个插件同时装时两道闸都跑，同一条命令的 cd 违规与 `agent-browser` 违规**不再一次报清**，AI
可能改完一处才看见另一处。`working-discipline` 3.0.0 收敛挂载拓扑正是为了消除这种多轮往返，
这次把它换成了「可单独停用」。

## 它拦什么

`PreToolUse` + matcher `Bash`，命中即 `exit 2` 阻断。

| | |
|---|---|
| **阻断** | 顶层片段以裸 `cd` 开头，且目标不是 no-op |
| **放行** | 子 shell `(cd /path && cmd)`、命令替换 `$(cd /path && pwd)`、字符串内的 `cd`（`echo "cd /tmp"`）、heredoc 正文里的 `cd`、以单个 `&` 后台化的片段、no-op cd（`cd .`、`cd $PWD`、`cd ${PWD}`、`cd <当前目录绝对路径>`，含符号链接等价与大小写等价路径） |

拦截输出（stderr，会作为附加上下文注入 Claude，控制在 400 字符量级）：

```text
[L1-BLOCKER] tool=Bash check=cd-guard finding="独立 `cd` 会污染后续所有 Bash 调用的 cwd(cwd=/x);违规片段：cd /var" hint="改用绝对路径,或子 shell `(cd /abs/path && cmd)`,git 命令优先 `git -C <path> <cmd>`;确实必须改变会话 cwd（如从 worktree 会话改主仓常驻产物）时报告用户,由他决定单次 CD_GUARD=off 还是停用 cd-blocker 插件"
```

**为什么值得存在**：Bash 工具的 cwd 在多次调用之间持久保留。AI 中间执行一次 `cd /tmp`，后续
所有相对路径操作都会失准——"为什么找不到 requirements/foo"这类现象排查半天才发现根因是 cwd
被静默改掉了。而 hint 里给的是**可直接照抄的模板**，实测撞到的 AI 一次就改对；同一条规则以软
文本注入时，同一个 AI 读过却照样违反。

## 怎么关

| 场景 | 做法 |
|---|---|
| 单次放行（长任务中途撞上顶死） | `CD_GUARD=off <命令>` 环境变量 |
| 某个项目长期不要它 | `/plugin` 里对该项目停用 cd-blocker |
| 全局不要它 | `/plugin` 里卸载 |

判据变更（正则、阈值、放行清单）**不是 AI 可以自行决定的**，见仓库规则
`.claude/rules/project/hook-restraint.md` 第 4 条：发现误杀只报不改，把可复现的输入与实际输出
交用户拍板。

## 判据的真实覆盖面

实际判据是「剥掉 heredoc 正文与子 shell 后，由 `; && || | 换行` 切出的顶层片段、`trim()` 后
以 `cd` 开头」（`hooks/guards/cd-guard.js` 的 `CD_PATTERN` 与 `checkCd()`）。它抓的是**文本
形态**，不是"这条命令是否改变父 shell 的 cwd"这个语义。

这是**提醒**，不是**保证**。别把"没被拦"读成"没问题"。

### Known Limitation：只认「裸 `cd` 开头」一族，19 类真污染写法放行

2026-07-31 那次 103 条真实 payload 的审计清点出 19 类同样污染父 shell cwd、但实测全部放行的
写法。分四组看：

- **同义或改写过的调用**：`pushd /tmp`、`source ./setup.sh` 或 `. ./setup.sh`（脚本正文里有
  `cd`）、`eval 'cd /tmp'`、`\cd /tmp`、`builtin cd /tmp`、`command cd /tmp`、`"cd" /tmp`
  （引号让首 token 不再字面等于 `cd`）
- **前缀挡住了段首**：`CDPATH=/ cd tmp`（环境变量赋值前缀）、`time cd /tmp`
- **分隔符不被识别**：`git status & cd /tmp`——单个 `&` 在 `splitSegments()` 里没有语义
  （只切 `&&`），整段被当成一个片段，而它以 `git` 开头
- **复合结构里分支标签排在 `cd` 之前**：`if ...; then cd /tmp; fi`、`{ cd /tmp; }`、
  `for d in *; do cd $d; done`、`case $x in a) cd /tmp;; esac`，以及函数体内的 `cd`

对照之下，本 guard 拦得住的其实只有 `cd /x`、`foo && cd /x`、`foo; cd /x` 这一族。

**19 类漏报按用户拍板不补**：补一条就多一个误杀面，且永远补不全 shell 语法。这也是仓库规则
`hook-restraint.md` 里「判据抓的是文本形态而非真实风险」那条的实证来源。

### Known Limitation：`stripSubshells` 的括号匹配不感知引号，一个假括号就能让真 `cd` 隐形

`hooks/lib/shell-parse.js` 剥子 shell 用的是 `/\([^()]*\)/g` 这个纯字符匹配，**不判断括号在
不在引号里**。引号内一个不成对的 `(` 会跟后面某个 `)` 配对，把中间的真实命令一起吃掉。
2026-07-31 的对照实测：

```text
echo "(start" && cd /tmp && echo "end)"   → exit 0 放行（cd 被整段剥离，checkCd 根本看不到它）
echo "a)" && cd /tmp                      → exit 2 拦下（只有 ) 没有 (，剥不掉）
(cd /tmp && ls) && cd /var                → exit 2 拦下（对照组：括号外的真 cd 仍在）
```

这条同时纠正了一个**因果误述**：早期文档说 `(cd /abs && cmd)` 放行是因为"cwd 不回流父进程"。
实际机制是**括号里的文本被删掉了**，guard 压根没做那个语义判断——第三行那个对照组就是旁证。
结论对同一件事仍然成立（子 shell 确实不污染父 shell），但**理由不同，而理由决定了边界**：既然
靠的是字符剥离，第一行那种"假括号"就能让真 `cd` 一起消失。

方向是**放行**（少看到东西 → 少拦），符合 `shell-parse.js` 的"宁可放行也不误拦"取向；代价是
不能据此声称自己"精确"覆盖了某类语义。

### 已知误报：shell 函数定义 `cd() { ...; }`

会被判成独立 `cd`——切分器只看到段首的 `cd` token，不区分「调用」与「定义」。真实触发过两次
（2026-07-26 与 2026-07-29）。未做特判：加一条「后跟 `()` 则跳过」会让解析器为一个近乎不存在
的场景变复杂，而绕开的成本只是删掉那行。

## 已修掉的四类误杀（随代码一起搬过来，均为审计实测的真实 BLOCK）

1. **heredoc 正文，最严重的一类**。`ssh prod bash -s <<'EOF' / cd /srv/app / git pull / EOF`
   被判成本地 cwd 污染，而那个 `cd` 在**远程主机**执行；`python3 - <<'EOF' / print(1) /
   cd /tmp / EOF` 里的 `cd` 甚至根本不是 shell 命令。根因是 heredoc 正文里的换行被
   `splitSegments()` 当成命令分隔符，于是正文每一行都被当作独立的本地命令判定。更糟的是 hint
   给的两个模板（改绝对路径 / 套子 shell）对 heredoc 正文**完全无从下手**——AI 撞上去改不动。
   修法是 `checkCd()` 先调 `stripHeredocs()` 剥离正文（只保留声明行本身，覆盖 `<<DELIM` /
   `<<-DELIM` / `<<'DELIM'` / `<<"DELIM"`，显式排除 here-string `<<<`）。
2. **`cd /tmp &`**：`&` 结尾的命令在子 shell 异步执行，父 shell 的 cwd 不变（`isBackgrounded()`）。
3. **符号链接等价**：macOS 上 cwd 为 `/private/tmp` 时 `cd /tmp` 实际是 no-op，而只做
   `path.resolve` 的字符串归一看不出来。
4. **`cd $PWD` 与大小写等价路径**（APFS 默认大小写不敏感），同上，按字面串比对会判成"真的换目录"。

违规片段回灌截断到 120 字符：原样回灌曾把 20 多行测试数据整段塞回上下文（实测单条 900+ 字符）
——一个用来纠正行为的提示，自己占掉了比被纠正的行为更多的注意力。

## 涉及 git 时优先 `git -C`，而不是子 shell

**事故来源（2026-07-20）**：subagent 要把改动 push 到一个与当前项目完全无关的第三方仓库，用的
是 `(cd /path/to/other-repo && git push origin main)`——命令本身合法，本 guard 也正常放行。但
推送被同时装着的另一个插件拦下，报了一条与该仓库毫无关系的 BLOCKED。根因在那个插件的
`resolveGitCwd()`：它用正则 `/^cd\s+.../` 匹配命令字符串**开头**的 `cd` 前缀来判定这条 git
命令作用于哪个仓库（同时显式支持 `git -C <path>`）。子 shell 语法带括号、不以 `cd` 开头，正则
天然匹配不上，于是 fall back 到当前会话所在的 worktree，把发往第三方仓库的 push 误认成本项目
的 push。

```bash
git -C /abs/path/to/repo push origin main     # 推荐
git -C /abs/path/to/repo status
(cd /abs/path && cmd)                          # 非 git 命令只能走这个，-C 是 git 专有选项
```

`-C` 是 git 官方支持的全局选项，语义等价，字面上不含 `cd` token、不进子 shell，能同时躲开本
guard 与这类跨插件误伤。遇到别的插件 cwd 探测与你的语法不兼容时，**改自己发出的命令语法，不要
去改对方插件的探测逻辑**。

## 目录结构

```text
cd-blocker/
├── .claude-plugin/plugin.json          # 只注册一个 PreToolUse(Bash) hook
├── hooks/
│   ├── guards/cd-guard.js              # 判据与文案，全部在这里
│   └── lib/shell-parse.js              # splitSegments / stripSubshells / stripHeredocs
├── tests/cd-guard.test.js              # 35 条回归，判据两侧齐全
└── README.md
```

没有 `.codex-plugin/`：本插件全部效力来自 `PreToolUse`，那是 Claude Code 专有机制，Codex 侧
装了也不生效，不做无效登记。

## 改判据后必跑回归

```bash
node plugins/cd-blocker/tests/cd-guard.test.js
```

35 条用例覆盖三组：曾经误杀现在应放行（heredoc 五种形态、后台化、`$PWD`、符号链接、大小写）、
仍必须拦（裸 cd / 链尾 / 换行后 / `cd ..` / 无参数 / 子 shell 之后 / heredoc 结束之后）、原本
正确放行不得回归成误杀（子 shell、嵌套、命令替换、字符串内、`cd .`、here-string），外加逃生口
（`CD_GUARD=off` 生效、非 `off` 值不生效）与四条基础设施异常（非 Bash 工具、command 缺失、
stdin 非 JSON、cwd 缺失）。

**只测一侧等于没测**：只测放行会把 guard 改废，只测拦截发现不了误杀。

用 `spawnSync` 把 payload 直接写进子进程 stdin，**全程不经过 shell**。用
`echo '<payload>' | node <guard>` 那种形式时，测试脚本自身的引号一旦失衡，后面的测试数据就变成
裸命令——2026-07-31 审计真撞过一次：guard 把审计脚本里 20 多行测试数据当成真命令拦下，并原样
回灌进 finding。

## 与 working-discipline 的关系

- 代码与判据是从 `working-discipline` 3.25.0 的 `hooks/guards/bash-guard.js` **逐字搬来**的，
  行为不变。那边同批删掉了 `checkCd` 及其五个辅助函数。
- `hooks/lib/shell-parse.js` 是**物理副本**。插件之间不能 `require` 对方的路径（各自装在独立的
  plugin 缓存目录下，路径不可预测且版本可能不同），所以这里是故意重复。本份只留 cd 判定要用的
  三个导出，那边只留 `agent-browser` 判定要用的三个——两边**导出面已经不同，不要"顺手统一"**。
- **同步义务**：任一侧修了 `splitSegments` 这类共有函数，另一侧手动同步，改完两边各跑一次自己
  的回归套件（本插件的 `tests/cd-guard.test.js` 与那边的 `test/guard-verify.js`）。
- `working-discipline` 的 `test/guard-verify.js` 留了一条**反向断言**：裸 `cd` 必须已经不被
  `bash-guard` 拦。少了它，哪天 cd 判据被误合回去就没人发现，两个插件会对同一条命令各拦一次。
