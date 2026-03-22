#!/bin/bash
# log_shipper.sh — Ships log lines to the allocator /api/vm-logs endpoint.
# Usage: log_shipper.sh <log_file> <allocator_url> <vm_name> <log_group> <api_token> [--docker-json]
set -euo pipefail

LOG_FILE="$1"
ALLOCATOR_URL="$2"
VM_NAME="$3"
LOG_GROUP="$4"
API_TOKEN="$5"
DOCKER_JSON="${6:-}"

BATCH_SIZE=50
FLUSH_INTERVAL=15
MAX_RETRIES=3
ENDPOINT="$ALLOCATOR_URL/api/vm-logs"
SELF_LOG="/var/log/log_shipper.log"

log() { echo "$(date -Is) [log_shipper:$(basename "$LOG_FILE")] $*" >> "$SELF_LOG"; }

send_batch() {
    local payload="$1"
    for attempt in $(seq 1 $MAX_RETRIES); do
        HTTP_CODE=$(curl -s -w "%{http_code}" -o /dev/null \
            -X POST "$ENDPOINT" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $API_TOKEN" \
            -d "$payload" --max-time 10 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
            return 0
        fi
        log "POST failed (HTTP $HTTP_CODE), attempt $attempt/$MAX_RETRIES"
        sleep $((attempt * 2))
    done
    log "Dropping batch after $MAX_RETRIES failures"
    return 0  # drop batch, don't crash
}

flush_buffer() {
    if [ ${#BUFFER[@]} -eq 0 ]; then
        return
    fi
    # Build JSON array of messages
    JSON_MESSAGES="["
    for i in "${!BUFFER[@]}"; do
        # Escape the line for JSON: backslashes, quotes, control chars
        ESCAPED=$(printf '%s' "${BUFFER[$i]}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()), end="")')
        if [ "$i" -gt 0 ]; then
            JSON_MESSAGES+=","
        fi
        JSON_MESSAGES+="$ESCAPED"
    done
    JSON_MESSAGES+="]"

    PAYLOAD=$(printf '{"log_group":"%s","log_stream":"%s","messages":%s}' \
        "$LOG_GROUP" "$VM_NAME" "$JSON_MESSAGES")

    send_batch "$PAYLOAD"
    log "Flushed ${#BUFFER[@]} lines"
    BUFFER=()
}

# Wait for the log file to appear
log "Waiting for $LOG_FILE to appear..."
while [ ! -f "$LOG_FILE" ]; do
    sleep 2
done
log "Tailing $LOG_FILE"

BUFFER=()
LAST_FLUSH=$(date +%s)

# tail -F follows through log rotation; -n +1 sends all existing lines
tail -F -n +1 "$LOG_FILE" 2>/dev/null | while IFS= read -r LINE; do
    # Parse Docker json-log format if requested
    if [ "$DOCKER_JSON" = "--docker-json" ]; then
        PARSED=$(printf '%s' "$LINE" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get("log", "").rstrip())
except Exception:
    print(sys.stdin.read().rstrip() if False else "")
' 2>/dev/null) || PARSED=""
        [ -z "$PARSED" ] && continue
        LINE="$PARSED"
    fi

    BUFFER+=("$LINE")

    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_FLUSH))

    if [ ${#BUFFER[@]} -ge $BATCH_SIZE ] || [ $ELAPSED -ge $FLUSH_INTERVAL ]; then
        flush_buffer
        LAST_FLUSH=$(date +%s)
    fi
done
