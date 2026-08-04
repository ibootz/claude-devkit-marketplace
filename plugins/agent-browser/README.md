# agent-browser — 浏览器自动化最佳实践

基于 [Vercel agent-browser](https://github.com/vercel-labs/agent-browser)（headless 浏览器自动化 CLI，Rust + CDP 直连 Chrome-for-Testing）的使用指令。**默认 headless 运行**，用四道机制替代「看到浏览器窗口」的监督。

## 为什么需要

headless 浏览器下人类看不到画面、无法中途授权或纠错，盲目自动化会出三类事故：

1. 登录失败（headless 没法点登录/过验证码）
2. 资源耗尽（一次开一堆 CFT 实例）
3. 操作错了不知道（看不到点了什么、跳到哪）

本插件把官方最佳实践固化成指令，配套 `working-discipline` 的 guard 做硬护栏。

## 四道机制

| 机制 | 解决 | 强制度 |
|------|------|--------|
| 鉴权前置 | 启动前先**盘点本机已有来源**（profile / vault / 凭据管理 CLI / 项目文档免登入口），四行全空才向用户索取账密/token/cookie | guard 硬拦 |
| 实例上限 4 | 全局最多 4 个并发实例（agent-browser 无内置上限） | guard 硬拦 |
| 登录态复用 | 持久化 `--profile`，跨会话不重登 | guard 硬拦 |
| snapshot + 标注截图 | headless 下靠结构化快照与 `--annotate` 截图回看每步 | 指令约束 |

## 组成：1 个 Skill

- `skills/agent-browser/SKILL.md` — 完整工作流、鉴权注入四法、实例管理、安全边界、命令速查、操作约束

> 硬护栏（鉴权检查 / 实例计数）不在本插件，在 `working-discipline` 的 `bash-guard`，避免两个插件抢同一道 Bash 闸。

## 一句话用法

触发后按指令走：**先盘点本机已有鉴权来源（为空才问用户要）→ `session list` 确认实例数 → `--profile` 注入登录态 → `open` → `snapshot -i` → 按 `@eN` 操作 → `screenshot --annotate` 复核 → `close`**。
