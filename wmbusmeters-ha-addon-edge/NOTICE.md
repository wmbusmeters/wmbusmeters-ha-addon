3.0.0.230
**MQTT discovery is now generated from the meter data** instead of fixed files for a few drivers. It works for every driver and creates more entities, with units and classes from the driver.

- The discovery of a meter is sent when its first telegram arrives after the add-on starts, no longer at start for all configured meters. "Enable mqtt discovery" still turns it on or off.
- Entities of fields that keep their name keep their history.
- Some entities change: the flag sensors are now named in lower case (e.g. `status_low_battery_level` instead of `status_LOW_BATTERY_LEVEL`) and are disabled by default, so enable the ones you need again; a few fields were renamed in the drivers since the fixed files were written (e.g. amiplus `device_date_time` is now `device_datetime`). The old entities are removed when the meter's discovery is sent; update dashboards and automations that used them.
- Own discovery templates in `<data path>/etc/mqtt_discovery` are no longer used.
- Entities of meters removed from the configuration are no longer removed automatically; delete them in Home Assistant.

See the add-on documentation, section "MQTT discovery".
