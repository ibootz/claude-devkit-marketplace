#!/usr/bin/env python3
"""汇总每个 run：臂、首个 API 请求的输入 token、SessionStart/UserPromptSubmit 注入是否落在子会话转录里。
用法：inspect.py <eval json> [<case 目录外的子会话转录 jsonl>...]"""
import json, sys, os, glob, re, collections
res = json.load(open(sys.argv[1]))
transcripts = sys.argv[2:]
# 按沙箱路径（cwd 里的 e-XXXX）索引转录里的注入
inj = collections.defaultdict(lambda: collections.Counter())
for t in transcripts:
    for l in open(t):
        d = json.loads(l)
        cwd = d.get('cwd') or ''
        m = re.search(r'/(e-[A-Za-z0-9]+)/', cwd)
        if not m: continue
        a = d.get('attachment') or {}
        if a.get('type') == 'hook_additional_context':
            inj[m.group(1)][a.get('hookName') or '?'] += 1
        if a.get('type') == 'hook_success':
            inj[m.group(1)]['ok:' + (a.get('hookName') or '?')] += 1
        if a.get('type') == 'hook_non_blocking_error':
            inj[m.group(1)]['ERR:' + (a.get('hookName') or '?') + ':' + str(a.get('exitCode'))] += 1
for c in res['cases']:
    for arm, runs in c['arms'].items():
        for i, r in enumerate(runs):
            tp = r['tracePath']; sb = re.search(r'/(e-[A-Za-z0-9]+)/', tp).group(1)
            first = None; hooks = []
            if os.path.exists(tp):
                for l in open(tp):
                    d = json.loads(l)
                    if d.get('type') == 'system' and d.get('subtype') == 'hook_response':
                        hooks.append('%s exit=%s' % (d.get('hook_name'), d.get('exit_code')))
                    if d.get('type') == 'assistant' and first is None:
                        u = d['message'].get('usage', {})
                        first = u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)
            print('%s %s#%d score=%.2f cost=%.4f sandbox=%s first_req_input_tokens=%s trace_hooks=%s transcript_inj=%s' % (
                c['name'], arm, i + 1, r['score'], r.get('costUsd') or 0, sb, first, hooks, dict(inj.get(sb, {}))))
