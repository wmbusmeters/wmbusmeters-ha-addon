3.0.0.226
The meter drivers **izar**, **qheat** and **qwater** are deprecated. Their replacements are **izarv2**, **qheatv2** and **qwaterv2**. The old drivers keep working for now; they are planned to be removed in a release after **2026-12-01**. Nothing changes automatically on that date.

If one of your meters uses an old driver, its device in Home Assistant now shows a "driver (deprecated, use ... before 2026-12-01)" entity. Change `driver=` in the meter configuration of this add-on to the new driver.

Some field names differ in the new drivers, so some entities of these meters change: update dashboards and automations that use them, and remove the old entities that become unavailable.
