from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" __init__.py """

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later, async_track_time_interval, async_track_state_change_event
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from datetime import timedelta

from .const import *

LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER]
GENERAL_PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]
MODBUS_NODE_PLATFORMS: list[Platform] = [Platform.SENSOR]


def _log_modbus_settings(entry_id: str, settings) -> None:
    """Vypíše aktuálne Modbus nastavenia do debug logu."""
    conn_type = settings.modbus_connection_type

    LOGGER.debug(
        "=== MODBUS NASTAVENIA [entry_id: %s] ===",
        entry_id,
    )
    LOGGER.debug("  Typ pripojenia : %s", conn_type)

    if conn_type == "existing_node":
        LOGGER.debug("  Modbus Node    : %s", settings.modbus_node_name)

    elif conn_type == "usb":
        LOGGER.debug("  Port (port)                       : %s", settings.port)
        LOGGER.debug("  Baudrate (baudrate)               : %s", settings.baudrate)
        LOGGER.debug("  Data Size (bytesize)              : %s", settings.bytesize)
        LOGGER.debug("  Stop Bits (stopbits)              : %s", settings.stopbits)
        LOGGER.debug("  Parity (parity)                   : %s", settings.parity)
        LOGGER.debug("  Delay (delay)                     : %s s", settings.delay)
        LOGGER.debug("  Msg Wait (message_wait_millisecond): %s ms", settings.message_wait_millisecond)
        LOGGER.debug("  Timeout (timeout)                 : %s s", settings.timeout)

    elif conn_type in ("tcp", "udp"):
        LOGGER.debug("  Host (host)                       : %s", settings.host)
        LOGGER.debug("  Port (port)                       : %s", settings.port)
        LOGGER.debug("  Msg Wait (message_wait_millisecond): %s ms", settings.message_wait_millisecond)
        LOGGER.debug("  Timeout (timeout)                 : %s s", settings.timeout)

    LOGGER.debug("  Device ID (modbus_device_id)       : %s", settings.modbus_device_id)
    LOGGER.debug("=== KONIEC MODBUS NASTAVENÍ ===")

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Coil Controller from a config entry."""
    
    # -----------------------------------------------------------------------
    # Zistenie typu zariadenia
    # -----------------------------------------------------------------------
    def _get(key, default):
        """Pomocná funkcia: číta z options, fallback na data, potom default."""
        return entry.options.get(key, entry.data.get(key, default))

    device_type = _get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

    # -----------------------------------------------------------------------
    # General – registrácia do hass.data so základnými nastaveniami
    # -----------------------------------------------------------------------
    if device_type == DEVICE_TYPE_GENERAL:
        include_device_name_in_entity = _get(CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY)
        heating_coil_total_power = float(_get(CONF_HEATING_COIL_TOTAL_POWER, DEFAULT_HEATING_COIL_TOTAL_POWER))

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault("shared", {})
        hass.data[DOMAIN]["shared"][CONF_HEATING_COIL_TOTAL_POWER] = heating_coil_total_power
        # Domain-level lock pre serializáciu my_controller() naprieč inštanciami
        if "controller_lock" not in hass.data[DOMAIN]["shared"]:
            hass.data[DOMAIN]["shared"]["controller_lock"] = asyncio.Lock()
        hass.data[DOMAIN][entry.entry_id] = {
            CONF_DEVICE_TYPE: device_type,
            CONF_DEVICE_NAME: _get(CONF_DEVICE_NAME, "General"),
            CONF_INCLUDE_DEVICE_NAME_IN_ENTITY: include_device_name_in_entity,
            CONF_HEATING_COIL_TOTAL_POWER: heating_coil_total_power,
        }

        await hass.config_entries.async_forward_entry_setups(entry, GENERAL_PLATFORMS)

        # Registrácia služieb pre General zariadenie
        if not hass.services.has_service(DOMAIN, SERVICE_TURN_OFF_ALL):
            hass.services.async_register(
                DOMAIN,
                SERVICE_TURN_OFF_ALL,
                turn_off_all_service,
            )
        if not hass.services.has_service(DOMAIN, SERVICE_TURN_ON_ALL):
            hass.services.async_register(
                DOMAIN,
                SERVICE_TURN_ON_ALL,
                turn_on_all_service,
            )

        entry.async_on_unload(entry.add_update_listener(update_listener))
        return True

    # -----------------------------------------------------------------------
    # Modbus Node – registrácia do hass.data s Modbus nastaveniami
    # -----------------------------------------------------------------------
    if device_type == DEVICE_TYPE_MODBUS_NODE:
        from .modbus_node import ModbusNodeInstance

        include_device_name_in_entity = _get(CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY)
        modbus_device_id = int(_get(CONF_MODBUS_DEVICE_ID, DEFAULT_MODBUS_DEVICE_ID))
        modbus_node_number = int(_get(CONF_MODBUS_NODE_NUMBER, 1))
        dac_type = _get(CONF_DAC_TYPE, DEFAULT_DAC_TYPE)
        modbus_connection_type = _get(CONF_MODBUS_CONNECTION_TYPE, DEFAULT_MODBUS_CONNECTION_TYPE)
        modbus_node_name = _get(CONF_MODBUS_NODE_NAME, "")
        modbus_port = _get(CONF_MODBUS_PORT, "")
        modbus_baudrate = int(_get(CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE))
        modbus_bytesize = int(_get(CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE))
        modbus_stopbits = int(_get(CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS))
        modbus_parity = _get(CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY)
        modbus_delay = int(_get(CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY))
        modbus_message_wait = int(_get(CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT))
        modbus_timeout = int(_get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT))
        modbus_host = _get(CONF_MODBUS_HOST, "")

        # Vytvorenie ModbusNodeInstance
        modbus_node_instance = ModbusNodeInstance(hass, entry.entry_id)
        modbus_node_instance.settings.modbus_connection_type = modbus_connection_type
        modbus_node_instance.settings.modbus_node_name = modbus_node_name
        modbus_node_instance.settings.port = str(modbus_port)
        modbus_node_instance.settings.baudrate = modbus_baudrate
        modbus_node_instance.settings.bytesize = modbus_bytesize
        modbus_node_instance.settings.stopbits = modbus_stopbits
        modbus_node_instance.settings.parity = modbus_parity
        modbus_node_instance.settings.delay = modbus_delay
        modbus_node_instance.settings.message_wait_millisecond = modbus_message_wait
        modbus_node_instance.settings.timeout = modbus_timeout
        modbus_node_instance.settings.host = modbus_host
        modbus_node_instance.settings.modbus_device_id = modbus_device_id
        modbus_node_instance.settings.dac_type = dac_type

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            CONF_DEVICE_TYPE: device_type,
            CONF_DEVICE_NAME: _get(CONF_DEVICE_NAME, "Modbus Node"),
            CONF_INCLUDE_DEVICE_NAME_IN_ENTITY: include_device_name_in_entity,
            CONF_MODBUS_NODE_NUMBER: modbus_node_number,
            CONF_MODBUS_DEVICE_ID: modbus_device_id,
            CONF_DAC_TYPE: dac_type,
            "modbus_node_instance": modbus_node_instance,
            CONF_MODBUS_CONNECTION_TYPE: modbus_connection_type,
            CONF_MODBUS_NODE_NAME: modbus_node_name,
            CONF_MODBUS_PORT: modbus_port,
            CONF_MODBUS_BAUDRATE: modbus_baudrate,
            CONF_MODBUS_BYTESIZE: modbus_bytesize,
            CONF_MODBUS_STOPBITS: modbus_stopbits,
            CONF_MODBUS_PARITY: modbus_parity,
            CONF_MODBUS_DELAY: modbus_delay,
            CONF_MODBUS_MESSAGE_WAIT: modbus_message_wait,
            CONF_MODBUS_TIMEOUT: modbus_timeout,
            CONF_MODBUS_HOST: modbus_host,
        }

        await hass.config_entries.async_forward_entry_setups(entry, MODBUS_NODE_PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(update_listener))
        return True

    # -----------------------------------------------------------------------
    # Heating Coil – plná inicializácia (pôvodný kód)
    # -----------------------------------------------------------------------
    from .heating_coil_controller import Heating_Coil_Controller_Instance

    # -----------------------------------------------------------------------
    # Načítanie základných konfiguračných parametrov
    # -----------------------------------------------------------------------
    device_name                  = _get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
    include_device_name_in_entity = _get(CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY)
    heating_coil_power           = float(_get(CONF_HEATING_COIL_POWER, DEFAULT_HEATING_COIL_POWER))
    heating_coil_total_power     = float(_get(CONF_HEATING_COIL_TOTAL_POWER, DEFAULT_HEATING_COIL_TOTAL_POWER))
    virtual_heating_coil         = bool(_get(CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL))

    # -----------------------------------------------------------------------
    # Načítanie rozšírených konfiguračných parametrov
    # -----------------------------------------------------------------------
    grid_export_status_entity = _get(CONF_GRID_EXPORT_STATUS_ENTITY, DEFAULT_CONF_GRID_EXPORT_STATUS_ENTITY)
    output_power_during_day_only = bool(_get(CONF_OUTPUT_POWER_DURING_DAY_ONLY, DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY))

    # -----------------------------------------------------------------------
    # Načítanie Modbus konfiguračných parametrov
    # SelectSelector ukladá hodnoty vždy ako str -> int konverzia kde treba
    # NumberSelector ukladá hodnoty ako float -> int konverzia kde treba
    # -----------------------------------------------------------------------
    modbus_node_entry_id        = _get(CONF_MODBUS_NODE_ENTRY_ID, DEFAULT_MODBUS_NODE_ENTRY_ID)
    modbus_connection_type      = _get(CONF_MODBUS_CONNECTION_TYPE, DEFAULT_MODBUS_CONNECTION_TYPE)
    modbus_node_name            = _get(CONF_MODBUS_NODE_NAME, "")
    modbus_port                 = _get(CONF_MODBUS_PORT, "")
    modbus_baudrate             = int(_get(CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE))
    modbus_bytesize             = int(_get(CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE))
    modbus_stopbits             = int(_get(CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS))
    modbus_parity               = _get(CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY)
    modbus_delay                = int(_get(CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY))
    modbus_message_wait         = int(_get(CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT))
    modbus_timeout              = int(_get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT))
    modbus_host                 = _get(CONF_MODBUS_HOST, "")
    modbus_device_id            = int(_get(CONF_MODBUS_DEVICE_ID, DEFAULT_MODBUS_DEVICE_ID))
    dac_output_port_id          = int(_get(CONF_DAC_OUTPUT_PORT_ID, DEFAULT_DAC_OUTPUT_PORT_ID))
    dac_output_type             = _get(CONF_DAC_OUTPUT_TYPE, DEFAULT_DAC_OUTPUT_TYPE)
    zero_power_point            = int(_get(CONF_ZERO_POWER_POINT, DEFAULT_ZERO_POWER_POINT))
    maximum_power_point         = int(_get(CONF_MAXIMUM_POWER_POINT, DEFAULT_MAXIMUM_POWER_POINT))
    gamma                        = int(_get(CONF_GAMMA, DEFAULT_GAMMA))
    # Power control strategy
    power_control_strategy       = _get(CONF_POWER_CONTROL_STRATEGY, DEFAULT_POWER_CONTROL_STRATEGY)
    # Master heating coil
    master_heating_coil_id       = _get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID)
    # Solar sensor
    solar_sensor_entity              = _get(CONF_SOLAR_SENSOR_ENTITY, DEFAULT_SOLAR_SENSOR_ENTITY)
    solar_sensor_unit                = _get(CONF_SOLAR_SENSOR_UNIT, DEFAULT_SOLAR_SENSOR_UNIT)
    maximum_solar_radiation_value_raw = float(_get(CONF_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_MAXIMUM_SOLAR_RADIATION_VALUE))
    # Prepočet na W – ak je jednotka kW, vynásobíme 1000
    if solar_sensor_unit == "kW":
        maximum_solar_radiation_value = maximum_solar_radiation_value_raw * 1000
    else:
        maximum_solar_radiation_value = maximum_solar_radiation_value_raw
    solar_sensor_attenuation         = int(_get(CONF_SOLAR_SENSOR_ATTENUATION, DEFAULT_SOLAR_SENSOR_ATTENUATION))
    solar_sensor_ramp_up_power_step  = int(_get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_STEP))
    solar_sensor_ramp_up_power_cycle = int(_get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE))
    solar_sensor_ramp_down_power_step  = int(_get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP))
    solar_sensor_ramp_down_power_cycle = int(_get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE))
    # PV power
    pv_power_entity              = _get(CONF_PV_POWER_ENTITY, DEFAULT_PV_POWER_ENTITY)
    pv_power_unit                = _get(CONF_PV_POWER_UNIT, DEFAULT_PV_POWER_UNIT)
    pv_power_max_power_raw       = float(_get(CONF_PV_POWER_MAX_POWER, DEFAULT_PV_POWER_MAX_POWER))
    # Prepočet na W – ak je jednotka kW, vynásobíme 1000
    if pv_power_unit == "kW":
        pv_power_max_power = pv_power_max_power_raw * 1000
    else:
        pv_power_max_power = pv_power_max_power_raw
    pv_power_ratio         = int(_get(CONF_PV_POWER_RATIO, DEFAULT_PV_POWER_RATIO))
    pv_power_ramp_up_power_step  = int(_get(CONF_PV_POWER_RAMP_UP_POWER_STEP, DEFAULT_PV_POWER_RAMP_UP_POWER_STEP))
    pv_power_ramp_up_power_cycle = int(_get(CONF_PV_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_UP_POWER_CYCLE))
    pv_power_ramp_down_power_step  = int(_get(CONF_PV_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_PV_POWER_RAMP_DOWN_POWER_STEP))
    pv_power_ramp_down_power_cycle = int(_get(CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_DOWN_POWER_CYCLE))
    # Power grid
    power_grid_entity              = _get(CONF_POWER_GRID_ENTITY, DEFAULT_POWER_GRID_ENTITY)
    power_grid_unit                = _get(CONF_POWER_GRID_UNIT, DEFAULT_POWER_GRID_UNIT)
    power_grid_dead_zone_w         = int(_get(CONF_POWER_GRID_DEAD_ZONE_W, DEFAULT_POWER_GRID_DEAD_ZONE_W))
    power_grid_offset_w            = int(_get(CONF_POWER_GRID_OFFSET_W, DEFAULT_POWER_GRID_OFFSET_W))
    power_grid_offset_export_limit_w = int(_get(CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_POWER_GRID_OFFSET_EXPORT_LIMIT_W))
    power_grid_ramp_up_power_step  = int(_get(CONF_POWER_GRID_RAMP_UP_POWER_STEP, DEFAULT_POWER_GRID_RAMP_UP_POWER_STEP))
    power_grid_ramp_up_power_cycle = int(_get(CONF_POWER_GRID_RAMP_UP_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_UP_POWER_CYCLE))
    power_grid_ramp_down_power_step  = int(_get(CONF_POWER_GRID_RAMP_DOWN_POWER_STEP, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_STEP))
    power_grid_ramp_down_power_cycle = int(_get(CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_CYCLE))
    # Battery power
    battery_power_entity              = _get(CONF_BATTERY_POWER_ENTITY, DEFAULT_BATTERY_POWER_ENTITY)
    battery_power_unit                = _get(CONF_BATTERY_POWER_UNIT, DEFAULT_BATTERY_POWER_UNIT)
    battery_power_dead_zone_w         = int(_get(CONF_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_BATTERY_POWER_DEAD_ZONE_W))
    battery_power_offset_w            = int(_get(CONF_BATTERY_POWER_OFFSET_W, DEFAULT_BATTERY_POWER_OFFSET_W))
    battery_power_ramp_up_power_step  = int(_get(CONF_BATTERY_POWER_RAMP_UP_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_STEP))
    battery_power_ramp_up_power_cycle = int(_get(CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_CYCLE))
    battery_power_ramp_down_power_step  = int(_get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_STEP))
    battery_power_ramp_down_power_cycle = int(_get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE))

    # Strategy 1 – ramp parameters (iba steps, cycles neexistujú)
    strategy_1_ramp_up_fast_power_step     = int(_get(CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_FAST_POWER_STEP))
    strategy_1_ramp_up_slow_power_step     = int(_get(CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP))
    strategy_1_ramp_down_fast_power_step   = int(_get(CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP))
    strategy_1_ramp_down_slow_power_step   = int(_get(CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP))
    strategy_1_power_grid_ramp_up_fast_threshold      = int(_get(CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD))
    strategy_1_battery_ramp_up_fast_threshold         = int(_get(CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD))
    strategy_1_solar_sensor_ramp_down_fast_threshold  = int(_get(CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD))
    strategy_1_power_grid_ramp_down_fast_threshold    = int(_get(CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD))
    strategy_1_battery_ramp_down_fast_threshold       = int(_get(CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD))

    strategy_1_grid_export_status_entity = _get(CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY, DEFAULT_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY)
    strategy_1_power_grid_entity         = _get(CONF_STRATEGY_1_POWER_GRID_ENTITY, DEFAULT_STRATEGY_1_POWER_GRID_ENTITY)
    strategy_1_power_grid_unit           = _get(CONF_STRATEGY_1_POWER_GRID_UNIT, DEFAULT_STRATEGY_1_POWER_GRID_UNIT)
    strategy_1_power_grid_dead_zone_w    = int(_get(CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W, DEFAULT_STRATEGY_1_POWER_GRID_DEAD_ZONE_W))
    strategy_1_power_grid_offset_w       = int(_get(CONF_STRATEGY_1_POWER_GRID_OFFSET_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_W))
    strategy_1_power_grid_offset_export_limit_w = int(_get(CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W))
    strategy_1_battery_charging_enablement_state = _get(CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE, DEFAULT_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE)
    strategy_1_battery_state_of_charge           = _get(CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE, DEFAULT_STRATEGY_1_BATTERY_STATE_OF_CHARGE)
    strategy_1_battery_power_entity      = _get(CONF_STRATEGY_1_BATTERY_POWER_ENTITY, DEFAULT_STRATEGY_1_BATTERY_POWER_ENTITY)
    strategy_1_battery_power_unit        = _get(CONF_STRATEGY_1_BATTERY_POWER_UNIT, DEFAULT_STRATEGY_1_BATTERY_POWER_UNIT)
    strategy_1_battery_power_dead_zone_w = int(_get(CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W))
    strategy_1_battery_power_offset_w    = int(_get(CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W, DEFAULT_STRATEGY_1_BATTERY_POWER_OFFSET_W))
    strategy_1_solar_sensor_entity       = _get(CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ENTITY)
    strategy_1_solar_sensor_unit         = _get(CONF_STRATEGY_1_SOLAR_SENSOR_UNIT, DEFAULT_STRATEGY_1_SOLAR_SENSOR_UNIT)
    strategy_1_maximum_solar_radiation_value_raw = float(_get(CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE))
    if strategy_1_solar_sensor_unit == "kW":
        strategy_1_maximum_solar_radiation_value = strategy_1_maximum_solar_radiation_value_raw * 1000
    else:
        strategy_1_maximum_solar_radiation_value = strategy_1_maximum_solar_radiation_value_raw
    strategy_1_solar_sensor_attenuation  = int(_get(CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ATTENUATION))

    tracked_entities_interval                          = int(_get(CONF_TRACKED_ENTITIES_INTERVAL, DEFAULT_TRACKED_ENTITIES_INTERVAL))

# ******************************************************************************************
# **** Uloženie všetkých nastavení do inštancie a do "core.config_entries"******************
# ******************************************************************************************    
    instance = Heating_Coil_Controller_Instance()
    # Nastavenie hass objektu a entry_id do inštancie
    instance.hass = hass
    instance._entry_id = entry.entry_id
    
    # Nastavenia základných parametrov
    instance.settings.device_name = device_name
    instance.settings.include_device_name_in_entity = include_device_name_in_entity
    instance.settings.heating_coil_power = heating_coil_power
    instance.settings.heating_coil_total_power = heating_coil_total_power
    instance.settings.virtual_heating_coil = virtual_heating_coil
    # Nastavenia rozšírených parametrov
    instance.settings.grid_export_status_entity = grid_export_status_entity
    instance.settings.output_power_during_day_only = output_power_during_day_only
    # Nastavenia Modbus parametrov
    instance.settings.modbus_connection_type       = modbus_connection_type
    instance.settings.modbus_node_name             = modbus_node_name
    instance.settings.port                         = str(modbus_port)
    instance.settings.baudrate                     = modbus_baudrate
    instance.settings.bytesize                     = modbus_bytesize
    instance.settings.stopbits                     = modbus_stopbits
    instance.settings.parity                       = modbus_parity
    instance.settings.delay                        = modbus_delay
    instance.settings.message_wait_millisecond     = modbus_message_wait
    instance.settings.timeout                      = modbus_timeout
    instance.settings.host                         = modbus_host
    instance.settings.modbus_device_id             = modbus_device_id
    instance.settings.dac_output_port_id           = dac_output_port_id
    instance.settings.dac_output_type              = dac_output_type
    instance.settings.zero_power_point             = zero_power_point
    instance.settings.maximum_power_point          = maximum_power_point
    instance.settings.gamma                         = gamma
    # Power control strategy
    instance.settings.power_control_strategy        = power_control_strategy
    # Master heating coil
    instance.settings.master_heating_coil_id        = master_heating_coil_id
    # Solar sensor
    instance.settings.solar_sensor_entity              = solar_sensor_entity
    instance.settings.solar_sensor_unit                = solar_sensor_unit
    instance.settings.maximum_solar_radiation_value    = maximum_solar_radiation_value
    instance.settings.solar_sensor_attenuation         = solar_sensor_attenuation
    instance.settings.solar_sensor_ramp_up_power_step  = solar_sensor_ramp_up_power_step
    instance.settings.solar_sensor_ramp_up_power_cycle = solar_sensor_ramp_up_power_cycle
    instance.settings.solar_sensor_ramp_down_power_step  = solar_sensor_ramp_down_power_step
    instance.settings.solar_sensor_ramp_down_power_cycle = solar_sensor_ramp_down_power_cycle
    # PV power
    instance.settings.pv_power_entity                = pv_power_entity
    instance.settings.pv_power_unit                  = pv_power_unit
    instance.settings.pv_power_max_power             = pv_power_max_power
    instance.settings.pv_power_ratio                 = pv_power_ratio
    instance.settings.pv_power_ramp_up_power_step    = pv_power_ramp_up_power_step
    instance.settings.pv_power_ramp_up_power_cycle   = pv_power_ramp_up_power_cycle
    instance.settings.pv_power_ramp_down_power_step  = pv_power_ramp_down_power_step
    instance.settings.pv_power_ramp_down_power_cycle = pv_power_ramp_down_power_cycle
    # Power grid
    instance.settings.power_grid_entity              = power_grid_entity
    instance.settings.power_grid_unit                = power_grid_unit
    instance.settings.power_grid_dead_zone_w         = power_grid_dead_zone_w
    instance.settings.power_grid_offset_w            = power_grid_offset_w
    instance.settings.power_grid_offset_export_limit_w = power_grid_offset_export_limit_w
    instance.settings.power_grid_ramp_up_power_step  = power_grid_ramp_up_power_step
    instance.settings.power_grid_ramp_up_power_cycle = power_grid_ramp_up_power_cycle
    instance.settings.power_grid_ramp_down_power_step  = power_grid_ramp_down_power_step
    instance.settings.power_grid_ramp_down_power_cycle = power_grid_ramp_down_power_cycle
    # Battery power
    instance.settings.battery_power_entity              = battery_power_entity
    instance.settings.battery_power_unit                = battery_power_unit
    instance.settings.battery_power_dead_zone_w         = battery_power_dead_zone_w
    instance.settings.battery_power_offset_w            = battery_power_offset_w
    instance.settings.battery_power_ramp_up_power_step  = battery_power_ramp_up_power_step
    instance.settings.battery_power_ramp_up_power_cycle = battery_power_ramp_up_power_cycle
    instance.settings.battery_power_ramp_down_power_step  = battery_power_ramp_down_power_step
    instance.settings.battery_power_ramp_down_power_cycle = battery_power_ramp_down_power_cycle
    instance.settings.strategy_1_ramp_up_fast_power_step = strategy_1_ramp_up_fast_power_step
    instance.settings.strategy_1_ramp_up_slow_power_step = strategy_1_ramp_up_slow_power_step
    instance.settings.strategy_1_ramp_down_fast_power_step = strategy_1_ramp_down_fast_power_step
    instance.settings.strategy_1_ramp_down_slow_power_step = strategy_1_ramp_down_slow_power_step
    instance.settings.strategy_1_power_grid_ramp_up_fast_threshold = strategy_1_power_grid_ramp_up_fast_threshold
    instance.settings.strategy_1_battery_ramp_up_fast_threshold = strategy_1_battery_ramp_up_fast_threshold
    instance.settings.strategy_1_solar_sensor_ramp_down_fast_threshold = strategy_1_solar_sensor_ramp_down_fast_threshold
    instance.settings.strategy_1_power_grid_ramp_down_fast_threshold = strategy_1_power_grid_ramp_down_fast_threshold
    instance.settings.strategy_1_battery_ramp_down_fast_threshold = strategy_1_battery_ramp_down_fast_threshold

    instance.settings.strategy_1_grid_export_status_entity = strategy_1_grid_export_status_entity
    instance.settings.strategy_1_power_grid_entity = strategy_1_power_grid_entity
    instance.settings.strategy_1_power_grid_unit = strategy_1_power_grid_unit
    instance.settings.strategy_1_power_grid_dead_zone_w = strategy_1_power_grid_dead_zone_w
    instance.settings.strategy_1_power_grid_offset_w = strategy_1_power_grid_offset_w
    instance.settings.strategy_1_power_grid_offset_export_limit_w = strategy_1_power_grid_offset_export_limit_w
    instance.settings.strategy_1_battery_charging_enablement_state = strategy_1_battery_charging_enablement_state
    instance.settings.strategy_1_battery_state_of_charge = strategy_1_battery_state_of_charge
    instance.settings.strategy_1_battery_power_entity = strategy_1_battery_power_entity
    instance.settings.strategy_1_battery_power_unit = strategy_1_battery_power_unit
    instance.settings.strategy_1_battery_power_dead_zone_w = strategy_1_battery_power_dead_zone_w
    instance.settings.strategy_1_battery_power_offset_w = strategy_1_battery_power_offset_w
    instance.settings.strategy_1_solar_sensor_entity = strategy_1_solar_sensor_entity
    instance.settings.strategy_1_solar_sensor_unit = strategy_1_solar_sensor_unit
    instance.settings.strategy_1_maximum_solar_radiation_value = strategy_1_maximum_solar_radiation_value
    instance.settings.strategy_1_solar_sensor_attenuation = strategy_1_solar_sensor_attenuation
    instance.settings.tracked_entities_interval = tracked_entities_interval

    # Nastavenie entity IDs po nastavení device_name
    instance.setup_entity_ids()

    # Debug výpis Modbus nastavení
    _log_modbus_settings(entry.entry_id, instance.settings)

    try:
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault("shared", {})
        # Domain-level lock pre serializáciu my_controller() naprieč inštanciami
        if "controller_lock" not in hass.data[DOMAIN]["shared"]:
            hass.data[DOMAIN]["shared"]["controller_lock"] = asyncio.Lock()
        hass.data[DOMAIN][entry.entry_id] = {
            "instance": instance,
            CONF_DEVICE_TYPE: DEVICE_TYPE_HEATING_COIL,
            CONF_DEVICE_NAME: device_name,
            CONF_INCLUDE_DEVICE_NAME_IN_ENTITY: include_device_name_in_entity,
            CONF_VIRTUAL_HEATING_COIL: virtual_heating_coil,
            CONF_HEATING_COIL_TOTAL_POWER: heating_coil_total_power,
            CONF_GRID_EXPORT_STATUS_ENTITY: grid_export_status_entity,
            CONF_OUTPUT_POWER_DURING_DAY_ONLY: output_power_during_day_only,
            # Modbus parametre
            CONF_MODBUS_CONNECTION_TYPE:    modbus_connection_type,
            CONF_MODBUS_NODE_NAME:          modbus_node_name,
            CONF_MODBUS_PORT:               modbus_port,
            CONF_MODBUS_BAUDRATE:           modbus_baudrate,
            CONF_MODBUS_BYTESIZE:           modbus_bytesize,
            CONF_MODBUS_STOPBITS:           modbus_stopbits,
            CONF_MODBUS_PARITY:             modbus_parity,
            CONF_MODBUS_DELAY:              modbus_delay,
            CONF_MODBUS_MESSAGE_WAIT:       modbus_message_wait,
            CONF_MODBUS_TIMEOUT:            modbus_timeout,
            CONF_MODBUS_HOST:               modbus_host,
            CONF_MODBUS_DEVICE_ID:          modbus_device_id,
            CONF_DAC_OUTPUT_PORT_ID:        dac_output_port_id,
            CONF_MODBUS_NODE_ENTRY_ID:      modbus_node_entry_id,
            CONF_DAC_OUTPUT_TYPE:           dac_output_type,
            CONF_ZERO_POWER_POINT:          zero_power_point,
            CONF_MAXIMUM_POWER_POINT:       maximum_power_point,
            CONF_GAMMA:                     gamma,
            # Power control strategy
            CONF_POWER_CONTROL_STRATEGY:    power_control_strategy,
            # Master heating coil
            CONF_MASTER_HEATING_COIL_ID:    master_heating_coil_id,
            # Solar sensor
            CONF_SOLAR_SENSOR_ENTITY:                solar_sensor_entity,
            CONF_SOLAR_SENSOR_UNIT:                  solar_sensor_unit,
            CONF_MAXIMUM_SOLAR_RADIATION_VALUE:      maximum_solar_radiation_value,
            CONF_SOLAR_SENSOR_ATTENUATION:           solar_sensor_attenuation,
            CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP:    solar_sensor_ramp_up_power_step,
            CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE:   solar_sensor_ramp_up_power_cycle,
            CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP:  solar_sensor_ramp_down_power_step,
            CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE: solar_sensor_ramp_down_power_cycle,
            # PV power
            CONF_PV_POWER_ENTITY:                pv_power_entity,
            CONF_PV_POWER_UNIT:                  pv_power_unit,
            CONF_PV_POWER_MAX_POWER:             pv_power_max_power,
            CONF_PV_POWER_RATIO:                 pv_power_ratio,
            CONF_PV_POWER_RAMP_UP_POWER_STEP:    pv_power_ramp_up_power_step,
            CONF_PV_POWER_RAMP_UP_POWER_CYCLE:   pv_power_ramp_up_power_cycle,
            CONF_PV_POWER_RAMP_DOWN_POWER_STEP:  pv_power_ramp_down_power_step,
            CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE: pv_power_ramp_down_power_cycle,
            # Power grid
            CONF_POWER_GRID_ENTITY:                power_grid_entity,
            CONF_POWER_GRID_UNIT:                  power_grid_unit,
            CONF_POWER_GRID_DEAD_ZONE_W:           power_grid_dead_zone_w,
            CONF_POWER_GRID_OFFSET_W:              power_grid_offset_w,
            CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W: power_grid_offset_export_limit_w,
            CONF_POWER_GRID_RAMP_UP_POWER_STEP:    power_grid_ramp_up_power_step,
            CONF_POWER_GRID_RAMP_UP_POWER_CYCLE:   power_grid_ramp_up_power_cycle,
            CONF_POWER_GRID_RAMP_DOWN_POWER_STEP:  power_grid_ramp_down_power_step,
            CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE: power_grid_ramp_down_power_cycle,
            # Battery power
            CONF_BATTERY_POWER_ENTITY:                battery_power_entity,
            CONF_BATTERY_POWER_UNIT:                  battery_power_unit,
            CONF_BATTERY_POWER_DEAD_ZONE_W:           battery_power_dead_zone_w,
            CONF_BATTERY_POWER_OFFSET_W:              battery_power_offset_w,
            CONF_BATTERY_POWER_RAMP_UP_POWER_STEP:    battery_power_ramp_up_power_step,
            CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE:   battery_power_ramp_up_power_cycle,
            CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP:  battery_power_ramp_down_power_step,
            CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE: battery_power_ramp_down_power_cycle,
            CONF_HEATING_COIL_POWER:                  heating_coil_power,            
            # Strategy 1
            CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP:    strategy_1_ramp_up_fast_power_step,
            CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP:    strategy_1_ramp_up_slow_power_step,
            CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP:  strategy_1_ramp_down_fast_power_step,
            CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP:  strategy_1_ramp_down_slow_power_step,
            CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD:    strategy_1_power_grid_ramp_up_fast_threshold,
            CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD:        strategy_1_battery_ramp_up_fast_threshold,
            CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD: strategy_1_solar_sensor_ramp_down_fast_threshold,
            CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD:    strategy_1_power_grid_ramp_down_fast_threshold,
            CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD:       strategy_1_battery_ramp_down_fast_threshold,
            CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY:    strategy_1_grid_export_status_entity,
            CONF_STRATEGY_1_POWER_GRID_ENTITY:            strategy_1_power_grid_entity,
            CONF_STRATEGY_1_POWER_GRID_UNIT:              strategy_1_power_grid_unit,
            CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W:       strategy_1_power_grid_dead_zone_w,
            CONF_STRATEGY_1_POWER_GRID_OFFSET_W:          strategy_1_power_grid_offset_w,
            CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W: strategy_1_power_grid_offset_export_limit_w,
            CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE: strategy_1_battery_charging_enablement_state,
            CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE:           strategy_1_battery_state_of_charge,
            CONF_STRATEGY_1_BATTERY_POWER_ENTITY:         strategy_1_battery_power_entity,
            CONF_STRATEGY_1_BATTERY_POWER_UNIT:           strategy_1_battery_power_unit,
            CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W:    strategy_1_battery_power_dead_zone_w,
            CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W:       strategy_1_battery_power_offset_w,
            CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY:          strategy_1_solar_sensor_entity,
            CONF_STRATEGY_1_SOLAR_SENSOR_UNIT:            strategy_1_solar_sensor_unit,
            CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE: strategy_1_maximum_solar_radiation_value,
            CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION:     strategy_1_solar_sensor_attenuation,
            CONF_TRACKED_ENTITIES_INTERVAL:                         tracked_entities_interval,
        }

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        
        # Register update listener for options changes
        entry.async_on_unload(entry.add_update_listener(update_listener))
            
        async def async_update_settings_sensors(_now=None):
            """Asynchrónna aktualizácia settings senzorov."""
            async_dispatcher_send(hass, f"{DOMAIN}_settings_update_{entry.entry_id}")
        
        async def async_run_my_controller(_now=None):
            """Periodické spúšťanie my_controller."""
            await instance.my_controller()


        # Plán jednorazových volaní
        entry.async_on_unload(async_call_later(hass, 2, async_update_settings_sensors))

        # Periodické spúšťanie my_controller každé UPDATE_INTERVAL sekúnd
        entry.async_on_unload(async_call_later(hass, 3, async_run_my_controller))


        # Okamžitá reakcia na zmenu solárneho senzora (mrak/zatmenie)
        # Nezávislý handler – nevolá my_controller, ale len upraví výkon podľa poklesu
        async def async_solar_state_changed(event):
            """Okamžitá reakcia na zmenu stavu solárneho senzora."""
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            if old_state and new_state and old_state.state == new_state.state:
                return
            LOGGER.debug("Solar sensor state changed, triggering independent solar handler")
            await instance.async_handle_solar_decrease()

        solar_tracked = []
        if solar_sensor_entity:
            solar_tracked.append(solar_sensor_entity)
        if strategy_1_solar_sensor_entity:
            solar_tracked.append(strategy_1_solar_sensor_entity)
        solar_tracked = list(set(filter(None, solar_tracked)))

        if solar_tracked:
            LOGGER.info("Solar sensor immediate tracking enabled for: %s", solar_tracked)
            entry.async_on_unload(
                async_track_state_change_event(
                    hass,
                    solar_tracked,
                    async_solar_state_changed,
                )
            )

        # Periodické spúšťanie async_run_my_controller podľa tracked_entities_interval
        LOGGER.info(f"Tracked entities interval enabled: every {tracked_entities_interval} seconds")
        entry.async_on_unload(
            async_track_time_interval(
                hass,
                async_run_my_controller,
                timedelta(seconds=tracked_entities_interval)
            )
        )

        
        LOGGER.info("Heating Coil Controller configuration saved successfully")

    except Exception as ex:
        LOGGER.error("Error while configuration saving: %s", ex)
        raise ConfigEntryNotReady from ex        

    return True


async def handle_turn_off_all(hass: HomeAssistant) -> None:
    """Spoločná logika pre vypnutie všetkých špirál – volaná z buttonu aj zo služby."""
    LOGGER.debug("All heating coils OFF")
    domain_data = hass.data.get(DOMAIN, {})

    for entry_id, entry_data in domain_data.items():
        if entry_id == "shared":
            continue
        if not isinstance(entry_data, dict):
            continue
        if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
            continue

        coil_instance = entry_data.get("instance")
        if coil_instance is None:
            continue

        enable_entity_id = coil_instance.SWITCH_ENTITY_ENABLE
        if enable_entity_id:
            await hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": enable_entity_id},
            )
            LOGGER.debug("Turned OFF: %s", enable_entity_id)

async def handle_turn_on_all(hass: HomeAssistant) -> None:
    """Spoločná logika pre zapnutie všetkých špirál – volaná z buttonu aj zo služby."""
    LOGGER.debug("All heating coils ON")
    domain_data = hass.data.get(DOMAIN, {})

    for entry_id, entry_data in domain_data.items():
        if entry_id == "shared":
            continue
        if not isinstance(entry_data, dict):
            continue
        if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
            continue

        coil_instance = entry_data.get("instance")
        if coil_instance is None:
            continue

        enable_entity_id = coil_instance.SWITCH_ENTITY_ENABLE
        if enable_entity_id:
            await hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": enable_entity_id},
            )
            LOGGER.debug("Turned ON: %s", enable_entity_id)

def get_modbus_node_instance(hass: HomeAssistant, modbus_node_entry_id: str):
    """Vráti ModbusNodeInstance pre dané entry_id.
    
    Heating Coil zariadenia volajú túto funkciu aby získali referenciu
    na zdieľanú Modbus komunikačnú inštanciu.
    
    Returns:
        ModbusNodeInstance alebo None ak neexistuje.
    """
    if not modbus_node_entry_id:
        LOGGER.error("No Modbus Node entry_id configured")
        return None
    
    domain_data = hass.data.get(DOMAIN, {})
    node_data = domain_data.get(modbus_node_entry_id)
    if node_data is None:
        LOGGER.error("Modbus Node entry '%s' not found in hass.data", modbus_node_entry_id)
        return None
    
    instance = node_data.get("modbus_node_instance")
    if instance is None:
        LOGGER.error("ModbusNodeInstance not found for entry '%s'", modbus_node_entry_id)
        return None
    
    return instance

async def turn_off_all_service(call: ServiceCall) -> None:
    """Handle turn_off_all service call."""
    await handle_turn_off_all(call.hass)

async def turn_on_all_service(call: ServiceCall) -> None:
    """Handle turn_on_all service call."""
    await handle_turn_on_all(call.hass)

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    device_type = entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

    # Synchronizácia output_power_during_day_only z Master na Slave config_entries
    if device_type == DEVICE_TYPE_HEATING_COIL:
        from .helpers import get_slave_entry_ids
        slave_entry_ids = get_slave_entry_ids(hass, entry.entry_id)
        if slave_entry_ids:
            # Táto špirála je Master – synchronizovať day_only na všetky Slave
            master_day_only = entry.options.get(
                CONF_OUTPUT_POWER_DURING_DAY_ONLY,
                entry.data.get(CONF_OUTPUT_POWER_DURING_DAY_ONLY, DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY),
            )
            for slave_eid in slave_entry_ids:
                slave_entry = hass.config_entries.async_get_entry(slave_eid)
                if slave_entry is None:
                    continue
                slave_day_only = slave_entry.options.get(
                    CONF_OUTPUT_POWER_DURING_DAY_ONLY,
                    slave_entry.data.get(CONF_OUTPUT_POWER_DURING_DAY_ONLY, DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY),
                )
                if slave_day_only != master_day_only:
                    new_options = dict(slave_entry.options)
                    new_options[CONF_OUTPUT_POWER_DURING_DAY_ONLY] = master_day_only
                    hass.config_entries.async_update_entry(slave_entry, options=new_options)
                    LOGGER.debug(
                        "Master→Slave sync config_entry: output_power_during_day_only=%s → slave %s",
                        master_day_only, slave_eid[:8],
                    )

    # Reload integráciu aby sa prejavili zmeny v názvoch entít a nastaveniach
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        device_type = entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

        # General – má GENERAL_PLATFORMS
        if device_type == DEVICE_TYPE_GENERAL:
            unload_ok = await hass.config_entries.async_unload_platforms(entry, GENERAL_PLATFORMS)
            if unload_ok and DOMAIN in hass.data:
                hass.data[DOMAIN].pop(entry.entry_id, None)
            return unload_ok

        # Modbus Node – má MODBUS_NODE_PLATFORMS + modbus klienta
        if device_type == DEVICE_TYPE_MODBUS_NODE:
            if DOMAIN in hass.data and entry.entry_id in hass.data.get(DOMAIN, {}):
                node_instance = hass.data[DOMAIN][entry.entry_id].get("modbus_node_instance")
                if node_instance and hasattr(node_instance, 'close_modbus_client'):
                    node_instance.close_modbus_client()
            unload_ok = await hass.config_entries.async_unload_platforms(entry, MODBUS_NODE_PLATFORMS)
            if unload_ok and DOMAIN in hass.data:
                hass.data[DOMAIN].pop(entry.entry_id, None)
            return unload_ok

        # Heating Coil – plný unload
        # Zatvoriť modbus klienta pred vypnutím
        if DOMAIN in hass.data and entry.entry_id in hass.data.get(DOMAIN, {}):
            instance = hass.data[DOMAIN][entry.entry_id].get("instance")
            if instance and hasattr(instance, 'close_modbus_client'):
                instance.close_modbus_client()
                LOGGER.debug("Closed modbus client during unload")
        
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            hass.data[DOMAIN].pop(entry.entry_id, None)

        return unload_ok

    except Exception as ex:
        LOGGER.error("Error unloading entry: %s", ex)
        # Ensure we cleanup even on error
        if DOMAIN in hass.data and entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return False

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
    
