# Heating Coil Controller

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/jozef-moravcik-homeassistant/heating-coil-controller)](https://github.com/jozef-moravcik-homeassistant/template-integration/releases)

Home Assistant integration designed for manual and automatic control of the power of heating coils in heating systems (boilers). The goal of automatic control is the efficient use of energy produced by the photovoltaic system, so that excess energy or the unsalable part of the energy can be consumed and used for heat production. This integration allows the coil power to accurately copy the current power curve of the produced energy and quickly respond to changes in the production of PV systems. A complicated power control strategy monitors the current power flow to the grid, power flow to the battery, monitors the power of solar radiation and other input data.

All releases 0.xx.xx are currently only BETA versions and are currently undergoing testing on several production systems.
After testing is complete, a new release series will be released starting with 1.xx.xx

## Features

- safe fuse against spiral overheating
- switch for manual and automatic power control
- several output power control strategies
- suitable even for very complicated infrastructure architectures
- controller allows control of an unlimited number of heating coils

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/jozef-moravcik-homeassistant/heating-coil-controller`
6. Select category: "Integration"
7. Click "Add"
8. Search for "Heating Coil Controller" and install it
9. Restart Home Assistant
10. Go to Settings → Devices & Services → Add Integration → Heating Coil Controller

### Manual Installation

1. Download the latest release
2. Copy the `custom_components/template_integration` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration → Heating Coil Controller

## Configuration

The integration is configured via the UI. You will need to provide:

- Configuration part 1
- Configuration part 2
- Configuration part 3
- Configuration part n

## Author

Jozef Moravčík (jozef.moravcik@moravcik.eu)

## License

MIT License - see [LICENSE](LICENSE) file
