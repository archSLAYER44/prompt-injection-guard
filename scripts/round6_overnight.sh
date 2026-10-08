#!/usr/bin/env bash
# Overnight driver: the round's training runs in sequence in rounds/round<N>/<tree>, then the report-only gate.
# Nothing is promoted and no test set is scored; the live tree is not modified. ROUND defaults to 7.
#
# Launch from the repo root, on mains power (the shell is zsh, so call bash explicitly):
#   ROUND=7 setsid nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block --who=round7 \
#     --why="round seven training" bash scripts/round6_overnight.sh > report/round7_overnight.log 2>&1 < /dev/null & disown
#
# Monitor:
#   cat report/round_six_overnight.log; tail -f rounds/round6/r1_rules/report/train_log.txt
#   pgrep -af "src.train|round6_overnight|gate_round6"; systemd-inhibit --list | grep round6
#   ls rounds/round6/*/DONE_* rounds/round6/STOPPED_* 2>/dev/null
#
# Optional arguments: tree names to run (default per round: 6 = r1_rules r2_data r3_rules_data, 7 = r1_rules r7_rules_drafted, 8 = r8_rules).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
ROUND="${ROUND:-7}"
RUNS="$ROOT/rounds/round$ROUND"
TREES=("$@")
if [ ${#TREES[@]} -eq 0 ]; then
  if [ "$ROUND" = 6 ]; then TREES=(r1_rules r2_data r3_rules_data); elif [ "$ROUND" = 8 ]; then TREES=(r8_rules); else TREES=(r1_rules r7_rules_drafted); fi
fi
if [ "$ROUND" = 6 ]; then GATE_TXT="$ROOT/report/round_six_gate.txt"; else GATE_TXT="$ROOT/report/round${ROUND}_gate.txt"; fi
LOCK="$RUNS/RUNNING"
AC=/sys/class/power_supply/AC/online

log() { echo "[$(date -Is)] $*"; }
ac_ok() { [ -r "$AC" ] && [ "$(cat "$AC")" = "1" ]; }

# ---- pre-flight -----------------------------------------------------------------------------------------
ac_ok || { log "refusing to start: not on mains power ($AC is not 1)"; exit 2; }
[ -x "$PY" ] || { log "refusing: $PY missing"; exit 2; }
if pgrep -f "src\.train|gate_round6|score_tests" >/dev/null; then
  log "refusing: a training, gate or test-scoring process is already running"; exit 2
fi
[ -e "$LOCK" ] && { log "refusing: $LOCK exists (another driver, or a crashed one: remove it by hand)"; exit 2; }
[ -f "$ROOT/data/cache/backup_round$ROUND/embeddings_norm.npy" ] || { log "refusing: data/cache/backup_round$ROUND/ missing"; exit 2; }
for t in "${TREES[@]}"; do
  T="$RUNS/$t"
  [ -d "$T/src" ] || { log "refusing: $T is not a run tree"; exit 2; }
  [ "$(readlink -f "$T/data/cache")" = "$(readlink -f "$ROOT/data/cache")" ] || { log "refusing: $T/data/cache does not resolve to the live cache"; exit 2; }
  ls "$T"/DONE_* >/dev/null 2>&1 && { log "refusing: $T already has a DONE marker (a run is scored once)"; exit 2; }
  [ -e "$T/report/train_log.txt" ] && { log "refusing: $T/report/train_log.txt exists"; exit 2; }
done
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# ---- the runs, one at a time -----------------------------------------------------------------------------
log "round $ROUND: ${TREES[*]} (python $("$PY" --version 2>&1), $(nproc) cores)"
for t in "${TREES[@]}"; do
  T="$RUNS/$t"
  ac_ok || { log "AC power lost before $t; stopping the sequence"; echo "AC lost" > "$RUNS/STOPPED_$t"; exit 3; }
  cd "$T" || exit 4
  start=$(date +%s)
  log "$t start"
  "$PY" -u -m src.train > report/train_log.txt 2>&1
  rc=$?
  end=$(date +%s)
  printf 'rc=%s\nstart=%s\nend=%s\nseconds=%s\n' "$rc" "$(date -Is -d @"$start")" "$(date -Is -d @"$end")" "$((end - start))" > "DONE_$rc"
  log "$t done rc=$rc in $((end - start)) s ($(( (end - start) / 60 )) min)"
  if [ "$rc" -ne 0 ]; then
    echo "rc=$rc" > "$RUNS/STOPPED_$t"
    log "stopping the sequence: a failed run may have left the shared cache mid-write; check $T/report/train_log.txt"
    exit 5
  fi
done

# ---- the gate, report only ---------------------------------------------------------------------------------
cd "$ROOT" || exit 4
log "gate start"
"$PY" scripts/gate_round6.py --round "$ROUND" > "$GATE_TXT" 2>&1
rc=$?
log "gate done rc=$rc; decision: $(grep -m1 '^DECISION' "$GATE_TXT" || echo "not found, read $GATE_TXT")"
exit $rc
