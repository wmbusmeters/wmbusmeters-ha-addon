#!/usr/bin/with-contenv bashio
# Hold a long-lived MQTT connection so the broker fires Last Will when the
# addon dies uncleanly (crash, SIGKILL, network drop). State transitions
# during normal operation are driven by /availability_filter.sh, which
# inspects wmbusmeters' log output.

ENV_FILE="/var/run/wmbusmeters/availability.env"

while [[ ! -f "$ENV_FILE" ]]; do sleep 1; done
# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "$MQTT_HOST" || "$MQTT_HOST" == "none" ]]; then
    bashio::log.info "Availability: MQTT not configured, LWT disabled."
    exec sleep infinity
fi

ARGS=('-h' "$MQTT_HOST")
[[ -n "$MQTT_PORT" ]] && ARGS+=('-p' "$MQTT_PORT")
[[ -n "$MQTT_USER" ]] && ARGS+=('-u' "$MQTT_USER")
[[ -n "$MQTT_PASSWORD" ]] && ARGS+=('-P' "$MQTT_PASSWORD")
ARGS+=('--will-topic' "$AVAILABILITY_TOPIC"
       '--will-payload' 'offline'
       '--will-retain' '--will-qos' '1'
       '-k' '30'
       '-t' "$AVAILABILITY_TOPIC")

bashio::log.info "Availability: holding LWT connection (topic=${AVAILABILITY_TOPIC})."

while true; do
    /usr/bin/mosquitto_sub "${ARGS[@]}" >/dev/null 2>&1
    bashio::log.warning "Availability: LWT connection dropped, reconnecting in 5s."
    sleep 5
done
