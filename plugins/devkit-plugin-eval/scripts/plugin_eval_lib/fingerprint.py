"""插件内容指纹：闸门判「审过的报告评的是不是这份内容」用。

算法：遍历插件目录（不跟随目录符号链接），跳过 FINGERPRINT_EXCLUDE 列出的顶层条目与
NOISE_NAMES 列出的任意层级条目；每个文件取「相对路径（posix）\\0 内容 sha256」一行，按路径排序
后整体再取 sha256。内容不含 NUL 字节时视为文本，CRLF 归一成 LF，使 Windows 检出与 macOS
检出得到同一指纹。符号链接文件记链接目标字符串，不读目标内容。
"""
import hashlib
import os
from pathlib import Path

# 顶层排除清单（spec「2.8 发版闸门」：指纹算整个插件目录、排除 evals/，补用例不让已审报告失效）。
# 后续可能加入 unit-tests.json，待用户拍板。
FINGERPRINT_EXCLUDE = ('evals',)

# 任意层级都跳过的运行时噪声：跑单测会生成 __pycache__，macOS Finder 会生成 .DS_Store，
# 它们不是插件内容，计入会让同一份内容在不同机器上得到不同指纹。
NOISE_NAMES = ('__pycache__', '.DS_Store')
NOISE_SUFFIXES = ('.pyc',)


def _is_noise(name):
    return name in NOISE_NAMES or name.endswith(NOISE_SUFFIXES)


def _content_digest(path):
    if path.is_symlink():
        return hashlib.sha256(('symlink:' + os.readlink(path)).encode('utf-8')).hexdigest()
    data = path.read_bytes()
    if b'\0' not in data:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def iter_files(plugin_dir, extra_exclude=(), base_exclude=FINGERPRINT_EXCLUDE):
    root = Path(plugin_dir)
    top_excluded = set(base_exclude) | set(extra_exclude)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        at_top = rel_dir == Path('.')
        dirnames[:] = sorted(d for d in dirnames
                             if not _is_noise(d) and not (at_top and d in top_excluded))
        for f in sorted(filenames):
            if _is_noise(f) or (at_top and f in top_excluded):
                continue
            yield (rel_dir / f).as_posix(), Path(dirpath) / f
        # 指向目录的符号链接不会被 os.walk 递归，也不在 filenames 里，单独记一行
        for d in list(dirnames):
            full = Path(dirpath) / d
            if full.is_symlink():
                dirnames.remove(d)
                yield (rel_dir / d).as_posix(), full


def plugin_fingerprint(plugin_dir, extra_exclude=()):
    lines = sorted('%s\0%s\n' % (rel, _content_digest(full)) for rel, full in iter_files(plugin_dir, extra_exclude))
    return 'sha256:' + hashlib.sha256(''.join(lines).encode('utf-8')).hexdigest()


def _digest_lines(lines):
    return 'sha256:' + hashlib.sha256(''.join(sorted(lines)).encode('utf-8')).hexdigest()


def evals_fingerprint(evals_dir, cases):
    """用例目录（evals/）的内容指纹，算法同插件指纹，跳过顶层 results/（eval 裸跑的产物）。
    cases 是 evals/ 下现有的全部用例（相对路径）。返回 {'shared': 不属于任何用例的文件（mocks/ 等共用件）的指纹,
    'cases': {用例: 该用例目录的指纹}}。续跑据此拒绝「首跑之后改过用例或 grader」：合并汇总时用例级 graders
    沿用首跑，判据变了会静默错分；分用例记，首跑之后新增用例不影响续跑。"""
    prefixes = sorted(cases, key=len, reverse=True)
    shared, per_case = [], {c: [] for c in cases}
    for rel, full in iter_files(evals_dir, ('results',), base_exclude=()):
        owner = next((c for c in prefixes if rel.startswith(c + '/')), None)
        line = '%s\0%s\n' % (rel if owner is None else rel[len(owner) + 1:], _content_digest(full))
        (shared if owner is None else per_case[owner]).append(line)
    return {'shared': _digest_lines(shared), 'cases': {c: _digest_lines(v) for c, v in per_case.items()}}
