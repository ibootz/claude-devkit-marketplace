#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// ---------------------------------------------------------------------------
// CLI parsing
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const flags = { scope: 'project', plugins: null, all: false, dryRun: false };
  for (const arg of argv) {
    if (arg.startsWith('--scope=')) {
      const val = arg.split('=')[1];
      if (val !== 'project' && val !== 'user') {
        console.error(`Error: --scope must be "project" or "user", got "${val}"`);
        process.exit(1);
      }
      flags.scope = val;
    } else if (arg.startsWith('--plugins=')) {
      flags.plugins = arg.split('=')[1].split(',').map(s => s.trim()).filter(Boolean);
    } else if (arg === '--all') {
      flags.all = true;
    } else if (arg === '--dry-run') {
      flags.dryRun = true;
    } else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
  }
  return flags;
}

function printUsage() {
  console.log(`
Usage: node scripts/uninstall-codex.js [options]

Options:
  --scope=project|user   Uninstall scope (default: project)
  --plugins=a,b,c        Comma-separated plugin names to uninstall
  --all                   Uninstall all installed plugins (skip interactive)
  --dry-run               Show what would be removed without making changes
  -h, --help              Show this help message
`.trim());
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------
function getMarketplaceRoot() {
  // scripts/uninstall-codex.js -> scripts/.. = marketplace root
  return path.resolve(__dirname, '..');
}

function getManifestPath(scope) {
  if (scope === 'user') {
    return path.join(os.homedir(), '.codex-marketplace-manifest.json');
  }
  return path.join(process.cwd(), '.codex-marketplace-manifest.json');
}

function getHooksJsonPath(scope) {
  if (scope === 'user') {
    return path.join(os.homedir(), '.codex', 'hooks.json');
  }
  return path.join(process.cwd(), '.codex', 'hooks.json');
}

function getSkillsDir(scope) {
  if (scope === 'user') {
    return path.join(os.homedir(), '.agents', 'skills');
  }
  return path.join(process.cwd(), '.agents', 'skills');
}

function getAgentsDir(scope) {
  if (scope === 'user') {
    return path.join(os.homedir(), '.codex', 'agents');
  }
  return path.join(process.cwd(), '.codex', 'agents');
}

// ---------------------------------------------------------------------------
// JSON read/write helpers
// ---------------------------------------------------------------------------
function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    return null;
  }
}

function writeJson(filePath, data) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
}

// ---------------------------------------------------------------------------
// Interactive plugin selection
// ---------------------------------------------------------------------------
function prompt(question) {
  const readline = require('readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => rl.question(question, answer => {
    rl.close();
    resolve(answer.trim());
  }));
}

async function selectPlugins(installedPlugins) {
  if (installedPlugins.length === 0) {
    console.log('No plugins are currently installed.');
    return [];
  }

  console.log('\nInstalled plugins:');
  installedPlugins.forEach((name, i) => {
    console.log(`  ${i + 1}. ${name}`);
  });
  console.log(`  a. All`);

  const answer = await prompt('\nSelect plugins to uninstall (comma-separated numbers, "a" for all): ');

  if (answer.toLowerCase() === 'a') {
    return [...installedPlugins];
  }

  const indices = answer.split(',').map(s => {
    const n = parseInt(s.trim(), 10);
    return isNaN(n) ? -1 : n - 1;
  }).filter(i => i >= 0 && i < installedPlugins.length);

  // Deduplicate
  return [...new Set(indices)].map(i => installedPlugins[i]);
}

// ---------------------------------------------------------------------------
// Uninstall logic
// ---------------------------------------------------------------------------

/**
 * Remove empty parent directories up to stopAt (exclusive).
 * E.g. removeEmptyParents('/a/.agents/skills', '/a') will try to remove
 * '/a/.agents' and '/a/.agents/skills' if empty.
 */
function removeEmptyParents(dirPath, stopAt) {
  let current = path.resolve(dirPath);
  const stop = path.resolve(stopAt);
  while (current !== stop && current.length > stop.length) {
    if (!fs.existsSync(current)) {
      current = path.dirname(current);
      continue;
    }
    try {
      if (fs.readdirSync(current).length === 0) {
        fs.rmSync(current, { recursive: true, force: true });
      } else {
        break; // not empty, stop ascending
      }
    } catch {
      break;
    }
    current = path.dirname(current);
  }
}

/**
 * Remove skill directories listed in the manifest.
 * @param {string[]} skillNames - Skill directory names to remove
 * @param {string} skillsDir - Target skills directory
 * @param {boolean} dryRun
 * @returns {{removed: string[], skipped: string[]}}
 */
function removeSkills(skillNames, skillsDir, dryRun, scopeBase) {
  const result = { removed: [], skipped: [] };
  for (const name of skillNames) {
    const skillPath = path.join(skillsDir, name);
    if (!fs.existsSync(skillPath)) {
      result.skipped.push(name);
      continue;
    }
    if (dryRun) {
      result.removed.push(name);
    } else {
      try {
        fs.rmSync(skillPath, { recursive: true, force: true });
        result.removed.push(name);
      } catch (err) {
        console.warn(`  Warning: Failed to remove skill "${name}": ${err.message}`);
        result.skipped.push(name);
      }
    }
  }
  // Clean up empty skills directory and parents
  if (!dryRun && scopeBase) {
    removeEmptyParents(skillsDir, scopeBase);
  }
  return result;
}

/**
 * Remove hook entries from hooks.json that match manifest entries.
 * Matches by full command path from manifest hookCommands for robustness.
 *
 * @param {string[]} manifestHooks - Hook identifiers from manifest (event/matcher/script)
 * @param {string} hooksJsonPath - Path to hooks.json
 * @param {string[]} hookCommands - Full command paths from manifest hookCommands
 * @param {boolean} dryRun
 * @returns {{removed: string[], skipped: string[]}}
 */
function removeHooks(manifestHooks, hooksJsonPath, hookCommands, dryRun) {
  const result = { removed: [], skipped: [] };

  if (!fs.existsSync(hooksJsonPath)) {
    // Already gone — all hooks count as skipped (already removed)
    manifestHooks.forEach(h => result.skipped.push(h));
    return result;
  }

  const hooksData = readJson(hooksJsonPath);
  if (!hooksData || !hooksData.hooks) {
    manifestHooks.forEach(h => result.skipped.push(h));
    return result;
  }

  // Build a lookup from manifest hook commands for full-path matching
  // hookCommands: full command strings like "node C:/path/to/script.js"
  const hookCommandSet = new Set();
  if (Array.isArray(hookCommands)) {
    hookCommands.forEach(c => hookCommandSet.add(c));
  }

  for (const [event, matchers] of Object.entries(hooksData.hooks)) {
    if (!Array.isArray(matchers)) continue;

    for (let mi = matchers.length - 1; mi >= 0; mi--) {
      const matcherEntry = matchers[mi];
      const matcherName = matcherEntry.matcher;
      if (!Array.isArray(matcherEntry.hooks)) continue;

      for (let hi = matcherEntry.hooks.length - 1; hi >= 0; hi--) {
        const hookEntry = matcherEntry.hooks[hi];
        const command = (hookEntry.command || '').replace(/\\/g, '/');
        // Match by full command path from manifest
        if (hookCommandSet.has(command)) {
          if (dryRun) {
            result.removed.push(`${event}/${matcherName}/${path.basename(command)}`);
          } else {
            matcherEntry.hooks.splice(hi, 1);
            result.removed.push(`${event}/${matcherName}/${path.basename(command)}`);
          }
        }
      }

      // Remove empty matcher entries
      if (!dryRun && matcherEntry.hooks && matcherEntry.hooks.length === 0) {
        matchers.splice(mi, 1);
      }
    }

    // Remove empty event entries
    if (!dryRun && Array.isArray(matchers) && matchers.length === 0) {
      delete hooksData.hooks[event];
    }
  }

  // Write back or remove hooks.json
  if (!dryRun) {
    if (Object.keys(hooksData.hooks).length === 0) {
      try {
        fs.unlinkSync(hooksJsonPath);
      } catch { /* ignore */ }
      // Try to remove .codex dir if empty
      const codexDir = path.dirname(hooksJsonPath);
      try {
        if (fs.readdirSync(codexDir).length === 0) {
          fs.rmSync(codexDir, { recursive: true, force: true });
        }
      } catch { /* ignore */ }
    } else {
      writeJson(hooksJsonPath, hooksData);
    }
  }

  // Anything in hookCommands not matched counts as skipped
  for (const cmd of hookCommandSet) {
    const found = result.removed.some(r => cmd.endsWith(r.split('/').pop()));
    if (!found) {
      result.skipped.push(cmd);
    }
  }

  return result;

}

/**
 * Remove agent .toml files listed in the manifest.
 * @param {string[]} agentFiles - TOML basenames to remove
 * @param {string} agentsDir - Target agents directory
 * @param {boolean} dryRun
 * @returns {{removed: string[], skipped: string[]}}
 */
function removeAgents(agentFiles, agentsDir, dryRun, scopeBase) {
  const result = { removed: [], skipped: [] };
  for (const name of agentFiles) {
    const agentPath = path.join(agentsDir, name);
    if (!fs.existsSync(agentPath)) {
      result.skipped.push(name);
      continue;
    }
    if (dryRun) {
      result.removed.push(name);
    } else {
      try {
        fs.unlinkSync(agentPath);
        result.removed.push(name);
      } catch (err) {
        console.warn(`  Warning: Failed to remove agent "${name}": ${err.message}`);
        result.skipped.push(name);
      }
    }
  }
  // Clean up empty agents directory and parents
  if (!dryRun && scopeBase) {
    removeEmptyParents(agentsDir, scopeBase);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  const flags = parseArgs(process.argv.slice(2));
  const manifestPath = getManifestPath(flags.scope);
  const hooksJsonPath = getHooksJsonPath(flags.scope);
  const skillsDir = getSkillsDir(flags.scope);
  const agentsDir = getAgentsDir(flags.scope);
  const scopeBase = flags.scope === "user" ? os.homedir() : process.cwd();

  if (flags.dryRun) {
    console.log('=== DRY RUN — no changes will be made ===\n');
  }

  // Read manifest
  const manifest = readJson(manifestPath);
  if (!manifest || !manifest.plugins) {
    console.log(`No manifest found at ${manifestPath}.`);
    console.log('Nothing to uninstall.');
    process.exit(0);
  }

  const installedPlugins = Object.keys(manifest.plugins);
  if (installedPlugins.length === 0) {
    console.log('Manifest contains no installed plugins.');
    process.exit(0);
  }

  // Determine which plugins to uninstall
  let selectedPlugins;
  if (flags.plugins) {
    // Filter to only plugins that exist in manifest
    selectedPlugins = flags.plugins.filter(p => {
      if (!manifest.plugins[p]) {
        console.warn(`Warning: Plugin "${p}" not found in manifest. Skipping.`);
        return false;
      }
      return true;
    });
  } else if (flags.all) {
    selectedPlugins = [...installedPlugins];
  } else {
    selectedPlugins = await selectPlugins(installedPlugins);
  }

  if (selectedPlugins.length === 0) {
    console.log('No plugins selected for uninstall.');
    process.exit(0);
  }

  console.log(`\nUninstalling from scope: ${flags.scope}`);
  console.log(`Plugins: ${selectedPlugins.join(', ')}\n`);

  const summary = {};

  for (const pluginName of selectedPlugins) {
    const pluginEntry = manifest.plugins[pluginName];
    if (!pluginEntry) continue;

    console.log(`[${pluginName}]`);

    const pluginSummary = { skills: { removed: 0, skipped: 0 }, hooks: { removed: 0, skipped: 0 }, agents: { removed: 0, skipped: 0 } };

    // Remove skills
    if (pluginEntry.skills && pluginEntry.skills.length > 0) {
      const r = removeSkills(pluginEntry.skills, skillsDir, flags.dryRun, scopeBase);
      pluginSummary.skills.removed = r.removed.length;
      pluginSummary.skills.skipped = r.skipped.length;
      if (r.removed.length > 0) {
        console.log(`  Skills removed: ${r.removed.join(', ')}`);
      }
      if (r.skipped.length > 0) {
        console.log(`  Skills skipped (not found): ${r.skipped.join(', ')}`);
      }
    }

    // Remove hooks
    if (pluginEntry.hooks && pluginEntry.hooks.length > 0) {
      const r = removeHooks(pluginEntry.hooks, hooksJsonPath, pluginEntry.hookCommands || [], flags.dryRun);
      pluginSummary.hooks.removed = r.removed.length;
      pluginSummary.hooks.skipped = r.skipped.length;
      if (r.removed.length > 0) {
        console.log(`  Hooks removed: ${r.removed.join(', ')}`);
      }
      if (r.skipped.length > 0) {
        console.log(`  Hooks skipped (not found): ${r.skipped.join(', ')}`);
      }
    }

    // Remove agents
    if (pluginEntry.agents && pluginEntry.agents.length > 0) {
      const r = removeAgents(pluginEntry.agents, agentsDir, flags.dryRun, scopeBase);
      pluginSummary.agents.removed = r.removed.length;
      pluginSummary.agents.skipped = r.skipped.length;
      if (r.removed.length > 0) {
        console.log(`  Agents removed: ${r.removed.join(', ')}`);
      }
      if (r.skipped.length > 0) {
        console.log(`  Agents skipped (not found): ${r.skipped.join(', ')}`);
      }
    }

    summary[pluginName] = pluginSummary;
    console.log();

    // Remove plugin from manifest
    if (!flags.dryRun) {
      delete manifest.plugins[pluginName];
    }
  }

  // Update or remove manifest file
  if (!flags.dryRun) {
    if (Object.keys(manifest.plugins).length === 0) {
      try {
        fs.unlinkSync(manifestPath);
      } catch { /* ignore */ }
    } else {
      writeJson(manifestPath, manifest);
    }
  }

  // Print summary
  console.log('=== Uninstall Summary ===');
  let totalRemoved = 0;
  let totalSkipped = 0;
  for (const [name, s] of Object.entries(summary)) {
    const removed = s.skills.removed + s.hooks.removed + s.agents.removed;
    const skipped = s.skills.skipped + s.hooks.skipped + s.agents.skipped;
    totalRemoved += removed;
    totalSkipped += skipped;
    console.log(`  ${name}: ${removed} removed, ${skipped} skipped`);
  }
  console.log(`\nTotal: ${totalRemoved} items removed, ${totalSkipped} items skipped`);

  if (flags.dryRun) {
    console.log('\n(Dry run — no changes were made)');
  }
}

main().catch(err => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
