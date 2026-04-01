#!/bin/bash
# log_shipper.sh — Ships log lines to the allocator /api/vm-logs endpoint.
#
# Usage:
#   log_shipper.sh <source> <allocator_url> <vm_name> <log_group> <api_token>
#
# <source> is either:
#   - A file path (e.g., /var/log/cloud-init-output.log) — tailed with tail -F
#   - "docker:<container_id>" — streamed via docker logs --follow
set -euo pipefail

SOURCE="$1"
ALLOCATOR_URL="$2"
VM_NAME="$3"
LOG_GROUP="$4"
API_TOKEN="$5"

BATCH_SIZE=50
FLUSH_INTERVAL=15
MAX_RETRIES=3
ENDPOINT="$ALLOCATOR_URL/api/vm-logs"
SELF_LOG="/var/log/log_shipper.log"

# Derive a short label for log messages
if [[ "$SOURCE" == docker:* ]]; then
    SOURCE_LABEL="docker:${SOURCE#docker:}"
    SOURCE_LABEL="${SOURCE_LABEL:0:20}"
else
    SOURCE_LABEL=$(basename "$SOURCE")
fi

log() { echo "$(date -Is) [log_shipper:$SOURCE_LABEL] $*" >> "$SELF_LOG"; }

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

BUFFER=()
LAST_FLUSH=$(date +%s)

# Flush remaining buffer on exit/signal
cleanup() {
    log "Signal received, flushing ${#BUFFER[@]} remaining lines..."
    flush_buffer
    log "Shutdown complete"
    exit 0
}
trap cleanup SIGTERM SIGINT EXIT

# Determine the input source
if [[ "$SOURCE" == docker:* ]]; then
    # Docker container logs via docker logs --follow
    CONTAINER_ID="${SOURCE#docker:}"
    log "Waiting for container $CONTAINER_ID..."
    while ! docker inspect "$CONTAINER_ID" &>/dev/null; do
        sleep 2
    done
    log "Streaming docker logs for container $CONTAINER_ID"
    INPUT_CMD="docker logs --follow --timestamps $CONTAINER_ID 2>&1"
else
    # File-based source via tail -F
    log "Waiting for $SOURCE to appear..."
    while [ ! -f "$SOURCE" ]; do
        sleep 2
    done
    log "Tailing $SOURCE"
    INPUT_CMD="tail -F -n +1 $SOURCE 2>/dev/null"
fi

# Read with a timeout so the flush timer fires even when no new lines
# arrive (e.g., cloud-init finishes and the file stops growing).
while true; do
    if IFS= read -t "$FLUSH_INTERVAL" -r LINE; then
        BUFFER+=("$LINE")
    fi

    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_FLUSH))

    if [ ${#BUFFER[@]} -ge $BATCH_SIZE ] || [ $ELAPSED -ge $FLUSH_INTERVAL ]; then
        flush_buffer
        LAST_FLUSH=$(date +%s)
    fi
done < <(eval "$INPUT_CMD")
