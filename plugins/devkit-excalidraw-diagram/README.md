# devkit-excalidraw-diagram — Excalidraw 图解

让 AI 把概念、架构、流程画成**可编辑的 `.excalidraw` 文件**，并把它渲染成 PNG 自己回看、迭代修版，直到排版过关才交付。
生成的文件可以直接拖进 [excalidraw.com](https://excalidraw.com) 或 Obsidian Excalidraw 继续改。

移植自 [coleam00/excalidraw-diagram-skill](https://github.com/coleam00/excalidraw-diagram-skill)（上游提交 `8646fcc`，2026-03-01）。


## 什么时候触发

| 说法 | 走哪里 |
|---|---|
| 「用 excalidraw 画个架构图」「生成一个 .excalidraw 文件」「出张能拖拽改的白板图」 | 本插件 `excalidraw-diagram` |
| 「画个图」「可视化一下」，没提 Excalidraw | `devkit-tool:show-me`（挑伪代码、调用树、Mermaid、HTML 等最小够用的视图） |

上游的触发描述是「任何想可视化流程、架构、概念的时候」，会和 `show-me` 抢同一批请求，所以这里收窄到点名 Excalidraw 或可编辑白板图。


## 前置依赖

1. **uv**（[安装说明](https://docs.astral.sh/uv/)）。渲染脚本用 PEP 723 内联声明依赖，`uv run` 首次运行时自动建环境并缓存在 uv 自己的缓存目录里。
2. **Chromium**，只需下载一次（`<skill-dir>` 是插件缓存里 `skills/excalidraw-diagram` 的绝对路径，AI 加载 skill 时能看到）：

   ```bash
   uv run '<skill-dir>/references/render_excalidraw.py' --install-browser
   ```

   漏了这步也没关系：渲染时缺 Chromium，脚本会打印上面这条命令。
3. **网络**：渲染模板从 esm.sh 加载 `@excalidraw/excalidraw`，离线环境渲染不了（生成 `.excalidraw` 文件本身不受影响）。


## 相对上游的改动

只改了「在插件里能跑起来」所必需的部分，设计方法论、视觉模式库、配色、元素模板原样保留，方便以后对照上游同步。

| 文件 | 改动 | 原因 |
|---|---|---|
| `SKILL.md` frontmatter | `description` 改为中文并收窄触发面，写明与 `show-me` 的分工 | 见上一节 |
| `SKILL.md` Setup / How to Render / First-Time Setup | 去掉 `cd .claude/skills/excalidraw-diagram/references`，改用 `<skill-dir>` 绝对路径与 `uv run <脚本>` | 插件装在缓存目录，不在 `.claude/skills/` 下 |
| `references/render_excalidraw.py` | 加 PEP 723 依赖头；新增 `--install-browser`；报错提示改成新命令；stdout/stderr 设 UTF-8 | 上游 `uv sync` 会把 `.venv` 建在 skill 目录里，插件升版本时缓存目录整个被替换，环境跟着丢 |
| `references/render_template.html` | `@excalidraw/excalidraw` 锁定到 `0.18.0` | 2026-10-24 实测：不锁版本时 esm.sh 解析到 0.18.1，其 `?bundle` 产物引用的一个子模块 404，模块加载不出来，渲染 30 秒超时；锁 0.18.0 后渲染成功（含中文） |
| `references/pyproject.toml`、`.gitignore`、上游 `README.md` | 未移植 | 依赖已内联进脚本；安装说明并入本文件 |

改配色：编辑 `skills/excalidraw-diagram/references/color-palette.md`，所有图跟着变。


## 许可

上游仓库未附 LICENSE 文件，版权归原作者 Cole Medin 所有，**不在本市场的 MIT 许可范围内**。
本插件仅作注明出处的移植；原作者若有异议，以原作者意见为准下架。
