"""臂计划：本次对照跑哪几个臂、各臂的插件从哪来，以及写进 run.json 的来源字段。

臂与跑的顺序：不装 → 上一版（取得到才跑）→ 当前版 → 当前版+环境插件（传了 --env-plugin 才跑）。

中止（抛 ArmSourceError，不建运行目录）：--base 解析不到；环境插件取不到、重名或与被测插件同名。
退化（跳过上一版臂，照跑两臂）：见 previous.py 模块说明；快照失败也在这里退化。

快照与环境插件的 `claude plugin validate`、hook 冒烟（spec「2.6 前置检查」硬项，被测插件、快照、环境插件都过）
由前置检查（票 04）负责：Plan.preflight_targets() 给出 [(标签, 目录)] 供它逐个检查。所以 plan_arms 排在
前置检查之前，且只写临时目录。

续跑（票 07）用 rebuild_plan 按首跑 run.json 记下的来源重建同一份计划：上一版须认定到同一提交、
环境插件须同版本同内容，对不上就抛 ArmSourceError，不混跑两份内容。
"""
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import arms, envplugins, fingerprint, previous, scoring

PREVIOUS_LABEL = '上一版'
ENV_LABEL = '当前版+环境插件'
GIT_CEILING = None   # 只给测试用：限定 git 向上找仓的边界


class ArmSourceError(Exception):
    pass


@dataclass
class Plan:
    specs: list
    previous: previous.Resolution
    env_plugins: list = field(default_factory=list)
    incomparable_cases: dict = field(default_factory=dict)
    snapshot_root: Optional[Path] = None
    snapshot_dir: Optional[Path] = None
    env_fingerprints: dict = field(default_factory=dict)   # 环境插件 spec → 内容指纹，续跑据此核对
    legacy: bool = False   # 续跑早于票 05 的运行（run.json 没有 previous_arm）：只跑首跑的两臂，不补写来源字段

    def source_dirs(self):
        """快照与环境插件目录（被测插件当前版不在内）。"""
        return [d for _, d in self.preflight_targets()]

    def preflight_targets(self):
        """[(标签, 目录)]：前置检查除被测插件外还要 validate 与冒烟的快照、环境插件。"""
        out = []
        if self.snapshot_dir:
            out.append(('上一版快照 %s（%s）' % (self.previous.version, (self.previous.commit or '')[:12]),
                        self.snapshot_dir))
        return out + [('环境插件 %s' % ep.spec, ep.dir) for ep in self.env_plugins]

    def cleanup(self):
        if self.snapshot_root is not None:
            shutil.rmtree(self.snapshot_root, ignore_errors=True)
            self.snapshot_root = None

    def env_records(self):
        return [dict(ep.record(), fingerprint=self.env_fingerprints.get(ep.spec)) for ep in self.env_plugins]

    def record_fields(self, arm_records):
        """写进 run.json 顶层的字段：上一版臂的认定结果、环境插件清单、两组附加的差。"""
        if self.legacy:
            return {}
        cur, prev, env = (arm_records.get(k) for k in ('current', 'previous', 'current_with_env'))
        prev_info = dict(self.previous.to_record(), ran=prev is not None,
                         incomparable_cases=self.incomparable_cases)
        return {
            'previous_arm': prev_info,
            'env_plugins': self.env_records(),
            'delta_vs_previous': self._delta(cur, prev, self.incomparable_cases) if cur and prev else None,
            'delta_env_vs_current': scoring.delta(env, cur) if cur and env else None,
        }

    def checkpoint_fields(self, arm_records):
        """检查点里的同名字段：臂尚未判分，两组差留 null；来源字段供续跑重建计划。"""
        if self.legacy:
            return {}
        return {
            'previous_arm': dict(self.previous.to_record(), ran='previous' in arm_records,
                                 incomparable_cases=self.incomparable_cases),
            'env_plugins': self.env_records(),
            'delta_vs_previous': None,
            'delta_env_vs_current': None,
        }

    @staticmethod
    def _delta(arm, base, excluded):
        """当前版 − 上一版。跨改名时不可比的用例照列逐用例差，但不进总体差。"""
        full = scoring.delta(arm, base)
        if excluded:
            keep = lambda a: {'cases': {k: v for k, v in a.get('cases', {}).items() if k not in excluded}}
            full['overall'] = scoring.delta(keep(arm), keep(base))['overall']
            full['excluded_from_overall'] = sorted(excluded)
        return full


def _env_list(env_specs, tested_name, env):
    try:
        eps = [envplugins.resolve(s, env=env) for s in env_specs]
        envplugins.check_set(eps, tested_name)
    except envplugins.EnvPluginError as e:
        raise ArmSourceError('环境插件：%s' % e)
    return eps


def plan_arms(*, plugin_dir, name, version, cases, evals_src, base=None, env_specs=(), tmp_parent=None,
              extra_exclude=(), env=None, log=None):
    """version 是工作目录 plugin.json 的 version 原值（没写为 None）。"""
    log = log or (lambda msg: None)
    env_plugins = _env_list(env_specs, name, env)
    try:
        res = previous.resolve(plugin_dir, version, base=base, current_name=name, ceiling=GIT_CEILING)
    except previous.BaseNotFound as e:
        raise ArmSourceError(str(e))

    plan = Plan(specs=[], previous=res, env_plugins=env_plugins)
    try:
        if not res.degraded:
            try:
                _take_snapshot(plan, tmp_parent)
            except previous.SnapshotError as e:
                res.degraded, res.reason_kind = True, 'snapshot-failed'
                res.reason = '上一版 %s（提交 %s）快照失败：%s' % (res.version, res.commit[:12], e)
                log('[上一版] 退化：%s' % res.reason)
        if res.degraded:
            log('[上一版] 跳过：%s' % res.reason)
        _finish(plan, plugin_dir=plugin_dir, name=name, cases=cases, evals_src=evals_src, extra_exclude=extra_exclude)
        return plan
    except BaseException:
        plan.cleanup()
        raise


def _take_snapshot(plan, tmp_parent):
    plan.snapshot_root = Path(tempfile.mkdtemp(prefix='devkit-plugin-eval-snap-', dir=tmp_parent))
    try:
        plan.snapshot_dir = previous.snapshot(plan.previous, plan.snapshot_root / 'snapshot')
    except previous.SnapshotError:
        plan.cleanup()
        raise


def _finish(plan, *, plugin_dir, name, cases, evals_src, extra_exclude):
    """快照与环境插件定好后，补环境插件指纹、跨改名不可比用例，列出臂清单。"""
    res, env_plugins = plan.previous, plan.env_plugins
    plan.env_fingerprints = {ep.spec: fingerprint.plugin_fingerprint(ep.dir) for ep in env_plugins}
    if res.cross_rename:
        plan.incomparable_cases = previous.cases_naming_skills(evals_src, cases, {name, res.name})

    specs = [arms.ArmSpec('none', '不装', None)]
    if plan.snapshot_dir:
        specs.append(arms.ArmSpec('previous', PREVIOUS_LABEL, plan.snapshot_dir, record=dict(
            source='git-snapshot', version=res.version, name=res.name, commit=res.commit,
            path_in_repo=res.path_in_repo, obtained_by=res.obtained_by, base=res.base,
            cross_rename=res.cross_rename,
            head_sha=None, dirty=None,   # 快照取自历史提交：没有工作区，当前版的 HEAD / dirty 不属于它
            fingerprint=fingerprint.plugin_fingerprint(plan.snapshot_dir, extra_exclude))))
    specs.append(arms.ArmSpec('current', '当前版', Path(plugin_dir)))
    if env_plugins:
        specs.append(arms.ArmSpec('current_with_env', ENV_LABEL, Path(plugin_dir), env_plugins=tuple(env_plugins),
                                  record=dict(source='working-tree+env', env_plugins=plan.env_records())))
    plan.specs = specs


def rebuild_plan(old, *, plugin_dir, name, version, cases, evals_src, tmp_parent=None, extra_exclude=(), env=None,
                 log=None):
    """续跑：按首跑 run.json（old）记下的来源重建臂计划。version 是 plugin.json 的 version 原值。

    - 没有 previous_arm 键（早于票 05 的运行）：只有不装与当前版两臂，legacy=True。
    - 上一版：首跑退化的照样退化；首跑有快照的，按同一 --base（或自动）重新认定，须落在同一提交，
      快照内容指纹须与首跑上一版臂记的一致。
    - 环境插件：按首跑入参重新取，版本与内容指纹须与首跑一致（installed 形态取的是本机当前安装，首跑后可能被更新）。
    对不上抛 ArmSourceError。
    """
    log = log or (lambda msg: None)
    if 'previous_arm' not in old:
        plan = Plan(specs=[], previous=previous.Resolution(degraded=True), legacy=True)
        plan.specs = [arms.ArmSpec('none', '不装', None), arms.ArmSpec('current', '当前版', Path(plugin_dir))]
        return plan

    env_recs = old.get('env_plugins') or []
    env_plugins = _env_list([r.get('spec') for r in env_recs], name, env)
    for r, ep in zip(env_recs, env_plugins):
        if r.get('version') != ep.version:
            raise ArmSourceError('环境插件 %s 的版本已从 %s 变为 %s，续跑会混入两版的结果；请重新对照'
                                 % (ep.spec, r.get('version'), ep.version))
        fp = fingerprint.plugin_fingerprint(ep.dir)
        if r.get('fingerprint') and r['fingerprint'] != fp:
            raise ArmSourceError('环境插件 %s 的内容指纹与首跑不同（%s → %s）；请重新对照' % (ep.spec, r['fingerprint'], fp))

    pa = old['previous_arm'] or {}
    keys = ('degraded', 'reason', 'reason_kind', 'commit', 'version', 'name', 'path_in_repo', 'obtained_by', 'base')
    if pa.get('degraded', True):
        res = previous.Resolution(**{k: pa.get(k) for k in keys})
        res.degraded = True
        res.current_name = name
    else:
        try:
            res = previous.resolve(plugin_dir, version, base=pa.get('base'), current_name=name, ceiling=GIT_CEILING)
        except previous.BaseNotFound as e:
            raise ArmSourceError('续跑重新认定上一版失败：%s' % e)
        if res.degraded or res.commit != pa.get('commit'):
            raise ArmSourceError('上一版认定与首跑不同（首跑提交 %s，现在 %s）；请重新对照'
                                 % (pa.get('commit'), res.commit if not res.degraded else '退化：%s' % res.reason))

    plan = Plan(specs=[], previous=res, env_plugins=env_plugins)
    try:
        if not res.degraded:
            try:
                _take_snapshot(plan, tmp_parent)
            except previous.SnapshotError as e:
                raise ArmSourceError('续跑重新取上一版快照失败：%s' % e)
        _finish(plan, plugin_dir=plugin_dir, name=name, cases=cases, evals_src=evals_src, extra_exclude=extra_exclude)
        old_fp = ((old.get('arms') or {}).get('previous') or {}).get('fingerprint')
        new_fp = next((s.record['fingerprint'] for s in plan.specs if s.key == 'previous'), None)
        if old_fp and new_fp != old_fp:
            raise ArmSourceError('上一版快照的内容指纹与首跑不同（%s → %s）；请重新对照' % (old_fp, new_fp))
        log('[续跑] 臂计划：%s' % '、'.join(s.label for s in plan.specs))
        return plan
    except BaseException:
        plan.cleanup()
        raise
