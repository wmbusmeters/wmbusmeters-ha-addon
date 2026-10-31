#!/usr/bin/with-contenv bashio
# ==============================================================================
# "MQTT discovery" in the manual mode: publishes the discovery payloads from
# the templates in <data path>/etc/mqtt_discovery/<driver>.json, one file per
# driver, like the add-on did before 3.1.
#
#   /mqtt_discovery.sh -h <broker> -p <port> -u <user> -P <password> \
#                      -c <options_custom.json> -w <data path>
#
# run.sh calls this at start-up, after the MQTT helpers are written. A template
# payload may use the placeholders {name}, {id}, {driver} and {attribute}.
#
# Exits cleanly (0): a missing template or an unreachable broker only skips the
# discovery, the add-on must never be blocked.
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

# Only the manual mode publishes from the templates, "auto" is published by
# send_meter_discovery.sh when the first telegram of a meter arrives.
CONFIG_MQTTDISCOVERY_MODE="$(jq --raw-output -c -M '.mqtt_discovery // empty' $CONFIG_PATH)"
if [ "$CONFIG_MQTTDISCOVERY_MODE" != "manual" ]; then
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

# Copy the bundled templates, but never overwrite one that the user edited:
# their own templates are the point of this mode. Update a copy by deleting it
# here and letting the next start copy the bundled version again.
[ ! -d $CONFIG_DATA_PATH/etc/mqtt_discovery ] && mkdir -p $CONFIG_DATA_PATH/etc/mqtt_discovery
templates_before=$(ls -1 ${CONFIG_DATA_PATH}/etc/mqtt_discovery 2>/dev/null | wc -l)
cp -n /mqtt_discovery/* ${CONFIG_DATA_PATH}/etc/mqtt_discovery/ 2>/dev/null || true
templates_after=$(ls -1 ${CONFIG_DATA_PATH}/etc/mqtt_discovery 2>/dev/null | wc -l)
bashio::log.info "Templates in ${CONFIG_DATA_PATH}/etc/mqtt_discovery: ${templates_after} file(s), seeded $((templates_after - templates_before)) new."

# Enumerate defined meters
IFS=$'\n'
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

    done
    bashio::log.info " Adding meter: ${aryKV['name']} ..."

    if [ "${aryKV['id']+true}" ] && [ "${aryKV['driver']+true}" ] ; then
        file="$CONFIG_DATA_PATH/etc/mqtt_discovery/${aryKV['driver']}.json"
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
            bashio::log.info "  No template for meter ${aryKV['name']}: $file not found"
        fi
    fi
done

bashio::log.info "MQTT Discovery (manual): published ${#aryDiscTopic[@]} discovery entities."

# Remove the retained discovery of this prefix that the templates do not
# publish any more, so that entities of templates or meters that are gone do
# not stay in Home Assistant forever.
bashio::log.info "MQTT Discovery cleanup..."
ramtmp="$(mktemp -p /dev/shm/)"
/usr/bin/mosquitto_sub ${pub_args[@]} -t "$MQTT_DISCOVERY_PREFIX/+/wmbusmeters/+/config" --retained-only -F "%t" > $ramtmp & PID=$!
sleep 1
kill $PID

readarray -t aryReadTopic < $ramtmp;
rm $ramtmp
for topic in ${aryReadTopic[@]}
do
    if [[ ! ${aryDiscTopic[@]} =~ $topic ]]; then
        bashio::log.info " Removing topic: $topic"
        /usr/bin/mosquitto_pub ${pub_args[@]} -r -t "${topic}" -n
    fi
done

exit 0
