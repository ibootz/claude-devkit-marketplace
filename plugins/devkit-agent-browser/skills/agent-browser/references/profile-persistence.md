# 持久化 profile：选目录与避坑

> 运行时决策细节。SKILL.md 只留「同一 profile 路径不能被两个实例同时打开」一句核心，本文件讲清目录选择、SingletonLock 机制、独立 profile 建法。需要选 `--profile` 目录、撞到 SingletonLock、或用户还没有独立 profile 时读本文件。

`--profile` 是复用登录态的首选方式，但**传什么值**与**指向哪个目录**直接影响成败。

## `--profile` 的两种形态（行为不同）

- **传名字**（如 `--profile Default`）= 只读快照那个 Chrome profile，不改原数据；适合「借一下登录态用完即弃」。多 agent 并发时天然互不冲突——每个实例各拷一份只读快照到临时目录。
- **传路径**（如 `--profile ~/.ab-profile` 或 `/Users/.../Chrome/Profile 1`）= 持久化目录，跨重启存全状态（cookies/IndexedDB/cache）。推荐用于长期复用登录态，**仅限同一时刻只有一个实例用它**。

## SingletonLock：为什么同路径不能并发

macOS 上用户日常 Chrome 正在运行时，它当前打开的 profile 目录会被 `SingletonLock` 独占。两个 agent-browser 实例指向同一个 `--profile <路径>` 时，第二个直接退出（`exit code 21`），Chrome 原生报错逐字如下：

```
Failed to create /private/tmp/ab-lock-test/SingletonLock: File exists (17)
Failed to create a ProcessSingleton for your profile directory. This means that
running multiple instances would start multiple browser processes rather than
opening a new window in the existing process. Aborting now to avoid profile corruption.
```

**agent-browser 遇锁即硬失败**：自身没有锁检测逻辑，按 500ms 间隔重试几次后把 Chrome 的 stderr 原样抛出，表现为即时失败而非变慢。

**登录态本身不会被写坏**——Chrome 中止的理由就写在报错里（`to avoid profile corruption`）。撞了只是起不来，不必担心预热好的身份被并发写烂。

因此**「建一个固定 profile 给所有 agent 共用」这个方案不成立**。要多 agent 并发复用同一份登录态，只有两条路：

- (a) 各 agent 用 `--profile <名字>`（传名字会拷只读快照到临时目录，天然互不冲突）；
- (b) 先从真身目录派生副本，每个 agent 各用一份副本路径。

**`--session` 不解决这件事**，它隔离的是浏览器实例不是磁盘目录。反过来还有个更早的坑：两个 agent 都不传 `--session` 时会共用名为 `default` 的同一个实例、抢同一批 tab，**且不报错**。并发时 `--session` 必须各自给稳定且互异的名字。

## 目录选择纪律

- **`--profile` 一律传全路径、且指向独立 profile 目录**（专用 AI Testing profile，或 `mktemp -d` 临时目录）。指向用户日常主力 profile 会让 CFT 与用户正在用的 Chrome 争抢同一目录，后果是强制关掉用户日常 Chrome 或 CFT 干脆起不来。
- 纯隔离测试（匿名公开页、不需要登录态）用 `--profile "$(mktemp -d)"` 起干净临时目录，零冲突。
- 若用户给的路径疑似日常 profile，先确认「这是不是你平时在用的 Chrome 窗口的 profile？」，是就让他另建一个。

## 用户还没有独立 profile 时

引导他建一个专用的（如 `AI Testing`），手动登录一次目标系统，再从 `chrome://version/` 的「个人资料路径」拿到磁盘路径交给你（注意磁盘目录名是 `Profile N`，不是 UI 显示名）。拿到后落到 `--profile <路径>`，并建议他把路径记进项目 `CLAUDE.md` / memory 方便下次复用。一次性的 UI 点击步骤由用户完成，你只负责拿到路径、注入 `--profile`、并在路径看起来是日常 profile 时拦一下。
