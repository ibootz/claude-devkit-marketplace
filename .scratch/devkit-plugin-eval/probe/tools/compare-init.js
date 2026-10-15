// 用法：node compare-init.js <result.json>...
// 逐 run 摘出 trace 里 system/init 行的结构字段与首个 assistant 消息的输入 token，
// 用来判断「装了空桩插件」与「不装插件」在模型可见面上是否一致。
// 沙箱 /private/tmp/e-* 清掉后，退回读 probe/traces/<标签>/<用例>-<臂>-<序号>/trace.jsonl 本地副本。
const fs = require('fs');
const path = require('path');

function locateTrace(tag, caseName, arm, n, tracePath) {
  if (tracePath && fs.existsSync(tracePath)) return tracePath;
  const local = path.join(__dirname, '..', 'traces', tag, `${caseName}-${arm}-${n}`, 'trace.jsonl');
  if (fs.existsSync(local)) return local;
  throw new Error(`trace 不存在：${tracePath}，本地副本也没有：${local}`);
}

function pick(init) {
  const plugins = (init.plugins || []).map((p) => p.name || p).sort();
  return {
    tools: (init.tools || []).slice().sort().join(','),
    skills: (init.skills || []).slice().sort().join(','),
    slash: (init.slash_commands || []).slice().sort().join(','),
    agents: (init.agents || []).slice().sort().join(','),
    mcp: (init.mcp_servers || []).map((s) => s.name).sort().join(','),
    plugins: plugins.join(','),
    model: init.model,
  };
}

for (const file of process.argv.slice(2)) {
  const r = JSON.parse(fs.readFileSync(file, 'utf8'));
  const tag = path.basename(file, '.json');
  for (const c of r.cases) {
    for (const arm of Object.keys(c.arms || {})) {
      c.arms[arm].forEach((run, i) => {
        const lines = fs.readFileSync(locateTrace(tag, c.name, arm, i + 1, run.tracePath), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
        const init = lines.find((l) => l.type === 'system' && l.subtype === 'init');
        const hooks = lines.filter((l) => l.type === 'system' && /^hook_/.test(l.subtype || '')).length;
        const firstAsst = lines.find((l) => l.type === 'assistant');
        const u = (firstAsst && firstAsst.message && firstAsst.message.usage) || {};
        const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
        console.log(JSON.stringify({ tag, case: c.name, arm, run: i + 1, hookLines: hooks, firstInputTokens: inTok, ...pick(init || {}) }));
      });
    }
  }
}
