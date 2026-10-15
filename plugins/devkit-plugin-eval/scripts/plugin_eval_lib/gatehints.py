"""闸门提示「建议跑对照（会先更新条款清单）」（票 15；spec「2.8 发版闸门（gate）」，设计票 20 第 4 条）。

三个来源合成恰好一条提示：
1. 注入文本指纹相对上次对照变了。当前指纹用 clauses.capture_injection 现取（真实 HOME、空临时 cwd，与 compare
   第 2 步同一取法与归一化）；比对基线依次取：最近一次离线对照 run.json 的 clause_check.injection_fingerprint、
   条款清单 clauses.json 的 injection_fingerprint。两者都没有就不比，只在说明里写一句。
2. 升版改动碰到 skill description：skills/**/SKILL.md 的 frontmatter description 有增、删、改。
3. 升版改动碰到 agent 定义：agents/*.md 整个文件有增、删、改。
2、3 的「升版改动」= 上一版本号的最后一个提交里的插件目录 → 当前工作区。新插件首版没有上一版，不比。

已对当前内容跑过离线对照（同版本、插件内容指纹相同的 kind=compare 运行）时不再提示，只在说明里记一句。
"""
import json
import re
import subprocess
from pathlib import Path

SUGGESTION = '建议跑对照（会先更新条款清单）'
_SKIP_CC_STATUS = ('unreliable', 'error')   # 这两种状态下记的指纹不可信，不拿来当基线


# ---------- 注入文本指纹 ----------

def injection_baseline(repo, name, runs):
    """(指纹, 来源说明, 归一化规则名)；都没有返回 None。runs 是 gate.load_runs 的结果（按 run_id 升序）。"""
    for run_id, rec, err in reversed(runs):
        if err or not isinstance(rec, dict) or rec.get('kind') != 'compare':
            continue
        cc = rec.get('clause_check') if isinstance(rec.get('clause_check'), dict) else {}
        fp = cc.get('injection_fingerprint')
        if isinstance(fp, str) and fp and cc.get('status') not in _SKIP_CC_STATUS:
            return fp, '上次对照 runs/%s' % run_id, cc.get('normalization')
    from . import clauses
    lst = clauses.load_list(repo, name)
    if isinstance(lst, dict) and lst.get('injection_fingerprint'):
        return lst['injection_fingerprint'], '条款清单 clauses.json', lst.get('normalization')
    return None


def injection_change(plugin_dir, repo, name, runs, *, env=None, tmp_parent=None, capture=None):
    """返回 (原因或 None, 说明行列表)。capture 只给单测替换取注入文字的函数。"""
    from . import clauses
    base = injection_baseline(repo, name, runs)
    if base is None:
        return None, ['没有上次对照或条款清单记下的注入文本指纹：本次不比较注入文本']
    fp, where, norm = base
    if norm and norm != clauses.NORMALIZATION['name']:
        return None, ['%s 的注入文本归一化规则是 %s，与当前 %s 不同：指纹不可比，本次不比较注入文本'
                      % (where, norm, clauses.NORMALIZATION['name'])]
    cap = (capture or clauses.capture_injection)(plugin_dir, env=env, tmp_parent=tmp_parent)
    if not cap.reliable:
        return None, ['注入 hook 有执行失败或两次输出不一致，本次不比较注入文本：%s'
                      % '；'.join(list(cap.failed) + ['%s（两次输出不同）' % k for k in cap.unstable] + list(cap.errors))]
    if cap.fingerprint == fp:
        return None, []
    return '注入文本指纹相对%s 变了（%s → %s）' % (where, fp[:19], cap.fingerprint[:19]), []


# ---------- skill description 与 agent 定义 ----------

def description_of(text):
    """SKILL.md frontmatter 里 description 的原文（含缩进续行，去首尾空白）；没有 frontmatter 或没有该键返回 None。"""
    lines = (text or '').replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != '---':
        return None
    out = None
    for ln in lines[1:]:
        if ln.strip() == '---':
            break
        if out is not None:
            if not ln.strip() or ln[:1] in (' ', '\t'):
                out.append(ln.strip())
                continue
            break
        m = re.match(r'^description\s*:(.*)$', ln)
        if m:
            out = [m.group(1).strip()]
    return None if out is None else '\n'.join(out).strip()


def _is_skill(rel):
    parts = rel.split('/')
    return len(parts) >= 3 and parts[0] == 'skills' and parts[-1] == 'SKILL.md'


def _is_agent(rel):
    parts = rel.split('/')
    return len(parts) == 2 and parts[0] == 'agents' and parts[1].endswith('.md')


def definitions(files):
    """{rel: 文本} → ({skill 名: description}, {agent 文件名: 全文})。skill 名取 skills/ 与 SKILL.md 之间的路径。"""
    skills, agents = {}, {}
    for rel, text in files.items():
        if _is_skill(rel):
            skills['/'.join(rel.split('/')[1:-1])] = description_of(text)
        elif _is_agent(rel):
            agents[rel.split('/')[1]] = (text or '').replace('\r\n', '\n')
    return skills, agents


def working_files(plugin_dir):
    plugin_dir = Path(plugin_dir)
    out = {}
    for sub, pattern in (('skills', '**/SKILL.md'), ('agents', '*.md')):
        base = plugin_dir / sub
        if base.is_dir():
            for p in base.glob(pattern):
                if p.is_file():
                    out[p.relative_to(plugin_dir).as_posix()] = p.read_text(encoding='utf-8', errors='replace')
    return out


def _git(git, top, *args):
    return subprocess.run([git, '-C', str(top), '-c', 'core.quotepath=off', *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def files_at(git, top, commit, plugin_path):
    """某提交里插件目录下 skills/**/SKILL.md 与 agents/*.md：{相对插件目录的路径: 文本}。取不到返回 None。"""
    prefix = '' if plugin_path in ('', '.') else plugin_path.rstrip('/') + '/'
    proc = _git(git, top, 'ls-tree', '-r', '--name-only', commit, '--', prefix + 'skills', prefix + 'agents')
    if proc.returncode != 0:
        return None
    out = {}
    for path in proc.stdout.splitlines():
        rel = path[len(prefix):] if path.startswith(prefix) else path
        if not (_is_skill(rel) or _is_agent(rel)):
            continue
        show = _git(git, top, 'show', '%s:%s' % (commit, path))
        if show.returncode != 0:
            return None
        out[rel] = show.stdout
    return out


def definition_changes(before, after):
    """两份 {rel: 文本} 之间 skill description 与 agent 定义的增删改：[原因]。"""
    (sk0, ag0), (sk1, ag1) = definitions(before), definitions(after)
    out = []
    for name in sorted(set(sk0) | set(sk1)):
        if name not in sk0:
            out.append('新增 skill `%s`' % name)
        elif name not in sk1:
            out.append('删除 skill `%s`' % name)
        elif sk0[name] != sk1[name]:
            out.append('skill `%s` 的 description 改了' % name)
    for name in sorted(set(ag0) | set(ag1)):
        if name not in ag0:
            out.append('新增 agent `%s`' % name)
        elif name not in ag1:
            out.append('删除 agent `%s`' % name)
        elif ag0[name] != ag1[name]:
            out.append('agent `%s` 的定义改了' % name)
    return out


def previous_version_commit(segs, raw_version):
    """升版改动的起点：上一版本号的最后一个提交（gate.segments 的结果，新到旧）。没有上一版返回 None。"""
    if not segs:
        return None
    if segs[0][0] == raw_version:
        return segs[1][1][0] if len(segs) > 1 else None
    return segs[0][1][0]       # 当前版本号尚未提交：HEAD 上的版本就是上一版


# ---------- 合成 ----------

def covered_by_compare(runs, version, plugin_fp):
    """已对当前内容跑过的离线对照 run_id（同版本、同插件内容指纹），没有返回 None。"""
    for run_id, rec, err in reversed(runs):
        if err or not isinstance(rec, dict) or rec.get('kind') != 'compare':
            continue
        p = rec.get('plugin') if isinstance(rec.get('plugin'), dict) else {}
        if p.get('version') == version and p.get('fingerprint') == plugin_fp:
            return run_id
    return None


def compare_suggestion(*, target, runs, plugin_fp, git=None, top=None, segs=None, env=None, tmp_parent=None,
                       capture=None):
    """返回 (提示 dict 或 None, 说明行列表)。提示 dict：{line, reasons, previous_version}；line 恰好一行。"""
    notes, reasons = [], []
    why, more = injection_change(target.plugin_dir, target.repo, target.name, runs, env=env, tmp_parent=tmp_parent,
                                 capture=capture)
    notes += more
    if why:
        reasons.append(why)
    prev_commit, prev_version = None, None
    if git and top is not None:
        prev_commit = previous_version_commit(segs, target.raw_version)
        if prev_commit is not None:
            from . import previous
            prev_version = prev_commit.version
            before = files_at(git, top, prev_commit.sha, previous._plugin_dir_of(prev_commit.path))
            if before is None:
                notes.append('取不到上一版 %s（提交 %s）的 skill / agent 文件：本次不比较 skill description 与 agent 定义'
                             % (prev_version, prev_commit.sha[:12]))
            else:
                changed = definition_changes(before, working_files(target.plugin_dir))
                if changed:
                    reasons.append('相对上一版 %s：%s' % (prev_version, '、'.join(changed)))
    if not reasons:
        return None, notes
    covered = covered_by_compare(runs, target.version, plugin_fp)
    if covered:
        notes.append('有变动（%s），但当前内容已跑过离线对照 runs/%s：不再建议跑对照' % ('；'.join(reasons), covered))
        return None, notes
    return {'line': '%s：%s' % (SUGGESTION, '；'.join(reasons)), 'reasons': reasons,
            'previous_version': prev_version}, notes
