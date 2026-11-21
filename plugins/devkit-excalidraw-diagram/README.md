# devkit-excalidraw-diagram — Excalidraw 图解

让 AI 把概念、架构、流程画成**可编辑的 `.excalidraw` 文件**，并把它渲染成 PNG 自己回看、迭代修版，直到排版过关才交付。
生成的文件可以直接拖进 [excalidraw.com](https://excalidraw.com) 或 Obsidian Excalidraw 继续改。

移植自 [coleam00/excalidraw-diagram-skill](https://github.com/coleam00/excalidraw-diagram-skill)（上游提交 `8646fcc`，2026-03-01）。


## 什么时候触发

| 说法 | 走哪里 |
|---|---|
| 「用 excalidraw 画个架构图」「生成一个 .excalidraw 文件」「出张能拖拽改的白板图」 | 本插件 `excalidraw-diagram` |
| 「画个架构图 / 流程图 / 时序图」，没提 Excalidraw | `devkit-svg-diagram:svg-diagram`（默认出图） |
| 「画个图」「可视化一下」，没说图种 | `devkit-tool:show-me`（挑伪代码、调用树、成品图、HTML 等最小够用的视图；要成品图时默认转调 svg-diagram） |

上游的触发描述是「任何想可视化流程、架构、概念的时候」，会和 `show-me` 抢同一批请求，所以这里收窄到点名 Excalidraw 或可编辑白板图。2026-11-21 起默认出图改由 `devkit-svg-diagram` 承担（devkit-tool 6.43.0），`show-me`、`tech-doc` 只在用户点名 Excalidraw 时转调本插件，或在未装 svg-diagram 时退到本插件。


## 前置依赖

1. **uv**（[安装说明](https://docs.astral.sh/uv/)）。渲染脚本用 PEP 723 内联声明依赖，`uv run` 首次运行时自动建环境并缓存在 uv 自己的缓存目录里。
2. **Chromium**，只需下载一次（`<skill-dir>` 是插件缓存里 `skills/excalidraw-diagram` 的绝对路径，AI 加载 skill 时能看到）：

   ```bash
   uv run '<skill-dir>/references/render_excalidraw.py' --install-browser
   ```

   漏了这步也没关系：渲染时缺 Chromium，脚本会打印上面这条命令。
3. **网络**：渲染模板从 esm.sh 加载 `@excalidraw/excalidraw`，离线环境渲染不了（生成 `.excalidraw` 文件本身不受影响）。


## 相对上游的改动

除下表所列（「在插件里能跑起来」所必需的部分与默认画风），设计方法论、视觉模式库、配色原样保留，方便以后对照上游同步。

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
| `SKILL.md` Styles 表、Text Rules、Quality Checklist 第 17–18 条；`references/element-templates.md` 全部模板；`references/design-guide.md` 第 4.5、7.1、7.3 条；`references/json-schema.md` 的 `roughness`、`fontFamily` 行 | 1.5.0：默认风格由手绘改为圆体（`roughness: 0` + `fontFamily: 6` Nunito）；手绘降为点名「手绘」「草图」才用 | 2026-10-26 用户拍板默认用圆体柔和风 |
| `SKILL.md` 新增 Handing the Diagram Over、Updating an Existing Diagram 两节，开头加改图指路，`description` 补改图触发说法 | 1.6.0：回复里 PNG 用普通链接、不加 `!`；同一话题已有图时在原文件上定点改、重渲染到原路径，只有布局整体变化才重画 | 实测 `![图注](file://…png)` 在 Claude Code 终端印成纯文本、点不动；整份重写要重新输出全部 JSON，还会冲掉用户在编辑器里的手改 |
| `SKILL.md` Styles 表加第五种风格及其规则；`references/color-palette.md` 末尾新增 Pastel Style 色板；`references/design-guide.md` 第 3.4 条注明例外 | 1.7.0：新增「柔和色块」风格（pastel）：低饱和分区底色 + 同色系浅描边、大分区里嵌小卡片、卡片上标题下灰色说明、三角箭头、范围外用虚线框；只有这种风格换色板，容器描边对比度低于 3:1 属有意为之，文字与箭头仍达标 | 2026-11-19 用户要能用 Excalidraw 复刻 nb 组方案文档里的柔和色块分层架构图；色值取自该样板 SVG |
| `references/color-palette.md` 通用色板、文字色、代码块配色全部重写，末尾新增 Brutal Style；`SKILL.md` Styles 表、Text Rules、Reference Gallery、Render 一节、Checklist 第 17 条；`references/element-templates.md`、`json-schema.md`、`design-guide.md` 第 4.5、7.3 条；`render_excalidraw.py` 与 `render_template.html`；`references/gallery/` 由 PNG 换成 SVG | 1.8.0：默认风格改为「Mac 扁平」（mac：等宽字体 + 柔和色块 + 细描边 + 卡片柔和投影 + 三角箭头 + 卡片文字居中），原「柔和色块」并入它；除新野兽派外所有风格共用一套 Mac 色板（浅底、同色相细描边、Apple 灰阶文字，文字对 4.5:1 达标，卡片细描边低于 3:1 属有意为之），代码块改浅底 Xcode 配色；新增「新野兽派」（brutal，保留自己的高饱和色板）；渲染脚本支持输出内嵌场景的 SVG、把 SVG 转成 PNG；图库 69 张改用 Mac 色板重渲染为内嵌场景的 SVG | 2026-11-21 用户嫌原商务配色丑，选定「Mac 扁平 + 柔和色块 + 等宽」为默认，并要求其他风格统一用这套颜色；同意收录新野兽派；图库要换成 SVG 或 Excalidraw 原始文件 |
| `references/pyproject.toml`、`.gitignore`、上游 `README.md` | 未移植 | 依赖已内联进脚本；安装说明并入本文件 |

改配色：编辑 `skills/excalidraw-diagram/references/color-palette.md`，所有图跟着变。


## 风格（1.8.0 起五种）

默认 Mac 扁平（1.8.0 起；1.5.0–1.7.0 默认圆体，1.1.0–1.4.0 默认手绘）。用户说出下表的说法时，整张图换成对应风格，一张图只用一种。

| 风格 | 用户怎么说 | 线条 | 正文字体 | 实测代价 |
|---|---|---|---|---|
| Mac 扁平（默认） | 不提风格；「Mac 扁平」「苹果风」「柔和色块」「色块卡片」「等宽」「工程风」，或给一张柔和色块分层图当样板 | 直线 | Cascadia 等宽 | 卡片下多一层柔和投影（7% 黑，下移 5px），白卡片靠它从白底浮起；标识符不会认错；中文字距偏大，O 与 0 难分，`->` 显示成 →；Cascadia 不带中文字形，中文回退系统黑体 |
| 圆体 | 「圆体」「Nunito」 | 直线 | Nunito | 大写 I 与小写 l 同形，`skuId` 会读成 `skuld`；Nunito 不带中文字形，中文为主的图和「干净」几乎一样 |
| 手绘 | 「手绘」「草图」 | 手绘抖动 | Excalifont 手写体 | 读起来像草稿 |
| 干净 | 「干净」「正式」「给客户看」 | 直线 | Helvetica | 大写 I 与小写 l 同形，`skuId` 会读成 `skuld` |
| 新野兽派 | 「野兽派」「新野兽派」「野蛮风格」「neo-brutalism」 | 直线 | Helvetica | 4px 纯黑粗边、黑色实心投影、直角、高饱和填充、箭头标签黑底白字；视觉很重，不适合正式文档；投影要占 10px 间距 |

前四种风格共用同一套 Mac 色板与结构规则：圆角框、实心浅底、同色相细描边、灰色三角箭头、卡片文字水平垂直都居中、分层图用浅灰分区嵌卡片；只有 Mac 扁平加投影。新野兽派用自己的高饱和色板。代码与 JSON 片段在任何风格下都用等宽字体。


## 参考图库（1.4.0 起）

`skills/excalidraw-diagram/references/gallery/` 收了 69 张图，分 11 类：架构、流程与行为、工程实践、数据与结构、协议与分布式、规划、分析与思考、产品与业务、界面与组织、数据图表。
每张有一句话图注、画法要点、已知瑕疵和画布尺寸，另有两节写 Excalidraw 画不好什么、哪类图该换什么工具。
AI 画指定类型的图（C4、时序图、ER 图、BPMN、甘特图……）时先查对应条目、看图，再照它的记号和版式画。

- 图片用 Mac 色板加等宽字体渲染（不带投影），只当版式参照，出图风格仍按上一节选。
- 1.8.0 起每张图是内嵌了 Excalidraw 场景的 SVG（共约 8.6 MB）：浏览器和 markdown 预览直接显示，拖进 excalidraw.com 能继续编辑；另带一张全景缩略图 `overview.png`。不带生成脚本。
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
