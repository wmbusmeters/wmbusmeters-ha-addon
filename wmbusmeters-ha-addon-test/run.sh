#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options_custom.json
RESET_CONF=$(bashio::config 'reset_config')

if [ ! -f ${CONFIG_PATH} ]
then
    echo '{"data_path": "/config/wmbusmeters", "enable_mqtt_discovery": "false", "conf": {"loglevel": "normal", "device": "auto:t1", "telegramdetails":"first", "donotprobe": "/dev/ttyAMA0", "logtelegrams": "false", "format": "json", "logfile": "/dev/stdout", "shell": "/wmbusmeters/mosquitto_pub.sh \"wmbusmeters/$METER_NAME\" \"$METER_JSON\"", "meter_shell": "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""}, "meters": [], "mqtt": {}}' | jq . > ${CONFIG_PATH}
fi

# Ensure meter_shell (first-telegram MQTT discovery) exists for pre-existing configs
if [ -z "$(jq -r '.conf.meter_shell // empty' ${CONFIG_PATH} 2>/dev/null)" ]; then
    bashio::log.info "Adding meter_shell to configuration ..."
    tmp_cfg=$(mktemp)
    jq '.conf.meter_shell = "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""' ${CONFIG_PATH} > ${tmp_cfg} && mv ${tmp_cfg} ${CONFIG_PATH}
fi

# MQTT discovery is now sent on demand. When the FIRST telegram from a
# meter arrives then this happens:
# wmbusmeters executes the "meter_shell" config setting which
# is send_meter_discovery.sh "$METER_JSON" "$METER_DRIVER"
# which takes as arguments:
#   the firs telegram with telegram details added
#   and the meter driver.
# These are used to generate a discovery json which is sent to HA.

if [ "${RESET_CONF}" = "yes" ]
then
    bashio::log.info "RESET CONFIG selected - reseting add-on configuration to default ..."
    echo '{"data_path": "/config/wmbusmeters", "enable_mqtt_discovery": "false", "conf": {"loglevel": "normal", "device": "auto:t1", "telegramdetails":"first", "donotprobe": "/dev/ttyAMA0", "logtelegrams": "false", "format": "json", "logfile": "/dev/stdout", "shell": "/wmbusmeters/mosquitto_pub.sh \"wmbusmeters/$METER_NAME\" \"$METER_JSON\"", "meter_shell": "send_meter_discovery.sh \"$METER_JSON\" \"$METER_DRIVER\""}, "meters": [], "mqtt": {}}' | jq . > ${CONFIG_PATH}
    bashio::addon.option "reset_config" "no"
    bashio::addon.restart
fi

CONFIG_DATA_PATH=$(bashio::jq "${CONFIG_PATH}" '.data_path')
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

# read each line of config file
while read -r line; do
    # split the line into parameter and values
    param="${line%=*}"
    values="${line#*=}"
    # check if values contain the delimiter ";"
    if [[ "$values" == *";"* ]]; then
        # split values into an array using ";" as the delimiter
        IFS=";" read -ra arr <<< "$values"
        # extract the first key from the parameter
        first_key="${param%=*}"
        # loop through the array and create separate key-value pairs
        for value in "${arr[@]}"; do
            echo "$first_key=$value"
        done
    else
        # if values do not contain ";", print the original key-value pair
        echo "$line"
    fi
done < $CONFIG_DATA_PATH/etc/wmbusmeters.conf > $CONFIG_DATA_PATH/etc/wmbusmeters.conf_tmp
mv $CONFIG_DATA_PATH/etc/wmbusmeters.conf_tmp $CONFIG_DATA_PATH/etc/wmbusmeters.conf

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

fi

chmod a+x /wmbusmeters/mosquitto_pub.sh

bashio::log.info "Running wmbusmeters ..."
if pgrep wmbusmeters > /dev/null; then
    pkill wmbusmeters
fi
/wmbusmeters/wmbusmeters --useconfig=$CONFIG_DATA_PATH
