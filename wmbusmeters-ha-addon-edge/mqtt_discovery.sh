#!/usr/bin/with-contenv bashio
# ==============================================================================
# "MQTT discovery" in the manual mode: publishes the configuration that was
# applied in the panel for a meter, /data/discovery/applied/<id>.json - for the
# meters whose mode is manual (the add-on's "MQTT discovery" setting or the
# meter's own "mqtt_discovery" key). A manual meter without an applied
# configuration publishes nothing and keeps its discovery until one is applied.
# The generated ("auto") discovery of every other meter is published by
# send_meter_discovery.sh when its first telegram arrives.
#
#   /mqtt_discovery.sh -h <broker> -p <port> -u <user> -P <password> \
#                      -c <options_custom.json> -w <data path>
#
# run.sh calls this at start-up, after the MQTT helpers are written. A payload
# may use the placeholders {name}, {id}, {driver} and {attribute}.
#
# Exits cleanly (0): a missing configuration or an unreachable broker only skips
# the discovery, the add-on must never be blocked.
# ==============================================================================

aryDiscTopic=()
pub_args=()
while getopts h:p:u:P:c:w: flag
do
    case "${flag}" in
        h|p|u|P) pub_args+=("-${flag}" ${OPTARG});;
        c) CONFIG_PATH=${OPTARG};;
        w) CONFIG_DATA_PATH=${OPTARG};;
    esac
done

# The add-on's "MQTT discovery" mode is the default of every meter; a meter may
# carry its own "mqtt_discovery" key and then that one wins (the panel shows
# the choice under every meter, see DOCS.md). Only meters whose mode is "manual"
# publish from the templates here: "auto" is published by send_meter_discovery.sh
# when the first telegram of that meter arrives, "disable" publishes nothing.
CONFIG_MQTTDISCOVERY_MODE="$(jq --raw-output -c -M '.mqtt_discovery // empty' $CONFIG_PATH)"

effective_mode() {  # $1: the meter's own mode, if it has one
    case "${1:-}" in
        auto|manual|disable) printf '%s' "$1" ;;
        *)                   printf '%s' "$CONFIG_MQTTDISCOVERY_MODE" ;;
    esac
}

# Nothing to publish when the add-on mode is not manual and no meter asks for
# it. "default" is not a mode: a meter without its own key uses the add-on one.
MANUAL_METERS=0
while IFS= read -r own_mode
do
    [ "$(effective_mode "$own_mode")" = "manual" ] && MANUAL_METERS=$(( MANUAL_METERS + 1 ))
done < <(jq -r '.meters[]? | .mqtt_discovery // "default"' $CONFIG_PATH 2>/dev/null)
if [ "${CONFIG_MQTTDISCOVERY_MODE}" != "manual" ] && [ "${MANUAL_METERS:-0}" = "0" ]; then
    exit 0
fi

bashio::log.info "MQTT Discovery (manual) ..."

# HA's discovery prefix. The generated ("auto") discovery always publishes to
# homeassistant, see send_meter_discovery.sh.
MQTT_DISCOVERY_PREFIX="homeassistant"
if bashio::services.available "mqtt"; then
    prefix=$(bashio::services mqtt "discovery_prefix")
    if [ -n "$prefix" ] && [ "$prefix" != "null" ]; then
        MQTT_DISCOVERY_PREFIX="$prefix"
    fi
fi

# The configurations applied in the panel, one file per meter (see
# rootfs/flask/discovery_files.py).
DISCOVERY_DIR="${WMBUSMETERS_DISCOVERY_DIR:-/data/discovery}"

# Enumerate defined meters
IFS=$'\n'
aryManualIds=()
arySkippedIds=()
for meter in $(jq -c -M '.meters[]' $CONFIG_PATH)
do
    declare -A aryKV
    declare kv
    for line in $(printf '%s\n' $meter | jq --raw-output -c -M '.')
    do
        aryKV["name"]=$(printf '%s\n' $meter | jq --raw-output -c -M '.name')
        aryKV["id"]=$(printf '%s\n' $meter | jq --raw-output -c -M '.id')
        aryKV["driver"]=$(printf '%s\n' $meter | jq --raw-output -c -M '.driver')
        aryKV["driver"]=${aryKV["driver"]%%:*}
        aryKV["discovery"]=$(printf '%s\n' $meter | jq --raw-output -c -M '.mqtt_discovery // empty')

    done

    MODE=$(effective_mode "${aryKV['discovery']}")
    if [ "$MODE" != "manual" ]; then
        bashio::log.info " Skipping meter ${aryKV['name']}: its MQTT discovery mode is ${MODE:-<not set>}."
        # Its discovery belongs to another run: the generated one is published
        # by send_meter_discovery.sh, a disabled meter keeps what it has.
        arySkippedIds+=("${aryKV['id']}")
        continue
    fi
    bashio::log.info " Adding meter: ${aryKV['name']} ..."
    aryManualIds+=("${aryKV['id']}")

    if [ "${aryKV['id']+true}" ] && [ "${aryKV['driver']+true}" ] ; then
        file="$DISCOVERY_DIR/applied/${aryKV['id']}.json"
        if test -f "$file"; then

            for attribute in $(jq --raw-output -c -M '. | keys[]' $file)
            do
                aryKV["attribute"]=$attribute

                filter=".${attribute}.component"
                component=$(jq --raw-output -c -M $filter $file)
                if [[ ! -z "$component" ]] && [ $component != "null" ] ; then
                    topic="$MQTT_DISCOVERY_PREFIX/$component/wmbusmeters/${aryKV['id']}_$attribute/config"

                    filter=".${attribute}.discovery_payload"
                    payload=$(jq --raw-output -c -M $filter $file)

                    for key in ${!aryKV[@]}; do
                        payload="${payload//\{$key\}/${aryKV[${key}]}}"
                    done
                    bashio::log.info "  Add/update topic: $topic"
                    aryDiscTopic+=($topic)
                    /usr/bin/mosquitto_pub ${pub_args[@]} -r -t "${topic}" -m "${payload}"
                fi
            done
        else
            # Nothing applied yet: keep what the meter has, e.g. the generated
            # discovery from before the switch to manual.
            bashio::log.info "  No discovery applied for meter ${aryKV['name']} yet: apply one in the panel. Its current discovery is kept."
            arySkippedIds+=("${aryKV['id']}")
        fi
    fi
done

bashio::log.info "MQTT Discovery (manual): published ${#aryDiscTopic[@]} discovery entities for ${#aryManualIds[@]} meter(s)."

# Remove the retained discovery of a manual meter that the templates do not
# publish any more, and of a meter that is not in the configuration any more, so
# that entities of templates or meters that are gone do not stay in Home
# Assistant forever. The discovery of the other meters is left alone: the
# generated one belongs to the meter that publishes it (send_meter_discovery.sh
# removes its own stale entities), and a disabled meter keeps what it has.
bashio::log.info "MQTT Discovery cleanup..."
ramtmp="$(mktemp -p /dev/shm/)"
/usr/bin/mosquitto_sub ${pub_args[@]} -t "$MQTT_DISCOVERY_PREFIX/+/wmbusmeters/+/config" --retained-only -F "%t" > $ramtmp & PID=$!
sleep 1
kill $PID

readarray -t aryReadTopic < $ramtmp;
rm $ramtmp
for topic in ${aryReadTopic[@]}
do
    # <prefix>/<component>/wmbusmeters/<id>_<attribute>/config
    rest="${topic#*\/wmbusmeters\/}"
    id="${rest%%_*}"

    # A meter that is skipped here (auto or disable) above keeps its discovery.
    # A plain loop keeps the IFS of the meter enumeration out of this test.
    skipped_meter=false
    for skipped_id in "${arySkippedIds[@]}"
    do
        if [ "${skipped_id}" = "${id}" ]; then
            skipped_meter=true
            break
        fi
    done
    [ "${skipped_meter}" = "true" ] && continue

    if [[ ! ${aryDiscTopic[@]} =~ $topic ]]; then
        bashio::log.info " Removing topic: $topic"
        /usr/bin/mosquitto_pub ${pub_args[@]} -r -t "${topic}" -n
    fi
done

exit 0
