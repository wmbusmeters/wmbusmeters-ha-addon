#!/usr/bin/env python3
# Copyright (C) 2026 bartman081523 (gpl-3.0-or-later)
"""Regression test for the MQTT discovery payloads checked in under
wmbusmeters-ha-addon-test/test/ (issue #2092).

HA rejects discovery payloads whose device_class / state_class /
unit_of_measurement / name / device.* values are empty {} objects --
exactly what the old to-ha-discovery.xslq emitted when a lookup failed.
PR #97 fixed the generation; this test pins the checked-in payloads so a
regeneration that reintroduces the failure modes fails CI:

  - an empty {} anywhere in a discovery_payload (the #2092 signature)
  - an empty string where HA expects a real string
  - a state_class on a date/timestamp entity
  - a date-like entity without device_class
  - a text status published as a numeric sensor instead of a binary_sensor
  - a cumulative total_/target_ sensor without state_class total/total_increasing

Pure stdlib, no Home Assistant installation required. Optional arguments
are explicit payload files; by default every *.json under
wmbusmeters-ha-addon-test/test/ is validated, except telegram.json which
is meter output, not discovery.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST = ROOT / "wmbusmeters-ha-addon-test" / "test"

FAILURES = []


def fail(entity, msg):
    FAILURES.append(f"{entity}: {msg}")
    print(f"FAIL {entity}: {msg}")


def ok(entity, msg):
    print(f"OK   {entity}: {msg}")


def walk_empties(obj, path=""):
    """Yield the path of every empty {} dict inside obj."""
    if isinstance(obj, dict):
        if not obj:
            yield path or "<root>"
        else:
            for k, v in obj.items():
                yield from walk_empties(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_empties(v, f"{path}[{i}]")


# Keys HA needs as real strings; an empty string is as broken as {}.
STRING_KEYS = ("device_class", "state_class", "unit_of_measurement", "name",
               "entity_category", "icon", "unique_id", "value_template",
               "json_attributes_template", "state_topic", "json_attributes_topic")
DEVICE_STRING_KEYS = ("manufacturer", "model", "name", "hw_version",
                      "serial_number")


def check_entity(name, entity):
    component = entity.get("component")
    payload = entity.get("discovery_payload") or {}
    if component not in ("sensor", "binary_sensor"):
        # Other components are not covered by the #2092 failure modes.
        return

    problems = []

    for path in walk_empties(payload):
        problems.append(f"empty {{}} at {path} -- failed xslq lookup, "
                        f"HA rejects the payload (issue #2092)")
    for key in STRING_KEYS:
        if payload.get(key) == "":
            problems.append(f"'{key}' is an empty string")
    device = payload.get("device") or {}
    for key in DEVICE_STRING_KEYS:
        if device.get(key) == "":
            problems.append(f"device.{key} is an empty string")

    device_class = payload.get("device_class")
    state_class = payload.get("state_class")

    if device_class in ("date", "timestamp") and state_class is not None:
        problems.append(f"date/timestamp entity must not carry "
                        f"state_class ({state_class!r})")
    if (name.endswith("_date") or name == "timestamp") and not device_class:
        problems.append("date-like entity without device_class "
                        "(the 'PonitInTime' typo class of #2092)")

    if name in ("status", "current_status") or name.startswith("status_"):
        if component != "binary_sensor":
            problems.append(f"text status published as {component}; "
                            f"expected binary_sensor with a device_class")
        elif not device_class:
            problems.append("binary_sensor status without a device_class")

    if (name.startswith(("total_", "target_")) and component == "sensor"
            and device_class not in ("date", "timestamp")
            and state_class not in ("total", "total_increasing")):
        problems.append(f"cumulative sensor with state_class "
                        f"{state_class!r}; expected total/total_increasing")

    if problems:
        for msg in problems:
            fail(name, msg)
    else:
        ok(name, f"{component}")


def check_file(path):
    try:
        data = json.loads(Path(path).read_text())
    except Exception as e:
        fail(Path(path).name, f"unreadable ({e})")
        return
    entities = {k: v for k, v in data.items()
                if isinstance(v, dict) and "component" in v}
    if not entities:
        fail(Path(path).name, "no discovery entities (component/"
             "discovery_payload) found -- if this is not a discovery "
             "payload, name it telegram.json or extend the skip rule")
        return
    print(f"--- {Path(path).name}: {len(entities)} entities")
    for name, entity in sorted(entities.items()):
        check_entity(name, entity)


def main():
    files = sys.argv[1:]
    if not files:
        files = sorted(str(p) for p in TEST.glob("*/*.json")
                       if p.name != "telegram.json")
    if not files:
        print(f"FAIL no payload files found under {TEST}")
        return 1
    for f in files:
        check_file(f)
    print(f"\n{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())