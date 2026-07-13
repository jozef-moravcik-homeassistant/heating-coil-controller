# Heating Coil Controller

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/jozef-moravcik-homeassistant/heating-coil-controller)](https://github.com/jozef-moravcik-homeassistant/heating-coil-controller/releases)
[![License](https://img.shields.io/github/license/jozef-moravcik-homeassistant/heating-coil-controller.svg)](LICENSE)

## v0.01.05
### Fixes:
- Some text keys and some translation texts have been updated.

## v0.01.04
### Fixes:
- The display of integer number entities number.heating_coil_n_max_power has changed, the decimal number is no longer displayed.

## v0.01.03

# New features
- added a safe fuse against spiral overheating
- added new switch for automatic / manual power control
- added new strategy "STRATEGY 2" for power control based only on data from the electricity meter and solar sensor. This strategy is intended for systems without a battery, allowing the export of surpluses to the grid.

# Fixes:
- In manual mode, after changing the power, this change was reflected on the output with a delay, because even in manual mode, the output value was recalculated within the set time interval, which is intended for automatic power control. From this version, in manual mode, the power change is reflected on the output immediately.

## v0.01.02

# Changes
- Icon has been added
- some minor bugs have been fixed
