# 0006 - MQTT discovery has three modes, per meter

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

Bringing the per-driver templates back was the first answer. In review
it was rejected: they would have to be maintained for every driver, and
they only covered the drivers they were written for.

## Decision

The boolean becomes the three-way option `mqtt_discovery`:

- `disable`: nothing is published; the meter data still goes to MQTT.
- `auto`: `send_meter_discovery.sh` generates and publishes the
  discovery from the telegrams of a meter and its driver, the 3.1
  behaviour. The default of `[test]`.
- `manual`: a configuration per meter, applied in the panel, is
  published by `mqtt_discovery.sh` at start-up.

The option is the default of every meter. A meter may carry its own
`mqtt_discovery` key (chosen in the panel; "Default" leaves it out),
which wins. `run.sh` keeps the key out of the wmbusmeters meter file.

The manual configuration is made with the generator, not with
templates: `send_meter_discovery.sh` keeps the generated discovery of
every meter in `/data/discovery/generated/<id>.json`, in every mode and
merged across restarts. In the panel a draft is generated from it,
downloaded, edited, uploaded and applied. Apply shows what the draft
adds, changes and removes, publishes it, only then removes the discovery
of the meter that the draft does not hold, stores it as
`/data/discovery/applied/<id>.json` and sets the meter to `manual`. The
bundled templates are removed.

An existing `enable_mqtt_discovery` is translated once on start
(`true` -> `auto`, `false` -> `disable`) and the key is dropped.

## Consequences

- A hand shaped entity survives add-on updates and restarts: only an
  Apply in the panel changes an applied configuration.
- Nothing to maintain per driver: the manual configuration starts from
  the same generator as `auto`, for every driver.
- Two meters with the same driver can have different configurations,
  because the files belong to the meter id. A meter with a wildcard id
  cannot have one.
- Topics, unique ids and the device of a manual configuration are those
  of the generated discovery, so switching between `auto` and `manual`
  keeps the entities and their history.
- The mode has to be honoured in both pipelines: `send_meter_discovery.sh`
  publishes only for `auto` meters, `mqtt_discovery.sh` only for
  `manual` meters. A `manual` meter without an applied configuration
  publishes nothing and keeps the discovery it has.
- `manual` removes the retained discovery of a meter that is not in the
  configuration any more; the discovery of `auto` and `disable` meters
  is left alone.
- A newer add-on may generate more or better entities; a manual meter
  gets them only when the user generates and applies a new draft.

## Evidence

- wmbusmeters#2138: "set force_update: true for measurement fields
  that represent flow (...), or add an add-on option to control it.
  A way to keep a user-edited discovery from being overwritten would
  also help."
- Review of wmbusmeters-ha-addon#114: maintaining the old json discovery
  files for every driver is not wanted.
- `tests/test_workflows.py` covers the mode checks of both pipelines,
  the defaults of the channels, the migration, the per-meter modes, the
  discovery cache, `rootfs/flask/discovery_files.py` (ids, validation,
  placeholders, preview), the batch publish helper, the manual pipeline
  with applied files and the panel.

## Alternatives considered

- `force_update: true` for flow fields of the generated discovery:
  rejected, it inflates the Home Assistant database for every user to
  serve one use case, and it is exactly the kind of per-user shaping the
  manual mode exists for.
- Per-driver templates bundled with the add-on: rejected in review, see
  Context.
- An overrides file merged into the generated discovery (only the keys
  the user changes): smaller, but it cannot remove entities and it is
  harder to review than the complete configuration that Apply previews.
- Keeping the boolean and adding a second "use my templates" switch:
  rejected, mutually exclusive flags invite states that publish twice.
