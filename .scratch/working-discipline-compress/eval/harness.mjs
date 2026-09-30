#!/usr/bin/env node
// working-discipline 注入压缩 A/B 行为评测装置
//
// 两组（arm）唯一差异是 --plugin-dir 加载的 working-discipline 目录：
//   old = snapshot/working-discipline（3.33.0 快照，只读）
//   new = plugins/working-discipline（主会话正在改的版本，本脚本只读它、不改它）
// 已装的 working-discipline@claude-devkit-marketplace 用 --settings 关掉；实测即便不关，
// --plugin-dir 同名插件也会覆盖已装版（见 PREMISE 待验证一节的回执），两道保险都留着。
//
// 用法（在任意 cwd 下用绝对路径调用即可）：
//   node harness.mjs --arm all --eval all --runs 3          # 全量：2 arm x 6 eval x 3 次
//   node harness.mjs --arm new --eval 2,parallel-config-audit --runs 3
//   node harness.mjs --arm old --eval enum-sql-readout --runs 1 --force
//   node harness.mjs --probe                                # 装置有效性探针：两组各跑一次最小调用
//   node harness.mjs --arm all --eval all --dry-run         # 只打印任务清单
//
// 落盘：eval/runs/<arm>/<eval-name>/run-<n>/{transcript.jsonl,final.md,meta.json,stderr.txt,project/}
//   project/ 是该 run 结束后 fixture 副本的现状（模型写的文件在里面）。
// 已有 meta.json 且 ok=true 的 run 默认跳过（可断点续跑）；--force 重跑覆盖。
//
// 关键点：run 的 cwd 放在系统临时目录、不放仓库内。实测 cwd 在本仓内时，仓根 CLAUDE.md
// 与 .claude/rules 会被自动加载（`git init` 也挡不住），给两组都叠一层无关指令；
// 放在临时目录则只剩用户级 CLAUDE.md。run 结束后 project/ 会拷回 eval/runs/ 下。
//
// 跨平台：Node 实现；claude 可执行文件先候选列表真跑 --version；prompt 走 stdin，避开命令行转义。

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const EVAL_ROOT = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(EVAL_ROOT, '..', '..', '..');
const FIXTURE_DIR = path.join(EVAL_ROOT, 'fixtures', 'mini-shop');
const RUNS_DIR = path.join(EVAL_ROOT, 'runs');
const SETTINGS_FILE = path.join(EVAL_ROOT, 'settings', 'disable-installed-wd.settings.json');
const EVALS_FILE = path.join(EVAL_ROOT, 'evals.json');
const PROBE_DIR = path.join(EVAL_ROOT, 'probe');

const ARM_DIRS = {
  old: path.join(REPO_ROOT, '.scratch', 'working-discipline-compress', 'snapshot', 'working-discipline'),
  new: path.join(REPO_ROOT, 'plugins', 'working-discipline'),
};
const MAX_CONCURRENCY = 4; // PREMISE 硬上限
const PLUGIN_NAME = 'working-discipline';

const PROBE_PROMPT =
  '不要调用任何工具。请原样复述你上下文里「# AI 工作纪律」段落的第一行原文，以及以「3.7」开头那一条的加粗标题原文。' +
  '若上下文里有多份「AI 工作纪律」，逐份分别列出。只输出复述结果。';

function die(msg) {
  console.error('错误：' + msg);
  process.exit(1);
}

function parseArgs(argv) {
  const a = {
    arm: 'all', eval: 'all', runs: 3, concurrency: MAX_CONCURRENCY, model: 'sonnet',
    timeoutSec: 600, retries: 1, force: false, dryRun: false, probe: false,
    runsRoot: path.join(fs.realpathSync(os.tmpdir()), 'wd-compress-eval'),
    runStart: 1,
  };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => {
      if (i + 1 >= argv.length) die(`${k} 缺少参数值`);
      return argv[++i];
    };
    switch (k) {
      case '--arm': a.arm = v(); break;
      case '--eval': a.eval = v(); break;
      case '--runs': a.runs = parseInt(v(), 10); break;
      case '--run-start': a.runStart = parseInt(v(), 10); break;
      case '--concurrency': a.concurrency = parseInt(v(), 10); break;
      case '--model': a.model = v(); break;
      case '--timeout-sec': a.timeoutSec = parseInt(v(), 10); break;
      case '--retries': a.retries = parseInt(v(), 10); break;
      case '--runs-root': a.runsRoot = path.resolve(v()); break;
      case '--force': a.force = true; break;
      case '--dry-run': a.dryRun = true; break;
      case '--probe': a.probe = true; break;
      case '-h': case '--help':
        console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('\n').slice(1, 27).join('\n'));
        process.exit(0);
        break;
      default: die('未知参数：' + k);
    }
  }
  if (!['old', 'new', 'all'].includes(a.arm)) die('--arm 必须是 old / new / all');
  if (!(a.runs >= 1) || !(a.runStart >= 1)) die('--runs / --run-start 必须是正整数');
  if (!(a.concurrency >= 1) || a.concurrency > MAX_CONCURRENCY) die(`--concurrency 必须在 1..${MAX_CONCURRENCY}`);
  if (a.runsRoot === REPO_ROOT || a.runsRoot.startsWith(REPO_ROOT + path.sep)) {
    die('--runs-root 不得在仓库内（仓根 CLAUDE.md 会污染两组），请用系统临时目录');
  }
  return a;
}

// ---------- claude CLI ----------

function resolveClaude() {
  const candidates = process.platform === 'win32' ? ['claude.cmd', 'claude.exe', 'claude'] : ['claude'];
  for (const cmd of candidates) {
    const r = spawnSync(cmd, ['--version'], { encoding: 'utf8', shell: cmd.endsWith('.cmd') });
    if (!r.error && r.status === 0) return { cmd, version: (r.stdout || '').trim() };
  }
  die('未能解析 claude 可执行文件，已尝试：' + candidates.join(', '));
}

const quoteWin = (s) => (/[\s"&|<>^]/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s);

const activeChildren = new Set();
process.on('SIGINT', () => {
  for (const c of activeChildren) c.kill('SIGTERM');
  process.exit(130);
});

function buildArgs({ model, pluginDir }) {
  return [
    '-p',
    '--model', model,
    '--output-format', 'stream-json',
    '--verbose',
    '--include-hook-events',
    '--settings', SETTINGS_FILE,
    '--plugin-dir', pluginDir,
    '--permission-mode', 'bypassPermissions',
    '--no-session-persistence',
  ];
}

// 起一次 claude -p：prompt 走 stdin，stdout 流式落盘，超时 SIGTERM 后 5 秒补 SIGKILL。
function spawnClaude({ claude, args, cwd, prompt, timeoutMs, stdoutFile }) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const isCmd = claude.cmd.endsWith('.cmd');
    const child = spawn(claude.cmd, isCmd ? args.map(quoteWin) : args, {
      cwd, shell: isCmd, stdio: ['pipe', 'pipe', 'pipe'],
    });
    activeChildren.add(child);
    const out = fs.createWriteStream(stdoutFile);
    let stderr = '';
    let timedOut = false;
    child.stdout.pipe(out);
    child.stderr.on('data', (d) => { stderr += d; if (stderr.length > 200000) stderr = stderr.slice(-100000); });
    child.stdin.on('error', () => {});
    child.stdin.end(prompt);
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => child.kill('SIGKILL'), 5000).unref();
    }, timeoutMs);
    const finish = (exitCode, signal, spawnError) => {
      clearTimeout(timer);
      activeChildren.delete(child);
      out.end(() => resolve({ exitCode, signal, timedOut, stderr, spawnError, durationMs: Date.now() - t0 }));
    };
    child.on('error', (e) => finish(null, null, String(e)));
    child.on('close', (code, signal) => finish(code, signal, null));
  });
}

// ---------- transcript 解析 ----------

function readEvents(file) {
  const events = [];
  if (!fs.existsSync(file)) return events;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch { /* 跳过被截断的末行 */ }
  }
  return events;
}

const sha1 = (s) => crypto.createHash('sha1').update(s).digest('hex').slice(0, 12);

function contextOf(output) {
  try { return JSON.parse(output).hookSpecificOutput.additionalContext || output; } catch { return output; }
}

// 装置有效性证据：加载的到底是哪个目录、注入了什么。
function extractInjection(events, pluginDir) {
  const init = events.find((e) => e.type === 'system' && e.subtype === 'init');
  const plugins = (init && init.plugins) || [];
  const wd = plugins.filter((p) => p.name === PLUGIN_NAME);
  const injections = [];
  for (const e of events) {
    if (e.type !== 'system' || e.subtype !== 'hook_response' || !e.output) continue;
    const text = contextOf(e.output);
    if (!text.includes('AI 工作纪律')) continue;
    const norm = text.split(pluginDir).join('<ROOT>'); // 路径不同会让哈希漂，先归一
    injections.push({
      event: e.hook_event,
      agent: e.hook_name,
      chars: text.length,
      sha1: sha1(norm),
      heading: text.split('\n')[0].slice(0, 80),
      title37: (text.match(/\*\*3\.7[^*\n]*\*\*/) || [null])[0],
    });
  }
  const counts = {};
  for (const i of injections) counts[i.event] = (counts[i.event] || 0) + 1;
  return {
    loadedPaths: wd.map((p) => p.path),
    loadedSources: wd.map((p) => p.source),
    pluginDirMatches: wd.length === 1 && path.resolve(wd[0].path) === path.resolve(pluginDir),
    counts,
    injections,
  };
}

function extractStats(events) {
  const byMsg = new Map(); // 同一条 API 消息的多个 content block 会拆成多个 assistant 事件，按 message.id 归并
  const agentCalls = [];
  const askUser = [];
  const writes = [];
  const toolCounts = {};
  for (const e of events) {
    if (e.type !== 'assistant' || e.parent_tool_use_id || !e.message) continue;
    const id = e.message.id || e.uuid;
    for (const b of e.message.content || []) {
      if (b.type !== 'tool_use') continue;
      toolCounts[b.name] = (toolCounts[b.name] || 0) + 1;
      byMsg.set(id, (byMsg.get(id) || 0) + 1);
      if (b.name === 'Agent' || b.name === 'Task') {
        const i = b.input || {};
        agentCalls.push({
          msgId: id, name: i.name, model: i.model, subagent_type: i.subagent_type,
          description: i.description, descriptionLen: (i.description || '').length,
        });
      }
      if (b.name === 'AskUserQuestion') askUser.push(id);
      if (b.name === 'Write' || b.name === 'Edit') writes.push((b.input || {}).file_path);
    }
  }
  const batches = [...byMsg.values()];
  return {
    toolCounts,
    firstToolBatchSize: batches.length ? batches[0] : 0, // 第一条带工具调用的 assistant 消息里并发了几个调用
    toolBatchSizes: batches,
    agentCalls,
    askUserQuestionCalls: askUser.length,
    writtenFiles: writes,
  };
}

function lastAssistantText(events) {
  let text = '';
  for (const e of events) {
    if (e.type === 'assistant' && !e.parent_tool_use_id && e.message) {
      const t = (e.message.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('\n');
      if (t) text = t;
    }
  }
  return text;
}

// ---------- 单个 run ----------

function copyDir(src, dst) {
  fs.cpSync(src, dst, { recursive: true });
}

function log(msg) {
  console.log(`[${new Date().toTimeString().slice(0, 8)}] ${msg}`);
}

async function runJob(job, opts, claude) {
  const { arm, ev, run } = job;
  const pluginDir = ARM_DIRS[arm];
  const outDir = path.join(RUNS_DIR, arm, ev.name, `run-${run}`);
  const metaFile = path.join(outDir, 'meta.json');
  const tag = `${arm}/${ev.name}/run-${run}`;
  if (!opts.force && fs.existsSync(metaFile)) {
    try {
      if (JSON.parse(fs.readFileSync(metaFile, 'utf8')).ok) {
        log(`跳过（已完成）${tag}`);
        return { tag, skipped: true, ok: true };
      }
    } catch { /* meta 损坏则重跑 */ }
  }
  fs.mkdirSync(outDir, { recursive: true });
  const attemptsLog = [];
  let verdict = null;
  const startedAt = new Date().toISOString();
  const totalStart = Date.now();

  for (let attempt = 1; attempt <= 1 + opts.retries; attempt++) {
    const tmpProject = path.join(opts.runsRoot, arm, ev.name, `run-${run}`, 'project');
    fs.rmSync(path.dirname(tmpProject), { recursive: true, force: true });
    copyDir(FIXTURE_DIR, tmpProject);
    const transcript = path.join(outDir, 'transcript.jsonl');
    const r = await spawnClaude({
      claude,
      args: buildArgs({ model: opts.model, pluginDir }),
      cwd: tmpProject,
      prompt: ev.prompt,
      timeoutMs: opts.timeoutSec * 1000,
      stdoutFile: transcript,
    });
    const events = readEvents(transcript);
    const result = events.find((e) => e.type === 'result') || null;
    const injection = extractInjection(events, pluginDir);
    const failReasons = [];
    if (r.spawnError) failReasons.push('spawn: ' + r.spawnError);
    if (r.timedOut) failReasons.push(`timeout>${opts.timeoutSec}s`);
    if (r.exitCode !== 0 && !r.timedOut) failReasons.push(`exit=${r.exitCode}${r.signal ? ' signal=' + r.signal : ''}`);
    if (!result) failReasons.push('no result event');
    else if (result.is_error) failReasons.push('result.is_error: ' + String(result.result).slice(0, 200));
    const armMismatch = !injection.pluginDirMatches;
    if (armMismatch) failReasons.push('arm 校验失败：加载的 working-discipline 不是预期目录 ' + JSON.stringify(injection.loadedPaths));
    const ok = failReasons.length === 0;
    attemptsLog.push({ attempt, ok, durationMs: r.durationMs, exitCode: r.exitCode, failReasons });
    verdict = { ok, r, events, result, injection };
    fs.writeFileSync(path.join(outDir, 'stderr.txt'), r.stderr || '');
    if (!ok && !armMismatch && attempt <= opts.retries) {
      fs.renameSync(transcript, path.join(outDir, `transcript.failed-${attempt}.jsonl`));
      log(`失败将重试 ${tag} attempt=${attempt}: ${failReasons.join('; ')}`);
      continue;
    }
    // 最终 attempt：把 project 现状拷回 eval/runs，清临时目录
    fs.rmSync(path.join(outDir, 'project'), { recursive: true, force: true });
    copyDir(tmpProject, path.join(outDir, 'project'));
    fs.rmSync(path.dirname(tmpProject), { recursive: true, force: true });
    break;
  }

  const { ok, r, events, result, injection } = verdict;
  const finalText = (result && typeof result.result === 'string' && result.result) || lastAssistantText(events);
  fs.writeFileSync(path.join(outDir, 'final.md'), finalText + '\n');
  const meta = {
    arm, eval: ev.name, evalId: ev.id, run, ok,
    attempts: attemptsLog,
    startedAt, finishedAt: new Date().toISOString(),
    wallMs: Date.now() - totalStart,
    lastAttemptMs: r.durationMs,
    exitCode: r.exitCode,
    timedOut: r.timedOut,
    model: opts.model,
    claudeVersion: claude.version,
    pluginDir,
    settingsFile: SETTINGS_FILE,
    permissionMode: 'bypassPermissions',
    resultModel: result && result.modelUsage ? Object.keys(result.modelUsage) : null,
    numTurns: result ? result.num_turns : null,
    apiMs: result ? result.duration_api_ms : null,
    costUsd: result ? result.total_cost_usd : null,
    injection,
    stats: extractStats(events),
  };
  fs.writeFileSync(metaFile, JSON.stringify(meta, null, 2));
  log(`${ok ? 'ok  ' : 'FAIL'} ${tag} ${(r.durationMs / 1000).toFixed(0)}s turns=${meta.numTurns}` +
    (ok ? '' : ' :: ' + attemptsLog[attemptsLog.length - 1].failReasons.join('; ')));
  return { tag, skipped: false, ok, ms: r.durationMs };
}

// ---------- 探针 ----------

async function runProbe(opts, claude) {
  const rows = [];
  await Promise.all(Object.keys(ARM_DIRS).map(async (arm) => {
    const dir = path.join(opts.runsRoot, 'probe', arm);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    const outDir = path.join(PROBE_DIR, `harness-${arm}`);
    fs.mkdirSync(outDir, { recursive: true });
    const transcript = path.join(outDir, 'transcript.jsonl');
    const r = await spawnClaude({
      claude, args: buildArgs({ model: opts.model, pluginDir: ARM_DIRS[arm] }), cwd: dir,
      prompt: PROBE_PROMPT, timeoutMs: opts.timeoutSec * 1000, stdoutFile: transcript,
    });
    const events = readEvents(transcript);
    const inj = extractInjection(events, ARM_DIRS[arm]);
    const result = events.find((e) => e.type === 'result');
    fs.writeFileSync(path.join(outDir, 'final.md'), (result && result.result) || '');
    fs.rmSync(dir, { recursive: true, force: true });
    rows.push({ arm, exit: r.exitCode, ms: r.durationMs, pluginDirMatches: inj.pluginDirMatches,
      loaded: inj.loadedPaths, injections: inj.injections, reply: (result && result.result) || null });
  }));
  for (const row of rows.sort((a, b) => a.arm.localeCompare(b.arm))) {
    console.log(`\n== ${row.arm}  exit=${row.exit}  ${(row.ms / 1000).toFixed(0)}s  加载目录匹配=${row.pluginDirMatches}`);
    console.log('   loaded:', row.loaded.join(', '));
    for (const i of row.injections) console.log(`   [${i.event}] chars=${i.chars} sha1(归一路径)=${i.sha1} 标题=${i.heading} 3.7=${i.title37}`);
    console.log('   模型复述:', String(row.reply).replace(/\n+/g, ' | '));
  }
  if (rows.some((r) => !r.pluginDirMatches || r.exit !== 0)) process.exitCode = 1;
}

// ---------- 主流程 ----------

function loadEvals() {
  return JSON.parse(fs.readFileSync(EVALS_FILE, 'utf8')).evals;
}

function selectEvals(all, sel) {
  if (sel === 'all') return all;
  const out = [];
  for (const s of sel.split(',').map((x) => x.trim()).filter(Boolean)) {
    const hit = all.find((e) => String(e.id) === s || e.name === s);
    if (!hit) die(`--eval 找不到 "${s}"，可选：${all.map((e) => `${e.id}/${e.name}`).join(', ')}`);
    out.push(hit);
  }
  return out;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  for (const arm of Object.keys(ARM_DIRS)) {
    if (!fs.existsSync(path.join(ARM_DIRS[arm], '.claude-plugin', 'plugin.json'))) die(`${arm} 目录不是有效插件：${ARM_DIRS[arm]}`);
  }
  if (!fs.existsSync(FIXTURE_DIR)) die('fixture 不存在：' + FIXTURE_DIR);
  const claude = resolveClaude();
  console.log(`claude ${claude.version} | model=${opts.model} | 并发=${opts.concurrency} | 超时=${opts.timeoutSec}s | 重试=${opts.retries}`);
  console.log(`runs-root(临时 cwd)=${opts.runsRoot}`);

  if (opts.probe) return runProbe(opts, claude);

  const evals = selectEvals(loadEvals(), opts.eval);
  const arms = opts.arm === 'all' ? ['old', 'new'] : [opts.arm];
  const jobs = [];
  // 按 run -> eval -> arm 交错排序：两组在时间上均匀混排，避免 API 状态漂移只落在某一组
  for (let run = opts.runStart; run < opts.runStart + opts.runs; run++) {
    for (const ev of evals) for (const arm of arms) jobs.push({ arm, ev, run });
  }
  console.log(`任务数 ${jobs.length}：arms=${arms.join(',')} evals=${evals.map((e) => e.name).join(',')} runs=${opts.runStart}..${opts.runStart + opts.runs - 1}`);
  if (opts.dryRun) {
    for (const j of jobs) console.log(`  ${j.arm}/${j.ev.name}/run-${j.run}`);
    console.log('claude 参数:', buildArgs({ model: opts.model, pluginDir: '<arm 目录>' }).join(' '));
    return;
  }

  const results = [];
  let next = 0;
  const worker = async () => {
    for (;;) {
      const i = next++;
      if (i >= jobs.length) return;
      try {
        results.push(await runJob(jobs[i], opts, claude));
      } catch (e) {
        log(`异常 ${jobs[i].arm}/${jobs[i].ev.name}/run-${jobs[i].run}: ${e && e.stack || e}`);
        results.push({ tag: `${jobs[i].arm}/${jobs[i].ev.name}/run-${jobs[i].run}`, ok: false, error: String(e) });
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(opts.concurrency, jobs.length) }, worker));

  const failed = results.filter((r) => !r.ok);
  const done = results.filter((r) => !r.skipped && r.ms);
  const avg = done.length ? done.reduce((s, r) => s + r.ms, 0) / done.length / 1000 : 0;
  console.log(`\n完成 ${results.length} 个：成功 ${results.length - failed.length}，失败 ${failed.length}，跳过 ${results.filter((r) => r.skipped).length}；本次实跑平均 ${avg.toFixed(0)}s/run`);
  for (const f of failed) console.log('  失败:', f.tag, f.error || '');
  if (failed.length) process.exitCode = 1;
}

main();
