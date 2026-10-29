# devkit-agent-browser — 浏览器自动化最佳实践

基于 [Vercel agent-browser](https://github.com/vercel-labs/agent-browser)（headless 浏览器自动化 CLI，Rust + CDP 直连 Chrome-for-Testing）的使用指令。**默认 headless 运行**，用四道机制替代「看到浏览器窗口」的监督。

## 为什么需要

headless 浏览器下人类看不到画面、无法中途授权或纠错，盲目自动化会出三类事故：

1. 登录失败（headless 没法点登录/过验证码）
2. 资源耗尽（一次开一堆 CFT 实例）
3. 操作错了不知道（看不到点了什么、跳到哪）

本插件把官方最佳实践压成一份会话开头注入的短规则，配套 `devkit-discipline` 的 guard 做硬护栏；通用操作（snapshot、refs、命令速查）交给 CLI 自带说明 `agent-browser skills get core`，随 CLI 版本更新。

## 四道机制

| 机制 | 解决 | 强制度 |
|------|------|--------|
| 鉴权前置 | 启动前先**盘点本机已有来源**（profile / vault / 凭据管理 CLI / 项目文档免登入口），四行全空才向用户索取账密/token/cookie | guard 硬拦 |
| 实例上限 4 | 全局最多 4 个并发实例（agent-browser 无内置上限） | guard 硬拦 |
| 登录态复用 | 持久化 `--profile`，跨会话不重登 | guard 硬拦 |
| snapshot + 标注截图 | headless 下靠结构化快照与 `--annotate` 截图回看每步 | CLI 自带说明（`skills get core`） |

## 组成：2 个 hook + 1 份按需读的参考文档（零 skill，2.1.0 起）

- `hooks/session-start.js`（SessionStart，1.4.0 起）— 注入 `context/session-start.md`：浏览器交互只用 agent-browser、不用 `browser-harness` 与 playwright 系 MCP、动手前先跑 `agent-browser skills get core`、每次新起 Chrome for Testing 实例、登录态复用二选一，以及 2.1.0 从原 skill 压进来的护栏——鉴权先盘点本机四个来源、启动前 `session list` 且 ≥4 先关、同一 profile 路径不能两实例同开、headless 必带 `--allowed-domains` 与 `--content-boundaries`、被风控时切 `--headed`。改规则改那份 md。正文里的 `${CLAUDE_PLUGIN_ROOT}` 由脚本替换成插件根目录绝对路径后再注入
- `references/profile-persistence.md` — `--profile` 选目录、SingletonLock、建独立 profile 的细节；注入里给它的绝对路径，撞到相关情形时才读
- `hooks/session-end-cleanup.js`（SessionEnd）— 会话结束清理本会话起的实例

> 硬护栏（鉴权检查 / 实例计数）不在本插件，在 `devkit-discipline` 的 `bash-guard`，避免两个插件抢同一道 Bash 闸。

## 一句话用法

装上即生效，无需调用：**先盘点本机已有鉴权来源（为空才问用户要）→ `session list` 确认实例数 → `--profile` 注入登录态 → `open` → `snapshot -i` → 按 `@eN` 操作 → `screenshot --annotate` 复核 → `close`**。

---

## 版本记录

### 2.1.0（2026-10-29）删掉 `agent-browser` skill，护栏压进会话注入

**改了什么：** 删除 `skills/agent-browser/`（SKILL.md 211 行）。其中 CLI 自带说明不覆盖的护栏压成 5 条短句并入 `context/session-start.md`，注入从 625 字增到 1266 字。`references/profile-persistence.md` 从 skill 目录挪到插件根，注入里给绝对路径；`hooks/session-start.js` 新增把正文 `${CLAUDE_PLUGIN_ROOT}` 换成插件根目录的占位替换。

**为什么：** 这个 skill 常驻占预算却几乎不被加载。统计口径是本机 80 天的会话记录（转述主会话的统计，本次未复核）：

- 1017 个会话中 740 个的 skill 清单里带着它的说明；
- 实际跑过浏览器的 30 个会话里，它被加载 **0 次**；
- 真正起作用的是注入里那句「动手前先跑 `agent-browser skills get core`」。

用户 2026-10-29 拍板删除。

**搬了什么、丢了什么：**

| 原 SKILL.md 内容 | 去向 |
|---|---|
| 鉴权盘点四来源、全空才问用户、何时跳过 | 注入 |
| 实例上限 4、启动前 `session list`、用完即关 | 注入 |
| 同一 profile 不能两实例同开（SingletonLock，exit 21） | 注入一句 + `references/profile-persistence.md` |
| headless 必带 `--allowed-domains`、`--content-boundaries`，建议 `--max-output` | 注入 |
| 被风控反复跳登录时切 `--headed` | 注入 |
| headless 工作流、snapshot / refs 纪律、命令速查 | 不搬，`agent-browser skills get core` 已讲 |
| 鉴权注入四法表、`--confirm-actions` / `--action-policy`、CDP 警告、三层清理与 SessionEnd 1.5s 预算说明、常见错误表 | 不搬；需要时看 `git show` 历史版本 |

**代价：** Codex 侧按插件目录安装时原本只能拿到这个 skill，删除后该安装方式不再带任何内容；走 `node scripts/install-codex.js` 安装时 SessionStart hook 会挂上（Codex 是否执行它、是否收 `additionalContext` 未核实）。

**回退：** `git revert` 本次提交，或从上一版恢复 `skills/agent-browser/` 整个目录并把注入最后一条改回「鉴权盘点、实例上限、安全边界的完整做法在 agent-browser skill 里，启动浏览器前读它」。
