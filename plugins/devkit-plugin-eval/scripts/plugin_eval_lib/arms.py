"""臂与臂组装目录。

每个臂一个组装目录，就是 `claude plugin eval` 的目标插件目录：
  <组装根>/<臂键>/
    .claude-plugin/plugin.json  ← 被测插件某一版的全部内容（「不装」臂是只有 plugin.json 的空桩）
    ...                         ← 被测插件其余文件，不含它自带的 evals/
    evals/                      ← 一律拷当前版仓里的用例，不含 evals/results/
「不装」臂用空桩跑 --ablation none，等同不装（票 01 报告第二节实测）。
上一版臂的 ArmSpec.source 是 git archive 解出的快照目录（previous.py）；环境插件臂在组装后由
envplugins.install 把环境插件拷进组装目录内（eval 只从 containment root 内加载用例 plugins 字段列的插件）。
断开的符号链接跳过不拷（装到本机时它同样指向不存在的文件），否则 copytree 拷完整棵树才抛 shutil.Error；
本包所有整棵拷贝都走 copy_tree，跟随符号链接拷内容。
"""
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

STUB_NAME = 'devkit-plugin-eval-noplugin-stub'
CASE_MARKERS = ('prompt.md', 'case.yaml')


@dataclass(frozen=True)
class ArmSpec:
    key: str                 # 目录名与 run.json 里的键：none / current / previous ...
    label: str               # 给人读的臂名：不装 / 当前版 / 上一版
    source: Optional[Path]   # 被测插件某一版所在目录；None 表示空桩
    env_plugins: tuple = ()  # envplugins.EnvPlugin：组装后拷进臂目录并写进每个用例的 plugins 字段
    record: Optional[dict] = None   # 该臂写进 run.json 的来源字段；None 用当前版的默认字段


def discover_cases(evals_dir):
    """返回用例目录（含 prompt.md 或 case.yaml）相对 evals/ 的 posix 路径，排序。

    用来与 eval 的 casesTotal 比对：加载失败的用例不进 --json（票 01 报告第六节第 4 条）。
    """
    evals_dir = Path(evals_dir)
    if not evals_dir.is_dir():
        return []
    found = set()
    for dirpath, dirnames, filenames in os.walk(evals_dir):
        rel = Path(dirpath).relative_to(evals_dir)
        if rel == Path('.'):
            dirnames[:] = [d for d in dirnames if d != 'results']
            continue
        if any(m in filenames for m in CASE_MARKERS):
            found.add(rel.as_posix())
            dirnames[:] = []   # 用例目录下的子目录（graders/、附加文件）不再当用例
    return sorted(found)


def write_stub(dest):
    manifest = dest / '.claude-plugin' / 'plugin.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        'name': STUB_NAME, 'version': '0.0.0',
        'description': 'devkit-plugin-eval「不装」臂空桩：无任何组件，只承载用例',
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_tree(src, dest, ignore=None):
    """shutil.copytree 的包装：跟随符号链接拷内容，断开的链接跳过不拷。
    不用 copytree 的 ignore_dangling_symlinks：标准库按进程 cwd 判断相对链接是否断开，
    指向别处的相对链接（如插件目录外的共用脚本）会被当成断链静默丢掉。"""
    def _ignore(dirpath, names):
        out = set(ignore(dirpath, names)) if ignore else set()
        return out | {n for n in names
                      if os.path.islink(os.path.join(dirpath, n)) and not os.path.exists(os.path.join(dirpath, n))}
    shutil.copytree(src, dest, ignore=_ignore)
    return dest


def assemble_arm(root, spec, evals_src, extra_exclude=()):
    dest = Path(root) / spec.key
    if dest.exists():
        raise FileExistsError(dest)
    if spec.source is None:
        write_stub(dest)
    else:
        top_excluded = {'evals', '.in_use'} | set(extra_exclude)
        src = Path(spec.source)

        def ignore(dirpath, names):
            return [n for n in names if Path(dirpath) == src and n in top_excluded]
        copy_tree(src, dest, ignore=ignore)

    evals_src = Path(evals_src)

    def ignore_results(dirpath, names):
        return ['results'] if Path(dirpath) == evals_src and 'results' in names else []
    copy_tree(evals_src, dest / 'evals', ignore=ignore_results)
    return dest
