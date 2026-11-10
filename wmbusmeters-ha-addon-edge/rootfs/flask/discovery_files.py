"""MQTT discovery files of the "manual" mode, one set per meter.

<dir>/generated/<id>.json  the discovery that the generator made from the
                           telegrams of the meter (send_meter_discovery.sh
                           writes it in every mode, see DOCS.md)
<dir>/drafts/<id>.json     a draft: generated, uploaded or edited, never
                           published by itself
<dir>/applied/<id>.json    the configuration that "Apply as manual" published;
                           mqtt_discovery.sh publishes it again at start-up

A file maps an attribute to {"component": ..., "discovery_payload": {...}}, the
format of the generator and of the templates of the add-on before 3.1. The
placeholders {name}, {id}, {driver} and {attribute} are replaced on publishing.
"""

import json
import os
import re
import tempfile

KINDS = ("generated", "drafts", "applied")

METER_ID_RE = re.compile(r"^[0-9A-Za-z]{1,16}$")
ATTRIBUTE_RE = re.compile(r"^[A-Za-z0-9_]+$")
COMPONENT_RE = re.compile(r"^[a-z_]+$")


def discovery_dir():
    return os.environ.get("WMBUSMETERS_DISCOVERY_DIR", "/data/discovery")


def valid_meter_id(meter_id):
    """Only a concrete meter id has its own files; a wildcard id does not."""
    return isinstance(meter_id, str) and METER_ID_RE.match(meter_id) is not None


def file_path(kind, meter_id):
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if not valid_meter_id(meter_id):
        raise ValueError(f"not a meter id: {meter_id!r}")
    return os.path.join(discovery_dir(), kind, f"{meter_id}.json")


def load(kind, meter_id):
    """The file as a dict, or None when there is none (or it is not valid json)."""
    try:
        with open(file_path(kind, meter_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def modified(kind, meter_id):
    """Unix time of the file, or None."""
    try:
        return os.path.getmtime(file_path(kind, meter_id))
    except OSError:
        return None


def save(kind, meter_id, data):
    """Write atomically, so that a reader never sees half a file."""
    path = file_path(kind, meter_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def validate(data):
    """The problems of a discovery file, an empty list when it can be published."""
    if not isinstance(data, dict):
        return ["The file must hold a JSON object of attributes."]
    if not data:
        return ["The file has no attributes."]
    errors = []
    for attribute, entry in data.items():
        if not ATTRIBUTE_RE.match(attribute):
            errors.append(f"{attribute!r}: an attribute name may only use letters, digits and _.")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{attribute}: must be an object with component and discovery_payload.")
            continue
        component = entry.get("component")
        if not isinstance(component, str) or not COMPONENT_RE.match(component):
            errors.append(f"{attribute}: component must be a Home Assistant MQTT component, e.g. sensor.")
        if not isinstance(entry.get("discovery_payload"), dict):
            errors.append(f"{attribute}: discovery_payload must be an object.")
    return errors


def substitute(text, values):
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def topics(data, meter_id, name, driver, prefix="homeassistant"):
    """topic -> payload string, as published; the same topics as the generated discovery."""
    out = {}
    for attribute, entry in (data or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get("discovery_payload"), dict):
            continue
        component = entry.get("component")
        if not isinstance(component, str) or not COMPONENT_RE.match(component):
            continue
        values = {"name": name, "id": meter_id, "driver": driver, "attribute": attribute}
        payload = substitute(json.dumps(entry["discovery_payload"], separators=(",", ":"), sort_keys=True), values)
        out[f"{prefix}/{component}/wmbusmeters/{meter_id}_{attribute}/config"] = payload
    return out


def meter_topics(retained, meter_id):
    """The retained discovery topics that belong to this meter."""
    marker = f"/wmbusmeters/{meter_id}_"
    return sorted(t for t in retained if marker in t and t.endswith("/config"))


def preview(new, old, retained, meter_id, name, driver, prefix="homeassistant"):
    """What applying `new` does. `old` is what was published last for this meter
    (the applied file, or the generated one), `retained` the discovery topics in
    the broker."""
    new_topics = topics(new, meter_id, name, driver, prefix)
    old_topics = topics(old, meter_id, name, driver, prefix)
    in_broker = set(meter_topics(retained, meter_id))
    added, changed, unchanged = [], [], []
    for topic, payload in sorted(new_topics.items()):
        if topic not in in_broker and topic not in old_topics:
            added.append(topic)
        elif topic in old_topics and old_topics[topic] == payload:
            unchanged.append(topic)
        else:
            changed.append(topic)
    removed = sorted(t for t in in_broker if t not in new_topics)
    return {"added": added, "changed": changed, "unchanged": unchanged, "removed": removed}


def find_meter(config, meter_id):
    """The meter of the add-on configuration with this id, or None."""
    for meter in (config or {}).get("meters", []) or []:
        if isinstance(meter, dict) and str(meter.get("id", "")) == meter_id:
            return meter
    return None


def driver_name(meter):
    """The driver of a meter entry, without the options after ':'."""
    return str((meter or {}).get("driver", "")).split(":", 1)[0]
