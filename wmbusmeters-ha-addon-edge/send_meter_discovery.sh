#!/bin/bash
# ==============================================================================
# Invoked by wmbusmeters via the "metershell" config when the FIRST telegram
# from a meter arrives, and again when a later telegram brings fields that the
# meter has not sent before (a meter can send several telegram formats).
#
#   wmbusmeters.conf: metershell=send_meter_discovery.sh "$METER_JSON" "$METER_DRIVER"
#
# Extracts the driver name from the first telegram's JSON, e.g.
#   { "driver":"amiplus", "id":"...", ... }
# and publishes the HA MQTT discovery payload(s) generated from that telegram
# and the driver - only this driver, nothing else. This is the "auto" MQTT
# discovery mode; in "manual" mode mqtt_discovery.sh publishes the configuration
# applied in the panel at start-up instead, and "disable" publishes nothing at
# all. In every mode the generated discovery is kept in
# /data/discovery/generated/<id>.json, the panel makes a manual draft from it.
# The add-on's "MQTT discovery" setting is the default of every meter, a meter
# may carry its own "mqtt_discovery" key and then that one wins. See the
# "MQTT discovery" section of DOCS.md.
#
# Exits cleanly (0) if anything is missing, wmbusmeters must never be blocked.
# ==============================================================================

# --- Log lines ----------------------------------------------------------------
# wmbusmeters copies these lines into the add-on log. They look like the
# add-on's own lines (bashio::log.info): a time stamp and green.
# BEGIN log
log_info() {
    printf '\033[32m[%s] INFO: %s\033[0m\n' "$(date +%H:%M:%S)" "$*" >&2
}
# END log

METER_JSON="${1:-}"
if [ -z "$METER_JSON" ]; then
    exit 0
fi

METER_DRIVER="${2:-}"
if [ -z "$METER_DRIVER" ]; then
    exit 0
fi

TELEGRAM_FILE=$(mktemp)
DRIVER_FILE=$(mktemp)
DISCOVERY_FILE=$(mktemp)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

printf '%s\n' "$METER_JSON" > $TELEGRAM_FILE
printf '%s\n' "$METER_DRIVER" > $DRIVER_FILE

trap 'rm -f "$TELEGRAM_FILE" "$DRIVER_FILE" "$DISCOVERY_FILE"' EXIT

# --- Resolve driver / id / name from the first telegram ----------------------
DRIVER=$(printf '%s' "$METER_JSON" | jq -r '.driver // empty' 2>/dev/null)
if [ -z "$DRIVER" ]; then
    log_info "metershell: no driver in telegram, ignoring"
    exit 0
fi

ID=$(printf '%s' "$METER_JSON" | jq -r '.id // empty' 2>/dev/null)
NAME="${METER_NAME:-}"
if [ -z "$NAME" ]; then
    NAME=$(printf '%s' "$METER_JSON" | jq -r '.name // empty' 2>/dev/null)
fi

if [ -z "$ID" ] || [ -z "$NAME" ]; then
    log_info "metershell: telegram missing meter id or name, ignoring"
    exit 0
fi

# --- Generate discovery json using to-ha-transform.xslq

xmq $TELEGRAM_FILE \
    transform --stringparam="drv=$DRIVER_FILE" $SCRIPT_DIR/to-ha-discovery.xslq \
    to-json | jq --sort-keys > $DISCOVERY_FILE

if [ "$3" != "" ]
then
    cp $DISCOVERY_FILE $3
    exit 0
fi

# --- Keep the generated discovery of the meter, in every mode -------------------
# The panel makes a draft of the "manual" mode from it. The new discovery is
# merged into the kept one (an attribute that is generated again replaces the
# old one), so a meter that sends several telegram formats keeps the entities
# of a format that has not arrived since the last start (wmbusmeters#2161).
# BEGIN discovery cache
DISCOVERY_DIR="${WMBUSMETERS_DISCOVERY_DIR:-/data/discovery}"
case "$ID" in
    *[!0-9A-Za-z]*) ;;
    *)
        if [ -s "$DISCOVERY_FILE" ] && mkdir -p "$DISCOVERY_DIR/generated" 2>/dev/null; then
            CACHE="$DISCOVERY_DIR/generated/$ID.json"
            if [ ! -s "$CACHE" ] || ! jq -s '.[0] + .[1]' "$CACHE" "$DISCOVERY_FILE" > "$CACHE.tmp" 2>/dev/null; then
                cp "$DISCOVERY_FILE" "$CACHE.tmp"
            fi
            mv "$CACHE.tmp" "$CACHE"
        fi
        ;;
esac
# END discovery cache

# --- "MQTT discovery" mode of this meter (auto/manual/disable) ----------------
# Generating from the telegram and the driver is the "auto" mode only. The
# add-on's "MQTT discovery" setting is the default of every meter, a meter may
# carry its own "mqtt_discovery" key and then that one wins (the panel shows the
# choice under every meter, see DOCS.md).
# BEGIN discovery mode
CONFIG_PATH=/data/options_custom.json
DEFAULT_MODE="$(jq -r '.mqtt_discovery // empty' "$CONFIG_PATH" 2>/dev/null)"
OWN_MODE="$(jq -r --arg name "$NAME" --arg id "$ID" \
    '[.meters[]? | select(.name == $name or .id == $id) | .mqtt_discovery // empty] | first // ""' \
    "$CONFIG_PATH" 2>/dev/null)"
MODE="$DEFAULT_MODE"
SOURCE="the add-on setting"
case "$OWN_MODE" in
    auto|manual|disable) MODE="$OWN_MODE"; SOURCE="the setting of the meter" ;;
esac
if [ "$MODE" != "auto" ]; then
    case "$MODE" in
        manual)  log_info "metershell: MQTT discovery is 'manual' (${SOURCE}): the configuration applied in the panel is published at start-up, no generated discovery for $NAME" ;;
        disable) log_info "metershell: MQTT discovery is 'disable' (${SOURCE}): publishing nothing for $NAME" ;;
        *)       log_info "metershell: MQTT discovery mode is '${MODE}' (${SOURCE}), not one of auto, manual, disable: publishing nothing for $NAME" ;;
    esac
    exit 0
fi
# END discovery mode

# --- MQTT publish helper (generated by run.sh, holds broker + credentials) ---
PUB=/wmbusmeters/mosquitto_pub.sh
if [ ! -x "$PUB" ]; then
    log_info "metershell: no MQTT broker configured, skipping discovery"
    exit 0
fi

# --- Publish discovery for this driver's attributes --------------------------
PUBLISHED=""
COUNT=0
log_info "metershell: MQTT discovery (auto) for $NAME ($DRIVER) ..."
for attribute in $(jq -r 'keys[]' "$DISCOVERY_FILE" 2>/dev/null)
do
    component=$(jq -r ".${attribute}.component // empty" "$DISCOVERY_FILE" 2>/dev/null)
    if [ -z "$component" ]; then
        continue
    fi

    topic="homeassistant/${component}/wmbusmeters/${ID}_${attribute}/config"

    payload=$(jq -c ".${attribute}.discovery_payload" "$DISCOVERY_FILE" 2>/dev/null)
    if [ -z "$payload" ]; then
        continue
    fi

    # substitute placeholders
    payload="${payload//\{name\}/${NAME}}"
    payload="${payload//\{id\}/${ID}}"
    payload="${payload//\{driver\}/${DRIVER}}"
    payload="${payload//\{attribute\}/${attribute}}"

    "$PUB" "$topic" "$payload"
    log_info "  Add/update topic: $topic"
    PUBLISHED="$PUBLISHED $topic"
    COUNT=$((COUNT + 1))
done

ENTITY="entities"
[ "$COUNT" = "1" ] && ENTITY="entity"
log_info "metershell: MQTT discovery (auto): published $COUNT $ENTITY for $NAME ($DRIVER)"

# --- Remove the discovery of fields that the driver does not define any more --
# E.g. entities of fields that the driver renamed or dropped, which HA would
# otherwise keep as unavailable entities forever. A field that is only missing
# from this telegram stays: a meter can send several telegram formats, and the
# discovery of a format that did not arrive yet must survive a restart
# (wmbusmeters#2161, wmbusmeters#2163).
# BEGIN discovery cleanup
RETAINED=/wmbusmeters/mosquitto_retained.sh
WMBUSMETERS=/wmbusmeters/wmbusmeters
if [ -x "$RETAINED" ] && [ -n "$PUBLISHED" ]; then
    # The fields the driver can print, from wmbusmeters itself. A name like
    # set_date_{storage_counter} stands for set_date_1, set_date_2 ...
    FIELDS=$("$WMBUSMETERS" --listfields="$DRIVER" 2>/dev/null | awk '{print $1}' | grep -E '^[a-z0-9_{}]+$')
    if [ -z "$FIELDS" ]; then
        log_info "metershell: the fields of driver $DRIVER are not known, keeping all discovery of $NAME"
    else
        EXACT=$(printf '%s\n' $FIELDS | sed 's/{[^}]*}/[0-9]+/g' | paste -sd '|')
        # Entities derived from a field are named <field>_text and <field>_<flag>,
        # in lower case. Not for the fields that every meter has: device_date_time
        # is not derived from device.
        PREFIX=$(printf '%s\n' $FIELDS | grep -v -x -E 'id|name|media|meter|device|rssi_dbm|timestamp(_[a-z]+)?' | sed 's/{[^}]*}/[0-9]+/g' | paste -sd '|')
        KEPT=0
        for old in $("$RETAINED" list "homeassistant/+/wmbusmeters/+/config" 2>/dev/null)
        do
            case "$old" in
                */wmbusmeters/"${ID}"_*/config) ;;
                *) continue ;;
            esac
            case " $PUBLISHED " in
                *" $old "*) continue ;;
            esac
            attribute="${old#*/wmbusmeters/"${ID}"_}"
            attribute="${attribute%/config}"
            if [[ "$attribute" =~ ^(${EXACT})$ ]] || { [ -n "$PREFIX" ] && [[ "$attribute" =~ ^(${PREFIX})_[a-z0-9_]+$ ]]; }; then
                KEPT=$((KEPT + 1))
                continue
            fi
            log_info "metershell: removing discovery of a field that driver $DRIVER does not define: $old"
            "$RETAINED" clear "$old"
        done
        if [ "$KEPT" -gt 0 ]; then
            log_info "metershell: keeping $KEPT discovery of $NAME for fields of $DRIVER that this telegram does not carry"
        fi
    fi
fi
# END discovery cleanup

exit 0
