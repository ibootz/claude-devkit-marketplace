#!/usr/bin/env node
// wenyan-discourse-coherence 评测装置 · 主脚本
//
// 只做一件事：以 headless `claude -p` 主会话为载体，按场景定义（scenarios/<id>/）
// 跑指定的 arm（baseline / no-style / new），把原始记录（含注入证据、模型回复全文、
// 运行元数据）落盘到 raw/<arm>/<scenario-id>/run-<n>.json。
//
// 不做评分、不做子代理派发、不修改 plugins/** 下任何文件。
//
// 【为什么不用子代理】wenyan-output-style 只通过主会话的 SessionStart 与
// UserPromptSubmit 注入，子代理两者都收不到（工单 01 premise 已核实事实）。
// 本脚本因此只调用 headless `claude -p`，绝不通过 Task/Agent 工具生成评测输出。
//
// 【跨平台】按仓库全局约定，写 Node.js 而非 shell 脚本；调用外部 claude CLI 前
// 先用候选列表真跑 `--version` 探测可执行文件，不只查 PATH 存在性。
//
// 用法：
//   node harness.mjs --arm baseline --scenario all \
//     --plugin-dir <baseline 快照里 wenyan-output-style 插件目录> \
//     --model claude-sonnet-4-5 \
//     --runs-root <jobs/tmp 下的 fixture 工作目录>
//
//   node harness.mjs --arm no-style --scenario all \
//     --model claude-sonnet-4-5 \
//     --runs-root <jobs/tmp 下的 fixture 工作目录>
//
//   node harness.mjs --arm new --scenario all \
//     --plugin-dir <04 号票产出的新版 wenyan-output-style 插件目录> \
//     --model claude-sonnet-4-5 \
//     --runs-root <jobs/tmp 下的 fixture 工作目录>
//
// --scenario 支持单个场景 id、逗号分隔多个 id，或 "all"。

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const EVAL_ROOT = path.dirname(fileURLToPath(import.meta.url));
const SCENARIOS_DIR = path.join(EVAL_ROOT, 'scenarios');
const FIXTURES_DIR = path.join(EVAL_ROOT, 'fixtures', 'mini-project');
const RAW_DIR = path.join(EVAL_ROOT, 'raw');
const DEFAULT_SETTINGS = path.join(EVAL_ROOT, 'settings', 'disable-styles.settings.json');

// 三组风格插件各自 SessionStart 注入头部的可识别子串（用于 stream-json 里的
// 逐条 hook 输出做字符串匹配，判定"这一轮到底注入了谁"）。
const STYLE_MARKERS = {
  'wenyan-output-style': '文言极简模式已启用',
  'plain-talk-output-style': '你处于「说人话」输出风格',
  'adhd-output-style': 'ADHD MODE ACTIVE',
};

// 每次调用 claude CLI 时统一放行的工具集合。三组场景在这一点上必须完全一致，
// 差异只应该来自启用的插件集合（--plugin-dir / --settings），不能来自工具权限。
const ALLOWED_TOOLS = 'Read Grep Glob Edit Write Bash';

const TRANSIENT_PATTERNS = [
  /rate.?limit/i,
  /\btimeout\b/i,
  /\b5\d\d\b.*(error|status)/i,
  /overloaded/i,
  /temporarily unavailable/i,
  /ECONNRESET/i,
  /ETIMEDOUT/i,
];

const PERSISTENT_PATTERNS = [
  /quota/i,
  /insufficient.?credit/i,
  /billing/i,
];

function usageAndExit(msg) {
  if (msg) console.error('错误：' + msg);
  console.error(
    '用法：node harness.mjs --arm <baseline|no-style|new> --scenario <id|all> ' +
      '--model <model-id> --runs-root <dir> [--plugin-dir <dir>] [--settings <file>] ' +
      '[--max-retries <n>]'
  );
  process.exit(msg ? 1 : 0);
}

function parseArgs(argv) {
  const args = { scenario: 'all', settings: DEFAULT_SETTINGS, maxRetries: 3 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '--arm':
        args.arm = next();
        break;
      case '--scenario':
        args.scenario = next();
        break;
      case '--model':
        args.model = next();
        break;
      case '--runs-root':
        args.runsRoot = next();
        break;
      case '--plugin-dir':
        args.pluginDir = next();
        break;
      case '--settings':
        args.settings = next();
        break;
      case '--max-retries':
        args.maxRetries = parseInt(next(), 10);
        break;
      case '--dry-run':
        args.dryRun = true;
        break;
      case '-h':
      case '--help':
        usageAndExit();
        break;
      default:
        usageAndExit('未知参数：' + a);
    }
  }
  if (!['baseline', 'no-style', 'new'].includes(args.arm)) {
    usageAndExit('--arm 必须是 baseline / no-style / new 之一');
  }
  if (!args.model) usageAndExit('--model 必填，且每次调用必须显式一致');
  if (!args.runsRoot) usageAndExit('--runs-root 必填（jobs/tmp 下的工作目录，不得是仓库根目录）');
  if (args.arm !== 'no-style' && !args.pluginDir) {
    usageAndExit(`--arm ${args.arm} 必须提供 --plugin-dir`);
  }
  if (args.arm === 'no-style' && args.pluginDir) {
    usageAndExit('--arm no-style 不接受 --plugin-dir（no-style 组不得加载任何风格插件）');
  }
  return args;
}

function resolveClaudeCli() {
  const candidates = process.platform === 'win32' ? ['claude.cmd', 'claude.exe', 'claude'] : ['claude'];
  for (const cmd of candidates) {
    const r = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
    if (!r.error && r.status === 0) return cmd;
  }
  throw new Error('未能解析 claude CLI 可执行文件，已尝试：' + candidates.join(', '));
}

function getClaudeVersion(cliPath) {
  const r = spawnSync(cliPath, ['--version'], { encoding: 'utf-8' });
  return (r.stdout || '').trim();
}

function listScenarioIds() {
  return fs
    .readdirSync(SCENARIOS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();
}

function loadScenario(id) {
  const dir = path.join(SCENARIOS_DIR, id);
  const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf-8'));
  if (meta.multiTurn) {
    meta.turns = JSON.parse(fs.readFileSync(path.join(dir, meta.turnsFile), 'utf-8'));
  } else {
    meta.prompt = fs.readFileSync(path.join(dir, meta.promptFile), 'utf-8');
  }
  return meta;
}

function copyFixture(rel, destRoot) {
  const src = path.join(FIXTURES_DIR, rel);
  const dst = path.join(destRoot, rel);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
}

function prepareRunDir(scenario, runDir) {
  fs.rmSync(runDir, { recursive: true, force: true });
  fs.mkdirSync(runDir, { recursive: true });
  for (const rel of scenario.fixtures) copyFixture(rel, runDir);
  return runDir;
}

function parseStreamJsonl(text) {
  const events = [];
  for (const raw of (text || '').split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      // 非法行跳过，不让单行解析失败拖垮整条记录；原始文本仍保留在 rawStdout 里。
    }
  }
  return events;
}

function extractInjectionProof(events) {
  const hookEvents = events.filter(
    (e) => e.type === 'system' && (e.hook_event === 'SessionStart' || e.hook_event === 'UserPromptSubmit')
  );
  const occurrences = { 'wenyan-output-style': 0, 'plain-talk-output-style': 0, 'adhd-output-style': 0 };
  for (const h of hookEvents) {
    const out = h.output;
    const text = typeof out === 'string' ? out : JSON.stringify(out ?? '');
    for (const [plugin, marker] of Object.entries(STYLE_MARKERS)) {
      if (text.includes(marker)) occurrences[plugin]++;
    }
  }
  return { hookEventCount: hookEvents.length, occurrences };
}

function extractResultEvent(events) {
  return events.find((e) => e.type === 'result') || null;
}

function extractAssistantText(events) {
  const parts = [];
  for (const e of events) {
    if (e.type === 'assistant' && e.message && Array.isArray(e.message.content)) {
      for (const block of e.message.content) {
        if (block.type === 'text' && block.text) parts.push(block.text);
      }
    }
  }
  return parts.join('\n\n');
}

function classifyFailure(spawnResult, events) {
  const resultEvent = extractResultEvent(events);
  const haystack = [
    spawnResult.stderr || '',
    resultEvent ? JSON.stringify(resultEvent) : '',
    spawnResult.status !== 0 ? String(spawnResult.status) : '',
  ].join('\n');
  if (spawnResult.status === 0 && resultEvent && resultEvent.is_error === false) {
    return { ok: true };
  }
  if (PERSISTENT_PATTERNS.some((re) => re.test(haystack))) {
    return { ok: false, transient: false, reason: 'persistent: ' + haystack.slice(0, 300) };
  }
  if (TRANSIENT_PATTERNS.some((re) => re.test(haystack)) || spawnResult.status !== 0) {
    return { ok: false, transient: true, reason: 'transient: ' + haystack.slice(0, 300) };
  }
  // 没命中已知模式但 is_error 为真：保守当作持久失败，不要无限重试一个未知错误。
  return { ok: false, transient: false, reason: 'unknown: ' + haystack.slice(0, 300) };
}

function runOnce({ cliPath, prompt, cwd, model, pluginDir, settingsPath, resumeSessionId }) {
  const args = [
    '-p',
    prompt,
    '--model',
    model,
    '--output-format',
    'stream-json',
    '--verbose',
    '--settings',
    settingsPath,
    '--allowedTools',
    ALLOWED_TOOLS,
  ];
  if (pluginDir) args.push('--plugin-dir', pluginDir);
  if (resumeSessionId) args.push('--resume', resumeSessionId);
  const spawnResult = spawnSync(cliPath, args, {
    cwd,
    encoding: 'utf-8',
    maxBuffer: 1024 * 1024 * 256,
  });
  const events = parseStreamJsonl(spawnResult.stdout);
  return { spawnResult, events };
}

function runTurnWithRetry(opts, maxRetries) {
  let retries = 0;
  for (;;) {
    const { spawnResult, events } = runOnce(opts);
    const verdict = classifyFailure(spawnResult, events);
    if (verdict.ok || !verdict.transient || retries >= maxRetries) {
      return { spawnResult, events, verdict, retries };
    }
    retries++;
  }
}

function runScenarioArm({ scenario, arm, cliPath, cliVersion, model, pluginDir, settingsPath, runsRoot, maxRetries }) {
  const runCount = scenario.runs[arm] || 0;
  const outDir = path.join(RAW_DIR, arm, scenario.id);
  fs.mkdirSync(outDir, { recursive: true });
  const summaries = [];
  for (let runIndex = 1; runIndex <= runCount; runIndex++) {
    const runDir = path.join(runsRoot, arm, scenario.id, `run-${runIndex}`);
    prepareRunDir(scenario, runDir);
    const turnsPrompts = scenario.multiTurn ? scenario.turns : [scenario.prompt];
    const record = {
      scenarioId: scenario.id,
      scenarioTitle: scenario.title,
      arm,
      runIndex,
      model,
      cliVersion,
      pluginDir: pluginDir || null,
      settingsFile: settingsPath,
      startedAt: new Date().toISOString(),
      runDir,
      turns: [],
      sessionId: null,
      failed: false,
      failureReason: null,
      totalRetries: 0,
    };
    let sessionId = null;
    for (let t = 0; t < turnsPrompts.length; t++) {
      const { spawnResult, events, verdict, retries } = runTurnWithRetry(
        {
          cliPath,
          prompt: turnsPrompts[t],
          cwd: runDir,
          model,
          pluginDir,
          settingsPath,
          resumeSessionId: sessionId,
        },
        maxRetries
      );
      record.totalRetries += retries;
      const resultEvent = extractResultEvent(events);
      const turnRecord = {
        turnIndex: t,
        prompt: turnsPrompts[t],
        exitCode: spawnResult.status,
        retries,
        injectionProof: extractInjectionProof(events),
        assistantText: extractAssistantText(events),
        resultEvent,
        stderrTail: (spawnResult.stderr || '').slice(-2000),
      };
      record.turns.push(turnRecord);
      if (resultEvent) sessionId = resultEvent.session_id;
      if (!verdict.ok) {
        record.failed = true;
        record.failureReason = verdict.reason;
        // 记录之后是否仍判定为「持久失败」——直接存布尔值，不要在写盘之后靠重新解析
        // failureReason 字符串去猜，那样等于把分类逻辑绕回一个已经加了前缀的派生字符串。
        record.persistentFailure = verdict.transient === false;
        break;
      }
    }
    record.sessionId = sessionId;
    record.finishedAt = new Date().toISOString();
    const outFile = path.join(outDir, `run-${runIndex}.json`);
    fs.writeFileSync(outFile, JSON.stringify(record, null, 2), 'utf-8');
    summaries.push({ runIndex, outFile, failed: record.failed, failureReason: record.failureReason, totalRetries: record.totalRetries });
    console.log(
      `[${arm}] ${scenario.id} run ${runIndex}/${runCount}: ${record.failed ? 'FAILED (' + record.failureReason + ')' : 'ok'}` +
        (record.totalRetries ? ` retries=${record.totalRetries}` : '')
    );
    if (record.failed) {
      if (record.persistentFailure) {
        // 持久失败：按工单要求，停在这里，不继续跑同场景剩余次数或后续场景。
        return { summaries, stoppedPersistently: true };
      }
    }
  }
  return { summaries, stoppedPersistently: false };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const cliPath = resolveClaudeCli();
  const cliVersion = getClaudeVersion(cliPath);
  const scenarioIds = args.scenario === 'all' ? listScenarioIds() : args.scenario.split(',').map((s) => s.trim());

  if (args.dryRun) {
    console.log('claude CLI:', cliPath, cliVersion);
    for (const id of scenarioIds) {
      const s = loadScenario(id);
      console.log(`- ${id} (core=${s.core}) runs[${args.arm}]=${s.runs[args.arm] || 0}`);
    }
    return;
  }

  console.log(`claude CLI: ${cliPath} (${cliVersion})`);
  console.log(`arm=${args.arm} model=${args.model} scenarios=${scenarioIds.join(',')}`);

  let stopped = false;
  const allSummaries = [];
  for (const id of scenarioIds) {
    if (stopped) break;
    const scenario = loadScenario(id);
    const { summaries, stoppedPersistently } = runScenarioArm({
      scenario,
      arm: args.arm,
      cliPath,
      cliVersion,
      model: args.model,
      pluginDir: args.pluginDir,
      settingsPath: args.settings,
      runsRoot: args.runsRoot,
      maxRetries: args.maxRetries,
    });
    allSummaries.push({ scenarioId: id, summaries });
    if (stoppedPersistently) {
      stopped = true;
      console.error(`持久失败，停在 scenario=${id}，不再继续后续场景。`);
    }
  }

  const reportPath = path.join(RAW_DIR, `run-report.${args.arm}.${Date.now()}.json`);
  fs.writeFileSync(reportPath, JSON.stringify({ arm: args.arm, model: args.model, cliVersion, stopped, allSummaries }, null, 2));
  console.log('run report:', reportPath);
  if (stopped) process.exitCode = 1;
}

main();
