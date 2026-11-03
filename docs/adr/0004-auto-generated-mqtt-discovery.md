# 0004 - MQTT discovery is generated from the driver sources

## Status

Accepted (pipeline in progress)

## Context

MQTT discovery configs were maintained as one hand written
`mqtt_discovery/*.json` per driver. That does not scale with driver
count and does not help Home Assistant Core or container users, who
cannot run the add-on (issue #927, 2023).

## Decision

Discovery messages are generated from the driver sources instead of
maintained by hand. The wmbusmeters daemon exposes telegram details,
`meter_shell` pipes them through `send_meter_discovery.sh` into
`to-ha-discovery.xslq`, and the resulting discovery json is sent the
first time a meter telegram arrives. Meter names are embedded directly
in the json. The discussion was moved from #927 into
wmbusmeters#2092, where driver field templates and status flag
decoding are being negotiated.

## Consequences

- New drivers produce discovery without a per-driver template;
  the hand written `mqtt_discovery/*.json` files become obsolete.
- Users on Home Assistant Core or in containers get the same discovery
  by running the same pipeline outside the add-on.

## Evidence

- `986dfbb` (2023-03-10) introduced the hand written templates.
- `e4009b4` (2026-09-21) sends the auto-generated discovery on the
  first telegram; `03d190a` (2026-09-22) embeds meter names in the
  json.
- `wmbusmeters-ha-addon-test/to-ha-discovery.xslq` and
  `send_meter_discovery.sh` in this repository.
- The meter side (`METER_DRIVER` env var for `meter_shell`) landed in
  the wmbusmeters repository (`c5c67170`, 2026-09-21).

## Alternatives considered

- Continue with per-driver json templates: rejected in #2092, it does
  not scale and cannot serve non-add-on installs.