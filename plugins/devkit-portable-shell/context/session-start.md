# 交付脚本跨平台（devkit-portable-shell 插件，会话级）

适用于会在别人机器上运行的东西：交付的脚本、插件 hook、写进文档供人照抄的命令。只在本机跑一次的临时命令不受约束。

- 不写 `.sh` / `.bash`。由配置文件调起的（`hooks.json` 的 `command`、`package.json` 的 scripts）用 JS，以 `node` 调起——node 是 macOS / Windows 唯一同名的解释器，而这类配置没有按平台分 command 的机制。由 `Bash` 工具或使用者手动执行的用 Python。
- 解析 Python 解释器时依次试 `python3` → `python` → `py -3`，以真正执行一次 `--version` 成功为准。只查 PATH 不够：Windows 的 `WindowsApps\python3` 是 Microsoft Store 的零字节桩，查得到、跑不了，`which('python3') or which('python')` 这种回落链会因此失效。
- Python 脚本调用另一个 Python 脚本用 `sys.executable`，不回 PATH 重新找。
- 调外部 CLI 前先解析出可执行文件路径再传给 `subprocess`：Windows 上 npm 装的 CLI 是 `.cmd`，裸命令名会报成「没安装」。
- 输出中文前先把 stdout 设成 UTF-8，否则 cmd 默认代码页下脚本会 `UnicodeEncodeError`。
- 命令示例用单引号：值以 `$` 开头时，双引号在 bash 里会展开成空串，命令照样返回 0。
- 文档正文写 `python3`，只在一处集中说明「Windows 换成 `python` 或 `py -3`」。
- 明确只用于单一平台的产物，在文件里写明「本文件只用于 X 平台」。
