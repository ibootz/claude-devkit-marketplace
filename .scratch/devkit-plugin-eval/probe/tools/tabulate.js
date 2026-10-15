// 用法：node tabulate.js <out 目录> <标签>...
// 逐标签列出花费、durationSeconds、起始时刻（Asia/Shanghai）、墙钟秒数与退出码。
const fs = require('fs');
const path = require('path');
const [dir, ...tags] = process.argv.slice(2);
const read = (t, ext) => fs.readFileSync(path.join(dir, `${t}.${ext}`), 'utf8').trim();
let total = 0;
for (const t of tags) {
  const r = JSON.parse(read(t, 'json'));
  const s = Number(read(t, 'start'));
  const e = Number(read(t, 'end'));
  total += r.costUsd;
  const at = new Date(s * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
  console.log(`${t}\tcost=$${r.costUsd.toFixed(4)}\tdur=${r.durationSeconds}s\tstart=${at}\twall=${e - s}s\t${read(t, 'exit')}`);
}
console.log(`total cost=$${total.toFixed(4)}`);
