# wmbusmeters Home Assistant Add-on
This add-on allows you to acquire utility meter readings without the vendors bridge or gateway as long as they support C1, T1 or S1 telegrams using the wireless mbus protocol (WMBUS).

# Releases
This repository contains two versions of add-on:

Edge - that will contain latest changes from both wmbusmeters and add-on changes. This can be used by users that want or need latest changes in wmbusmeters repository.

Stable - will contain wmbusmeters stable release combained with add-on changes on that time. 

# Upgrade from older add-on versions

1. Manualy backup existing configs and uninstall wmbusmeters addon
1. Navigate to Add-ons > Add-on Store > Repositories
1. Remove https://github.com/weetmuts/wmbusmeters and add https://github.com/wmbusmeters/wmbusmeters-ha-addon
1. Navigate to Add-ons > Add-on Store and press "Ctrl+R" or reload page in other way
1. Install wmbusmeters add-on
1. Enable "Show in sidebar"
1. Start the addon container
1. Navigate to wmbusmeter in sidebar, manualy restore configuration and save it.

# Installation
Simply click this button:

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fwmbusmeters%2Fwmbusmeters-ha-addon)

or to install manually simply add wmbusmeters Home Assistant Add-on repository:

```
https://github.com/wmbusmeters/wmbusmeters-ha-addon
```
Please refer to the wmbusmeters [documentation](https://github.com/wmbusmeters/wmbusmeters/blob/master/README.md) and add-on [documentation](https://github.com/wmbusmeters/wmbusmeters-ha-addon/blob/main/wmbusmeters-ha-addon-edge/DOCS.md) for detailed information on how to install and configure the Add-on.

## Issues
Issues are being tracked centrally, so if you find any issues with the add-on, please check the [central issue tracker](https://github.com/wmbusmeters/wmbusmeters/issues) for similar issues and open new if needed. 

Feel free to [create a PR](CONTRIBUTING.md) for fixes and enhancements here.
