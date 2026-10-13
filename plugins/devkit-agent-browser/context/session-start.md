# 浏览器自动化（devkit-agent-browser 插件，会话级）

- 需要浏览器交互时（打开页面、填表、点击、截图、抓数据、测试 web 应用、自动化 Electron 应用），只用 `agent-browser` CLI。`browser-harness` CLI 与 `mcp__*playwright*` 系工具都不用：前者会独占用户当前 Chrome 的调试会话，后者不随 agent-browser 的版本同步。
- 动手前先跑 `agent-browser skills get core`，取当前安装版本的用法；专用场景用 `agent-browser skills list` 查。未安装时执行 `npm i -g agent-browser && agent-browser install`。
- 每次新起独立的 Chrome for Testing 实例，不连用户正在使用的 Chrome 主实例——共用会抢 tab、覆盖用户手上的调试状态。`--profile` 传全路径，不指向用户日常使用的 profile。
- 复用登录态按项目自己的免登指引二选一：应用支持的免登入口（如 URL 里注入 JWT），或 `--profile` 指向可复用的 profile 目录。用户当轮指定了哪种就用哪种。
- 鉴权盘点、实例上限、安全边界的完整做法在 `agent-browser` skill 里，启动浏览器前读它。
