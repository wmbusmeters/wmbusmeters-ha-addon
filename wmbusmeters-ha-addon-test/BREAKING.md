The meter drivers **izar**, **qheat** and **qwater** are deprecated and will be removed after **2026-12-01**. Their replacements are **izarv2**, **qheatv2** and **qwaterv2**.

If one of your meters uses an old driver, its device in Home Assistant now shows a "driver (deprecated, use ... before 2026-12-01)" entity. Change `driver=` in the meter configuration of this add-on to the new driver before that date.

Some field names differ in the new drivers, so some entities of these meters change: update dashboards and automations that use them, and remove the old entities that become unavailable.
