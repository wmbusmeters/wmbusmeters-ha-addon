# 0007 - The automatic discovery cleanup follows the driver, not the telegram

## Status

Accepted (wmbusmeters#2161, wmbusmeters#2163)

## Context

The generated discovery (0004) is sent when the first telegram of a meter
arrives after a start. To remove entities of fields that a driver renamed
or dropped, `send_meter_discovery.sh` then removed every retained
discovery of the meter that it did not publish (#108).

Some meters send several telegram formats: a qcaloric heat cost
allocator sends current/annual values and monthly storage 8 values,
Techem meters decoded by fhkvdataiii send a proprietary 0x80 and an OMS
0x08 telegram. The fields of one format are missing from the other. On
every restart where the other format arrived first, the cleanup removed
valid entities, with their names, areas and statistics.

Waiting for all formats before publishing (a WAITFOR marker in the
driver) was considered: the formats can be 20 to 51 hours apart, and
configurable meters (Kamstrup) do not have a known field set.

## Decision

The cleanup removes the discovery of a field only when the driver does
not define the field any more. The fields come from wmbusmeters itself,
`wmbusmeters --listfields=<driver>`:

- a field listed by the driver stays, also when this telegram lacks it;
  a template like `set_date_{storage_counter}` matches any number;
- an entity derived from a field (`<field>_text`, `<field>_<flag>` in
  lower case) stays with the field; not for the fields every meter has
  (`device_date_time` is not derived from `device`);
- when the driver's fields are not known (e.g. an own driver), nothing
  is removed.

wmbusmeters runs the metershell again when a telegram brings fields the
meter has not printed since the start (with the details of all fields
received so far), so the entities of every format are created as the
formats arrive.

## Consequences

- Restarts no longer remove entities of a telegram format that has not
  arrived yet; entities of renamed or dropped fields are still removed.
- A flag that a driver drops keeps its `<field>_<flag>` entity, since it
  looks derived from a field that still exists; the safe direction.
- Discovery does not wait for a meter's formats: the first telegram
  creates its entities, later formats add theirs.
- The cleanup depends on `--listfields` of the bundled wmbusmeters.

## Evidence

- wmbusmeters#2161 (qcaloric) and wmbusmeters#2163 (Techem fhkvdataiii),
  with telegrams of both formats; tested live on a local build: after a
  restart with the storage 8 telegram first, "keeping 6 discovery of
  test_qcaloric for fields of qcaloric that this telegram does not
  carry".
- `tests/test_workflows.py`: the cleanup cases (old upper case flag
  sensors, another telegram format, a renamed field, an unknown driver,
  other meters) with `--listfields` stubbed in its real output format.

## Alternatives considered

- No automatic cleanup at all: renamed driver fields would leave
  unavailable entities for every user.
- WAITFOR markers in the drivers: rejected for the long gaps between
  formats and for configurable meters, see Context.
- Accumulating the field set across restarts in the add-on: the driver
  definition is the authority on which fields exist, and it is already
  available.
