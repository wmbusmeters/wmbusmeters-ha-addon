# Home Assistant Community Add-on: wmbusmeters (W-MBus to MQTT)

This add-on allows you to acquire utility meter readings **without** the vendors bridge or gateway as long as they support C1, T1 or S1 telegrams using the wireless mbus protocol (WMBUS).


## Installation

The installation of this add-on is pretty straightforward and not different in
comparison to installing any other community-driven Home Assistant add-on.

1. Navigate to Add-ons > Add-on Store > Repositories
1. Add https://github.com/wmbusmeters/wmbusmeters-ha-addon
1. Install Wmbusmeters
1. Enable "Show in sidebar"
1. Plug-in your radio receiver USB dongle
1. Start the addon container
1. In the log tab in the add-on, not in the sidebar, you should see all the W-Mbus telegrams that wmbusmeter is able to receive. <br> _If you don't see anything, check the logs carefully. <br> If you configure it late evening or in the night, please note the radio modules often send telegrams less frequently than in typical working hours or don't send them at all. <br> If your antenna is in a distance to the radio module, try to locate it closer._
1. You are ready to configure! Go to wmbusmeter in sidebar, add necessary configuration and save it. <br> _Once you configure your first meter, you will no longer see meter output in the log.  Check your MQTT server and make sure you set up the sensor, per the next step._
   **Note:** A meter requires four values, name, driver, id, and key
1. Finally, don't forget about adding the MQTT sensor into your Home Assistant.


## Configuration

Once the wmbusmeters is receiving the telegrams you need to configure your meter using `meters` section (see below) to pass the readings to MQTT topic.

#### Option: `wmbusmeters config location`

Path relative for add-on where wmbusmeters files are stored:
```
/logs/meter_readings/
/etc/wmbusmeters.conf
/etc/wmbusmeters.d/
```

#### Section: `wmbusmeters configuration`

Content of this section will be used as `wmbusmeters.conf`.
If two values for configuration parameter is needed, like:
```yaml
donotprobe: /dev/ttyAMA0
donotprobe: /dev/ttyUSB0
```
In web configuration interface it should be provided in one line using `;` delimiter between values, like: `donotprobe=/dev/ttyAMA0;/dev/ttyUSB0`

See [project README for more information][docs]

#### Section: `meters`

Specify your meters configuration parameters. The `driver` and `id` values can be read from the add-on logs after the initial start (with empty `meters` configuration). The `name` is your label for the meter and `key` is the encryption key to decrypt telegrams (if your meter use any).

See [project README for more information][docs]

#### Section: `Custom MQTT configuration`

By default it is not enabled and leverages the _Moquitto broker_ addon details provided by supervisor. However, you can specify the custom mqtt broker connection details here.


## Home Assistant integration

### MQTT discovery

"MQTT discovery" has three settings:

- **Disable**: no Home Assistant entities are created or updated; the meter data is still published to MQTT. Configure the entities yourself (see _Manual configuration_ below).
- **Automatic**: the add-on creates the Home Assistant entities itself. When the first telegram of a meter arrives after the add-on starts, the discovery is generated from that telegram and the meter driver: one entity per field of the telegram, with the unit, device class and state class that the driver describes. This is the behaviour of 3.1 and later. The `[test]` add-on is delivered with this setting, the `[edge]` and stable add-ons with _Disable_: turning it on there is your choice.
- **Manual**: the add-on publishes the discovery payloads from the templates in `<data path>/etc/mqtt_discovery/<driver>.json`, one file per driver, like the add-on did before 3.1. This is for entities that the generated discovery does not describe the way you need them, e.g. a flow sensor that needs `force_update: true` so that every telegram, including a repeated `0`, reaches Home Assistant (#2138).

A configuration that was written before this option existed keeps its setting: the old "Enable mqtt discovery" (`true`/`false`) becomes _Automatic_/_Disable_ on the first start after the update.

A meter whose driver has no template gets no discovery in the manual mode; the templates of the add-on are only a starting point. Existing templates are never overwritten: the add-on copies its own templates only when the file does not exist, so your edits survive an update. To go back to the bundled version of a template, delete the file in `<data path>/etc/mqtt_discovery` and restart the add-on.

The manual mode removes the retained discovery topics of this broker that the templates do not publish, so entities of deleted templates or meters do not stay in Home Assistant forever.

In the automatic mode:

- Status fields get a problem sensor, a text sensor with the status text, and one binary sensor per flag the driver knows. The flag sensors are disabled by default: enable the ones that matter to you. Their `info` attribute describes the flag.
- Discovery that is no longer published for a meter, e.g. for a field that a driver renamed, is removed when the meter's discovery is sent.
- A meter that uses a deprecated driver gets a "driver (deprecated, use ... before ...)" entity. Change `driver=` of the meter to the driver it names.
- Entities of meters that you removed from the configuration are not removed automatically; delete them in Home Assistant.

A status like `DRY ERROR_FLAGS_128` contains a bit that the driver does not describe yet (here bit value 128 of the `ERROR_FLAGS` lookup). If you know what it means for your meter, please tell the [wmbusmeters project](https://github.com/wmbusmeters/wmbusmeters/issues), so that the driver can describe it.

### Manual configuration

Without discovery, you need to tell Home Assistant how to extract the readings from the MQTT. You can add the following sensor definition into your `mqtt:` section of `configuration.yaml`.

```yaml
mqtt:
  sensor:
    - state_topic: "wmbusmeters/MainWater"
      json_attributes_topic: "wmbusmeters/MainWater"
      unit_of_measurement: m³
      value_template: "{{ value_json.total_m3 }}"
      name: Water usage
      icon: "mdi:gauge"
      state_class: total_increasing
      device_class: water
```

_Please note: 

- `MainWater` is the water meter name used in `meters` configuration._
- `device_class` is necessary to be adapt on your meters type (water, gas, etc.) [see here](https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes)

## Caveat

In case of wrong configuration, addon will stop working. To fix that - go to addon configuration tab, select `yes` for config reset, save and restart addon. After restart default configuration should be in place.

Or to edit config file manually - go to HassOS console and enter `login`, this will drop you to root shell. Enter `vi /mnt/data/supervisor/addons/data/[image_id]_wmbusmeters-ha-addon/options_custom.json`, fix error, save and start addon. [See here](https://developers.home-assistant.io/docs/operating-system/debugging/) how to get remote ssh access to supervisor in order to be able to edit file.

## Support

Got questions?

You have several options to get them answered:

- [Open an issue here][issue] in project GitHub
- The Home Assistant [Community Forum][forum].
- Join the [Reddit subreddit][reddit] in [/r/homeassistant][reddit]

## Authors & contributors

[Wmbusmeters contributors][contributors]

[contributors]: https://github.com/wmbusmeters/wmbusmeters-ha-addon/graphs/contributors
[forum]: https://community.home-assistant.io/c/home-assistant-os/25
[github]: https://github.com/wmbusmeters/wmbusmeters-ha-addon
[docs]: https://github.com/wmbusmeters/wmbusmeters
[issue]: https://github.com/wmbusmeters/wmbusmeters/issues
[reddit]: https://reddit.com/r/homeassistant
