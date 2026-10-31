#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options_custom.json
RESET_CONF=$(bashio::config 'reset_config')

# A breaking change of this version (NOTICE.md, written by the build from BREAKING.md:
# the version on the first line, the text below) is shown once as a persistent
# notification in HA. Fresh installs have nothing to migrate, they only remember it.
if [ -s /NOTICE.md ]; then
    NOTICE_VERSION=$(head -n 1 /NOTICE.md)
    if [ "$(cat /data/notice_shown 2>/dev/null)" != "${NOTICE_VERSION}" ]; then
        if [ ! -f ${CONFIG_PATH} ]; then
            echo "${NOTICE_VERSION}" > /data/notice_shown
        elif curl -sf -X POST                 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}"                 -H "Content-Type: application/json"                 -d "$(jq -n --arg title "Wmbusmeters ${NOTICE_VERSION}: breaking change"                             --arg message "$(tail -n +2 /NOTICE.md)"                             --arg id "wmbusmeters_breaking_${NOTICE_VERSION}"                             '{title: $title, message: $message, notification_id: $id}')"                 http://supervisor/core/api/services/persistent_notification/create > /dev/null; then
            bashio::log.info "Breaking change notice for ${NOTICE_VERSION} shown in Home Assistant."
            echo "${NOTICE_VERSION}" > /data/notice_shown
        else
            bashio::log.warning "Could not show the breaking change notice for ${NOTICE_VERSION}, will retry on next start."
        fi
    fi
fi

if [ ! -f ${CONFIG_PATH} ]
then
    echo '{"data_path": "/homeassistant/wmbusmeters", "mqtt_discovery": "disable", "conf": {"loglevel": "normal", "device": "auto:t1", "addtelegramdetails":"first", "donotprobe": "/dev/ttyAMA0", "logtelegrams": "false", "format": "json", "logfile": "/dev/stdout", "shell": "/wmbusmeters/mosquitto_pub.sh \"wmbusmeters/$METER_NAME\" \"$METER_JSON\"", "metershell": "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""}, "meters": [], "mqtt": {}}' | jq . > ${CONFIG_PATH}
fi

# Ensure metershell (first-telegram MQTT discovery) exists for pre-existing configs
if [ -z "$(jq -r '.conf.metershell // empty' ${CONFIG_PATH} 2>/dev/null)" ]; then
    bashio::log.info "Adding metershell to configuration ..."
    tmp_cfg=$(mktemp)
    jq 'del(.conf.meter_shell) | .conf.metershell = "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""' ${CONFIG_PATH} > ${tmp_cfg} && mv ${tmp_cfg} ${CONFIG_PATH}
fi

# wmbusmeters only accepts addtelegramdetails in the config file, rename the old telegramdetails key
if [ "$(jq -r '.conf | has("telegramdetails")' ${CONFIG_PATH} 2>/dev/null)" = "true" ]; then
    bashio::log.info "Renaming telegramdetails to addtelegramdetails in configuration ..."
    tmp_cfg=$(mktemp)
    jq '.conf.addtelegramdetails //= .conf.telegramdetails | del(.conf.telegramdetails)' ${CONFIG_PATH} > ${tmp_cfg} && mv ${tmp_cfg} ${CONFIG_PATH}
fi

# "Enable mqtt discovery" (true/false) became the three-way "mqtt_discovery"
# (disable/auto/manual): true -> auto, false -> disable. An existing choice of
# the new option always wins, the old key is only read once and then dropped.
# BEGIN mqtt discovery mode migration
legacy_flag=$(jq -r '.enable_mqtt_discovery | tostring' ${CONFIG_PATH} 2>/dev/null)
if [ -n "${legacy_flag}" ] && [ "${legacy_flag}" != "null" ]; then
    mode=$(jq -r '.mqtt_discovery // empty' ${CONFIG_PATH} 2>/dev/null)
    if [ -z "${mode}" ]; then
        case "${legacy_flag}" in
            true) mode=auto ;;
            *)    mode=disable ;;
        esac
        bashio::log.info "MQTT discovery mode \"${mode}\" takes over the old \"Enable mqtt discovery\": ${legacy_flag} ..."
    fi
    tmp_cfg=$(mktemp)
    jq --arg m "${mode}" '.mqtt_discovery = $m | del(.enable_mqtt_discovery)' ${CONFIG_PATH} > ${tmp_cfg} && mv ${tmp_cfg} ${CONFIG_PATH}
fi
# END mqtt discovery mode migration

# MQTT discovery is now sent on demand. When the FIRST telegram from a
# meter arrives then this happens:
# wmbusmeters executes the "metershell" config setting which
# is send_meter_discovery.sh "$METER_JSON" "$METER_DRIVER"
# which takes as arguments:
#   the firs telegram with telegram details added
#   and the meter driver.
# These are used to generate a discovery json which is sent to HA.

if [ "${RESET_CONF}" = "yes" ]
then
    bashio::log.info "RESET CONFIG selected - reseting add-on configuration to default ..."
    echo '{"data_path": "/homeassistant/wmbusmeters", "mqtt_discovery": "disable", "conf": {"loglevel": "normal", "device": "auto:t1", "addtelegramdetails":"first", "donotprobe": "/dev/ttyAMA0", "logtelegrams": "false", "format": "json", "logfile": "/dev/stdout", "shell": "/wmbusmeters/mosquitto_pub.sh \"wmbusmeters/$METER_NAME\" \"$METER_JSON\"", "metershell": "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""}, "meters": [], "mqtt": {}}' | jq . > ${CONFIG_PATH}
    bashio::app.option "reset_config" "no"
    bashio::app.restart
fi

CONFIG_DATA_PATH=$(bashio::jq "${CONFIG_PATH}" '.data_path')

# The selected "MQTT discovery" mode is announced at every start, so that the
# log shows it without opening the panel (docs: "MQTT discovery" in DOCS.md).
MQTT_DISCOVERY_MODE="$(jq -r '.mqtt_discovery // empty' ${CONFIG_PATH} 2>/dev/null)"
case "${MQTT_DISCOVERY_MODE}" in
    auto)    bashio::log.info "MQTT discovery mode: auto - the generated discovery is published when the first telegram of a meter arrives";;
    manual)  bashio::log.info "MQTT discovery mode: manual - the templates in ${CONFIG_DATA_PATH}/etc/mqtt_discovery are published at start-up";;
    disable) bashio::log.info "MQTT discovery mode: disable - no Home Assistant entities are created or updated; the meter data is still published to MQTT";;
    *)       bashio::log.warning "MQTT discovery mode is '${MQTT_DISCOVERY_MODE}', not one of auto, manual, disable - nothing is published";;
esac

# f21a2e3a replaced the config mapping with homeassistant_config, which mounts
# the HA configuration at /homeassistant instead of /config. A data_path under
# /config now points at an empty ephemeral directory, so migrate it to
# /homeassistant - the same host directory as before. Check the mount, back up
# the configuration, rescue files that still exist at the old location and log
# every step.
# BEGIN data_path migration
config_dir_mounted() {
    grep -q " /homeassistant " /proc/mounts
}

case "${CONFIG_DATA_PATH}" in
    /config/*)
        OLD_DATA_PATH="${CONFIG_DATA_PATH}"
        NEW_DATA_PATH="/homeassistant${CONFIG_DATA_PATH#/config}"
        if config_dir_mounted; then
            mkdir -p "${NEW_DATA_PATH}"
            if [ -d "${OLD_DATA_PATH}" ] && [ -n "$(ls -A "${OLD_DATA_PATH}" 2>/dev/null)" ]; then
                if cp -a -n "${OLD_DATA_PATH}/." "${NEW_DATA_PATH}/"; then
                    bashio::log.info "Copied files that still existed at ${OLD_DATA_PATH} to ${NEW_DATA_PATH} ..."
                else
                    bashio::log.warning "Could not copy all files from ${OLD_DATA_PATH} to ${NEW_DATA_PATH} ..."
                fi
            fi
            cp -p ${CONFIG_PATH} ${CONFIG_PATH}.bak
            tmp_cfg=$(mktemp)
            if jq --arg p "${NEW_DATA_PATH}" '.data_path = $p' ${CONFIG_PATH} > ${tmp_cfg}; then
                mv ${tmp_cfg} ${CONFIG_PATH}
                CONFIG_DATA_PATH="${NEW_DATA_PATH}"
                bashio::log.info "Migrated data_path from ${OLD_DATA_PATH} to ${NEW_DATA_PATH} (the same host directory as before the homeassistant_config mapping). Backup: ${CONFIG_PATH}.bak"
            else
                rm -f ${tmp_cfg}
                bashio::log.warning "Could not rewrite data_path in ${CONFIG_PATH}, keeping ${OLD_DATA_PATH} ..."
            fi
        else
            bashio::log.warning "data_path ${OLD_DATA_PATH} refers to the pre-homeassistant_config mapping, but /homeassistant is not mounted - keeping ${OLD_DATA_PATH}. Files there are lost when the add-on is updated. Set the config location to ${NEW_DATA_PATH} instead."
        fi
        ;;
esac
# END data_path migration
# The same mapping change applies to the paths in conf: a logfile or meterfiles
# under /config cannot be written and wmbusmeters exits with status 14
# (wmbusmeters#2140). Migrate every conf value that is a path under /config to
# /homeassistant, the same host directory, with a backup and a log line per key.
# BEGIN conf path migration
CONF_OLD_PREFIX="/config/"
CONF_NEW_PREFIX="/homeassistant/"
CONF_OLD_PATHS=$(jq -r --arg old "${CONF_OLD_PREFIX}" '(.conf // {}) | to_entries[] | select((.value | type) == "string" and (.value | startswith($old))) | "\(.key)=\(.value)"' ${CONFIG_PATH})
if [ -n "${CONF_OLD_PATHS}" ]; then
    if config_dir_mounted; then
        cp -p ${CONFIG_PATH} ${CONFIG_PATH}.conf_paths.bak
        tmp_cfg=$(mktemp)
        if jq --arg old "${CONF_OLD_PREFIX}" --arg new "${CONF_NEW_PREFIX}" '.conf |= with_entries(if (.value | type) == "string" and (.value | startswith($old)) then .value = $new + (.value | ltrimstr($old)) else . end)' ${CONFIG_PATH} > ${tmp_cfg}; then
            mv ${tmp_cfg} ${CONFIG_PATH}
            while IFS='=' read -r conf_key conf_old; do
                conf_new="${CONF_NEW_PREFIX}${conf_old#"${CONF_OLD_PREFIX}"}"
                # wmbusmeters does not create the directories itself.
                case "${conf_key}" in
                    meterfiles) mkdir -p "${conf_new}" ;;
                    logfile) mkdir -p "$(dirname "${conf_new}")" ;;
                esac
                bashio::log.info "Migrated ${conf_key} from ${conf_old} to ${conf_new} (the same host directory as before the homeassistant_config mapping)."
            done <<< "${CONF_OLD_PATHS}"
            bashio::log.info "Backup of the configuration before the conf path migration: ${CONFIG_PATH}.conf_paths.bak"
        else
            rm -f ${tmp_cfg}
            bashio::log.warning "Could not rewrite the /config paths in conf of ${CONFIG_PATH}, keeping them ..."
        fi
    else
        bashio::log.warning "conf has paths under /config, which refer to the pre-homeassistant_config mapping, but /homeassistant is not mounted - keeping them. Change them to /homeassistant/... in the add-on configuration."
    fi
fi
# END conf path migration
CONFIG_CONF=$(bashio::jq "${CONFIG_PATH}" '.conf')
CONFIG_METERS=$(bashio::jq "${CONFIG_PATH}" '.meters')

bashio::log.info "CONFIG_CONF ..."
bashio::log.info "${CONFIG_CONF}"
bashio::log.info "CONFIG_METERS ..."
bashio::log.info "${CONFIG_METERS}"

bashio::log.info "Syncing wmbusmeters configuration ..."
if ! bashio::fs.directory_exists "${CONFIG_DATA_PATH}/logs/meter_readings"; then
    mkdir -p "${CONFIG_DATA_PATH}/logs/meter_readings"
fi
if ! bashio::fs.directory_exists "${CONFIG_DATA_PATH}/etc/wmbusmeters.d"; then
    mkdir -p "${CONFIG_DATA_PATH}/etc/wmbusmeters.d"
fi
if ! bashio::fs.directory_exists "${CONFIG_DATA_PATH}/etc/wmbusmeters.drivers.d"; then
    mkdir -p "${CONFIG_DATA_PATH}/etc/wmbusmeters.drivers.d"
fi
if [ ! -d /data/drivers ]
then
    mkdir -p /data/drivers
fi
rm -rf ${CONFIG_DATA_PATH}/etc/wmbusmeters.drivers.d/*
if [ -n "$(ls -A /data/drivers 2>/dev/null)" ]; then
    cp /data/drivers/* "${CONFIG_DATA_PATH}/etc/wmbusmeters.drivers.d/"
fi

echo -e "$CONFIG_CONF" | jq -r 'to_entries|map("\(.key)=\(.value|tostring)")|.[]' > $CONFIG_DATA_PATH/etc/wmbusmeters.conf

# A value with ";" lists several values for the same key, e.g. device=auto:t1;rtlwmbus
# becomes two device= lines. A ";" inside parentheses belongs to the value itself,
# e.g. the shell command in CMD(...), and does not split it.
# BEGIN conf split
split_outside_parens() {
    local s="$1" part="" depth=0 c i
    for (( i=0; i<${#s}; i++ )); do
        c="${s:i:1}"
        case "$c" in
            "(") depth=$((depth + 1)) ;;
            ")") [ $depth -gt 0 ] && depth=$((depth - 1)) ;;
        esac
        if [ "$c" = ";" ] && [ $depth -eq 0 ]; then
            printf '%s\n' "$part"
            part=""
        else
            part+="$c"
        fi
    done
    printf '%s\n' "$part"
}

while IFS= read -r line; do
    # The key ends at the first "=", the value may contain "=" too.
    key="${line%%=*}"
    values="${line#*=}"
    if [[ "$values" == *";"* ]]; then
        split_outside_parens "$values" | while IFS= read -r value; do
            echo "$key=$value"
        done
    else
        echo "$line"
    fi
done < $CONFIG_DATA_PATH/etc/wmbusmeters.conf > $CONFIG_DATA_PATH/etc/wmbusmeters.conf_tmp
mv $CONFIG_DATA_PATH/etc/wmbusmeters.conf_tmp $CONFIG_DATA_PATH/etc/wmbusmeters.conf
# END conf split

bashio::log.info "Registering meters ..."
rm -f $CONFIG_DATA_PATH/etc/wmbusmeters.d/*
meter_no=0
IFS=$'\n'
for meter in $(jq -c -M '.meters[]' $CONFIG_PATH)
do
    meter_no=$(( meter_no+1 ))
    METER_NAME=$(printf 'meter-%04d' "$(( meter_no ))")
    bashio::log.info "Adding $METER_NAME ..."
    METER_DATA=$(printf '%s\n' $meter | jq --raw-output -c -M '.')
    echo -e "$METER_DATA" | jq -r 'to_entries|map("\(.key)=\(.value|tostring)")|.[]' > $CONFIG_DATA_PATH/etc/wmbusmeters.d/$METER_NAME
done

bashio::log.info "Generating MQTT configuration ... "
if bashio::jq.exists "${CONFIG_PATH}" ".mqtt.server"
then
  MQTT_HOST=$(bashio::jq "${CONFIG_PATH}" ".mqtt.server")
  if bashio::jq.exists "${CONFIG_PATH}" ".mqtt.port"; then MQTT_PORT=$(bashio::jq "${CONFIG_PATH}" ".mqtt.port"); fi
  if bashio::jq.exists "${CONFIG_PATH}" ".mqtt.username"; then MQTT_USER=$(bashio::jq "${CONFIG_PATH}" ".mqtt.username"); fi
  if bashio::jq.exists "${CONFIG_PATH}" ".mqtt.password"; then MQTT_PASSWORD=$(bashio::jq "${CONFIG_PATH}" ".mqtt.password"); fi
else
  if ! bashio::services.available "mqtt"; then
    bashio::log.warning "No internal MQTT service found or configured"
    MQTT_HOST="none"
  else
    bashio::log.info "MQTT service found, fetching credentials ..."
    MQTT_HOST=$(bashio::services mqtt "host")
    MQTT_PORT=$(bashio::services mqtt "port")
    MQTT_USER=$(bashio::services mqtt "username")
    MQTT_PASSWORD=$(bashio::services mqtt "password")
  fi
fi

touch /wmbusmeters/mosquitto_pub.sh

if [[ "$MQTT_HOST" != "none" ]]; then
    bashio::log.info "Broker $MQTT_HOST will be used."
    pub_args=('-h' "$MQTT_HOST")
    pub_args_quoted=('-h' "'$MQTT_HOST'")
    [[ ! -z ${MQTT_PORT+x} ]] && pub_args+=( '-p' $MQTT_PORT ) && pub_args_quoted+=( '-p' \'$MQTT_PORT\' )
    [[ ! -z ${MQTT_USER+x} ]] && pub_args+=( '-u' $MQTT_USER ) && pub_args_quoted+=( '-u' \'$MQTT_USER\' )
    [[ ! -z ${MQTT_PASSWORD+x} ]] && pub_args+=( '-P' $MQTT_PASSWORD ) && pub_args_quoted+=( '-P' \'$MQTT_PASSWORD\' )

    cat > /wmbusmeters/mosquitto_pub.sh << EOL
#!/usr/bin/with-contenv bashio
TOPIC=\$1
MESSAGE=\$2
/usr/bin/mosquitto_pub ${pub_args_quoted[@]} -r -t "\$TOPIC" -m "\$MESSAGE"
EOL

    # Used by send_meter_discovery.sh to remove discovery that is no longer published.
    cat > /wmbusmeters/mosquitto_retained.sh << EOL
#!/usr/bin/with-contenv bashio
# list <filter>: print the topics of the retained messages matching the filter
# clear <topic>: remove the retained message of the topic
case "\$1" in
    list)  /usr/bin/mosquitto_sub ${pub_args_quoted[@]} -t "\$2" --retained-only -F "%t" -W 2 ;;
    clear) /usr/bin/mosquitto_pub ${pub_args_quoted[@]} -r -t "\$2" -n ;;
esac
EOL
    chmod a+x /wmbusmeters/mosquitto_retained.sh

    # Manual MQTT discovery: publish the templates in
    # <data path>/etc/mqtt_discovery, like the add-on did before 3.1. Only in
    # the "manual" mode, "auto" is published by send_meter_discovery.sh when a
    # telegram arrives and "disable" publishes nothing.
    if [ "${MQTT_DISCOVERY_MODE}" = "manual" ]; then
        /mqtt_discovery.sh ${pub_args[@]} -c ${CONFIG_PATH} -w ${CONFIG_DATA_PATH} || true
    fi

fi

chmod a+x /wmbusmeters/mosquitto_pub.sh

bashio::log.info "Running wmbusmeters ..."
if pgrep wmbusmeters > /dev/null; then
    pkill wmbusmeters
fi
/wmbusmeters/wmbusmeters --useconfig=$CONFIG_DATA_PATH
