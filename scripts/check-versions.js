#!/usr/bin/env node
// check-versions.js — 插件版本三方一致性检查
//
// 【为什么需要】
// 同一个插件的版本号登记在三处，改了插件却漏改市场清单是反复发生的遗漏：
//   1. plugins/<dir>/.claude-plugin/plugin.json    ← 真相源（插件自身声明）
//   2. .claude-plugin/marketplace.json             ← Claude Code 市场清单
//   3. .agents/plugins/marketplace.json            ← Codex 市场清单（install-codex.js 读它）
// 真实案例：working-discipline 连续两次 bump（1.8.0 / 1.9.0）都只改了 plugin.json，
// 两份市场清单卡在 1.7.1；omp 升到 2.3.0 后 .agents 清单仍是 2.2.0。
// 用户按市场清单安装时拿到的是过期版本号，且 description 一并陈旧。
//
// 【豁免规则】
// 远程源插件（source 非本地路径，如 {"source":"github","repo":"..."}）：
//   - 不比对 plugin.json —— 仓库里没有本地目录，天然没有 plugin.json
//   - 允许缺席 .agents/plugins/marketplace.json —— install-codex.js 只从
//     plugins/<name>/ 本地目录安装（其第 223/248/262/343 行均为
//     path.join(MARKETPLACE_ROOT, 'plugins', pluginName, ...)，完全不读 source
//     字段），所以远程源插件对 Codex 不可安装，不登记是有意设计而非遗漏
//
// 【用法】
//   node scripts/check-versions.js          # 检查，有问题 exit 1
//   node scripts/check-versions.js --fix    # 把两份市场清单的 version 对齐 plugin.json
//   node scripts/check-versions.js --quiet  # 只输出问题行，通过时不打表
//
// --fix 只改 version 字段，不动 description —— description 的内容需要人工判断该写什么，
// 机器对齐会把陈旧描述固化下来。修完仍需自行检查 description 是否同步。

'use strict'

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const PLUGINS_DIR = path.join(ROOT, 'plugins')
const CC_MARKET = path.join(ROOT, '.claude-plugin', 'marketplace.json')
const CODEX_MARKET = path.join(ROOT, '.agents', 'plugins', 'marketplace.json')

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

// source 形态判定：
//   字符串 "./plugins/xxx"            → 本地
//   {"source":"local","path":"..."}   → 本地
//   {"source":"github","repo":"..."}  → 远程
function isLocalSource(source) {
  if (typeof source === 'string') return source.startsWith('./plugins/')
  if (source && typeof source === 'object') return source.source === 'local'
  return false
}

// 扫 plugins/*/.claude-plugin/plugin.json，以 plugin.json 里声明的 name 为键
function collectLocalPlugins() {
  const out = {}
  if (!fs.existsSync(PLUGINS_DIR)) return out
  for (const entry of fs.readdirSync(PLUGINS_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const manifest = path.join(PLUGINS_DIR, entry.name, '.claude-plugin', 'plugin.json')
    if (!fs.existsSync(manifest)) continue
    let json
    try {
      json = readJson(manifest)
    } catch (e) {
      out['__parse_error__' + entry.name] = { error: `${manifest} 解析失败: ${e.message}` }
      continue
    }
    out[json.name || entry.name] = { version: json.version, dir: entry.name, manifest }
  }
  return out
}

function indexMarket(file) {
  const json = readJson(file)
  const byName = {}
  for (const p of json.plugins || []) byName[p.name] = p
  return { json, byName }
}

function main() {
  const argv = process.argv.slice(2)
  const fix = argv.includes('--fix')
  const quiet = argv.includes('--quiet')

  const local = collectLocalPlugins()
  const cc = indexMarket(CC_MARKET)
  const codex = indexMarket(CODEX_MARKET)

  const names = [...new Set([
    ...Object.keys(local),
    ...Object.keys(cc.byName),
    ...Object.keys(codex.byName),
  ])].sort()

  const problems = []
  const rows = []
  let fixedCc = 0
  let fixedCodex = 0

  for (const name of names) {
    if (name.startsWith('__parse_error__')) {
      problems.push(local[name].error)
      continue
    }

    const lp = local[name]
    const ccEntry = cc.byName[name]
    const codexEntry = codex.byName[name]

    // 远程源以 Claude Code 清单的 source 为准判定（Codex 清单可能压根没这条）
    const remote = ccEntry ? !isLocalSource(ccEntry.source) : false

    const truth = lp ? lp.version : (ccEntry ? ccEntry.version : null)
    const rowIssues = []

    if (!lp && !remote) {
      rowIssues.push(`市场清单登记了 ${name}，但 plugins/ 下没有对应的 plugin.json（幽灵条目或目录被删）`)
    }
    if (lp && !ccEntry) {
      rowIssues.push(`plugins/${lp.dir} 存在，但 .claude-plugin/marketplace.json 未登记 ${name}`)
    }
    if (!codexEntry && !remote) {
      rowIssues.push(`${name} 未登记到 .agents/plugins/marketplace.json（Codex 用户装不到）`)
    }

    if (ccEntry && truth && ccEntry.version !== truth) {
      if (fix) {
        ccEntry.version = truth
        fixedCc++
      } else {
        rowIssues.push(`.claude-plugin/marketplace.json 里是 ${ccEntry.version}，应为 ${truth}`)
      }
    }
    if (codexEntry && truth && codexEntry.version !== truth) {
      if (fix) {
        codexEntry.version = truth
        fixedCodex++
      } else {
        rowIssues.push(`.agents/plugins/marketplace.json 里是 ${codexEntry.version}，应为 ${truth}`)
      }
    }

    rows.push({
      name,
      local: lp ? lp.version : '-',
      cc: ccEntry ? ccEntry.version : '-',
      codex: codexEntry ? codexEntry.version : '-',
      remote,
      ok: rowIssues.length === 0,
    })
    for (const issue of rowIssues) problems.push(`${name}: ${issue}`)
  }

  if (fix && (fixedCc || fixedCodex)) {
    fs.writeFileSync(CC_MARKET, JSON.stringify(cc.json, null, 2) + '\n')
    fs.writeFileSync(CODEX_MARKET, JSON.stringify(codex.json, null, 2) + '\n')
    console.log(`已对齐 version：.claude-plugin/marketplace.json ${fixedCc} 处，.agents/plugins/marketplace.json ${fixedCodex} 处`)
    console.log('注意：--fix 不改 description，请自行确认市场清单里的描述是否也需同步更新')
  }

  if (!quiet) {
    console.log('plugin.json   | cc-market | codex-market | plugin')
    console.log('--------------|-----------|--------------|-------')
    for (const r of rows) {
      const flag = r.ok ? '  ' : '✗ '
      const tag = r.remote ? ' (远程源)' : ''
      console.log(
        flag + String(r.local).padEnd(12) + ' | ' +
        String(r.cc).padEnd(9) + ' | ' +
        String(r.codex).padEnd(12) + ' | ' +
        r.name + tag
      )
    }
    console.log('')
  }

  if (problems.length) {
    console.error(`发现 ${problems.length} 处版本登记问题：`)
    for (const p of problems) console.error('  - ' + p)
    console.error('\n修法：改 plugin.json 后同步两份市场清单的 version 与 description，或先跑 node scripts/check-versions.js --fix 对齐 version')
    process.exit(1)
  }

  console.log(`✓ ${rows.length} 个插件的版本登记三方一致`)
  process.exit(0)
}

main()
