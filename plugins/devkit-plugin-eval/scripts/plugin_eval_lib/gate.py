"""发版闸门（gate）：判被测插件当前版本能否发布（spec「2.8 发版闸门（gate）」，票 14）。

入参是插件目录，不要求已登记、不调 claude。用户发版（推 main）前手动运行，本仓不接 git hook。

判定由三块组成，全过才「过闸」：
1. 单测声明（unittests.py）：有 unit-tests.json 就逐条跑，任一失败、超时、声明不合法、解释器解析不到都判失败；
   未声明只提示。`eval-skip:` 不豁免单测。
2. 评测依据：扫 `<仓>/plugin-evals/<插件名>/runs/*/run.json`，逐份按 assess_run 判能否采信：
   同版本、插件内容指纹与当前一致（指纹排除 evals/）、完整（completeness.gate_exclusion_reason）、
   dirty `is False`（读哪个来源见 _dirty_source）、注入到达核验不为 false，再加二者之一——已审的离线对照（kind=compare），
   或通过的规则子集（kind=gate，票 15 产出）。
   major 升版、或当前版本的升版提交带 `eval-required:` trailer 的版本（闸门内）只认已审的离线对照。
3. 跳过：当前版本的升版提交带 `eval-skip:` trailer 时第 2 块放行，并在输出里列出。

每次运行另输出：历史里全部 `eval-skip:` 版本；漏检——闸门内版本推到 main 时既无已审报告、也无 `eval-skip:`。

trailer 归属：plugin.json 的提交历史（沿 HEAD，`git log --follow` 跨改名）里，版本号为 V 的那一段连续提交
（含引入 V 的升版提交）上写的 trailer，都算 V 的声明。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import completeness, fingerprint, gitstate, previous, unittests
from .pending import REVIEW_DONE

MANIFEST_REL = '.claude-plugin/plugin.json'
TRAILER_SKIP = 'eval-skip'
TRAILER_REQUIRED = 'eval-required'
MAIN_REF_CANDIDATES = ('origin/main', 'main', 'origin/master', 'master')

BASIS_COMPARE = 'compare'
BASIS_GATE = 'gate'
SKIPPED_KINDS = ('clauses',)       # 单跑条款清单的运行：不是评测结果，扫 runs/ 时跳过
JUDGE_UNTRUSTED_NOTE = '本报告 AI 判分不采信，已审时由用户判断'
DIRTY_BLOCKER = '插件目录有未提交改动（不含 evals/），先提交再跑 gate'


class GateError(Exception):
    pass


# ---------- 被测插件 ----------

@dataclass
class Target:
    plugin_dir: Path
    name: str
    raw_version: Optional[str]      # plugin.json 原值，没写为 None
    version: str                    # run.json 里的写法：没写记 'noversion'（与 compare 一致）
    repo: Path
    plugin_path: str                # 相对仓根的 posix 路径，仓根插件为 '.'
    extra_exclude: tuple

    @property
    def runs_dir(self):
        return self.repo / 'plugin-evals' / self.name / 'runs'


def run_version(raw):
    return raw or 'noversion'


def locate(plugin_dir):
    """按 registry 的约定（`<仓>/plugins/<目录>/` 或仓根本身）定出仓根与插件路径。"""
    plugin_dir = Path(plugin_dir).expanduser().resolve()
    manifest = plugin_dir / MANIFEST_REL
    if not manifest.is_file():
        raise GateError('%s 下没有 %s，不是插件目录' % (plugin_dir, MANIFEST_REL))
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
    except ValueError as e:
        raise GateError('%s 不是合法 JSON：%s' % (manifest, e))
    name = data.get('name') if isinstance(data, dict) else None
    if not name:
        raise GateError('%s 没有 name' % manifest)
    raw = data.get('version')
    if plugin_dir.parent.name == 'plugins':
        repo, rel = plugin_dir.parent.parent, 'plugins/%s' % plugin_dir.name
    else:
        repo, rel = plugin_dir, '.'
    extra = ('.git', 'plugin-evals') if rel == '.' else ()     # 与 compare.load_target 同口径
    return Target(plugin_dir, name, raw, run_version(raw), repo, rel, extra)


# ---------- git 历史 ----------

@dataclass
class Commit:
    sha: str
    path: str                       # 该提交里 plugin.json 的路径
    version: Optional[str]
    trailers: List[tuple] = field(default_factory=list)   # [(小写键, 值)]
    body_lines: List[tuple] = field(default_factory=list)  # 提交信息全文里形如「键: 值」的行 [(小写键, 值)]

    def trailer(self, key):
        return [v for k, v in self.trailers if k == key]

    def required(self):
        """eval-required:：trailer 之外再按提交信息全文逐行宽松识别（声明后面跟了空行和署名段时 git 不认它是 trailer）。"""
        got = self.trailer(TRAILER_REQUIRED)
        return got or [v for k, v in self.body_lines if k == TRAILER_REQUIRED]

    def untrailered(self):
        """正文出现 eval-skip: / eval-required:、trailer 却没取到的键：输出警告（eval-skip: 不宽松识别，只警告）。"""
        return sorted({k for k, _ in self.body_lines if k in (TRAILER_SKIP, TRAILER_REQUIRED) and not self.trailer(k)})


def _git(git, top, *args):
    return subprocess.run([git, '-C', str(top), '-c', 'core.quotepath=off', *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def _parse_trailers(text):
    out = []
    for ln in text.splitlines():
        if ':' in ln:
            k, v = ln.split(':', 1)
            if k.strip():
                out.append((k.strip().lower(), v.strip()))
    return out


_BODY_KEY_RE = re.compile(r'^(eval-required|eval-skip):(.*)$', re.IGNORECASE)


def _body_keys(text):
    out = []
    for ln in text.splitlines():
        m = _BODY_KEY_RE.match(ln.strip())
        if m:
            out.append((m.group(1).lower(), m.group(2).strip()))
    return out


def manifest_history(git, top, manifest_rel, ref):
    """沿 ref 追踪 plugin.json（跨改名），新到旧：[Commit]。读不出 plugin.json 的提交、merge 提交跳过。"""
    proc = _git(git, top, 'log', '--follow', '--date-order',
                '--format=%x00%H%x1f%(trailers:only,unfold)%x1d%B%x1e', '--name-only', ref, '--', manifest_rel)
    if proc.returncode != 0:
        return []
    out = []
    for chunk in proc.stdout.split('\x00')[1:]:
        head, _, names = chunk.partition('\x1e')
        sha, _, rest = head.partition('\x1f')
        trailers, _, body = rest.partition('\x1d')
        paths = [ln.strip() for ln in names.splitlines() if ln.strip()]
        if not paths:
            continue
        data = previous._manifest_at(git, top, sha.strip(), paths[-1])
        if data is None:
            continue
        out.append(Commit(sha.strip(), paths[-1], data.get('version'), _parse_trailers(trailers), _body_keys(body)))
    return out


def segments(hist):
    """把新到旧的提交按版本号切成连续段：[(版本号, [提交，新到旧])]。"""
    segs = []
    for c in hist:
        if segs and segs[-1][0] == c.version:
            segs[-1][1].append(c)
        else:
            segs.append((c.version, [c]))
    return segs


def major_of(version):
    m = re.match(r'^v?(\d+)', str(version or ''))
    return int(m.group(1)) if m else None


def is_major_bump(version, prev_version):
    a, b = major_of(version), major_of(prev_version)
    return a is not None and b is not None and a > b


def resolve_main_ref(git, top, main_ref=None):
    for ref in ([main_ref] if main_ref else MAIN_REF_CANDIDATES):
        if _git(git, top, 'rev-parse', '--verify', '-q', ref + '^{commit}').returncode == 0:
            return ref
    return None


# ---------- 单份 run.json 能否采信 ----------

@dataclass
class Assessment:
    run_id: str
    kind: Optional[str]
    version: Optional[str]
    accepted: bool
    reasons: List[str]
    notes: List[str]
    reviewed_at: Optional[str] = None

    def to_dict(self):
        return dict(self.__dict__)


_DIRTY_DESC = {True: 'true（有未提交改动）', None: 'null（取不到 git 状态）'}


def _dirty_source(rec):
    """闸门读的 dirty：(字段名, 值)，没有任何 dirty 记录时为 None。

    续跑过的运行有两个来源：`preflight.dirty` 取自最后一次续跑，`arms.<臂>.dirty` 沿用首跑。读前者：
    续跑在插件内容指纹与首跑不同时拒绝续跑，所以最后一次续跑时 dirty=false 就说明整次运行评的内容
    （首跑与各次续跑都是这一份）等于那时的已提交内容，可追溯到提交。首跑时未提交、续跑前提交了的运行因此可采信。
    没有 preflight 段的记录（早于票 04）退回读 `arms.current.dirty`。上一版臂（git 快照）的 dirty 恒为 null，不读。"""
    pre = rec.get('preflight')
    if isinstance(pre, dict) and 'dirty' in pre:
        return 'preflight.dirty', pre['dirty']
    cur = (rec.get('arms') or {}).get('current') if isinstance(rec.get('arms'), dict) else None
    if isinstance(cur, dict) and 'dirty' in cur:
        return 'arms.current.dirty', cur['dirty']
    return None


def _dirty_reason(rec):
    src = _dirty_source(rec)
    if src is None:
        return '没有 dirty 记录，无法确认结果对应哪个提交'
    key, val = src
    if val is False:
        return None
    return 'dirty 不是 false：%s=%s' % (key, _DIRTY_DESC.get(val, repr(val)))


def _dirty_note(rec):
    """续跑过、首跑时 dirty 不是 false 的运行：采信时提示一句。"""
    src = _dirty_source(rec)
    cur = (rec.get('arms') or {}).get('current') if isinstance(rec.get('arms'), dict) else None
    if not src or src[0] != 'preflight.dirty' or not isinstance(cur, dict) or cur.get('dirty') is False:
        return None
    return ('首跑时 arms.current.dirty=%s，最后一次续跑时 preflight.dirty=false；续跑保证内容指纹不变，按后者采信'
            % _DIRTY_DESC.get(cur.get('dirty'), repr(cur.get('dirty'))))


def _degraded_note(rec):
    prev = rec.get('previous_arm')
    if not isinstance(prev, dict) or not prev.get('degraded'):
        return None
    kind = prev.get('reason_kind')
    if kind == 'no-different-version':
        return '上一版臂退化（no-different-version）：新插件首评或从未升过版本号，报告按基线规则比不装'
    return ('上一版臂退化（%s）：取不到上一版，报告只比了不装、没比版本回归；spec 2.2 定由审阅者判断能否作依据，'
            '已审即采信' % kind)


def assess_run(rec, *, version, plugin_fp, run_id='?'):
    """判一份 run.json 能否作当前版本的闸门依据。reasons 非空即不采信；notes 是采信时也要列出的提示。"""
    if not isinstance(rec, dict):
        return Assessment(run_id, None, None, False, ['run.json 不是对象'], [])
    kind = rec.get('kind')
    plugin = rec.get('plugin') if isinstance(rec.get('plugin'), dict) else {}
    reasons, notes = [], []
    if kind not in (BASIS_COMPARE, BASIS_GATE):
        reasons.append('kind=%r，既不是离线对照（compare）也不是规则子集（gate）' % kind)
    if plugin.get('version') != version:
        reasons.append('版本 %s 与当前 %s 不同' % (plugin.get('version'), version))
    if plugin.get('fingerprint') != plugin_fp:
        reasons.append('插件内容指纹与当前不一致（评测之后改过 evals/ 以外的内容）：%s → 当前 %s'
                       % (plugin.get('fingerprint'), plugin_fp))
    why = completeness.gate_exclusion_reason(rec)
    if why:
        reasons.append(why)
    why = _dirty_reason(rec)
    if why:
        reasons.append(why)
    elif _dirty_note(rec):
        notes.append(_dirty_note(rec))
    inj = rec.get('injection_check')
    if isinstance(inj, dict) and inj.get('ok') is False:
        reasons.append('注入未到达或无法核验（injection_check.ok=false）：%s' % '；'.join(inj.get('problems') or []))
    elif not isinstance(inj, dict) and kind == BASIS_COMPARE:
        notes.append('run.json 没有注入到达核验结果')
    versions = rec.get('claude_code_versions')
    mixed = isinstance(versions, list) and len(set(versions)) > 1
    review = rec.get('review') if isinstance(rec.get('review'), dict) else {}
    if kind == BASIS_COMPARE:
        if review.get('status') != REVIEW_DONE:
            reasons.append('审阅状态为「%s」：待审报告不能作发版依据' % review.get('status'))
        if mixed:
            notes.append('Claude Code 版本混用（%s）：报告已告警，审阅者审过，照常采信' % '、'.join(versions))
        note = _degraded_note(rec)
        if note:
            notes.append(note)
        judge = rec.get('judge') if isinstance(rec.get('judge'), dict) else {}
        if judge.get('trusted') is False:
            notes.append(JUDGE_UNTRUSTED_NOTE)
    elif kind == BASIS_GATE:
        if rec.get('passed') is not True:
            reasons.append('规则子集未通过（passed=%r）' % rec.get('passed'))
        if mixed:
            reasons.append('Claude Code 版本混用（%s）：规则子集无人审阅，不作依据' % '、'.join(versions))
    return Assessment(run_id, kind, plugin.get('version'), not reasons, reasons, notes,
                      review.get('reviewed_at') if kind == BASIS_COMPARE else None)


def load_runs(runs_dir):
    """[(run_id, run.json 内容或 None, 读取错误)]，按 run_id 排序。"""
    out = []
    if not Path(runs_dir).is_dir():
        return out
    for p in sorted(Path(runs_dir).glob('*/run.json')):
        try:
            out.append((p.parent.name, json.loads(p.read_text(encoding='utf-8')), None))
        except (OSError, ValueError) as e:
            out.append((p.parent.name, None, '读不出 run.json：%s' % e))
    return out


def assess_all(runs, *, version, plugin_fp):
    """单跑条款清单的运行（kind=clauses）不是评测结果，直接跳过、不列进「未采信」。"""
    res = []
    for run_id, rec, err in runs:
        if not err and isinstance(rec, dict) and rec.get('kind') in SKIPPED_KINDS:
            continue
        if err:
            res.append(Assessment(run_id, None, None, False, [err], []))
        else:
            res.append(assess_run(rec, version=version, plugin_fp=plugin_fp, run_id=run_id))
    return res


# ---------- 闸门判定 ----------

@dataclass
class GateResult:
    passed: bool
    data: dict
    lines: List[str]


def _fingerprint_at(git, top, commit, path_in_repo, tmp_parent=None):
    """某个提交里插件目录的内容指纹（git archive 解到临时目录再算，算法同当前版）。取不到返回 None。"""
    work = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-gate-', dir=tmp_parent))
    try:
        res = previous.Resolution(degraded=False, commit=commit, path_in_repo=path_in_repo, git=git, toplevel=str(top))
        d = previous.snapshot(res, work)
        return fingerprint.plugin_fingerprint(d, ('.git', 'plugin-evals') if path_in_repo == '.' else ())
    except previous.SnapshotError:
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _plugin_dir_of(manifest_path):
    return previous._plugin_dir_of(manifest_path)


def find_leaks(git, top, target, runs, main_ref, since=None, tmp_parent=None):
    """漏检：main 上闸门内（major 升版或声明 eval-required:）的版本，既无已审报告、也无 eval-skip:。
    起算点：--since 指定的提交；缺省取 main 上第一次入库 plugin-evals/<插件名>/ 的提交（插件开始评测之前的
    版本不追溯）。返回 (漏检列表, 说明行)。"""
    manifest_rel = MANIFEST_REL if target.plugin_path == '.' else '%s/%s' % (target.plugin_path, MANIFEST_REL)
    hist = manifest_history(git, top, manifest_rel, main_ref)
    if not hist:
        return [], ['%s 上没有 %s 的提交，跳过漏检' % (main_ref, manifest_rel)]
    if since:
        proc = _git(git, top, 'rev-parse', '--verify', '-q', since + '^{commit}')
        if proc.returncode != 0:
            raise GateError('--since %s 解析不到提交' % since)
        start, start_desc = proc.stdout.strip(), '--since %s' % since
    else:
        evals_rel = 'plugin-evals/%s' % target.name
        proc = _git(git, top, 'log', '--format=%H', '--reverse', main_ref, '--', evals_rel)
        shas = proc.stdout.split() if proc.returncode == 0 else []
        if not shas:
            return [], ['%s 上还没有入库过 %s/：漏检从首份评测记录入库起算，本次不查' % (main_ref, evals_rel)]
        start, start_desc = shas[0], '%s 首次入库 %s/ 的提交 %s' % (main_ref, evals_rel, shas[0][:12])
    tip = _git(git, top, 'rev-parse', main_ref + '^{commit}').stdout.strip()
    segs = segments(hist)
    leaks = []
    for i, (ver, commits) in enumerate(segs):
        intro = commits[-1]
        if _git(git, top, 'merge-base', '--is-ancestor', start, intro.sha).returncode != 0:
            continue                 # 早于起算点引入的版本不追溯
        prev_ver = segs[i + 1][0] if i + 1 < len(segs) else None
        required = [v for c in commits for v in c.trailer(TRAILER_REQUIRED)]
        major = is_major_bump(ver, prev_ver)
        if not (major or required):
            continue
        if any(c.trailer(TRAILER_SKIP) for c in commits):
            continue
        # 推到 main 的内容：下一个版本引入之前的那一刻；最新的版本取 main 的头
        shipped = tip if i == 0 else _git(git, top, 'rev-parse', segs[i - 1][1][-1].sha + '^').stdout.strip()
        rv = run_version(ver)
        reviewed = [(rid, rec) for rid, rec, err in runs if not err and isinstance(rec, dict)
                    and rec.get('kind') == BASIS_COMPARE and (rec.get('plugin') or {}).get('version') == rv
                    and (rec.get('review') or {}).get('status') == REVIEW_DONE]
        why_gated = ('major 升版（%s → %s）' % (prev_ver, ver)) if major else \
            '升版提交声明 eval-required: %s' % '；'.join(required)
        entry = {'version': ver, 'intro_commit': intro.sha, 'shipped_commit': shipped, 'gated_by': why_gated}
        if not reviewed:
            entry['why'] = '没有该版本的已审离线对照报告'
            leaks.append(entry)
            continue
        fp = _fingerprint_at(git, top, shipped, _plugin_dir_of(commits[0].path), tmp_parent)
        ok = [rid for rid, rec in reviewed
              if assess_run(rec, version=rv, plugin_fp=fp, run_id=rid).accepted] if fp else []
        if not ok:
            entry['why'] = ('有已审报告（%s），但无一可采信：评的内容与推到 main 的不一致，或 dirty / 不完整 / 注入未到达'
                            % '、'.join(rid for rid, _ in reviewed))
            leaks.append(entry)
    return leaks, ['漏检起算点：%s' % start_desc]


def skip_records(hists):
    """历史里全部 eval-skip: 记录：[{version, commit, reason}]，按提交去重，新到旧。"""
    seen, out = set(), []
    for hist in hists:
        for c in hist:
            for reason in c.trailer(TRAILER_SKIP):
                key = (c.sha, reason)
                if key in seen:
                    continue
                seen.add(key)
                out.append({'version': c.version, 'commit': c.sha, 'reason': reason})
    return out


def evaluate(plugin_dir, *, main_ref=None, since=None, platform=None, git=None, run_tests=True,
             unit_runner=None, tmp_parent=None):
    target = locate(plugin_dir)
    git = shutil.which('git') if git is None else git
    plugin_fp = fingerprint.plugin_fingerprint(target.plugin_dir, target.extra_exclude)
    notes, blockers = [], []      # blockers：与评测依据无关、单独判未过闸的原因

    # ---- git：当前版本的升版 trailer、上一版本号、跳过记录、漏检 ----
    top, hist_head, cur_commits, prev_version, main_used = None, [], [], None, None
    leaks, leak_notes, hists = [], [], []
    if git:
        proc = _git(git, target.repo, 'rev-parse', '--show-toplevel')
        if proc.returncode == 0 and _git(git, target.repo, 'rev-parse', '--verify', '-q', 'HEAD').returncode == 0:
            top = Path(proc.stdout.strip()).resolve()
    if top is None:
        notes.append('不在 git 仓里（或没有 git、没有提交）：读不到升版提交的 trailer，不判 major，不查跳过与漏检')
    else:
        rel = Path(target.plugin_dir).resolve().relative_to(top).as_posix() if target.plugin_dir != top else '.'
        manifest_rel = MANIFEST_REL if rel == '.' else '%s/%s' % (rel, MANIFEST_REL)
        hist_head = manifest_history(git, top, manifest_rel, 'HEAD')
        hists.append(hist_head)
        segs = segments(hist_head)
        if segs and segs[0][0] == target.raw_version:
            cur_commits = segs[0][1]
            prev_version = segs[1][0] if len(segs) > 1 else None
        else:
            prev_version = segs[0][0] if segs else None
            notes.append('当前版本号 %s 尚未提交：读不到它的升版提交 trailer' % target.version)
        main_used = resolve_main_ref(git, top, main_ref)
        if main_ref and not main_used:
            raise GateError('--main-ref %s 解析不到提交' % main_ref)
        if main_used:
            hists.append(manifest_history(git, top, manifest_rel, main_used))
            leak_target = Target(target.plugin_dir, target.name, target.raw_version, target.version, target.repo,
                                 rel, target.extra_exclude)
            leaks, leak_notes = find_leaks(git, top, leak_target, load_runs(target.runs_dir), main_used,
                                           since=since, tmp_parent=tmp_parent)
        else:
            leak_notes = ['找不到 main 分支（试过 %s）：跳过漏检；可用 --main-ref 指定' % '、'.join(MAIN_REF_CANDIDATES)]
        _, dirty = gitstate.git_state(top, rel, git=git)
        if dirty is not False:
            # 工作区与 HEAD 不一致时，已审报告评的内容不一定是将要推出去的提交（例：工作区恰好等于已审内容、HEAD 不同）
            blockers.append(DIRTY_BLOCKER if dirty else '读不到插件目录的 git 状态（git status 失败），无法确认工作区与提交一致')
        if not prev_version:
            notes.append('新插件首个版本（历史上没有更早的版本号）：不按 major 升版判闸门内%s'
                         % ('' if not any(c.required() for c in cur_commits)
                            else '；升版提交声明了 eval-required:，仍按声明判闸门内'))
        for c in cur_commits:
            for k in c.untrailered():
                notes.append('警告：提交 %s 的正文里出现 `%s:`，但 git 没把它认作 trailer（多半是后面还跟着空行与署名段）%s'
                             % (c.sha[:12], k, '；已按正文宽松识别' if k == TRAILER_REQUIRED
                                else '；eval-skip: 只认 trailer，本次不放行——改成提交信息最后一段'))

    required = [v for c in cur_commits for v in c.required()]
    skipped = [v for c in cur_commits for v in c.trailer(TRAILER_SKIP)]
    major = is_major_bump(target.raw_version, prev_version)
    gated = bool(major or required)
    gated_by = []
    if major:
        gated_by.append('major 升版（%s → %s）' % (prev_version, target.raw_version))
    if required:
        gated_by.append('升版提交声明 eval-required: %s' % '；'.join(required))

    # ---- 评测依据 ----
    runs = load_runs(target.runs_dir)
    assessments = assess_all(runs, version=target.version, plugin_fp=plugin_fp)
    accepted = [a for a in assessments if a.accepted]
    basis = [a for a in accepted if a.kind == BASIS_COMPARE] if gated else \
        sorted(accepted, key=lambda a: a.kind != BASIS_COMPARE)
    eval_ok = bool(basis)
    via_skip = not eval_ok and bool(skipped)

    # ---- 单测声明 ----
    if run_tests:
        ut_result = (unit_runner or unittests.run_plugin)(target.plugin_dir, platform=platform)
        tests_ok, test_lines = unittests.gate_verdict(ut_result)
    else:
        ut_result, tests_ok, test_lines = None, True, ['本次未跑（run_tests=False，只供单测用）']

    passed = (eval_ok or via_skip) and tests_ok and not blockers
    data = {
        'plugin': target.name, 'version': target.version, 'plugin_dir': str(target.plugin_dir),
        'fingerprint': plugin_fp, 'passed': passed, 'blockers': blockers,
        'judge_untrusted': [a.run_id for a in basis if JUDGE_UNTRUSTED_NOTE in a.notes],
        'gated': gated, 'gated_by': gated_by, 'previous_version': prev_version,
        'eval_ok': eval_ok, 'eval_skip': skipped, 'passed_via_skip': via_skip,
        'basis': [a.to_dict() for a in basis],
        'rejected_same_version': [a.to_dict() for a in assessments if not a.accepted and a.version == target.version],
        'other_runs': sum(1 for a in assessments if not a.accepted and a.version != target.version),
        'unit_tests': {'ok': tests_ok, 'result': _strip_output(ut_result), 'lines': test_lines},
        'skip_records': skip_records(hists), 'main_ref': main_used, 'leaks': leaks,
        'notes': notes + leak_notes,
    }
    return GateResult(passed, data, render(data, target))


def _strip_output(result):
    if not result:
        return result
    r = dict(result)
    r['tests'] = [{k: v for k, v in t.items() if k != 'output'} for t in result['tests']]
    return r


def render(d, target):
    lines = ['闸门检查：%s %s' % (d['plugin'], d['version']),
             '- 插件目录：%s（仓内路径 %s）' % (d['plugin_dir'], target.plugin_path),
             '- 插件内容指纹：%s（排除 evals/）' % d['fingerprint']]
    if d['gated']:
        lines.append('- 覆盖：闸门内——%s；须有已审的离线对照' % '；'.join(d['gated_by']))
    else:
        lines.append('- 覆盖：闸门外（非 major、未声明 eval-required:）；须有已审的离线对照，或通过的规则子集')
    if d['blockers']:
        lines += ['', '## 未过闸原因（与评测依据无关）'] + ['- %s' % b for b in d['blockers']]
    lines += ['', '## 评测依据']
    if d['judge_untrusted']:
        lines.append('- **注意：%s**（%s）' % (JUDGE_UNTRUSTED_NOTE, '、'.join('runs/%s' % r for r in d['judge_untrusted'])))
    if d['basis']:
        for a in d['basis']:
            what = '已审的离线对照（审阅于 %s）' % a['reviewed_at'] if a['kind'] == BASIS_COMPARE else '通过的规则子集'
            lines.append('- 采信 runs/%s：%s' % (a['run_id'], what))
            lines += ['  - 提示：%s' % n for n in a['notes']]
    elif d['passed_via_skip']:
        lines.append('- 没有可采信的记录；升版提交声明 eval-skip: %s，放行（事后由你决定是否补评）'
                     % '；'.join(d['eval_skip']))
    else:
        lines.append('- 没有可采信的记录：需要%s' % ('已审的离线对照' if d['gated'] else '已审的离线对照，或通过的规则子集'))
    if d['rejected_same_version']:
        lines += ['', '同版本但未采信的记录：']
        for a in d['rejected_same_version']:
            lines.append('- runs/%s（%s）：%s' % (a['run_id'], a['kind'], '；'.join(a['reasons'])))
    if d['other_runs']:
        lines.append('（另有 %d 份其它版本或读不出的记录，未列出）' % d['other_runs'])
    lines += ['', '## 单测声明'] + ['- %s' % ln if not ln.startswith('    ') else ln for ln in d['unit_tests']['lines']]
    lines += ['', '## 跳过记录（eval-skip:，全部版本）']
    if d['skip_records']:
        lines += ['- %s（提交 %s）：%s' % (s['version'], s['commit'][:12], s['reason']) for s in d['skip_records']]
    else:
        lines.append('- 无')
    lines += ['', '## 漏检（闸门内版本推到 main 时既无已审报告、也无 eval-skip:）']
    if d['leaks']:
        for x in d['leaks']:
            lines.append('- %s（%s；引入提交 %s，推到 %s 的内容 %s）：%s' % (
                x['version'], x['gated_by'], x['intro_commit'][:12], d['main_ref'], x['shipped_commit'][:12],
                x['why']))
        lines.append('  出现漏检即触发 spec 重开条件：闸门改接 pre-push')
    else:
        lines.append('- 无')
    if d['notes']:
        lines += ['', '## 说明'] + ['- %s' % n for n in d['notes']]
    verdict = '过闸' if d['passed'] else '未过闸'
    why = list(d['blockers'])
    if not (d['eval_ok'] or d['passed_via_skip']):
        why.append('缺可采信的评测依据')
    if not d['unit_tests']['ok']:
        why.append('单测未通过')
    lines += ['', '结论：%s%s' % (verdict, '（%s）' % '、'.join(why) if why else
                                    '（经 eval-skip: 放行）' if d['passed_via_skip'] else '')]
    return lines


def main(args):
    try:
        res = evaluate(args.plugin_dir, main_ref=args.main_ref, since=args.since)
    except GateError as e:
        print('错误：%s' % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.data, ensure_ascii=False, indent=2))
    else:
        print('\n'.join(res.lines))
    return 0 if res.passed else 1
