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

除下表所列（「在插件里能跑起来」所必需的部分与默认手绘画风），设计方法论、视觉模式库、配色原样保留，方便以后对照上游同步。

| 文件 | 改动 | 原因 |
|---|---|---|
| `SKILL.md` frontmatter | `description` 改为中文并收窄触发面，写明与 `show-me` 的分工 | 见上一节 |
| `SKILL.md` Setup / How to Render / First-Time Setup | 去掉 `cd .claude/skills/excalidraw-diagram/references`，改用 `<skill-dir>` 绝对路径与 `uv run <脚本>` | 插件装在缓存目录，不在 `.claude/skills/` 下 |
| `references/render_excalidraw.py` | 加 PEP 723 依赖头；新增 `--install-browser`；报错提示改成新命令；stdout/stderr 设 UTF-8 | 上游 `uv sync` 会把 `.venv` 建在 skill 目录里，插件升版本时缓存目录整个被替换，环境跟着丢 |
| `references/render_template.html` | `@excalidraw/excalidraw` 锁定到 `0.18.0` | 2026-10-24 实测：不锁版本时 esm.sh 解析到 0.18.1，其 `?bundle` 产物引用的一个子模块 404，模块加载不出来，渲染 30 秒超时；锁 0.18.0 后渲染成功（含中文） |
| `SKILL.md` Modern Aesthetics / Text Rules / Quality Checklist 第 17–18 条；`references/element-templates.md`；`references/json-schema.md` 的 `fontFamily` 行 | 默认画风由上游的直线 + 等宽字体（`roughness: 0`、`fontFamily: 3`）改为手绘（`roughness: 1`、`fontFamily: 5` Excalifont）；代码 / JSON 片段里的文字仍用 `fontFamily: 3` | 1.1.0，用户要默认手绘风；规则放在出图的 skill 里，`show-me` 转调、直接点名、`tech-doc` 配图三条入口拿到同一种画风。同步上游时这几处按本行手动合并 |
| `SKILL.md` 新增 Asset Libraries 一节；新增 `references/excalidraw_lib.py` | 上游没有素材库能力。1.2.0 新增：画数据库、缓存、队列、负载均衡、云服务这类具体组件时，从 libraries.excalidraw.com 的公共目录取图标插入 | 用户要用公共素材库；见下一节 |
| 新增 `references/design-guide.md`；`SKILL.md` 设计流程第 4 步指向它，Quality Checklist 增第 28–34 条，字号改为三档预设，粗线宽 3 改 4；`references/color-palette.md` 整表换色 | 1.3.0 新增。design-guide 汇总 C4 model、Ilograph、Azure / AWS 架构图规范、NN/g、WCAG、Refactoring UI、Excalidraw 源码等来源的作图经验，分准确、排版、配色、字体与强调、容器与图标、箭头、手绘边界七节，每条标明是有出处、推断还是经验值。色板换成 Excalidraw 取色器自带的颜色，描边对白底对比度都在 3:1 以上 | 用户要把网上的专业作图经验并入本 skill；换色板后，用户在编辑器里手改时用的是同一套颜色 |
| `SKILL.md` Modern Aesthetics 下的 Roughness 一节改为 Styles 表；Text Rules 加字宽估算；Quality Checklist 第 17–18 条；`references/design-guide.md` 第 4.5、7.3 条；`references/element-templates.md`、`references/json-schema.md` 的 `fontFamily` 说明 | 1.4.0：风格从手绘、干净两种扩到四种，新增圆体（`roughness: 0` + Nunito）与等宽（`roughness: 0` + Cascadia，圆角），每种写明选用说法与实测代价 | 用户要加圆体与等宽圆角两种风格；代价来自 2026-10-25 的风格实测（8 种风格 × 4 类技术图） |
| 新增 `references/gallery/`（`README.md` + 70 张 PNG）；`SKILL.md` 设计流程第 4 步与新增的 Reference Gallery 一节指向它 | 1.4.0：69 张各类技术图的样例与画法、瑕疵，画指定类型的图时先查对应条目 | 用户要把这套样例图作为画特定技术图时的参照 |
| `references/pyproject.toml`、`.gitignore`、上游 `README.md` | 未移植 | 依赖已内联进脚本；安装说明并入本文件 |

改配色：编辑 `skills/excalidraw-diagram/references/color-palette.md`，所有图跟着变。


## 风格（1.4.0 起四种）

默认手绘。用户说出下表的说法时，整张图换成对应风格，一张图只用一种。

| 风格 | 用户怎么说 | 线条 | 正文字体 | 实测代价 |
|---|---|---|---|---|
| 手绘（默认） | 不提风格；「手绘」「草图」 | 手绘抖动 | Excalifont 手写体 | 读起来像草稿 |
| 干净 | 「干净」「正式」「给客户看」 | 直线 | Helvetica | 大写 I 与小写 l 同形，`skuId` 会读成 `skuld` |
| 圆体 | 「圆体」「柔和」「Nunito」 | 直线 | Nunito | 同上；Nunito 不带中文字形，中文回退系统黑体，中文为主的图和「干净」几乎一样 |
| 等宽 | 「等宽」「等宽圆角」「工程风」 | 直线 | Cascadia 等宽 | 标识符不会认错；中文字距偏大，O 与 0 难分，`->` 显示成 → |

四种风格都是圆角框、实心填充、同一套配色；代码与 JSON 片段在任何风格下都用等宽字体。


## 参考图库（1.4.0 起）

`skills/excalidraw-diagram/references/gallery/` 收了 69 张图，分 11 类：架构、流程与行为、工程实践、数据与结构、协议与分布式、规划、分析与思考、产品与业务、界面与组织、数据图表。
每张有一句话图注、画法要点、已知瑕疵和画布尺寸，另有两节写 Excalidraw 画不好什么、哪类图该换什么工具。
AI 画指定类型的图（C4、时序图、ER 图、BPMN、甘特图……）时先查对应条目、看图，再照它的记号和版式画。

- 图片用等宽直角风渲染，只当版式参照，出图风格仍按上一节选。
- 插件只带压成 64 色的 PNG（约 6.7 MB），不带 `.excalidraw` 源文件和生成脚本。
- 图里的业务是虚构电商「青禾商城」。


## 素材库（1.2.0 起）

画图时，如果节点是具体的技术组件（数据库、缓存、负载均衡、浏览器、某个云服务），AI 会从 Excalidraw 公共素材库取现成图标，不再画带文字的方框。

素材文件不随插件分发，用到时才下载到本机：

| 目录 | 用途 | 查找顺序 |
|---|---|---|
| `<项目>/.claude/excalidraw-libraries/` | 团队共用的库，可以提交进项目仓库 | 先查 |
| `~/.claude/excalidraw-libraries/` | 个人下载的库，所有项目通用 | 后查 |

所有操作都通过 `skills/excalidraw-diagram/references/excalidraw_lib.py` 完成。这个脚本只用 Python 标准库，用 `uv run` 执行：

| 子命令 | 作用 |
|---|---|
| `search <关键词>` | 搜公共目录（libraries.excalidraw.com，约 230 个库），目录在本机缓存 24 小时 |
| `fetch <source 或库名> [--project]` | 下载库文件；带 `--project` 时存进项目目录 |
| `list` | 列出本机已下载的库 |
| `items <库>` | 列出库里的条目：序号、名称、元素数、尺寸、条目里的文字 |
| `preview <库>` | 把全部条目排成带序号的网格，渲染成 PNG。很多库的条目没有名称，要看图挑选 |
| `insert <场景文件> <库> <条目> --x --y [--width/--height]` | 把条目缩放后插进 `.excalidraw` 文件，自动重新生成 id 并编组；输出 JSON，里面有包围框和可供箭头绑定的元素 id |

自己放库文件：把 `.excalidrawlib` 文件放进上面任一目录即可，v1、v2 两种格式都能读。

许可：公共目录里的库由各作者上传，许可以每个库的说明为准；目录仓库 excalidraw-libraries 本身是 MIT 许可。插件只带脚本，不带任何第三方素材。


## 许可

上游仓库未附 LICENSE 文件，版权归原作者 Cole Medin 所有，**不在本市场的 MIT 许可范围内**。
本插件仅作注明出处的移植；原作者若有异议，以原作者意见为准下架。
