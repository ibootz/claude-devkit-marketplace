#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const readline = require('readline');

// ─── Constants ───────────────────────────────────────────────────────────────
const MARKETPLACE_ROOT = path.resolve(__dirname, '..');
const MARKETPLACE_JSON = path.join(MARKETPLACE_ROOT, '.agents', 'plugins', 'marketplace.json');
const IS_WINDOWS = process.platform === 'win32';

// ─── CLI Parsing ─────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const args = { scope: 'project', plugins: null, all: false, dryRun: false };
  for (const arg of argv.slice(2)) {
    if (arg === '--all') { args.all = true; }
    else if (arg === '--dry-run') { args.dryRun = true; }
    else if (arg.startsWith('--scope=')) { args.scope = arg.slice('--scope='.length); }
    else if (arg.startsWith('--plugins=')) { args.plugins = arg.slice('--plugins='.length).split(',').map(s => s.trim()).filter(Boolean); }
    else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
  }
  if (args.scope !== 'project' && args.scope !== 'user') {
    error(`Invalid scope "${args.scope}". Use --scope=project or --scope=user`);
  }
  return args;
}

function printUsage() {
  console.log(`Usage: node scripts/install-codex.js [options]

Options:
  --scope=project|user   Install target scope (default: project)
  --plugins=a,b,c        Comma-separated plugin names
  --all                   Install all plugins (skip interactive)
  --dry-run               Show what would be done without doing it
  -h, --help              Show this help
`);
}

// ─── Utility ─────────────────────────────────────────────────────────────────
function error(msg) {
  console.error(`\x1b[31mError: ${msg}\x1b[0m`);
  process.exit(1);
}

function log(msg) { console.log(msg); }

function logDry(msg) { console.log(`\x1b[36m[DRY RUN]\x1b[0m ${msg}`); }

/** Ensure directory exists (sync). */
function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/** Copy directory recursively. Returns true if actually copied, false if skipped. */
function copyDirRecursive(src, dest, dryRun) {
  if (!fs.existsSync(src)) return false;
  const srcStat = fs.statSync(src);
  if (!srcStat.isDirectory()) return false;

  // Check if target exists and is identical
  if (fs.existsSync(dest)) {
    if (dirEquals(src, dest)) {
      return false; // skipped — identical
    }
  }

  if (dryRun) return true;

  function copyRecursive(s, d) {
    ensureDir(d);
    for (const entry of fs.readdirSync(s, { withFileTypes: true })) {
      const srcPath = path.join(s, entry.name);
      const destPath = path.join(d, entry.name);
      if (entry.isDirectory()) {
        copyRecursive(srcPath, destPath);
      } else {
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }

  copyRecursive(src, dest);
  return true;
}

/** Check if two directories have identical contents (recursive). */
function dirEquals(a, b) {
  if (!fs.existsSync(b)) return false;
  const statB = fs.statSync(b);
  if (!statB.isDirectory()) return false;

  const entriesA = fs.readdirSync(a).sort();
  const entriesB = fs.readdirSync(b).sort();
  if (entriesA.length !== entriesB.length) return false;
  if (!entriesA.every((e, i) => e === entriesB[i])) return false;

  for (const name of entriesA) {
    const pA = path.join(a, name);
    const pB = path.join(b, name);
    const stA = fs.statSync(pA);
    const stB = fs.statSync(pB);
    if (stA.isDirectory() !== stB.isDirectory()) return false;
    if (stA.isDirectory()) {
      if (!dirEquals(pA, pB)) return false;
    } else {
      if (!fileEquals(pA, pB)) return false;
    }
  }
  return true;
}

/** Check if two files have identical content. */
function fileEquals(a, b) {
  if (!fs.existsSync(b)) return false;
  const sA = fs.statSync(a);
  const sB = fs.statSync(b);
  if (sA.size !== sB.size) return false;
  const bufA = fs.readFileSync(a);
  const bufB = fs.readFileSync(b);
  return bufA.equals(bufB);
}

/** Copy a single file. Returns true if copied, false if skipped (identical). */
function copyFile(src, dest, dryRun) {
  if (!fs.existsSync(src)) return false;
  if (fs.existsSync(dest) && fileEquals(src, dest)) return false;
  if (dryRun) return true;
  ensureDir(path.dirname(dest));
  fs.copyFileSync(src, dest);
  return true;
}

// ─── Target Paths ────────────────────────────────────────────────────────────
function getTargetPaths(scope) {
  if (scope === 'user') {
    const home = os.homedir();
    return {
      skillsDir: path.join(home, '.agents', 'skills'),
      hooksJson: path.join(home, '.codex', 'hooks.json'),
      agentsDir: path.join(home, '.codex', 'agents'),
    };
  }
  // project scope — use CWD
  const cwd = process.cwd();
  return {
    skillsDir: path.join(cwd, '.agents', 'skills'),
    hooksJson: path.join(cwd, '.codex', 'hooks.json'),
    agentsDir: path.join(cwd, '.codex', 'agents'),
  };
}

// ─── Load Marketplace ────────────────────────────────────────────────────────
function loadMarketplace() {
  if (!fs.existsSync(MARKETPLACE_JSON)) {
    error(`Marketplace file not found: ${MARKETPLACE_JSON}\nRun this script from the marketplace root directory.`);
  }
  try {
    return JSON.parse(fs.readFileSync(MARKETPLACE_JSON, 'utf-8'));
  } catch (e) {
    error(`Failed to parse marketplace.json: ${e.message}`);
  }
}

// ─── Interactive Plugin Selection ─────────────────────────────────────────────
async function interactiveSelect(plugins) {
  const selected = new Set(plugins.map((_, i) => i)); // all selected by default

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  // Detect if we have a real TTY — if not, skip interactive
  if (!process.stdin.isTTY) {
    rl.close();
    return plugins.map((_, i) => i);
  }

  function render() {
    console.log('');
    console.log('Select plugins to install (enter number to toggle, enter to confirm):');
    for (let i = 0; i < plugins.length; i++) {
      const mark = selected.has(i) ? '\x1b[32m[x]\x1b[0m' : '[ ]';
      const p = plugins[i];
      console.log(`  ${mark} ${i + 1}. \x1b[1m${p.name}\x1b[0m - ${p.description}`);
    }
    console.log('');
    console.log('  Press enter to install selected, or type numbers (e.g. "1 3 5" to toggle).');
  }

  return new Promise((resolve) => {
    render();
    rl.on('line', (input) => {
      const trimmed = input.trim();
      if (trimmed === '') {
        rl.close();
        const result = [...selected].sort((a, b) => a - b);
        resolve(result);
        return;
      }
      // Parse numbers
      const nums = trimmed.split(/[\s,]+/).map(s => parseInt(s, 10)).filter(n => !isNaN(n));
      for (const n of nums) {
        const idx = n - 1;
        if (idx >= 0 && idx < plugins.length) {
          if (selected.has(idx)) selected.delete(idx);
          else selected.add(idx);
        }
      }
      // Clear and re-render
      process.stdout.write('\x1Bc');
      render();
    });
  });
}

// ─── Install Skills ──────────────────────────────────────────────────────────
function installSkills(pluginName, targetSkillsDir, dryRun) {
  const srcDir = path.join(MARKETPLACE_ROOT, 'plugins', pluginName, 'skills');
  if (!fs.existsSync(srcDir)) return { installed: [], skipped: false };

  const skillDirs = fs.readdirSync(srcDir, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => d.name);

  if (skillDirs.length === 0) return { installed: [], skipped: false };

  const installed = [];
  for (const skillName of skillDirs) {
    const src = path.join(srcDir, skillName);
    const dest = path.join(targetSkillsDir, skillName);
    const didCopy = copyDirRecursive(src, dest, dryRun);
    if (didCopy) {
      installed.push(skillName);
    }
  }

  // For summary: even if identical (skipped), we still list them as "present"
  return { installed: skillDirs, skipped: skillDirs.length === 0 };
}

// ─── Install Hooks ───────────────────────────────────────────────────────────
function installHooks(pluginName, targetHooksJson, dryRun) {
  const pluginJsonPath = path.join(MARKETPLACE_ROOT, 'plugins', pluginName, '.claude-plugin', 'plugin.json');
  if (!fs.existsSync(pluginJsonPath)) return { installed: [], skipped: true };

  let pluginJson;
  try {
    pluginJson = JSON.parse(fs.readFileSync(pluginJsonPath, 'utf-8'));
  } catch (e) {
    return { installed: [], skipped: true, error: e.message };
  }

  if (!pluginJson.hooks || Object.keys(pluginJson.hooks).length === 0) {
    return { installed: [], skipped: true };
  }

  const pluginDir = path.join(MARKETPLACE_ROOT, 'plugins', pluginName);
  const installed = [];
  const newEntries = {}; // eventType -> [{ matcher, hooks: [...] }]

  for (const [eventType, entries] of Object.entries(pluginJson.hooks)) {
    for (const entry of entries) {
      const matcher = entry.matcher;
      const resolvedHooks = [];
      for (const h of entry.hooks) {
        if (h.type !== 'command') continue;
        const cmd = h.command.replace('${CLAUDE_PLUGIN_ROOT}', pluginDir).replace(/\\/g, '/');
        resolvedHooks.push({
          type: 'command',
          command: cmd,
          timeout: h.timeout || 30,
        });
        // Extract script filename for summary
        const scriptMatch = cmd.match(/([^/\s\\]+\.js)/);
        installed.push({ eventType, matcher, script: scriptMatch ? scriptMatch[1] : cmd });
      }
      if (resolvedHooks.length > 0) {
        if (!newEntries[eventType]) newEntries[eventType] = [];
        newEntries[eventType].push({ matcher, hooks: resolvedHooks });
      }
    }
  }

  if (Object.keys(newEntries).length === 0) {
    return { installed: [], skipped: true };
  }

  // Merge into hooks.json
  let existing = {};
  if (fs.existsSync(targetHooksJson)) {
    try {
      existing = JSON.parse(fs.readFileSync(targetHooksJson, 'utf-8'));
    } catch (e) {
      existing = {};
    }
  }
  if (!existing.hooks) existing.hooks = {};

  let merged = false;
  for (const [eventType, entries] of Object.entries(newEntries)) {
    if (!existing.hooks[eventType]) existing.hooks[eventType] = [];
    for (const entry of entries) {
      // Check for duplicates
      const existingForType = existing.hooks[eventType];
      let found = false;
      for (const existingEntry of existingForType) {
        if (existingEntry.matcher !== entry.matcher) continue;
        if (!existingEntry.hooks) continue;
        for (const existingHook of existingEntry.hooks) {
          if (existingHook.command === entry.hooks[0].command) {
            found = true;
            break;
          }
        }
        if (found) break;
      }
      if (!found) {
        existing.hooks[eventType].push(entry);
        merged = true;
      }
    }
  }

  if (merged && !dryRun) {
    ensureDir(path.dirname(targetHooksJson));
    fs.writeFileSync(targetHooksJson, JSON.stringify(existing, null, 2) + '\n', 'utf-8');
  }

  if (dryRun && merged) {
    logDry(`Would merge hooks into ${targetHooksJson}`);
  }

  return { installed, skipped: false, merged };
}

// ─── Install Agents ──────────────────────────────────────────────────────────
function installAgents(pluginName, targetAgentsDir, dryRun) {
  const agentsSrcDir = path.join(MARKETPLACE_ROOT, 'plugins', pluginName, '.codex', 'agents');
  if (!fs.existsSync(agentsSrcDir)) return { installed: [], skipped: true };

  const tomlFiles = fs.readdirSync(agentsSrcDir)
    .filter(f => f.endsWith('.toml'));

  if (tomlFiles.length === 0) return { installed: [], skipped: true };

  const installed = [];
  for (const f of tomlFiles) {
    const src = path.join(agentsSrcDir, f);
    const dest = path.join(targetAgentsDir, f);
    const didCopy = copyFile(src, dest, dryRun);
    installed.push(f.replace('.toml', ''));
  }

  return { installed, skipped: false };
}

// ─── Manifest ────────────────────────────────────────────────────────────────
function getManifestPath(scope) {
  if (scope === 'user') {
    return path.join(os.homedir(), '.codex-marketplace-manifest.json');
  }
  return path.join(process.cwd(), '.codex-marketplace-manifest.json');
}

function readManifest(manifestPath) {
  try {
    return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
  } catch {
    return { version: 1, plugins: {} };
  }
}

function writeManifest(manifestPath, manifest, dryRun) {
  if (dryRun) {
    logDry(`Would write manifest to ${manifestPath}`);
    return;
  }
  ensureDir(path.dirname(manifestPath));
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n', 'utf-8');
}

// ─── Main ────────────────────────────────────────────────────────────────────
async function main() {
  const args = parseArgs(process.argv);
  const marketplace = loadMarketplace();
  const plugins = marketplace.plugins;
  const targets = getTargetPaths(args.scope);

  // Plugin selection
  let selectedIndices;
  if (args.all) {
    selectedIndices = plugins.map((_, i) => i);
  } else if (args.plugins) {
    selectedIndices = [];
    for (const name of args.plugins) {
      const idx = plugins.findIndex(p => p.name === name);
      if (idx === -1) {
        error(`Plugin "${name}" not found in marketplace. Available: ${plugins.map(p => p.name).join(', ')}`);
      }
      selectedIndices.push(idx);
    }
  } else {
    selectedIndices = await interactiveSelect(plugins);
    if (selectedIndices.length === 0) {
      log('No plugins selected. Exiting.');
      process.exit(0);
    }
  }

  const selectedPlugins = selectedIndices.map(i => plugins[i]);

  // Ensure target directories exist (unless dry run)
  if (!args.dryRun) {
    ensureDir(targets.skillsDir);
    ensureDir(targets.agentsDir);
    ensureDir(path.dirname(targets.hooksJson));
  }

  // Install each plugin
  const summary = {
    skills: {},
    hooks: {},
    agents: {},
    skillsOnly: [],
  };

  for (const plugin of selectedPlugins) {
    const skillResult = installSkills(plugin.name, targets.skillsDir, args.dryRun);
    const hookResult = installHooks(plugin.name, targets.hooksJson, args.dryRun);
    const agentResult = installAgents(plugin.name, targets.agentsDir, args.dryRun);

    if (skillResult.installed.length > 0) {
      summary.skills[plugin.name] = skillResult.installed;
    }
    if (hookResult.installed && hookResult.installed.length > 0) {
      summary.hooks[plugin.name] = hookResult.installed;
    }
    if (agentResult.installed && agentResult.installed.length > 0) {
      summary.agents[plugin.name] = agentResult.installed;
    }

    const hasHooks = hookResult.installed && hookResult.installed.length > 0;
    const hasAgents = agentResult.installed && agentResult.installed.length > 0;
    if (!hasHooks && !hasAgents && skillResult.installed.length > 0) {
      summary.skillsOnly.push(plugin.name);
    }
  }

  // Write manifest for uninstall support
  const manifestPath = getManifestPath(args.scope);
  const manifest = readManifest(manifestPath);

  for (const plugin of selectedPlugins) {
    const skillNames = summary.skills[plugin.name] || [];
    const hookEntries = summary.hooks[plugin.name] || [];
    const agentNames = summary.agents[plugin.name] || [];

    manifest.plugins[plugin.name] = {
      skills: skillNames,
      hooks: hookEntries.map(h => `${h.eventType}/${h.matcher}/${h.script}`),
      hookCommands: hookEntries.map(h => h.command),
      agents: agentNames.map(a => `${a}.toml`),
    };
  }

  writeManifest(manifestPath, manifest, args.dryRun);

  // Print summary
  printSummary(summary, args, targets);
}

function printSummary(summary, args, targets) {
  const scopeLabel = args.scope === 'user'
    ? `user-level (${path.dirname(targets.hooksJson)})`
    : `project-level (${path.dirname(targets.hooksJson)})`;

  log('');
  log('\x1b[1m═══ Codex CLI Plugin Installation Summary ═══\x1b[0m');
  log(`Scope: ${scopeLabel}`);
  if (args.dryRun) log('\x1b[36mMode: DRY RUN (no changes made)\x1b[0m');
  log('');

  // Skills
  const skillNames = Object.keys(summary.skills);
  if (skillNames.length > 0) {
    log('  \x1b[1mSkills:\x1b[0m');
    for (const [name, skills] of Object.entries(summary.skills)) {
      log(`    \x1b[32m✓\x1b[0m ${name}: ${skills.join(', ')}`);
    }
  }

  // Hooks
  const hookNames = Object.keys(summary.hooks);
  if (hookNames.length > 0) {
    log('  \x1b[1mHooks:\x1b[0m');
    for (const [name, hooks] of Object.entries(summary.hooks)) {
      const hookLabels = hooks.map(h => `${h.eventType}/${h.matcher} (${h.script})`);
      log(`    \x1b[32m✓\x1b[0m ${name}: ${hookLabels.join(', ')}`);
    }
  }

  // Agents
  const agentNames = Object.keys(summary.agents);
  if (agentNames.length > 0) {
    log('  \x1b[1mAgents:\x1b[0m');
    for (const [name, agents] of Object.entries(summary.agents)) {
      log(`    \x1b[32m✓\x1b[0m ${name}: ${agents.join(', ')}`);
    }
  }

  // Skipped (skills only)
  if (summary.skillsOnly.length > 0) {
    log('');
    log('  \x1b[32mInstalled (skills only):\x1b[0m');
    for (const name of summary.skillsOnly) {
      log(`    - ${name}`);
    }
  }

  log('');
  log('\x1b[33mPlease restart Codex CLI for changes to take effect.\x1b[0m');
}

// ─── Run ─────────────────────────────────────────────────────────────────────
main().catch(e => {
  error(`Unexpected error: ${e.message}\n${e.stack}`);
});
