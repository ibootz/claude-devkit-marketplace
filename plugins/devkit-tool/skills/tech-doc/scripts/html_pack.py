# /// script
# requires-python = ">=3.9"
# dependencies = ["beautifulsoup4>=4.12", "pillow>=10"]
# ///
"""单文件 HTML 文档的打包工具：图片转 base64 内嵌、Excalidraw 源稿一并藏进文件、自动生成目录。

子命令（由 uv 按上方 PEP 723 声明自动装依赖）：
    uv run html_pack.py new <doc.html> --title 标题
        按 assets/doc-template.html 新建一份空文档，正文写在 <main> 里。
    uv run html_pack.py pack <doc.html> [-o out.html] [--max-width 2000]
        把 <img src="本地路径"> 换成 data URI；图片旁有同名 .excalidraw 时把源稿 JSON 嵌进
        <script type="application/json" class="excalidraw-src">；填充 <nav class="toc">；做离线自检。
        默认原地改写。
    uv run html_pack.py assemble <part1.html> [<part2.html> ...] -o out.html --title 标题
        多篇正文片段（只含正文标签，不含 <html>/<head>）按顺序拼进模板，篇间链接
        `20-essence.html#某id` 改写成页内 `#某id`，再执行 pack。
    uv run html_pack.py extract <doc.html> <输出目录>
        把内嵌的 Excalidraw 源稿还原成 <名>.excalidraw，供改图后重新渲染、再 pack 回去。

退出码：0 成功；1 输入缺失、图片缺失、模板占位符没替换、id 重复；2 含 mermaid。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, Tag

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "doc-template.html"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
WARN_BYTES = 20 * 1024 * 1024


class Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def slugify(text: str) -> str:
    out = []
    for ch in text.strip().lower():
        if ch == " ":
            out.append("-")
        elif ch in "-_" or ch.isalnum() or unicodedata.category(ch).startswith(("L", "N", "M")):
            out.append(ch)
    return "".join(out) or "section"


def is_remote(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https")


def local_path(url: str, base: Path) -> Path:
    raw = unquote(urlparse(url).path) if url.startswith("file:") else unquote(url.split("#")[0].split("?")[0])
    p = Path(raw)
    return p if p.is_absolute() else (base / p).resolve()


def template_html(title: str, body: str) -> str:
    t = TEMPLATE.read_text(encoding="utf-8")
    from html import escape
    return t.replace("{{TITLE}}", escape(title)).replace("{{BODY}}", body)


# ---------- pack ----------

def encode_image(p: Path, max_width: int) -> str:
    data = p.read_bytes()
    mime = MIME.get(p.suffix.lower(), "application/octet-stream")
    if mime in ("image/png", "image/jpeg", "image/webp") and max_width > 0:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if im.width > max_width:
                im = im.resize((max_width, round(im.height * max_width / im.width)), Image.LANCZOS)
                buf = io.BytesIO()
                fmt = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[mime]
                im.save(buf, fmt, optimize=True, **({"quality": 88} if fmt != "PNG" else {}))
                if buf.tell() < len(data):
                    data = buf.getvalue()
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def embed_excalidraw(soup: BeautifulSoup, img: Tag, src_file: Path) -> None:
    name = img.get("data-excalidraw") or src_file.stem
    try:
        payload = json.dumps(json.loads(src_file.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError as e:
        raise Fail(f"{src_file} 不是合法 JSON：{e}")
    payload = payload.replace("</", "<\\/")
    for old in soup.select("script.excalidraw-src"):
        if old.get("data-name") == name:
            old.decompose()
    s = soup.new_tag("script", attrs={"type": "application/json", "class": "excalidraw-src", "data-name": name})
    s.string = payload
    (soup.body or soup).append(s)
    img["data-excalidraw"] = name


def fill_toc(soup: BeautifulSoup) -> None:
    nav = soup.select_one("nav.toc")
    seen: set[str] = {t["id"] for t in soup.find_all(id=True)}
    heads = soup.select("main h1, main h2, main h3")
    for h in heads:
        if not h.get("id"):
            base = slugify(h.get_text())
            hid, n = base, 1
            while hid in seen:
                hid, n = f"{base}-{n}", n + 1
            h["id"] = hid
            seen.add(hid)
    if nav is None or (nav.contents and not nav.get("data-auto")):
        return  # 没有目录位，或作者手写了目录
    nav.clear()
    nav["data-auto"] = "1"
    if len(heads) < 3:
        return
    title = soup.new_tag("div", attrs={"class": "toc-title"})
    title.string = "目录"
    ul = soup.new_tag("ul")
    for h in heads:
        li = soup.new_tag("li", attrs={"class": f"l{h.name[1]}"})
        a = soup.new_tag("a", href=f"#{h['id']}")
        a.string = h.get_text(" ", strip=True)
        li.append(a)
        ul.append(li)
    nav.append(title)
    nav.append(ul)


def check(soup: BeautifulSoup, raw: str, warnings: list[str]) -> None:
    for ph in ("{{TITLE}}", "{{BODY}}"):
        if ph in raw:
            raise Fail(f"模板占位符 {ph} 没有替换")
    hits = soup.select(".mermaid, code.language-mermaid, pre.mermaid")
    if hits:
        raise Fail("含 mermaid 图，单文件 HTML 里渲染不了：改用 Excalidraw 出 PNG，或直接手写 <svg>。", 2)
    ids: dict[str, int] = {}
    for t in soup.find_all(id=True):
        ids[t["id"]] = ids.get(t["id"], 0) + 1
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise Fail(f"id 重复，页内跳转会错位：{', '.join(dup[:10])}")
    for tag in soup.find_all(["a", "img", "script", "link", "source", "iframe"]):
        for attr in ("href", "src"):
            v = tag.get(attr)
            if not v or v.startswith(("#", "data:", "mailto:")):
                continue
            if v.startswith(("file:", "vscode:")):
                warnings.append(f"本机路径链接，别人的机器上打不开：{v}")
            elif is_remote(v):
                if tag.name != "a":
                    warnings.append(f"<{tag.name}> 引用远程资源，离线打不开：{v}")
            elif tag.name == "a" and v.startswith(("http:", "https:")):
                pass
            else:
                warnings.append(f"<{tag.name} {attr}> 指向本地文件，不随 HTML 带走：{v}")
        if tag.name == "a" and tag.get("href", "").startswith("#") and len(tag["href"]) > 1:
            if tag["href"][1:] not in ids:
                warnings.append(f"页内链接目标不存在：{tag['href']}")


def pack_soup(soup: BeautifulSoup, base: Path, max_width: int, warnings: list[str]) -> None:
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        if is_remote(src):
            continue  # check() 统一报
        p = local_path(src, base)
        if not p.is_file():
            raise Fail(f"图片不存在：{src}（解析为 {p}）")
        img["src"] = encode_image(p, max_width)
        exc = p.with_suffix(".excalidraw")
        if exc.is_file():
            embed_excalidraw(soup, img, exc)
        if not img.get("alt"):
            warnings.append(f"图片缺 alt：{src}")
    fill_toc(soup)


def write_out(soup: BeautifulSoup, out: Path, warnings: list[str]) -> int:
    raw = str(soup)
    check(soup, raw, warnings)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    tmp.replace(out)
    size = out.stat().st_size
    for w in dict.fromkeys(warnings):
        print(f"警告：{w}", file=sys.stderr)
    if size > WARN_BYTES:
        print(f"警告：HTML {size / 1048576:.1f} MB，超过 20 MB，钉钉、邮件可能传不上；调小 --max-width。", file=sys.stderr)
    n_img = len([i for i in soup.find_all("img") if (i.get("src") or "").startswith("data:")])
    n_exc = len(soup.select("script.excalidraw-src"))
    print(f"已生成 {out.resolve()}（{size / 1024:.0f} KB，内嵌图片 {n_img} 张，Excalidraw 源稿 {n_exc} 份，警告 {len(set(warnings))} 条）")
    return 0


def cmd_pack(a) -> int:
    src = a.doc.resolve()
    if not src.is_file():
        raise Fail(f"输入不存在：{src}")
    soup = BeautifulSoup(src.read_text(encoding="utf-8"), "html.parser")
    warnings: list[str] = []
    pack_soup(soup, src.parent, a.max_width, warnings)
    return write_out(soup, (a.output or src).resolve(), warnings)


def cmd_assemble(a) -> int:
    parts = [p.resolve() for p in a.parts]
    for p in parts:
        if not p.is_file():
            raise Fail(f"输入不存在：{p}")
    names = {p.name: p for p in parts}
    body = []
    for p in parts:
        frag = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
        inner = frag.body or frag
        for a_tag in inner.find_all("a", href=True):
            href = a_tag["href"]
            path_part, _, frag_id = href.partition("#")
            if path_part and Path(unquote(path_part)).name in names and not is_remote(href):
                a_tag["href"] = f"#{frag_id}" if frag_id else f"#part-{Path(path_part).stem}"
        # 片段里的相对图片路径按片段所在目录解析，先转成绝对路径
        for img in inner.find_all("img", src=True):
            s = img["src"]
            if not s.startswith("data:") and not is_remote(s):
                img["src"] = local_path(s, p.parent).as_uri()
        body.append(f'<section class="part" id="part-{p.stem}">\n{inner.decode_contents()}\n</section>')
    soup = BeautifulSoup(template_html(a.title, "\n".join(body)), "html.parser")
    warnings: list[str] = []
    pack_soup(soup, a.output.resolve().parent, a.max_width, warnings)
    return write_out(soup, a.output.resolve(), warnings)


def cmd_new(a) -> int:
    out = a.doc.resolve()
    if out.exists():
        raise Fail(f"已存在，不覆盖：{out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    from html import escape
    out.write_text(template_html(a.title, f"<h1>{escape(a.title)}</h1>\n"), encoding="utf-8")
    print(f"已新建 {out}")
    return 0


def cmd_extract(a) -> int:
    soup = BeautifulSoup(a.doc.read_text(encoding="utf-8"), "html.parser")
    a.outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in soup.select("script.excalidraw-src"):
        name = s.get("data-name") or f"figure-{n}"
        (a.outdir / f"{name}.excalidraw").write_text(
            json.dumps(json.loads(s.string or "{}"), ensure_ascii=False, indent=2), encoding="utf-8")
        print(a.outdir.resolve() / f"{name}.excalidraw")
        n += 1
    print(f"还原 {n} 份。改图并渲染出同名 PNG 后，把对应 <img data-excalidraw=\"<名>\"> 的 src 改成该 PNG 路径，再跑 pack。")
    return 0


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="单文件 HTML 文档打包")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("doc", type=Path); p.add_argument("--title", required=True)
    p = sub.add_parser("pack"); p.add_argument("doc", type=Path); p.add_argument("-o", "--output", type=Path)
    p.add_argument("--max-width", type=int, default=2000, help="位图宽于此值时等比缩小，0 表示不缩")
    p = sub.add_parser("assemble"); p.add_argument("parts", nargs="+", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True); p.add_argument("--title", required=True)
    p.add_argument("--max-width", type=int, default=2000)
    p = sub.add_parser("extract"); p.add_argument("doc", type=Path); p.add_argument("outdir", type=Path)
    a = ap.parse_args()
    try:
        return {"new": cmd_new, "pack": cmd_pack, "assemble": cmd_assemble, "extract": cmd_extract}[a.cmd](a)
    except Fail as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
