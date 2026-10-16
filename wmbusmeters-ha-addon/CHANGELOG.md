## 3.1.0 
- Updated to version [3.1.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
- **Breaking change:**
  **MQTT discovery is now generated from the meter data** instead of fixed files for a few drivers. It works for every driver and creates more entities, with units and classes from the driver.
  
  - The discovery of a meter is sent when its first telegram arrives after the add-on starts, no longer at start for all configured meters. "Enable mqtt discovery" still turns it on or off.
  - Entities of fields that keep their name keep their history.
  - Some entities change: the flag sensors are now named in lower case (e.g. `status_low_battery_level` instead of `status_LOW_BATTERY_LEVEL`) and are disabled by default, so enable the ones you need again; a few fields were renamed in the drivers since the fixed files were written (e.g. amiplus `device_date_time` is now `device_datetime`). The old entities are removed when the meter's discovery is sent; update dashboards and automations that used them.
  - Own discovery templates in `<data path>/etc/mqtt_discovery` are no longer used.
  - Entities of meters removed from the configuration are no longer removed automatically; delete them in Home Assistant.
  
  See the add-on documentation, section "MQTT discovery".
## 3.0.0-RC1 
- Updated to version [3.0.0-RC1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 2.0.0 
- Updated to version [2.0.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 2.0.0-RC1 
- Updated to version [2.0.0-RC1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.20.0 
- Updated to version [1.20.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.19.0 
- Updated to version [1.19.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.18.0-RC1 
- Updated to version [1.18.0-RC1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.17.1 
- Updated to version [1.17.1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.16.1 
- Updated to version [1.16.1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.15.0 
- Updated to version [1.15.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.14.0 
- Updated to version [1.14.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.13.1 
- Updated to version [1.13.1](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
## 1.12.0 
- Updated to version [1.12.0](https://github.com/wmbusmeters/wmbusmeters/blob/master/CHANGES)
##