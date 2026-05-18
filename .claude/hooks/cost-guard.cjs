#!/usr/bin/env node
/**
 * cost-guard.cjs — Hard cap on LLM spend in autonomous mode.
 *
 * Trigger: PreToolUse on Bash commands that may invoke an LLM (curl to
 * OpenAI/Anthropic/Azure endpoints) and on Task tool spawns.
 *
 * Reads a running cost ledger at .claude/.cost-ledger.jsonl. If the
 * cumulative USD spend exceeds COST_CAP_USD (default 90, leaving 10%
 * headroom under a $100 budget), the hook returns exit code 2 and
 * writes a HALT marker so the autonomous loop stops cleanly.
 *
 * The ledger is append-only. Each line is a JSON object:
 *   { ts, provider, model, input_tokens, output_tokens, cost_usd, source }
 *
 * Application code in app/extractors/llm_judge.py is responsible for
 * appending to the ledger after every LLM call. This hook only reads.
 *
 * Fail-open: any error in this hook results in exit 0 (allow), so a
 * broken hook never silently denies operations.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const COST_CAP_USD = parseFloat(process.env.CK_LLM_COST_CAP_USD || '90');
const LEDGER_PATH = path.join(process.cwd(), '.claude', '.cost-ledger.jsonl');
const HALT_MARKER = path.join(process.cwd(), '.claude', '.HALT-COST');
const REPORT_DIR = path.join(process.cwd(), 'plans', 'reports');

function readLedgerTotal() {
  if (!fs.existsSync(LEDGER_PATH)) return 0;
  try {
    const raw = fs.readFileSync(LEDGER_PATH, 'utf-8');
    let total = 0;
    for (const line of raw.split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (typeof entry.cost_usd === 'number') total += entry.cost_usd;
      } catch (_) {
        // skip malformed lines
      }
    }
    return total;
  } catch (_) {
    return 0;
  }
}

function writeHaltMarker(total) {
  try {
    fs.mkdirSync(path.dirname(HALT_MARKER), { recursive: true });
    fs.writeFileSync(
      HALT_MARKER,
      `Cost cap hit: $${total.toFixed(2)} >= $${COST_CAP_USD.toFixed(2)} at ${new Date().toISOString()}\n`,
      'utf-8'
    );
    fs.mkdirSync(REPORT_DIR, { recursive: true });
    const reportPath = path.join(
      REPORT_DIR,
      `COST-CAP-HIT-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`
    );
    fs.writeFileSync(
      reportPath,
      [
        '# Cost Cap Hit — Autonomous Run Halted',
        '',
        `**Time:** ${new Date().toISOString()}`,
        `**Cap:** $${COST_CAP_USD.toFixed(2)}`,
        `**Total spent:** $${total.toFixed(2)}`,
        `**Ledger:** \`${LEDGER_PATH}\``,
        '',
        '## What to do',
        '1. Review `.claude/.cost-ledger.jsonl` to see which calls drove the cost.',
        '2. Investigate prompts in `app/extractors/prompts/` for caching gaps.',
        '3. To resume: delete `.claude/.HALT-COST`, optionally raise `CK_LLM_COST_CAP_USD`.',
        '4. Consider switching to local Ollama for non-critical paths.',
        '',
      ].join('\n'),
      'utf-8'
    );
  } catch (_) {
    // best-effort
  }
}

function isLLMCall(input) {
  const cmd = (input.tool_input && (input.tool_input.command || input.tool_input.prompt || '')) || '';
  if (typeof cmd !== 'string') return false;
  return /api\.openai\.com|api\.anthropic\.com|openai\.azure\.com|generativelanguage\.googleapis\.com/i.test(cmd);
}

(async () => {
  try {
    // Honor existing halt marker — block everything LLM-ish until cleared.
    if (fs.existsSync(HALT_MARKER)) {
      let raw = '';
      try {
        let chunks = [];
        process.stdin.on('data', (c) => chunks.push(c));
        await new Promise((r) => process.stdin.on('end', r));
        raw = Buffer.concat(chunks).toString('utf-8');
      } catch (_) {}
      let input = {};
      try {
        input = JSON.parse(raw || '{}');
      } catch (_) {}
      if (input.tool_name === 'Bash' && isLLMCall(input)) {
        process.stderr.write('HALT-COST marker present at .claude/.HALT-COST. LLM calls are blocked.\n');
        process.exit(2);
      }
      // For non-LLM Bash, allow.
      process.exit(0);
    }

    const total = readLedgerTotal();
    if (total >= COST_CAP_USD) {
      writeHaltMarker(total);
      process.stderr.write(
        `Cost cap hit: $${total.toFixed(2)} >= $${COST_CAP_USD.toFixed(2)}. ` +
          `Halt marker written. Remove .claude/.HALT-COST to resume.\n`
      );
      process.exit(2);
    }

    process.exit(0);
  } catch (err) {
    // Fail-open: never block on hook bugs.
    process.stderr.write(`cost-guard hook error (allowing): ${err.message}\n`);
    process.exit(0);
  }
})();
