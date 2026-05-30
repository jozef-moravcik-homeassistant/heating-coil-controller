# Heating Coil Controller

A custom Home Assistant integration for intelligent power management of electric heating coils (water heaters, boilers, etc.). It maximises self-consumption of locally generated photovoltaic energy by continuously adjusting coil output power based on real-time PV production, battery storage state, and grid power flow. Instead of exporting surplus solar power to the grid at a low feed-in tariff, the system diverts it into heating, while at the same time protecting battery state-of-charge and respecting grid import/export limits.

Key capabilities:
- Adjusts coil output power in fine increments (1 – 100 %) via an analogue DAC signal (0-10 V, 0-20 mA, 4-20 mA)
- Coordinates multiple coils so their combined power never exceeds a configured total-power limit
- Responds to fast solar-production drops with an immediate protective ramp-down
- Communicates with hardware via Modbus (TCP, USB/serial, UDP)
- Fully UI-configured through Home Assistant config/options flows — no YAML required

---

## Requirements

- Home Assistant 2024.1 or newer
- At least one Modbus DAC device (supported: **AMVOL08**, **DACI4_I4-20**) connected via TCP, USB serial, or UDP
- SSR Relay for output power
- Power sensors exposed as Home Assistant entities (PV production, grid power, battery power, battery SOC, etc.)

---

## Installation

### HACS

1. Open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/jozef-moravcik-homeassistant/heating-coil-controller` as an **Integration** repository.
3. Search for *Heating Coil Controller* and click **Download**.
4. Restart Home Assistant.

---

## Configuration overview

The integration uses **three device types**. You create them in order — General first, then at least one Modbus Node, and finally one or more Heating Coils.

Navigate to **Settings → Devices & Services → Add Integration → Heating Coil Controller** to add each device.

---

### 1. General

Create **exactly one** General device. It holds system-wide parameters shared by all heating coils:

| Parameter | Description |
|---|---|
| **Device name** | Friendly name (e.g. `General`) |
| **Total power limit (kW)** | Maximum combined output power of all coils. The system will not allow the sum to exceed this value. |

The General device also exposes two buttons — *Turn OFF all* and *Turn ON all* — and a sensor that shows the current total power consumption of all coils.

---

### 2. Modbus Node

Create one Modbus Node device for each physical Modbus connection (TCP/IP, USB serial, or UDP). A single Modbus Node can serve multiple heating coils connected to the same physical device.

| Parameter | Description |
|---|---|
| **Device name** | Friendly name (e.g. `Node TCP 1`) |
| **Connection type** | `TCP`, `USB`, `UDP`, or *Existing node* (reuse a previously configured node) |
| **Host / Port** | For TCP/UDP: IP address and port (default 502) |
| **Serial port** | For USB: device path (e.g. `/dev/ttyUSB0`) |
| **Baud rate, data bits, stop bits, parity** | Serial port parameters (for USB connections) |
| **Modbus device ID** | Modbus slave address of the DAC hardware (1 – 254) |
| **DAC type** | Hardware model: `amvol08` (8 × 0-10 V) or `daci4_i420` (4 × 4-20 mA) |

A Modbus Node also provides an *Error code* sensor that reports communication faults as a bitmask.

---

### 3. Heating Coil

Create one Heating Coil device for each physical coil (or one *virtual* coil to group several coils together — see below). You can add an unlimited number of heating coils.

#### Basic settings

| Parameter | Description |
|---|---|
| **Device name** | Friendly name (e.g. `Coil 1`) |
| **Modbus Node** | Select which Modbus Node this coil is connected to |
| **DAC output port** | Output channel number on the DAC device (1 – 32) |
| **DAC output type** | Signal type: `0-10V`, `0-20mA`, or `4-20mA` |
| **Nominal coil power (kW)** | Rated electrical power of the heating element at 100 % output |
| **Zero-power point (%)** | DAC % value below which the coil produces no heat (calibration) |
| **Maximum-power point (%)** | DAC % value that corresponds to 100 % coil power (calibration) |
| **Gamma correction** | Non-linearity correction for the heating element response curve (-50 to +50) |

#### Output power limit entity

Each coil automatically creates a **Max Power** number entity (0 – 100 %). This acts as a real-time ceiling on the coil's output regardless of the automation strategy. Set it to 0 to block the coil completely; leave it at 100 for full automation control.

#### Master / Slave grouping

To control several physical coils in sync, designate one as **Master** and the others as **Slaves**:

- On each slave coil, set **Master Heating Coil** to the entry ID of the master.
- Slaves automatically inherit the master's output percentage and synchronise their ON/OFF state and Max Power setting.

#### Virtual Heating Coil

Enable **Virtual Heating Coil** to create a logical coil that has no direct Modbus output of its own. Instead, it runs the power automation algorithm and distributes the resulting output percentage to all slave coils assigned to it. Use this to treat several physical coils as a single unit in the automation logic.

---

## Power control strategies

Each Heating Coil independently selects its power control strategy. Available strategies:

| Strategy | Description |
|---|---|
| **Manual** | Output is set manually via the *Output power %* number entity. No automation. |
| **Solar radiation sensor** | Proportional control based on a solar irradiance sensor (W or kW). Output tracks solar production with configurable attenuation and ramp rates. |
| **PV power** | Proportional control based on a PV power sensor. Similar to solar sensor but uses actual inverter power output. |
| **Grid power** | Regulates output to maintain grid power flow within a configurable dead zone around a target offset. Ramps up when the grid is exporting (surplus), ramps down when importing. |
| **Battery power** | Regulates output based on battery charging/discharging power. Ramps up while the battery is absorbing surplus, ramps down when the battery is discharging. |
| **Strategy 1 (advanced)** | Synchronous multi-source control — the recommended strategy for systems with PV + battery + grid. See below. |

---

### Strategy 1 — Synchronous multi-source control

Strategy 1 is a synchronous, interval-driven algorithm that combines grid and battery signals into a single coordinated ramp. It evaluates four operating scenarios on every polling interval (`tracked_entities_interval`, default 5 s):

| Scenario | Conditions | Behaviour |
|---|---|---|
| **1** | Grid export OFF, battery charging ON, SOC < 100 % | Battery-only control. Ramp up when battery is absorbing surplus, ramp down when discharging. Grid signal is ignored. |
| **2** | Grid export ON, battery charging ON, SOC < 100 % | Battery + grid export control. Battery takes priority; additional ramp-up when grid is exporting. |
| **3** | Grid export OFF, battery not charging | Battery discharge protection + slow probing. Ramp down when battery discharges or grid imports; slow upward probe when both are in dead zone. |
| **4** | Grid export ON, battery not charging | Full bidirectional grid + battery discharge control. |

**Battery always takes priority over grid.** If the battery requests a ramp-down and the grid simultaneously requests a ramp-up, the grid signal is suppressed for that interval.

**Fast ramp-down on solar drop:** An independent state-change handler monitors the solar sensor. If the solar power drops by more than `solar_sensor_ramp_down_fast_threshold` (default 300 W) in a single reading, the coil output is reduced immediately by the fast ramp-down step — independent of the polling interval.

#### Strategy 1 configuration parameters

| Parameter | Default | Description |
|---|---|---|
| `tracked_entities_interval` | 5 s | Polling interval for all tracked entities |
| `strategy_1_power_grid_entity` | — | Entity that reports grid power (positive = import, negative = export) |
| `strategy_1_power_grid_unit` | kW | Unit of the grid power entity |
| `strategy_1_power_grid_dead_zone_w` | 300 W | Dead zone width around the grid target |
| `strategy_1_power_grid_offset_w` | 100 W | Target grid power offset (small positive = slight import preference) |
| `strategy_1_power_grid_offset_export_limit_w` | 9000 W | Grid offset when export is enabled |
| `strategy_1_battery_power_entity` | — | Entity that reports battery power (positive = charging, negative = discharging) |
| `strategy_1_battery_power_unit` | W | Unit of the battery power entity |
| `strategy_1_battery_power_dead_zone_w` | 300 W | Dead zone width around the battery target |
| `strategy_1_battery_power_offset_w` | -1000 W | Battery target offset |
| `strategy_1_entity_battery_charging_enablement_state` | — | Entity (sensor or input_boolean) that indicates whether battery charging is active |
| `strategy_1_entity_battery_state_of_charge` | — | Entity reporting battery SOC (0 – 100 %) |
| `strategy_1_solar_sensor_entity` | — | Solar sensor entity for fast-drop detection |
| `strategy_1_solar_sensor_unit` | W | Unit of the solar sensor |
| `strategy_1_solar_sensor_ramp_down_fast_threshold` | 300 W | Drop threshold that triggers immediate fast ramp-down |
| `strategy_1_ramp_up_fast_power_step` | 1 % | Step size for fast ramp-up |
| `strategy_1_ramp_up_slow_power_step` | 1 % | Step size for slow ramp-up (probing) |
| `strategy_1_ramp_down_fast_power_step` | 25 % | Step size for fast ramp-down |
| `strategy_1_ramp_down_slow_power_step` | 1 % | Step size for slow ramp-down |
| `strategy_1_power_grid_ramp_up_fast_threshold` | 4000 W | Grid export level above which fast ramp-up is used |
| `strategy_1_power_grid_ramp_down_fast_threshold` | 4000 W | Grid import level above which fast ramp-down is used |
| `strategy_1_battery_ramp_up_fast_threshold` | 4000 W | Battery charging level above which fast ramp-up is used |
| `strategy_1_battery_ramp_down_fast_threshold` | 4000 W | Battery discharging level above which fast ramp-down is used |

---

## Entities created per device

### General device
| Entity | Type | Description |
|---|---|---|
| `button.heating_coil_general_off_all` | Button | Turn off all coils |
| `button.heating_coil_general_on_all` | Button | Turn on all coils |
| `sensor.heating_coil_general_total_power` | Sensor | Combined output power of all coils (kW) |

### Modbus Node device
| Entity | Type | Description |
|---|---|---|
| `sensor.heating_coil_node_<name>_error_code` | Sensor | Modbus communication error bitmask |

### Heating Coil device
| Entity | Type | Description |
|---|---|---|
| `switch.heating_coil_<name>_enable` | Switch | Enable/disable this coil |
| `switch.heating_coil_<name>_only_use_power_above_export_limit` | Switch | Restrict operation to export-surplus periods only |
| `number.heating_coil_<name>_max_power` | Number | Real-time output power ceiling (0 – 100 %) |
| `sensor.heating_coil_<name>_output_power_percent` | Sensor | Current output (%) |
| `sensor.heating_coil_<name>_output_power_kw` | Sensor | Current output (kW) |

---

## Services

| Service | Description |
|---|---|
| `heating_coil_controller.turn_off_all` | Immediately disables all heating coils |
| `heating_coil_controller.turn_on_all` | Re-enables all heating coils |

---

## Recommended setup sequence

1. **Add General** — configure the total power limit for your installation.
2. **Add Modbus Node(s)** — one per physical Modbus connection. Configure connection type, address, and DAC hardware type.
3. **Add Heating Coil(s)** — assign each coil to its Modbus Node, configure the DAC port, coil power, and output curve.
4. **Select a power control strategy** — for systems with PV + battery + grid, choose *Strategy 1* and configure the sensor entities and ramp parameters to match your hardware.
5. **Test** — use the *Output power %* sensor and the Modbus Node error sensor to verify communication and output.

---

## Debugging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.heating_coil_controller: debug
```

---

## Version

Current version: **0.01.01**

Author: Jozef Moravcik — jozef.moravcik@moravcik.eu
