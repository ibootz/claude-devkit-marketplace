"""被测插件的 hook 声明与常驻注入的静态测量（spec「2.2 离线对照」第 7 步：常驻 token 静态算）。

- 读声明：plugin.json 的 `hooks`（内联对象、单个或多个相对路径）与默认的 `hooks/hooks.json`，只取 `type: command`。
- 执行：真实 HOME、空临时 cwd（spec 第 2 步同款口径），`${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}`
  按文字替换（与 Claude Code 一致），CLAUDE_PLUGIN_DATA 指向临时目录，免得写脏用户真实数据目录。
- 只执行「常驻」事件：SessionStart、UserPromptSubmit、SubagentStart——每次会话 / 每轮 / 每个子代理必注。
  PreToolUse 等按工具入参条件注入，列进 conditional_hooks，不执行、不计常驻。
- token 不调模型，按字符估算，口径见 estimate_tokens。

每个 hook 的身份（key）= 「事件 | matcher | command 原文」：转录里 hook 结果的 `command` 也是未展开的原文，
两边可直接比对（spec「2.5」注入信号一行：靠「事件 + matcher + 脚本相对路径」指纹加内容标签归因）。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RESIDENT_EVENTS = ('SessionStart', 'UserPromptSubmit', 'SubagentStart')
# 纯文本 stdout 会被当作上下文的事件（官方 hooks 文档）；其余事件只认 JSON 的 additionalContext
PLAIN_STDOUT_EVENTS = ('SessionStart', 'UserPromptSubmit')
SESSION_SOURCES = ('startup', 'resume', 'clear', 'compact')
DEFAULT_TIMEOUT_SEC = 60
BLOCKING_EXIT_CODE = 2
LABEL_MAX = 60
STATIC_SESSION_ID = 'devkit-plugin-eval-static'

# 估算系数：码位 ≥ U+2E80（中日韩文字与全角标点）每字 1.33 token，其余每字 0.29 token。
# 校准依据（Claude Code 2.1.300、claude-opus-5-5 实测首请求输入 token）：devkit-discipline 4.1.0 装与不装
# 首请求差约 6574（SessionStart + 一次 UserPromptSubmit 注入 + 一条 skill 列表），按本式估 6305 + skill 列表约 215；
# devkit-clickable-paths 的 UserPromptSubmit 注入实测约 1369，本式估 1404。误差约 ±5%，只作信息。
WIDE_CODEPOINT = 0x2E80
WIDE_RATE = 1.33
NARROW_RATE = 0.29
METHOD = {
    'name': 'char-estimate-v1',
    'formula': 'round(宽字符数 × %.2f + 其余字符数 × %.2f)，宽字符 = 码位 ≥ U+%04X' % (WIDE_RATE, NARROW_RATE, WIDE_CODEPOINT),
    'calibration': 'Claude Code 2.1.300 / claude-opus-5-5 首请求输入 token 实测，误差约 ±5%',
    'scope': '只计注入正文，不含 Claude Code 包装的 system-reminder 前缀；不调模型',
    'execution': '真实 HOME、空临时 cwd、CLAUDE_PLUGIN_DATA 指向临时目录；PATH 与 eval 子进程相同（已去掉 asdf shims）',
}


@dataclass(frozen=True)
class HookSpec:
    event: str
    matcher: Optional[str]
    command: str
    timeout: Optional[int]

    @property
    def key(self):
        return '%s|%s|%s' % (self.event, self.matcher or '', self.command)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _specs_from_mapping(mapping):
    """mapping 形如 {事件: [{matcher, hooks: [{type, command, timeout}]}]}。"""
    out = []
    if not isinstance(mapping, dict):
        return out
    for event, groups in mapping.items():
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            matcher = group.get('matcher')
            for h in group.get('hooks') or []:
                if isinstance(h, dict) and h.get('type') == 'command' and isinstance(h.get('command'), str):
                    timeout = h.get('timeout')
                    out.append(HookSpec(event, matcher if matcher not in ('',) else None, h['command'],
                                        timeout if isinstance(timeout, (int, float)) else None))
    return out


def _specs_from_file(path):
    data = _read_json(path)
    return _specs_from_mapping(data.get('hooks') if isinstance(data, dict) and 'hooks' in data else data)


def load_hook_specs(plugin_dir):
    """返回插件声明的全部 command 型 hook，按声明顺序（plugin.json 在前，默认 hooks/hooks.json 在后）。"""
    root = Path(plugin_dir)
    specs, loaded_files = [], set()
    manifest = root / '.claude-plugin' / 'plugin.json'
    declared = _read_json(manifest).get('hooks') if manifest.is_file() else None
    if isinstance(declared, dict):
        specs += _specs_from_mapping(declared)
    else:
        for rel in ([declared] if isinstance(declared, str) else declared if isinstance(declared, list) else []):
            if not isinstance(rel, str):
                continue
            path = (root / rel).resolve()
            if path.is_file() and path not in loaded_files:
                loaded_files.add(path)
                specs += _specs_from_file(path)
    default = (root / 'hooks' / 'hooks.json').resolve()
    if default.is_file() and default not in loaded_files:
        specs += _specs_from_file(default)
    return specs


def matcher_matches(matcher, value):
    if matcher in (None, '', '*'):
        return True
    try:
        return re.fullmatch(matcher, value) is not None
    except re.error:
        return matcher == value


def _session_source(matcher):
    for s in SESSION_SOURCES:
        if matcher_matches(matcher, s):
            return s
    return 'startup'


def _payload(spec, cwd, transcript_path):
    ev = {'session_id': STATIC_SESSION_ID, 'transcript_path': str(transcript_path), 'cwd': str(cwd),
          'hook_event_name': spec.event, 'permission_mode': 'default'}
    if spec.event == 'SessionStart':
        ev['source'] = _session_source(spec.matcher)
    elif spec.event == 'UserPromptSubmit':
        ev['prompt'] = '你好'
    elif spec.event == 'SubagentStart':
        ev.update(agent_id='devkit-plugin-eval-static-agent', agent_type='general-purpose')
    return ev


def extract_injection(event, stdout):
    """从 hook stdout 取注入正文；没有注入返回 None。"""
    s = (stdout or '').strip()
    if not s:
        return None
    if s.startswith('{'):
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            ctx = (obj.get('hookSpecificOutput') or {}).get('additionalContext')
            return ctx if isinstance(ctx, str) and ctx.strip() else None
    return s if event in PLAIN_STDOUT_EVENTS else None


def estimate_tokens(text):
    if not text:
        return 0
    wide = sum(1 for ch in text if ord(ch) >= WIDE_CODEPOINT)
    return int(round(wide * WIDE_RATE + (len(text) - wide) * NARROW_RATE))


def content_label(text):
    """内容标签：注入正文第一行非空文字（截到 LABEL_MAX 字），用来在转录里认出这条 hook 的注入。"""
    for line in (text or '').splitlines():
        line = line.strip()
        if line:
            return line[:LABEL_MAX]
    return None


def _expand(command, plugin_root, data_dir):
    return command.replace('${CLAUDE_PLUGIN_ROOT}', str(plugin_root)).replace('${CLAUDE_PLUGIN_DATA}', str(data_dir))


def run_hook(spec, plugin_root, *, env, work_parent=None):
    """执行一条 hook 一次。返回 exit_code、timed_out、duration_ms、raw_text（不论退出码都解析出的注入）、
    text（Claude Code 实际会注入的）、stderr 尾部。临时目录用完即删。

    text 的口径（2.1.300 实测）：UserPromptSubmit hook 输出 JSON 后以 3 退出，additionalContext 照样进了
    子会话转录、也没有失败记录；所以只有超时与退出码 2（阻断，官方文档：此时忽略 stdout）不算注入。"""
    plugin_root = Path(plugin_root).resolve()   # hook 在临时 cwd 里跑，相对路径会指错
    if work_parent:
        Path(work_parent).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='pe-hook-', dir=str(work_parent) if work_parent else None))
    try:
        cwd, data_dir = work / 'cwd', work / 'plugin-data'
        cwd.mkdir()
        data_dir.mkdir()
        transcript = work / 'transcript.jsonl'
        transcript.write_text('', encoding='utf-8')
        child = dict(env)
        child.update(CLAUDE_PLUGIN_ROOT=str(plugin_root), CLAUDE_PLUGIN_DATA=str(data_dir), CLAUDE_PROJECT_DIR=str(cwd))
        payload = json.dumps(_payload(spec, cwd, transcript), ensure_ascii=False).encode('utf-8')
        started = time.monotonic()
        res = {'exit_code': None, 'timed_out': False, 'stderr': ''}
        try:
            proc = subprocess.run(_expand(spec.command, plugin_root, data_dir), shell=True, cwd=str(cwd), env=child,
                                  input=payload, capture_output=True, timeout=spec.timeout or DEFAULT_TIMEOUT_SEC)
            res['exit_code'] = proc.returncode
            stdout = proc.stdout.decode('utf-8', errors='replace')
            res['stderr'] = proc.stderr.decode('utf-8', errors='replace')[-500:]
        except subprocess.TimeoutExpired:
            res['timed_out'] = True
            stdout = ''
        res['duration_ms'] = int((time.monotonic() - started) * 1000)
        res['raw_text'] = extract_injection(spec.event, stdout)
        res['text'] = None if res['timed_out'] or res['exit_code'] == BLOCKING_EXIT_CODE else res['raw_text']
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


def static_profile(plugin_dir, *, env=None, work_parent=None):
    """执行插件全部常驻事件 hook，返回逐 hook 与逐事件的注入字数、估算 token、内容标签。

    expected（到达核验要不要等它）：静态有注入正文，或静态执行失败（失败时不知道它会不会注入，从严算）。
    静态退出 0 却没输出的 hook 是条件注入（如依赖转录内容），不核验到达。
    """
    env = dict(os.environ if env is None else env)
    hooks, conditional, errors = [], [], []
    by_event = {}
    try:
        specs = load_hook_specs(plugin_dir)
    except (OSError, ValueError) as e:     # hook 声明读不出来不中止对照，记进 errors 由报告首段标出
        specs = []
        errors.append('读 hook 声明失败：%s' % e)
    for spec in specs:
        if spec.event not in RESIDENT_EVENTS:
            conditional.append({'key': spec.key, 'event': spec.event, 'matcher': spec.matcher, 'command': spec.command})
            continue
        r = run_hook(spec, plugin_dir, env=env, work_parent=work_parent)
        failed = r['timed_out'] or r['exit_code'] != 0
        text = r['text'] or ''
        item = {
            'key': spec.key, 'event': spec.event, 'matcher': spec.matcher, 'command': spec.command,
            'exit_code': r['exit_code'], 'timed_out': r['timed_out'], 'duration_ms': r['duration_ms'],
            'chars': len(text), 'tokens_est': estimate_tokens(text),
            'label': content_label(r['raw_text']), 'expected': bool(r['raw_text']) or failed,
        }
        if failed:
            item['stderr_tail'] = r['stderr']
            errors.append('%s：%s' % (spec.key, '超时' if r['timed_out'] else '退出码 %s' % r['exit_code']))
        hooks.append(item)
        agg = by_event.setdefault(spec.event, {'hooks': 0, 'injecting_hooks': 0, 'chars': 0, 'tokens_est': 0})
        agg['hooks'] += 1
        agg['injecting_hooks'] += 1 if text else 0
        agg['chars'] += item['chars']
        agg['tokens_est'] += item['tokens_est']
    return {
        'method': METHOD,
        'hooks': hooks,
        'by_event': by_event,
        'total_tokens_est': sum(v['tokens_est'] for v in by_event.values()),
        'conditional_hooks': conditional,
        'errors': errors,
    }
