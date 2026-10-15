// 用法：node compare-init.js <result.json>...
// 逐 run 摘出 trace 里 system/init 行的结构字段与首个 assistant 消息的输入 token，
// 用来判断「装了空桩插件」与「不装插件」在模型可见面上是否一致。
const fs = require('fs');

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
  for (const c of r.cases) {
    for (const arm of Object.keys(c.arms || {})) {
      c.arms[arm].forEach((run, i) => {
        const lines = fs.readFileSync(run.tracePath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
        const init = lines.find((l) => l.type === 'system' && l.subtype === 'init');
        const hooks = lines.filter((l) => l.type === 'system' && /^hook_/.test(l.subtype || '')).length;
        const firstAsst = lines.find((l) => l.type === 'assistant');
        const u = (firstAsst && firstAsst.message && firstAsst.message.usage) || {};
        const inTok = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0);
        console.log(JSON.stringify({ tag: file.split('/').pop().replace('.json', ''), case: c.name, arm, run: i + 1, hookLines: hooks, firstInputTokens: inTok, ...pick(init || {}) }));
      });
    }
  }
}
