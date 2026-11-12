# 单文件 HTML 文档

SKILL.md 第零步选了 HTML 时读。HTML 是原稿本身：直接写 HTML、直接改 HTML，不经过 md。交付物只有一个 `<名>.html`，图片、图的 Excalidraw 源稿、样式全在文件里，离线双击即开。

工具是 `<本 skill 目录>/scripts/html_pack.py`，用 `uv run` 执行，依赖由脚本头的 PEP 723 声明自动安装（首次运行要联网）。下文 `PACK` 指 `uv run '<本 skill 目录>/scripts/html_pack.py'`。

---

## 一、落点

- 交付物：`<落点>/<名>.html`，落点默认当前目录，用户指定优先。
- 图的工作文件：`$TMPDIR/tech-doc/<名>/figures/`（未设 `$TMPDIR` 用 `/tmp`，Windows 用 `%TEMP%`）。打包后它们已经进了 HTML，交付前删掉这个临时目录，落点旁不留 `figures/`。

## 二、起稿

```bash
PACK new '<落点>/<名>.html' --title '<标题>'
```

它按 `assets/doc-template.html` 生成骨架：样式、左侧目录位 `<nav class="toc">`、正文位 `<main>`。正文写在 `<main>` 里，`<head>` 与样式不动。

## 三、正文写法

SKILL.md 第一到第三步的规则照用，只是落成 HTML 标签：

| 内容 | 写法 |
|---|---|
| 编制说明 | `<p class="meta">日期、依据与范围、读者假定</p>`，紧跟 `<h1>` |
| 章节 | `<h2>` / `<h3>`，不写 id 时打包自动按标题生成；页内链接写 `<a href="#id">` |
| 行 × 列的对照、时间线 | `<table>`，表头用 `<th>` |
| 先后步骤 | `<ol>`；并列要点 `<ul>`，细节嵌套 `<ul>` |
| 关键结论、关键数字 | `<strong>` |
| 代码、命令、日志 | `<pre><code>`；行内 `<code>` |
| 依据强度标签 | `<span class="tag">【推断】</span>` |
| 大段分隔 | `<hr>` |

- 文字里的 `<` `>` `&` 写成 `&lt;` `&gt;` `&amp;`，代码块里同样。
- 链接只放读者能打开的：网址、页内 `#id`。仓库文件写仓库内相对路径的文字，或 GitLab / GitHub 网页地址；不写 `file://`、`vscode://`，它们在读者机器上打不开。
- 不引外部 CSS、JS、字体；不用 mermaid——文件里没有 mermaid 运行时，打包会拒绝（退出码 2）。

## 四、配图

SKILL.md 第四步的六条照用。图注写在图前：`<p class="caption-lead">图 N 说的是：……</p>`。按图的复杂度二选一：

**Excalidraw（默认，结构、流程、时序、状态图都用它）**
1. 调 `devkit-excalidraw-diagram:excalidraw-diagram`，`.excalidraw` 与渲染出的同名 PNG 都写进第一节的临时 `figures/`，文件名 `<序号>-<主题>`。
2. 正文里引 PNG 的绝对路径：
   ```html
   <figure><img src="/tmp/tech-doc/<名>/figures/01-overview.png" alt="图 1 全景"></figure>
   ```
3. 打包时 PNG 转成 base64 写进 `src`，宽于 2000 像素的等比缩到 2000（`--max-width` 可调，0 为不缩）；PNG 旁的同名 `.excalidraw` 自动嵌进文件末尾的 `<script type="application/json" class="excalidraw-src">`，以后改图从这里取回。

**手写 SVG（只用于简单图：≤5 个方框、一条时间轴、几根柱子）**
- 直接写 `<figure><svg viewBox="0 0 宽 高" role="img" aria-label="图注">…</svg></figure>`，不经过文件。
- 配色用模板里的角色变量，与 `figures.md`「三、全篇统一」同一套，写在 `style` 里：`style="fill:var(--svc);stroke:var(--svc-s)"`；平台 `--plat`、外部 `--ext`、目标 `--target`、范围外 `--out`（各自带 `-s` 是描边）。写进 `style` 而不是 `fill="var(--svc)"` 属性：Chromium 实测两种都生效，其它浏览器对属性里的 `var()` 未核实，`style` 是标准 CSS，稳妥。
- 每个方框有 `<text>` 标签，每条箭头旁有动作标签；文字写 `style="font-family:inherit"`，中文才不掉成衬线字体。
- 超过上面的规模就改用 Excalidraw：手写 SVG 的布局全靠算坐标，复杂图容易重叠。

## 五、打包与检查

每次改完正文或换了图都重跑：

```bash
PACK pack '<落点>/<名>.html'
```

原地改写。成功输出一行：文件大小、内嵌图片张数、Excalidraw 源稿份数、警告条数。

| 退出码 | 含义 | 处理 |
|---|---|---|
| 1 | 图片不存在、模板占位符没替换、id 重复 | 按 stderr 那一行改 HTML 后重跑 |
| 2 | 含 mermaid | 改用 Excalidraw 或手写 SVG |

警告逐条处理，交付时为 0 条，或在回复里说明保留的理由：
- 本地文件链接、`file://` / `vscode://` 链接、远程图片——读者打不开，删掉或改写成文字、内嵌图片。
- 页内链接目标不存在——改 `href` 或给目标标题加 `id`。
- 图片缺 `alt`——补上，与图注一致。
- 文件超过 20 MB——调小 `--max-width`，钉钉、邮件传不上大文件。

打包后在浏览器里看一遍：图都显示、目录能跳。macOS `open`，Windows `start`；子代理不打开，交主会话。然后删掉临时 `figures/`。

## 六、修改已有 HTML

- 改文字：直接编辑 HTML 正文，再 `pack`。
- 改图：
  1. `PACK extract '<名>.html' "$TMPDIR/tech-doc/<名>/figures"` 取回全部 `.excalidraw`；
  2. 在取回的 `.excalidraw` 上改，渲染出同名 PNG；
  3. 把 HTML 里对应 `<img data-excalidraw="<名>">` 的 `src` 从 `data:...` 换成新 PNG 的绝对路径；
  4. `pack`：新 PNG 内嵌，同名源稿替换旧的。

`src` 里的 base64 很长，用 `Edit` 换时以 `data-excalidraw="<名>"` 所在的那段 `<img ...>` 为定位，或用一行 Python 按 `data-excalidraw` 属性替换，不把整段 base64 读进上下文。

## 七、多篇合成一个 HTML

多个子代理并行写各篇时，每篇写成**正文片段**文件 `<篇号>-<篇位>.html`：只含 `<h1>` 起的正文标签，不含 `<html>` `<head>` `<body>`。片段里的 `id` 全组唯一，建议以篇号开头（`20-core`）。篇间链接写 `<a href="20-essence.html#20-core">`，图照第四节写绝对路径或相对片段文件的路径。

```bash
PACK assemble 10-guide.html 20-essence.html ... -o '<落点>/<名>.html' --title '<标题>'
```

按命令行顺序拼进模板，每篇包成 `<section class="part" id="part-<文件名>">`，篇间链接改成页内跳转，再执行一遍 `pack`（第五节的退出码与警告同样适用）。
