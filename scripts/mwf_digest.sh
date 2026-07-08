#!/usr/bin/env bash
# mwf_digest.sh — launchd entry point (weekday mornings, 5:00 AM local time).
#
# Drains the paper backlog in digestible tranches. Each session:
#   1. Rebuilds the wiki knowledge base from email_src/ (offline, no API key).
#   2. Sends BATCH_COUNT separate distillation emails to $DIGEST_TO (default $SMTP_USER),
#      each a self-contained Karpathy-style audio tour of the next TRANCHE_SIZE
#      papers that are new since the last email. Only those papers are marked
#      seen, so the next email/session picks up where this one left off.
#   3. Stops early once the backlog is empty (no spurious "recap" emails).
#
# Each email = exactly ONE gTTS request, so BATCH_COUNT (3-4) per session stays
# far under gTTS's ~100 requests/hour ceiling. A short pause separates them.
#
# Credentials come from ~/.zsh_aliases (SMTP_USER/PASS/HOST/PORT).
#
# Tunables (env-overridable):
#   BATCH_COUNT   number of emails per session (default 3)
#   TRANCHE_SIZE  papers featured per email     (default 12)
#   BATCH_PAUSE   seconds between emails         (default 45)

set -uo pipefail

BATCH_COUNT="${BATCH_COUNT:-3}"
TRANCHE_SIZE="${TRANCHE_SIZE:-12}"
BATCH_PAUSE="${BATCH_PAUSE:-45}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/mwf_digest_$(date '+%Y%m%d_%H%M%S').log"

log() { printf '%s %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG_FILE"; }

# Load Gmail SMTP credentials from ~/.zsh_aliases WITHOUT sourcing the whole
# file (it references interactive-only zsh state like compdef). We grep the
# four SMTP_* export lines and eval only those.
if [[ -f "$HOME/.zsh_aliases" ]]; then
    while IFS= read -r line; do
        eval "$line"
    done < <(grep -E '^export SMTP_(USER|PASS|HOST|PORT)=' "$HOME/.zsh_aliases")
    export SMTP_USER SMTP_PASS SMTP_HOST SMTP_PORT
else
    log "[WARN] ~/.zsh_aliases not found; SMTP env vars must be set another way"
fi

# Resolve a Python interpreter that has gtts installed
if [[ -x "/opt/miniconda3/bin/python3" ]]; then
    PY="/opt/miniconda3/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    log "[ERROR] No python3 found"
    exit 1
fi

log "[INFO] Using python: $PY"
log "[INFO] Session plan: up to $BATCH_COUNT email(s), $TRANCHE_SIZE papers each"

# 1) Rebuild wiki (stdlib-only, offline) so the graph reflects the latest alerts.
log "[INFO] Compiling knowledge base"
"$PY" "$ROOT/src/wiki.py" >>"$LOG_FILE" 2>&1 && log "[INFO] Wiki compiled" \
    || log "[WARN] Wiki compile failed (non-fatal)"

if [[ -z "${SMTP_PASS:-}" ]]; then
    log "[ERROR] SMTP_PASS is unset — cannot email. Aborting."
    exit 2
fi

# 2) Send up to BATCH_COUNT tranche emails, stopping when the backlog is dry.
sent=0
for i in $(seq 1 "$BATCH_COUNT"); do
    log "[INFO] Tranche $i/$BATCH_COUNT: distilling next $TRANCHE_SIZE papers"
    out="$("$PY" "$ROOT/src/wiki_digest.py" \
              --to "${DIGEST_TO:-${SMTP_USER}}" \
              --limit "$TRANCHE_SIZE" \
              --max-featured "$TRANCHE_SIZE" \
              --skip-if-empty \
              --tag "b${i}" 2>>"$LOG_FILE")"
    rc=$?
    if [[ $rc -ne 0 ]]; then
        log "[ERROR] Tranche $i failed (rc=$rc) — stopping session"
        break
    fi
    if [[ "$out" == "SKIPPED_EMPTY" ]]; then
        log "[INFO] Backlog empty — no more tranches to send. Sent $sent this session."
        break
    fi
    sent=$((sent + 1))
    log "[INFO] Tranche $i emailed"
    if [[ $i -lt $BATCH_COUNT ]]; then
        sleep "$BATCH_PAUSE"
    fi
done

log "[INFO] Session complete — $sent email(s) sent"
exit 0
