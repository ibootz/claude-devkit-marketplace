// 用法：node summarize.js <result.json>
const r=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));
console.log(`claude=${r.claudeVersion} dur=${r.durationSeconds}s cost=$${r.costUsd.toFixed(4)} partial=${r.partial} ${r.partialReason||''} ablation=${r.suite.ablation}`);
console.log('aggregates', JSON.stringify(r.aggregates));
console.log('plugins', JSON.stringify(r.suite.plugins));
for (const c of r.cases){
  console.log(`\n# ${c.name} score=${c.aggregates&&c.aggregates.score} delta=${c.aggregates&&c.aggregates.delta} agg=${JSON.stringify(c.aggregates)} err=${c.error||''}`);
  if (c.plugins) console.log(' case.plugins', JSON.stringify(c.plugins));
  for (const arm of Object.keys(c.arms||{})){
    c.arms[arm].forEach((run,i)=>{
      console.log(`  [${arm}#${i+1}] score=${run.score} turns=${run.turns} cost=${(run.costUsd||0).toFixed(4)} dur=${run.durationSeconds}s err=${run.error} trace=${run.tracePath}`);
      for (const g of run.graders) console.log(`     ${g.passed?'PASS':'FAIL'} ${g.name}${g.scored===false?' (unscored)':''} — ${g.explanation}`);
    });
  }
}
