#!/usr/bin/env bash
# morning-check.sh — Morning health snapshot for autonomous runs.
#
# Run this each morning (or whenever you wake the laptop) to see what
# Claude did overnight. Prints in plain text — no fancy formatting.
#
# Usage:
#   bash scripts/morning-check.sh
#
# What it shows:
#   1. Halt markers (cost cap hit, paused tasks)
#   2. Git activity since 24h ago
#   3. LLM cost ledger total
#   4. Pause/halt reports written by Claude
#   5. Last test run status (if pytest cache exists)
#   6. Branch state and uncommitted changes
#   7. Active plan state

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "================================================================"
echo "  MORNING CHECK — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  Repo: $REPO_ROOT"
echo "================================================================"
echo

# --- 1. Halt markers ---
echo "[1] Halt markers"
echo "--------"
if [[ -f .claude/.HALT-COST ]]; then
  echo "  COST CAP HIT — autonomous run halted on cost"
  cat .claude/.HALT-COST
  echo "  -> Resolve: review ledger, optionally raise CK_LLM_COST_CAP_USD, then rm .claude/.HALT-COST"
else
  echo "  no cost halt marker"
fi
if compgen -G "plans/reports/HALTED-*" > /dev/null; then
  echo "  HALT reports present:"
  ls -1 plans/reports/HALTED-* 2>/dev/null | head -5
else
  echo "  no HALT reports"
fi
if compgen -G "plans/reports/PAUSED-*" > /dev/null; then
  echo "  PAUSE reports present:"
  ls -1 plans/reports/PAUSED-* 2>/dev/null | head -5
else
  echo "  no PAUSE reports"
fi
echo

# --- 2. Git activity since 24h ago ---
echo "[2] Git activity (last 24h)"
echo "--------"
git log --since="24 hours ago" --oneline --decorate 2>/dev/null | head -50 || echo "  (no commits or repo error)"
echo
echo "  Branches modified in 24h:"
git for-each-ref --sort=-committerdate refs/heads --format='  %(committerdate:short) %(refname:short)' 2>/dev/null | head -10
echo

# --- 3. LLM cost ledger total ---
echo "[3] LLM cost"
echo "--------"
if [[ -f .claude/.cost-ledger.jsonl ]]; then
  total=$(awk -F'"cost_usd":' '/cost_usd/{ split($2, a, /[,}]/); s+=a[1] } END{ printf "%.4f", s+0 }' .claude/.cost-ledger.jsonl 2>/dev/null || echo "0")
  count=$(wc -l < .claude/.cost-ledger.jsonl 2>/dev/null | tr -d ' ' || echo 0)
  cap="${CK_LLM_COST_CAP_USD:-90}"
  echo "  Calls: $count"
  echo "  Total: \$${total}  (cap: \$${cap})"
  echo
  echo "  Top 5 most expensive calls:"
  jq -s 'sort_by(-.cost_usd)[:5] | .[] | "  \(.ts // "?")  \(.model // "?")  \$\(.cost_usd // 0)"' \
    .claude/.cost-ledger.jsonl 2>/dev/null | sed 's/^"//;s/"$//' | head -5 \
    || awk -F'"cost_usd":' '/cost_usd/{ split($2, a, /[,}]/); print "  $" a[1] }' .claude/.cost-ledger.jsonl | sort -rn | head -5
else
  echo "  no ledger yet (no LLM calls made)"
fi
echo

# --- 4. Pause/Halt report contents (last 3) ---
echo "[4] Latest pause/halt reports"
echo "--------"
shopt -s nullglob
reports=( plans/reports/PAUSED-*.md plans/reports/HALTED-*.md plans/reports/COST-CAP-HIT-*.md )
if (( ${#reports[@]} == 0 )); then
  echo "  none"
else
  for r in $(ls -t "${reports[@]}" 2>/dev/null | head -3); do
    echo "  $r"
    head -15 "$r" | sed 's/^/    /'
    echo
  done
fi
shopt -u nullglob

# --- 5. Last test run ---
echo "[5] Last test run"
echo "--------"
if [[ -d .pytest_cache ]]; then
  if [[ -f .pytest_cache/v/cache/lastfailed ]] && [[ -s .pytest_cache/v/cache/lastfailed ]]; then
    echo "  pytest reports failures:"
    cat .pytest_cache/v/cache/lastfailed | head -20 | sed 's/^/    /'
  else
    echo "  pytest cache present, no recorded failures"
  fi
else
  echo "  no pytest cache (no tests run yet)"
fi
echo

# --- 6. Branch + uncommitted ---
echo "[6] Working tree state"
echo "--------"
git rev-parse --abbrev-ref HEAD 2>/dev/null | xargs -I{} echo "  Current branch: {}"
git status --short | head -20 | sed 's/^/  /' || echo "  (clean)"
echo

# --- 7. Active plan ---
echo "[7] Active plan"
echo "--------"
if [[ -d plans ]]; then
  latest_plan=$(ls -td plans/*/ 2>/dev/null | head -1 | sed 's:/$::' || true)
  if [[ -n "${latest_plan:-}" ]] && [[ -f "$latest_plan/plan.md" ]]; then
    echo "  Plan: $latest_plan"
    echo "  Frontmatter:"
    awk '/^---$/{c++; if(c==2) exit; next} c==1 {print "    " $0}' "$latest_plan/plan.md" 2>/dev/null
    echo
    echo "  Phase progress:"
    grep -E "^\| *[0-9]+ *\|" "$latest_plan/plan.md" 2>/dev/null | head -10 | sed 's/^/    /' || echo "    (no phase table)"
  else
    echo "  no active plan"
  fi
else
  echo "  no plans/ directory"
fi
echo

# --- 8. Recent journal entries (decisions, completions) ---
echo "[8] Recent journal entries (last 5)"
echo "--------"
if [[ -d docs/journals ]]; then
  ls -t docs/journals/*.md 2>/dev/null | head -5 | sed 's/^/  /'
else
  echo "  no journal directory yet"
fi
echo

echo "================================================================"
echo "  Done. Quick triage:"
echo "    halt markers? -> resolve first"
echo "    pause reports? -> review and unblock"
echo "    cost > 70%?   -> consider caching review"
echo "    test failures? -> may indicate retry-loop stuck"
echo "================================================================"
