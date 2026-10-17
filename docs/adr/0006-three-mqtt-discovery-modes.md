# 0006 - MQTT discovery has three modes

## Status

Accepted (wmbusmeters#2138)

## Context

3.1 replaced the hand written `mqtt_discovery/*.json` templates with
discovery generated from the driver (0004). The "Enable mqtt discovery"
boolean, and with it the only way to choose, survived: on or off, with
the generated pipeline behind both. Users who had edited a template to
suit their meter - for example a flow sensor that needs
`force_update: true` so that a repeated `0` is not suppressed by Home
Assistant - lost it, because the generated discovery is republished at
every start of the add-on and overwrites the retained topic
(wmbusmeters#2138).

## Decision

The boolean becomes the three-way option `mqtt_discovery`:

- `disable`: nothing is published.
- `auto`: `send_meter_discovery.sh` generates and publishes the
  discovery from the first telegram of a meter and its driver. The
  default of `[test]`, the 3.1 behaviour.
- `manual`: `mqtt_discovery.sh` publishes the templates in
  `<data path>/etc/mqtt_discovery/<driver>.json` at start-up, the
  pre-3.1 pipeline. The bundled templates are copied in with `cp -n`, so
  a template the user edited is never overwritten.

An existing `enable_mqtt_discovery` is translated once on start
(`true` -> `auto`, `false` -> `disable`) and the key is dropped. The
mode lives in `options_custom.json` and is chosen in the add-on panel,
like the option it replaces.

## Consequences

- A user who needs a hand shaped entity can keep it across add-on
  updates again, and the generated pipeline stays the default.
- The mode has to be honoured in both pipelines: `send_meter_discovery.sh`
  publishes only in `auto`, `run.sh` calls `mqtt_discovery.sh` only in
  `manual`.
- `manual` keeps the pre-3.1 cleanup: retained discovery topics of the
  prefix that the templates of the configured meters do not publish are
  removed. Switching `auto` -> `manual` therefore removes the generated
  entities of drivers without a template.
- The templates stay unmaintained and only cover the drivers they were
  written for; DOCS.md says so and points at `auto` for everything else.
- The mode choice is per add-on, not per meter.

## Evidence

- wmbusmeters#2138: "set force_update: true for measurement fields
  that represent flow (...), or add an add-on option to control it.
  A way to keep a user-edited discovery from being overwritten would
  also help."
- `tests/test_workflows.py` covers the mode check in both pipelines, the
  defaults of the channels, the migration and the manual call in
  `run.sh`; the payloads of the restored templates are pinned by
  `tests/test_discovery_payloads.py`.

## Alternatives considered

- `force_update: true` for flow fields of the generated discovery:
  rejected, it inflates the Home Assistant database for every user to
  serve one use case, and it is exactly the kind of per-user shaping the
  manual mode exists for.
- A per-meter mode: rejected for now, the configuration already carries
  one discovery setting and a per-meter option is a larger change.
- Keeping the boolean and adding a second "use my templates" switch:
  rejected, mutually exclusive flags invite states that publish twice.
