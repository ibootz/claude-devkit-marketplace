# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Excalidraw asset libraries (.excalidrawlib): search the public catalog at
libraries.excalidraw.com, download a library, list its items, and insert one
item into an .excalidraw scene.

Local library directories, searched in this order:
  1. <nearest ancestor of cwd>/.claude/excalidraw-libraries/   (project)
  2. ~/.claude/excalidraw-libraries/                           (user)

Subcommands:
  search <keyword...>        search the catalog (name / description / author)
  fetch <source|name>        download a catalog library into the user dir
                             (--project: into the project dir instead)
  list                       list downloaded libraries
  items <lib>                list the items of a library (index, name, size, text)
  preview <lib>              render all items into a labelled PNG grid; many
                             libraries have unnamed items, so look before picking
  insert <scene> <lib> <item> --x X --y Y [--width W | --height H]
                             copy an item into the scene: translated to (X, Y)
                             as its top-left corner, optionally scaled, with
                             fresh ids / seeds / groupIds; prints a JSON summary
                             (new ids, outer group id, bbox, anchor element id)
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG_URL = "https://libraries.excalidraw.com/libraries.json"
LIB_BASE = "https://libraries.excalidraw.com/libraries/"
USER_DIR = Path.home() / ".claude" / "excalidraw-libraries"
CATALOG_CACHE = USER_DIR / ".catalog.json"
CATALOG_TTL_SECONDS = 24 * 3600
SHAPES = {"rectangle", "ellipse", "diamond"}


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def project_dir() -> Path | None:
    for d in [Path.cwd(), *Path.cwd().parents]:
        cand = d / ".claude" / "excalidraw-libraries"
        if cand.is_dir() and cand.resolve() != USER_DIR.resolve():
            return cand
    return None


def lib_dirs() -> list[Path]:
    dirs = [d for d in (project_dir(), USER_DIR) if d and d.is_dir()]
    return dirs


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "devkit-excalidraw-diagram"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def load_catalog(refresh: bool = False) -> list[dict]:
    fresh = CATALOG_CACHE.exists() and time.time() - CATALOG_CACHE.stat().st_mtime < CATALOG_TTL_SECONDS
    if fresh and not refresh:
        return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    try:
        raw = http_get(CATALOG_URL)
        data = json.loads(raw)
        USER_DIR.mkdir(parents=True, exist_ok=True)
        CATALOG_CACHE.write_bytes(raw)
        return data
    except Exception as e:  # network down: fall back to a stale cache
        if CATALOG_CACHE.exists():
            print(f"WARN: catalog download failed ({e}); using cached copy", file=sys.stderr)
            return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
        die(f"cannot download catalog {CATALOG_URL}: {e}")


def local_name(source: str) -> str:
    return source.replace("/", "__")


def local_libs() -> list[Path]:
    seen, out = set(), []
    for d in lib_dirs():
        for p in sorted(d.glob("*.excalidrawlib")):
            if p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out


def cmd_search(args) -> None:
    terms = [t.lower() for t in args.keywords]
    have = {p.name for p in local_libs()}
    hits = 0
    for lib in load_catalog(args.refresh):
        authors = " ".join(a.get("name", "") for a in lib.get("authors", []))
        hay = f"{lib.get('name', '')} {lib.get('description', '')} {authors}".lower()
        if all(t in hay for t in terms):
            hits += 1
            mark = " [downloaded]" if local_name(lib["source"]) in have else ""
            desc = (lib.get("description") or "").replace("\n", " ")[:90]
            print(f"{lib['source']}\t{lib.get('name', '')}{mark}\t{desc}")
    if not hits:
        print("no match; try a broader keyword (catalog is English)", file=sys.stderr)


def cmd_fetch(args) -> None:
    catalog = load_catalog()
    key = args.library.lower()
    match = [l for l in catalog if l["source"].lower() == key] or [
        l for l in catalog if l.get("name", "").lower() == key
    ]
    if not match:
        die(f"'{args.library}' not in catalog; run `search` and pass the source column")
    lib = match[0]
    raw = http_get(LIB_BASE + urllib.parse.quote(lib["source"]))
    json.loads(raw)  # validate
    target_dir = (Path.cwd() / ".claude" / "excalidraw-libraries") if args.project else USER_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / local_name(lib["source"])
    out.write_bytes(raw)
    print(out)


def cmd_list(_args) -> None:
    libs = local_libs()
    if not libs:
        print(f"no libraries yet; `fetch` one into {USER_DIR}", file=sys.stderr)
    for p in libs:
        print(f"{p.stem}\t{len(load_items(p))} items\t{p}")


def resolve_lib(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.is_file():
        return p
    key = arg.lower().removesuffix(".excalidrawlib")
    libs = local_libs()
    for lib in libs:
        stem = lib.stem.lower()
        if stem == key or stem.endswith("__" + key) or stem == local_name(key):
            return lib
    try:
        for entry in load_catalog():
            if entry.get("name", "").lower() == key:
                for lib in libs:
                    if lib.name == local_name(entry["source"]):
                        return lib
    except SystemExit:
        pass
    die(f"library '{arg}' not found locally; run `fetch` first (see `list`)")


def load_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files", {})
    if "libraryItems" in data:  # v2
        raw = [(it.get("name") or "", it.get("elements", [])) for it in data["libraryItems"]]
    elif "library" in data:  # v1: list of element lists, no names
        raw = [("", els) for els in data["library"]]
    else:
        die(f"{path} is not an .excalidrawlib file")
    items = []
    for i, (name, els) in enumerate(raw):
        els = [e for e in els if not e.get("isDeleted")]
        items.append({"index": i, "name": name or f"#{i}", "elements": els, "files": files})
    return items


def bbox(els: list[dict]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for e in els:
        if e.get("points"):
            xs += [e["x"] + p[0] for p in e["points"]]
            ys += [e["y"] + p[1] for p in e["points"]]
        else:
            xs += [e["x"], e["x"] + e.get("width", 0)]
            ys += [e["y"], e["y"] + e.get("height", 0)]
    return min(xs), min(ys), max(xs), max(ys)


def cmd_items(args) -> None:
    for it in load_items(resolve_lib(args.library)):
        if not it["elements"]:
            continue
        x0, y0, x1, y1 = bbox(it["elements"])
        print(f"#{it['index']}\t{it['name']}\t{len(it['elements'])} elements\t{x1 - x0:.0f}x{y1 - y0:.0f}\t{item_text(it)[:60]}")


def cmd_preview(args) -> None:
    """Lay every item out in a labelled grid and render it, so unnamed items can be seen."""
    lib = resolve_lib(args.library)
    items = [it for it in load_items(lib) if it["elements"]]
    cell, box, cols = 240, 170, args.columns
    els: list[dict] = []
    for n, it in enumerate(items):
        x0, y0, x1, y1 = bbox(it["elements"])
        s = min(1.0, box / max((x1 - x0) or 1, (y1 - y0) or 1))
        cx, cy = (n % cols) * cell, (n // cols) * (cell + 30)
        els += transform(it["elements"], cx, cy, s, f"pv{n}")
        label = f"#{it['index']} {it['name']}" if not it["name"].startswith("#") else f"#{it['index']}"
        els.append({
            "type": "text", "id": f"pv{n}_label", "x": cx, "y": cy + box + 12, "width": cell - 20, "height": 24,
            "text": label[:28], "originalText": label[:28], "fontSize": 18, "fontFamily": 3,
            "textAlign": "left", "verticalAlign": "top", "strokeColor": "#c92a2a", "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid", "roughness": 0, "opacity": 100,
            "angle": 0, "seed": n + 1, "version": 1, "versionNonce": n + 2, "isDeleted": False, "groupIds": [],
            "boundElements": None, "link": None, "locked": False, "containerId": None, "lineHeight": 1.25,
        })
    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.gettempdir()) / "excalidraw-lib-preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{lib.stem}.excalidraw"
    files = items[0]["files"] if items else {}
    out.write_text(json.dumps({"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
                               "elements": els, "appState": {"viewBackgroundColor": "#ffffff"},
                               "files": files}, ensure_ascii=False), encoding="utf-8")
    renderer = Path(__file__).with_name("render_excalidraw.py")
    uv = shutil.which("uv")
    if not uv:
        print(f"{out}\nuv not found; render manually: uv run '{renderer}' '{out}'", file=sys.stderr)
        return
    subprocess.run([uv, "run", "-q", str(renderer), str(out)], check=True)  # prints the PNG path


def pick_item(items: list[dict], sel: str) -> dict:
    m = re.fullmatch(r"#?(\d+)", sel)
    if m and int(m.group(1)) < len(items):
        return items[int(m.group(1))]
    exact = [it for it in items if it["name"].lower() == sel.lower()]
    if exact:
        return exact[0]
    # name fragment first, then the item's own text (v1 libraries have no names)
    for hay in (lambda it: it["name"], item_text):
        part = [it for it in items if sel.lower() in hay(it).lower()]
        if len(part) == 1:
            return part[0]
        if part:
            die(f"'{sel}' matches several items: " + ", ".join(f"#{it['index']} {item_text(it)[:30]}" for it in part[:15]))
    die(f"no item '{sel}'; run `items` / `preview` to see names and indexes")


def item_text(it: dict) -> str:
    return " / ".join(e["text"].replace("\n", " ") for e in it["elements"] if e.get("type") == "text" and e.get("text"))


def transform(item_els: list[dict], x: float, y: float, s: float, prefix: str, roughness: int | None = None) -> list[dict]:
    """Copy item elements to (x, y) top-left, scaled by s, with fresh ids / seeds / groups."""
    els = copy.deepcopy(item_els)
    x0, y0, _, _ = bbox(els)
    id_map = {e["id"]: f"{prefix}_{i}" for i, e in enumerate(els)}
    group_map: dict[str, str] = {}
    outer = f"{prefix}_grp"
    for e in els:
        e["id"] = id_map[e["id"]]
        e["x"] = x + (e["x"] - x0) * s
        e["y"] = y + (e["y"] - y0) * s
        for k in ("width", "height"):
            if k in e:
                e[k] = e[k] * s
        if e.get("points"):
            e["points"] = [[p[0] * s, p[1] * s] for p in e["points"]]
            e["lastCommittedPoint"] = None
        if "fontSize" in e:
            e["fontSize"] = round(e["fontSize"] * s, 1)
        e["groupIds"] = [group_map.setdefault(g, f"{prefix}_g{len(group_map)}") for g in e.get("groupIds", [])] + [outer]
        if e.get("containerId"):
            e["containerId"] = id_map.get(e["containerId"])
        if e.get("boundElements"):
            e["boundElements"] = [
                {**b, "id": id_map[b["id"]]} for b in e["boundElements"] if b.get("id") in id_map
            ] or None
        for k in ("startBinding", "endBinding"):
            if e.get(k):
                tgt = id_map.get(e[k].get("elementId"))
                e[k] = {**e[k], "elementId": tgt} if tgt else None
        if roughness is not None and "roughness" in e:
            e["roughness"] = roughness
        e["seed"] = random.randint(1, 2**31 - 1)
        e["versionNonce"] = random.randint(1, 2**31 - 1)
        e["version"] = 1
        e["frameId"] = None
        e.pop("index", None)  # fractional index; Excalidraw regenerates it
    return els


def cmd_insert(args) -> None:
    scene_path = Path(args.scene)
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    item = pick_item(load_items(resolve_lib(args.library)), args.item)
    if not item["elements"]:
        die("item has no elements")

    x0, y0, x1, y1 = bbox(item["elements"])
    w, h = (x1 - x0) or 1, (y1 - y0) or 1
    s = args.width / w if args.width else (args.height / h if args.height else 1.0)

    slug = re.sub(r"[^a-z0-9]+", "_", item["name"].lower()).strip("_")[:20] or "item"
    prefix = args.id_prefix or f"lib_{slug}_{random.randint(1000, 9999)}"
    existing = {e.get("id") for e in scene.get("elements", [])}
    if any(i.startswith(prefix + "_") for i in existing if i):
        die(f"id prefix '{prefix}' collides with existing elements; pass another --id-prefix")
    els = transform(item["elements"], args.x, args.y, s, prefix, args.roughness)
    outer = f"{prefix}_grp"

    scene.setdefault("elements", []).extend(els)
    if item["files"]:
        used = {e.get("fileId") for e in els if e.get("fileId")}
        scene.setdefault("files", {}).update({k: v for k, v in item["files"].items() if k in used})
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")

    nx0, ny0, nx1, ny1 = bbox(els)
    shapes = [e for e in els if e.get("type") in SHAPES] or els
    anchor = max(shapes, key=lambda e: abs(e.get("width", 0) * e.get("height", 0)))
    print(json.dumps({
        "item": item["name"],
        "group": outer,
        "bbox": [round(nx0), round(ny0), round(nx1 - nx0), round(ny1 - ny0)],
        "anchor": anchor["id"],
        "ids": [e["id"] for e in els],
    }, ensure_ascii=False))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="search the public catalog")
    p.add_argument("keywords", nargs="+")
    p.add_argument("--refresh", action="store_true", help="ignore the 24h catalog cache")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("fetch", help="download a catalog library")
    p.add_argument("library", help="catalog source (e.g. author/name.excalidrawlib) or exact name")
    p.add_argument("--project", action="store_true", help="save into ./.claude/excalidraw-libraries/")
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("list", help="list downloaded libraries")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("items", help="list the items of a library")
    p.add_argument("library", help="local file stem, catalog name, or path")
    p.set_defaults(fn=cmd_items)

    p = sub.add_parser("preview", help="render all items of a library into a labelled PNG grid")
    p.add_argument("library")
    p.add_argument("--columns", type=int, default=6)
    p.add_argument("--out-dir", help="default: <system temp>/excalidraw-lib-preview/")
    p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("insert", help="insert a library item into a scene")
    p.add_argument("scene", help=".excalidraw file to modify in place")
    p.add_argument("library")
    p.add_argument("item", help="item name, unique name fragment, or #index")
    p.add_argument("--x", type=float, required=True, help="left edge of the inserted item")
    p.add_argument("--y", type=float, required=True, help="top edge of the inserted item")
    size = p.add_mutually_exclusive_group()
    size.add_argument("--width", type=float, help="scale proportionally to this width")
    size.add_argument("--height", type=float, help="scale proportionally to this height")
    p.add_argument("--id-prefix", help="prefix for the new element ids")
    p.add_argument("--roughness", type=int, choices=[0, 1, 2], help="override the item's roughness")
    p.set_defaults(fn=cmd_insert)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
