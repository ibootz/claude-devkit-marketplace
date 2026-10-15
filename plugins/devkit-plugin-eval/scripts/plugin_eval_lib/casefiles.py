"""用例文件（eval 原生格式）的生成、检查与 tags 改写（票 11）。草稿、正式用例、基线标记共用。

一个用例目录（`claude plugin eval` 2.1.301 的 schema，二进制里的 zod 定义）：
  prompt.md        frontmatter（name / tags / max_turns / timeout_seconds / allowed_tools …）+ 正文即被测 prompt
  graders/<名>.md  只有 frontmatter；type 取 regex / tool_used / tool_order / file_exists（本机制只用规则 grader）
  judge/<id>.md    AI 评委判定标准（票 09；frontmatter 只认 rule / arms / clause，正文是判定标准）
  case.yaml        只在要文件桩时写：context.scaffold_script 指向 scaffold.sh
  scaffold.sh      eval 用 bash 执行（`--scaffold` 下；eval 的契约，不是本插件的脚本）
草稿目录另有 draft.json（drafts.META_FILE）；eval 静默忽略用例目录里的附加文件（spec「实施待定」第 3 条实测）。
"""
import json
import re
from pathlib import Path

PROMPT_KEYS = ('name', 'tags', 'plugins', 'runs', 'model', 'max_turns', 'timeout_seconds', 'allowed_tools',
               'append_system_prompt', 'env')
GRADER_TYPES = ('regex', 'tool_used', 'tool_order', 'file_exists')
GRADER_FIELDS = {
    'regex': ('target', 'pattern', 'flags', 'match', 'weight', 'arm'),
    'tool_used': ('tool', 'input_match', 'min', 'max', 'weight', 'arm'),
    'tool_order': ('before', 'after', 'weight', 'arm'),
    'file_exists': ('path', 'exists', 'weight', 'arm'),
}
REGEX_TARGETS = ('last_message', 'trace', 'files', 'mock_calls')
# eval 默认只给只读工具；Bash / Write / Edit / WebFetch 要操作者 --allow-tools，compare 不给，用例里写了也拿不到
ALLOWED_TOOLS = ('Read', 'Glob', 'Grep', 'Agent', 'Skill', 'TodoWrite')
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,63}$')
_GRADER_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
_FM_RE = re.compile(r'^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)', re.DOTALL)
SCAFFOLD_FILE = 'scaffold.sh'
MAX_TURNS_LIMIT = 200


def _q(s):
    """YAML 单引号标量：反斜杠原样（正则不用双写），单引号双写。"""
    return "'%s'" % str(s).replace("'", "''")


def _flow_list(items):
    return '[%s]' % ', '.join(json.dumps(str(x), ensure_ascii=False) for x in items)


def _scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return '{%s}' % ', '.join('%s: %s' % (k, _scalar(x)) for k, x in v.items() if x is not None)
    return _q(v)


# ---------------- 生成 ----------------

def render_prompt(spec):
    fm = ['name: %s' % spec['slug'], 'tags: %s' % _flow_list(spec.get('tags') or [])]
    if spec.get('max_turns'):
        fm.append('max_turns: %d' % int(spec['max_turns']))
    if spec.get('timeout_seconds'):
        fm.append('timeout_seconds: %d' % int(spec['timeout_seconds']))
    if spec.get('allowed_tools'):
        fm.append('allowed_tools: [%s]' % ', '.join(spec['allowed_tools']))
    return '---\n%s\n---\n%s\n' % ('\n'.join(fm), spec['prompt'].strip())


def render_grader(g):
    lines = ['type: %s' % g['type']]
    for k in GRADER_FIELDS[g['type']]:
        if g.get(k) is not None and g.get(k) != '':
            lines.append('%s: %s' % (k, _scalar(g[k])))
    return '---\n%s\n---\n' % '\n'.join(lines)


def render_judge(j):
    fm = []
    if j.get('rule'):
        fm.append('rule: %s' % j['rule'])
    if j.get('clause'):
        fm.append('clause: %s' % j['clause'])
    if j.get('arms'):
        fm.append('arms: [%s]' % ', '.join(j['arms']))
    head = '---\n%s\n---\n' % '\n'.join(fm) if fm else ''
    return head + j['criterion'].strip() + '\n'


def render_scaffold(files):
    """files：[{path, content}]，生成 bash 文件桩（eval 的 scaffold_script 契约是 bash）。"""
    lines = ['#!/bin/bash', 'set -e']
    for i, f in enumerate(files, 1):
        path = f['path']
        parent = str(Path(path).parent)
        if parent not in ('', '.'):
            lines.append('mkdir -p %s' % _sh_quote(parent))
        tag = 'PE_EOF_%d' % i
        while tag in f['content'].splitlines():
            tag += '_X'
        body = f['content'] if f['content'].endswith('\n') else f['content'] + '\n'
        lines.append("cat > %s <<'%s'\n%s%s" % (_sh_quote(path), tag, body, tag))
    return '\n'.join(lines) + '\n'


def _sh_quote(s):
    return "'%s'" % s.replace("'", "'\\''")


def render_case(spec):
    """spec → {相对路径: 文本}。spec 先过 validate_spec。"""
    out = {'prompt.md': render_prompt(spec)}
    for g in spec['graders']:
        out['graders/%s.md' % g['name']] = render_grader(g)
    for j in spec.get('judge') or []:
        out['judge/%s.md' % j['id']] = render_judge(j)
    ctx = []
    if spec.get('scaffold_files'):
        out[SCAFFOLD_FILE] = render_scaffold(spec['scaffold_files'])
        ctx.append('  scaffold_script: %s' % SCAFFOLD_FILE)
    if spec.get('history_file'):              # 票 13：回放用例的合成历史（设计票 19），history_text 是 jsonl 原文
        out[spec['history_file']] = spec['history_text']
        ctx.append('  history_file: %s' % spec['history_file'])
    if ctx:
        out['case.yaml'] = 'schema_version: "1.1"\nname: %s\ncontext:\n%s\n' % (spec['slug'], '\n'.join(ctx))
    return out


def write_case(case_dir, spec):
    case_dir = Path(case_dir)
    for rel, text in render_case(spec).items():
        p = case_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        if rel == SCAFFOLD_FILE:
            p.chmod(0o755)
    return case_dir


# ---------------- 检查 ----------------

def _safe_rel(path):
    p = str(path or '')
    return bool(p) and not p.startswith(('/', '\\', '~')) and '..' not in Path(p).parts and ':' not in p


def scored(g):
    """计分的规则 grader：不是 with-only，也不是 eval 隐式视同 with-only 的 tool_used: Skill（scoring._exclusion_reason）。"""
    return g.get('arm') != 'with-only' and not (g.get('type') == 'tool_used' and g.get('tool') == 'Skill'
                                                 and g.get('arm') is None)


def validate_spec(spec):
    """返回问题清单（空 = 可写）。只查结构：正则是 JS 语法，这里不编译。"""
    p = []
    if not SLUG_RE.match(str(spec.get('slug') or '')):
        p.append('slug %r 不合法（小写字母、数字、连字符，2～64 字符）' % spec.get('slug'))
    if not str(spec.get('prompt') or '').strip():
        p.append('prompt 为空')
    mt = spec.get('max_turns')
    if mt is not None and (not isinstance(mt, int) or not 1 <= mt <= MAX_TURNS_LIMIT):
        p.append('max_turns 应是 1～%d 的整数' % MAX_TURNS_LIMIT)
    bad_tools = [t for t in spec.get('allowed_tools') or [] if t not in ALLOWED_TOOLS]
    if bad_tools:
        p.append('allowed_tools 只能用只读工具 %s，不能用 %s' % ('、'.join(ALLOWED_TOOLS), '、'.join(bad_tools)))
    graders = spec.get('graders') or []
    names = set()
    for g in graders:
        n, t = g.get('name'), g.get('type')
        if not _GRADER_NAME_RE.match(str(n or '')) or n in names:
            p.append('grader 名 %r 不合法或重复' % n)
        names.add(n)
        if t not in GRADER_TYPES:
            p.append('grader %s 的 type %r 不是规则 grader（%s）' % (n, t, '、'.join(GRADER_TYPES)))
            continue
        extra = [k for k in g if k not in GRADER_FIELDS[t] + ('name', 'type') and g[k] not in (None, '')]
        if extra:
            p.append('grader %s（%s）有不认识的字段 %s' % (n, t, '、'.join(sorted(extra))))
        if t == 'regex':
            if not g.get('pattern'):
                p.append('grader %s 缺 pattern' % n)
            if g.get('target') not in (None, '') + REGEX_TARGETS:
                p.append('grader %s 的 target %r 不在 %s' % (n, g.get('target'), '、'.join(REGEX_TARGETS)))
            m = g.get('match')
            if m not in (None, '', 'contains', 'not_contains') and not re.match(r'^count:\d+$', str(m)):
                p.append('grader %s 的 match %r 应为 contains / not_contains / count:N' % (n, m))
        elif t == 'tool_used':
            if not g.get('tool'):
                p.append('grader %s 缺 tool' % n)
            for k in ('min', 'max'):
                if g.get(k) is not None and (not isinstance(g[k], int) or g[k] < 0):
                    p.append('grader %s 的 %s 应是非负整数' % (n, k))
            if g.get('max') == 0 and g.get('min') is None:
                # eval 的 min 缺省为 1：只写 max: 0 恒不通过（票 11 演示实测「expected 1..0」）
                p.append('grader %s 判「没调用」要同时写 min: 0（eval 的 min 缺省为 1，只写 max: 0 恒不通过）' % n)
        elif t == 'tool_order':
            if not g.get('before') or not g.get('after'):
                p.append('grader %s 缺 before / after' % n)
        elif t == 'file_exists':
            if not _safe_rel(g.get('path')):
                p.append('grader %s 的 path 应是相对路径' % n)
        if g.get('arm') not in (None, '', 'with-only', 'both'):
            p.append('grader %s 的 arm %r 应为 with-only / both' % (n, g.get('arm')))
    if not any(scored(g) for g in graders if g.get('type') in GRADER_TYPES):
        p.append('没有计分的规则 grader（with-only 与 tool_used: Skill 不计分）：基线与是否通过都判不了')
    jids = set()
    for j in spec.get('judge') or []:
        if not _GRADER_NAME_RE.match(str(j.get('id') or '')) or j.get('id') in jids:
            p.append('judge id %r 不合法或重复' % j.get('id'))
        jids.add(j.get('id'))
        if not str(j.get('criterion') or '').strip():
            p.append('judge %s 没有判定标准' % j.get('id'))
        if j.get('rule') and j['rule'] not in names:
            p.append('judge %s 的 rule %r 不是本用例的 grader' % (j.get('id'), j['rule']))
    for f in spec.get('scaffold_files') or []:
        if not _safe_rel(f.get('path')):
            p.append('文件桩路径 %r 应是用例工作目录内的相对路径' % f.get('path'))
        if not isinstance(f.get('content'), str):
            p.append('文件桩 %r 没有内容' % f.get('path'))
    return p


def frontmatter(text):
    """(frontmatter 原文或 None, 正文)。"""
    m = _FM_RE.match(text or '')
    if not m:
        return None, text or ''
    return m.group(1), text[m.end():]


def _keys(fm):
    return [ln.split(':', 1)[0].strip() for ln in (fm or '').splitlines()
            if ln.strip() and not ln.startswith((' ', '\t', '-', '#')) and ':' in ln]


def check_case_dir(case_dir):
    """已落盘的用例目录能否被 eval 加载（票 01 报告第六节：两种加载失败）。返回问题清单。"""
    case_dir = Path(case_dir)
    p = []
    prompt = case_dir / 'prompt.md'
    if not prompt.is_file() and not (case_dir / 'case.yaml').is_file():
        return ['没有 prompt.md 或 case.yaml']
    if prompt.is_file():
        fm, body = frontmatter(prompt.read_text(encoding='utf-8'))
        unknown = [k for k in _keys(fm) if k not in PROMPT_KEYS]
        if unknown:
            p.append('prompt.md frontmatter 有 eval 不认识的键 %s（会让用例加载失败）' % '、'.join(unknown))
        if not body.strip():
            p.append('prompt.md 正文（被测 prompt）为空')
    gdir = case_dir / 'graders'
    graders = sorted(gdir.glob('*.md')) if gdir.is_dir() else []
    if not graders:
        p.append('graders/ 下没有 grader（eval 要求至少一个）')
    for g in graders:
        fm, _ = frontmatter(g.read_text(encoding='utf-8'))
        if fm is not None and 'type' not in _keys(fm):
            p.append('graders/%s 带 frontmatter 却没有 type（会让用例加载失败）' % g.name)
        if fm is not None and re.search(r'^max\s*:\s*0\s*$', fm, re.M) and 'min' not in _keys(fm):
            p.append('graders/%s 只写了 max: 0 没写 min（eval 的 min 缺省为 1，恒不通过）' % g.name)
    yaml = case_dir / 'case.yaml'
    if yaml.is_file():
        m = re.search(r'scaffold_script\s*:\s*(\S+)', yaml.read_text(encoding='utf-8'))
        if m and not (case_dir / m.group(1).strip('\'"')).is_file():
            p.append('case.yaml 的 scaffold_script 指向的 %s 不存在' % m.group(1))
        h = re.search(r'^\s*history_file\s*:\s*(\S+)', yaml.read_text(encoding='utf-8'), re.M)
        if h:
            rel = h.group(1).strip('\'"')
            hp = case_dir / rel
            if not _safe_rel(rel) or not hp.is_file() or hp.is_symlink():
                p.append('case.yaml 的 history_file 应指向用例目录内的普通文件，%s 不是' % rel)
            if not prompt.is_file():
                p.append('配了 history_file 就要有被测 prompt（prompt.md）')
    return p


# ---------------- tags 改写 ----------------

_TAGS_LINE_RE = re.compile(r'^tags\s*:(.*)$', re.MULTILINE)


def _tag_file(case_dir):
    """tags 写在哪个文件：case.yaml 有 tags 行就改它，否则改 prompt.md 的 frontmatter。"""
    case_dir = Path(case_dir)
    yaml = case_dir / 'case.yaml'
    if yaml.is_file() and _TAGS_LINE_RE.search(yaml.read_text(encoding='utf-8')):
        return yaml
    return case_dir / 'prompt.md'


def _replace_tags_block(block, tags):
    """block 是 YAML 文本（frontmatter 或 case.yaml）：把 tags 换成 flow 列表；没有就追加一行。"""
    lines = block.split('\n')
    out, i, done = [], 0, False
    while i < len(lines):
        ln = lines[i]
        if not done and re.match(r'^tags\s*:', ln):
            out.append('tags: %s' % _flow_list(tags))
            done = True
            i += 1
            if not ln.split(':', 1)[1].split(' #')[0].strip():       # 块状列表：吃掉后面的 - 项
                while i < len(lines) and re.match(r'^\s+-\s', lines[i]):
                    i += 1
            continue
        out.append(ln)
        i += 1
    if not done:
        out.append('tags: %s' % _flow_list(tags))
    return '\n'.join(out)


def set_tags(case_dir, tags):
    """把用例的 tags 整体换成 tags（保持顺序、去重）。返回改写的文件。"""
    tags = list(dict.fromkeys(tags))
    f = _tag_file(case_dir)
    text = f.read_text(encoding='utf-8') if f.is_file() else ''
    if f.name == 'case.yaml':
        new = _replace_tags_block(text.rstrip('\n'), tags) + '\n'
    else:
        fm, body = frontmatter(text)
        if fm is None:
            new = '---\ntags: %s\n---\n%s' % (_flow_list(tags), text)
        else:
            new = '---\n%s\n---\n%s' % (_replace_tags_block(fm, tags), body)
    f.write_text(new, encoding='utf-8')
    return f


def retarget_judge_clause(case_dir, old, new):
    """judge/*.md frontmatter 的 clause: old 改成 new（new 为 None 时删掉这一行）。返回改了几个文件。"""
    n = 0
    d = Path(case_dir) / 'judge'
    if not d.is_dir():
        return 0
    for f in sorted(d.glob('*.md')):
        text = f.read_text(encoding='utf-8')
        fm, body = frontmatter(text)
        if fm is None:
            continue
        pat = re.compile(r'^clause\s*:\s*[\'"]?%s[\'"]?\s*$' % re.escape(old), re.MULTILINE)
        if not pat.search(fm):
            continue
        fm2 = pat.sub('clause: %s' % new if new else '', fm)
        fm2 = '\n'.join(ln for ln in fm2.split('\n') if ln.strip())
        f.write_text('---\n%s\n---\n%s' % (fm2.strip('\n'), body), encoding='utf-8')
        n += 1
    return n
