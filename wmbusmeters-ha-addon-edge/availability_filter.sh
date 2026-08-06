#!/usr/bin/with-contenv bashio
# Inspect wmbusmeters log output line by line, re-emit each line unchanged
# (so the HA log view still shows everything), and publish online/offline
# transitions to the MQTT availability topic when matching patterns appear.
#
# Patterns:
#   "No wmbus device detected" -> wmbusmeters has zero active listeners
#       (printed only when all configured devices are gone, so it stays correct
#       in multi-dongle setups where losing one device is not yet a full
#       outage). Other per-device messages like "Lost ... closing" and
#       "[ALARM SpecifiedDeviceNotFound]" are intentionally NOT matched.
#   "Started config ..." -> a listener became active. Safe to mark online
#       even if other devices are still down; at least one is producing
#       telegrams.

ENV_FILE="/var/run/wmbusmeters/availability.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"

PUB_ARGS=()
if [[ -n "$MQTT_HOST" && "$MQTT_HOST" != "none" ]]; then
    PUB_ARGS=('-h' "$MQTT_HOST")
    [[ -n "$MQTT_PORT" ]] && PUB_ARGS+=('-p' "$MQTT_PORT")
    [[ -n "$MQTT_USER" ]] && PUB_ARGS+=('-u' "$MQTT_USER")
    [[ -n "$MQTT_PASSWORD" ]] && PUB_ARGS+=('-P' "$MQTT_PASSWORD")
fi

LAST_STATE=""

publish() {
    local state="$1"
    [[ -z "$AVAILABILITY_TOPIC" ]] && return 0
    [[ "${#PUB_ARGS[@]}" -eq 0 ]] && return 0
    [[ "$state" == "$LAST_STATE" ]] && return 0
    if /usr/bin/mosquitto_pub "${PUB_ARGS[@]}" -r -q 1 \
            -t "$AVAILABILITY_TOPIC" -m "$state" 2>/dev/null; then
        LAST_STATE="$state"
        printf '[availability] -> %s\n' "$state" >&2
    fi
}

while IFS= read -r line; do
    printf '%s\n' "$line"
    if [[ "$line" == *"Started config"* ]]; then
        publish "online"
    elif [[ "$line" == *"No wmbus device detected"* ]]; then
        publish "offline"
    fi
done
