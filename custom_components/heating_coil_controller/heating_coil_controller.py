from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" heating_coil_controller.py """

"""Coordinator for Heating Coil Controller."""

from datetime import timedelta
import logging
import struct
import dataclasses
import json
import asyncio
import time
import math

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.dispatcher import async_dispatcher_send
#from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNKNOWN, STATE_UNAVAILABLE, STATE_OK, STATE_PROBLEM
from .const import *
from .heating_coil_power_automation import HeatingCoilPowerAutomation

LOGGER = logging.getLogger(__name__)

class Heating_Coil_Controller_Instance:

    def __init__(self) -> None:
#        self._Data = self.Data()
        self.settings = self.Settings()
        self._is_running = False
        self._first_cycle_done = False  # Ochrana prvého cyklu – preskočiť total power limit
        self._power_automation = HeatingCoilPowerAutomation()
        self._ramp_cancel_callback = None  # Cancel handle pre naplánovaný ramp callback
        self._last_dac_count: int | None = None  # Posledná odoslaná DAC hodnota (pre deduplikáciu)
        self._prev_solar_w: float | None = None  # Predchádzajúca hodnota solárneho senzora [W] pre nezávislú detekciu
        self._prev_solar_w_s2: float | None = None  # Predchádzajúca hodnota solárneho senzora [W] pre Strategy 2
        self._was_enabled: bool = False  # Predchádzajúci stav enable switcha pre detekciu OFF→ON

        self.hass = None
        self._entry_id = None # Budete potrebovat ulozit entry_id aj sem
        
        # Ukladaci priestor pre stavy senzorov
        self.sensor_states = {
            ENTITY_OUTPUT_POWER_PERCENT: None,
            ENTITY_OUTPUT_POWER_KW: None,
            ENTITY_ENABLE: None,
            ENTITY_MAX_POWER: None,
            ENTITY_THERMAL_PROTECTION_ACTIVE: False,
        }

        # Stav bezpečnostnej poistky – interná premenná
        self._thermal_protection_active: bool = False

        # Entity ID budú nastavené po nastavení entry_id
        self.SENSOR_ENTITY_OUTPUT_POWER_PERCENT = None
        self.SENSOR_ENTITY_OUTPUT_POWER_KW = None
        self.SWITCH_ENTITY_ENABLE = None
        self.SWITCH_ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT = None
        self.NUMBER_ENTITY_MAX_POWER = None

        # Virtualne operacne premenne pre sensory
        self.output_power_percent = None
        self.output_power_kw = None
        self.enable = None
        self.max_power = None
        self._requested_power_percent: float = 0.0  # požadovaný výkon pred aplikáciou total power limitu
    
    def setup_entity_ids(self):
        """Setup entity IDs after entry_id is set."""
        if self._entry_id:
            from .const import sanitize_device_name
            device_name_sanitized = sanitize_device_name(self.settings.device_name)
            
            self.SENSOR_ENTITY_OUTPUT_POWER_PERCENT = f"sensor.{device_name_sanitized}_{ENTITY_OUTPUT_POWER_PERCENT}"
            self.SENSOR_ENTITY_OUTPUT_POWER_KW = f"sensor.{device_name_sanitized}_{ENTITY_OUTPUT_POWER_KW}"
            self.SWITCH_ENTITY_ENABLE = f"switch.{device_name_sanitized}_{ENTITY_ENABLE}"
            self.SWITCH_ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT = f"switch.{device_name_sanitized}_{ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT}"
            self.NUMBER_ENTITY_MAX_POWER = f"number.{device_name_sanitized}_{ENTITY_MAX_POWER}"
    
    def close_modbus_client(self):
        """Zatvorí Modbus klienta – deleguje na referovaný Modbus Node."""
        modbus_node = self._get_modbus_node()
        if modbus_node is not None:
            modbus_node.close_modbus_client()

    def _get_modbus_node(self):
        """Vráti ModbusNodeInstance pre tento Heating Coil."""
        if self.hass is None or self._entry_id is None:
            return None
        from . import get_modbus_node_instance
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        modbus_node_entry_id = entry_data.get(CONF_MODBUS_NODE_ENTRY_ID, "")
        if not modbus_node_entry_id:
            return None
        return get_modbus_node_instance(self.hass, modbus_node_entry_id)

    def _get_master_instance(self):
        """Vráti inštanciu Master Heating Coil pre tento slave.

        Returns:
            Heating_Coil_Controller_Instance mastera alebo None ak nemá mastera.
        """
        if self.hass is None or self._entry_id is None:
            return None
        if self.settings.master_heating_coil_id == DEFAULT_MASTER_HEATING_COIL_ID:
            return None

        domain_data = self.hass.data.get(DOMAIN, {})
        master_data = domain_data.get(self.settings.master_heating_coil_id, {})
        if not isinstance(master_data, dict):
            return None
        return master_data.get("instance")

    def _get_slave_instances(self):
        """Vráti zoznam inštancií Slave Heating Coil pre tohto mastera.

        Returns:
            list[Heating_Coil_Controller_Instance] slave špirál (prázdny ak nemá slaves).
        """
        if self.hass is None or self._entry_id is None:
            return []

        from .helpers import get_slave_entry_ids
        slave_entry_ids = get_slave_entry_ids(self.hass, self._entry_id)
        if not slave_entry_ids:
            return []

        domain_data = self.hass.data.get(DOMAIN, {})
        slaves = []
        for sid in slave_entry_ids:
            sdata = domain_data.get(sid, {})
            if isinstance(sdata, dict):
                inst = sdata.get("instance")
                if inst is not None:
                    slaves.append(inst)
        return slaves


    @dataclasses.dataclass
    class Settings:
        # === Nastavenia dynamických parametrov ===

        # Základné konfiguračné parametre
        device_name: str = DEFAULT_DEVICE_NAME                          # názov zariadenia
        include_device_name_in_entity: bool = DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY  # zahrnúť názov zariadenia v entity
        virtual_heating_coil: bool = DEFAULT_VIRTUAL_HEATING_COIL        # virtuálna špirála (bez Modbus komunikácie)
        grid_export_status_entity = DEFAULT_CONF_GRID_EXPORT_STATUS_ENTITY            # referencia na externu entitu stavu exportu do siete
        grid_export_status_entity_available: bool = False                              # dostupnosť entity stavu exportu do siete
        grid_export_status_value = None
        output_power_during_day_only: bool = DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY  # výkon len cez deň

        # Modbus konfiguračné parametre
        modbus_connection_type: str = DEFAULT_MODBUS_CONNECTION_TYPE    # typ pripojenia: existing_node / usb / tcp / udp
        modbus_node_name: str = ""                                       # názov existujúceho Modbus nodu
        port: str = ""                                                   # USB port alebo TCP/UDP port (str kvôli USB napr. /dev/ttyUSB0)
        baudrate: int = DEFAULT_MODBUS_BAUDRATE                         # (baudrate) - len pre USB
        bytesize: int = DEFAULT_MODBUS_BYTESIZE                         # (bytesize) - len pre USB
        stopbits: int = DEFAULT_MODBUS_STOPBITS                         # (stopbits) - len pre USB
        parity: str = DEFAULT_MODBUS_PARITY                             # (parity) - len pre USB
        delay: int = DEFAULT_MODBUS_DELAY                               # (delay) - len pre USB
        message_wait_millisecond: int = DEFAULT_MODBUS_MESSAGE_WAIT     # (message_wait_millisecond)
        timeout: int = DEFAULT_MODBUS_TIMEOUT                           # (timeout)
        host: str = ""                                                   # (host) - len pre TCP/UDP
        modbus_device_id: int = DEFAULT_MODBUS_DEVICE_ID              # Modbus Device ID (1-254)
        dac_output_port_id: int = DEFAULT_DAC_OUTPUT_PORT_ID           # ID portu analógového výstupu (1-32)
        dac_output_type: str = DEFAULT_DAC_OUTPUT_TYPE                 # Typ analógového výstupu
        zero_power_point: int = DEFAULT_ZERO_POWER_POINT               # Bod nulového výkonu [%]
        maximum_power_point: int = DEFAULT_MAXIMUM_POWER_POINT         # Bod maximálneho výkonu [%]
        gamma: int = DEFAULT_GAMMA                                   # Gamma [%]
        heating_coil_power: float = DEFAULT_HEATING_COIL_POWER         # Výkon špirály [kW]
        heating_coil_total_power: float = DEFAULT_HEATING_COIL_TOTAL_POWER  # Súčtový limit výkonu [kW] – zdieľaný
        # Power control strategy
        power_control_strategy: str = DEFAULT_POWER_CONTROL_STRATEGY
        # Master heating coil
        master_heating_coil_id: str = DEFAULT_MASTER_HEATING_COIL_ID
        # Solar sensor
        solar_sensor_entity: str = DEFAULT_SOLAR_SENSOR_ENTITY
        solar_sensor_entity_available: bool = False
        solar_sensor_unit: str = DEFAULT_SENSOR_UNIT
        maximum_solar_radiation_value: float = DEFAULT_MAXIMUM_SOLAR_RADIATION_VALUE  # vždy vo W (prepočítané z kW ak treba)
        solar_radiation_value_percent: float = 0.0  # aktuálna hodnota solárneho senzora v % voči maximu
        solar_sensor_attenuation: int = DEFAULT_SOLAR_SENSOR_ATTENUATION
        solar_sensor_ramp_up_power_step: int = DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_STEP
        solar_sensor_ramp_up_power_cycle: int = DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE
        solar_sensor_ramp_down_power_step: int = DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP
        solar_sensor_ramp_down_power_cycle: int = DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE
        # PV power
        pv_power_entity: str = DEFAULT_PV_POWER_ENTITY
        pv_power_entity_available: bool = False
        pv_power_unit: str = DEFAULT_SENSOR_UNIT
        pv_power_max_power: float = DEFAULT_PV_POWER_MAX_POWER  # vždy vo W (prepočítané z kW ak treba)
        pv_power_max_power_percent: float = 0.0  # aktuálna hodnota PV výkonu v % voči maximu
        pv_power_ratio: int = DEFAULT_PV_POWER_RATIO
        pv_power_ramp_up_power_step: int = DEFAULT_PV_POWER_RAMP_UP_POWER_STEP
        pv_power_ramp_up_power_cycle: int = DEFAULT_PV_POWER_RAMP_UP_POWER_CYCLE
        pv_power_ramp_down_power_step: int = DEFAULT_PV_POWER_RAMP_DOWN_POWER_STEP
        pv_power_ramp_down_power_cycle: int = DEFAULT_PV_POWER_RAMP_DOWN_POWER_CYCLE
        # Power grid
        power_grid_entity: str = DEFAULT_POWER_GRID_ENTITY
        power_grid_entity_available: bool = False
        power_grid_unit: str = DEFAULT_SENSOR_UNIT
        power_grid_value_w: float = 0.0  # aktuálna hodnota z elektromera vo W (kladná=export, záporná=import)
        power_grid_dead_zone_w: int = DEFAULT_POWER_GRID_DEAD_ZONE_W  # mŕtva zóna [W]
        power_grid_offset_w: int = DEFAULT_POWER_GRID_OFFSET_W  # offset [W]
        power_grid_offset_export_limit_w: int = DEFAULT_POWER_GRID_OFFSET_EXPORT_LIMIT_W  # offset pre export limit [W]
        power_grid_ramp_up_power_step: int = DEFAULT_POWER_GRID_RAMP_UP_POWER_STEP
        power_grid_ramp_up_power_cycle: int = DEFAULT_POWER_GRID_RAMP_UP_POWER_CYCLE
        power_grid_ramp_down_power_step: int = DEFAULT_POWER_GRID_RAMP_DOWN_POWER_STEP
        power_grid_ramp_down_power_cycle: int = DEFAULT_POWER_GRID_RAMP_DOWN_POWER_CYCLE
        # Battery power
        battery_power_entity: str = DEFAULT_BATTERY_POWER_ENTITY
        battery_power_entity_available: bool = False
        battery_power_unit: str = DEFAULT_SENSOR_UNIT
        battery_power_value_w: float = 0.0  # aktuálna hodnota z batérie vo W (kladná=nabíjanie, záporná=vybíjanie)
        battery_power_dead_zone_w: int = DEFAULT_BATTERY_POWER_DEAD_ZONE_W
        battery_power_offset_w: int = DEFAULT_BATTERY_POWER_OFFSET_W
        battery_power_ramp_up_power_step: int = DEFAULT_BATTERY_POWER_RAMP_UP_POWER_STEP
        battery_power_ramp_up_power_cycle: int = DEFAULT_BATTERY_POWER_RAMP_UP_POWER_CYCLE
        battery_power_ramp_down_power_step: int = DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_STEP
        battery_power_ramp_down_power_cycle: int = DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE


        # Strategy 1 (synchronous variant of Strategy 2 – no per-ramp cycles)
        strategy_1_ramp_up_fast_power_step: int = DEFAULT_STRATEGY_1_RAMP_UP_FAST_POWER_STEP
        strategy_1_ramp_up_slow_power_step: int = DEFAULT_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP
        strategy_1_ramp_down_fast_power_step: int = DEFAULT_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP
        strategy_1_ramp_down_slow_power_step: int = DEFAULT_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP
        strategy_1_power_grid_ramp_up_fast_threshold: int = DEFAULT_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD
        strategy_1_power_grid_ramp_down_fast_threshold: int = DEFAULT_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD
        strategy_1_battery_ramp_up_fast_threshold: int = DEFAULT_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD
        strategy_1_battery_ramp_down_fast_threshold: int = DEFAULT_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD
        strategy_1_solar_sensor_ramp_down_fast_threshold: int = DEFAULT_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD
        # Strategy 1 – part 1
        strategy_1_grid_export_status_entity: str = DEFAULT_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY
        strategy_1_grid_export_status_entity_available: bool = False
        strategy_1_grid_export_status_value = None
        strategy_1_power_grid_entity: str = DEFAULT_STRATEGY_1_POWER_GRID_ENTITY
        strategy_1_power_grid_entity_available: bool = False
        strategy_1_power_grid_unit: str = DEFAULT_STRATEGY_1_POWER_GRID_UNIT
        strategy_1_power_grid_value_w: float = 0.0
        strategy_1_power_grid_dead_zone_w: int = DEFAULT_STRATEGY_1_POWER_GRID_DEAD_ZONE_W
        strategy_1_power_grid_offset_w: int = DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_W
        strategy_1_power_grid_offset_export_limit_w: int = DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W
        strategy_1_battery_charging_enablement_state: str = DEFAULT_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE
        strategy_1_battery_charging_enablement_state_available: bool = False
        strategy_1_battery_charging_enablement_state_value: str | None = None
        strategy_1_battery_state_of_charge: str = DEFAULT_STRATEGY_1_BATTERY_STATE_OF_CHARGE
        strategy_1_battery_state_of_charge_available: bool = False
        strategy_1_battery_state_of_charge_value: float = 0.0
        strategy_1_battery_power_entity: str = DEFAULT_STRATEGY_1_BATTERY_POWER_ENTITY
        strategy_1_battery_power_entity_available: bool = False
        strategy_1_battery_power_unit: str = DEFAULT_STRATEGY_1_BATTERY_POWER_UNIT
        strategy_1_battery_power_value_w: float = 0.0
        strategy_1_battery_power_dead_zone_w: int = DEFAULT_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W
        strategy_1_battery_power_offset_w: int = DEFAULT_STRATEGY_1_BATTERY_POWER_OFFSET_W
        only_use_power_above_export_limit: bool = False
        strategy_1_solar_sensor_entity: str = DEFAULT_STRATEGY_1_SOLAR_SENSOR_ENTITY
        strategy_1_solar_sensor_entity_available: bool = False
        strategy_1_solar_sensor_unit: str = DEFAULT_STRATEGY_1_SOLAR_SENSOR_UNIT
        strategy_1_maximum_solar_radiation_value: float = DEFAULT_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE
        strategy_1_solar_radiation_value_percent: float = 0.0
        strategy_1_solar_sensor_value_w: float = 0.0
        strategy_1_solar_sensor_attenuation: int = DEFAULT_STRATEGY_1_SOLAR_SENSOR_ATTENUATION

        # Thermal protection (safety fuse)
        thermal_protection_sensor_entity: str = DEFAULT_THERMAL_PROTECTION_SENSOR_ENTITY
        thermal_protection_max_temp: int = DEFAULT_THERMAL_PROTECTION_MAX_TEMP

        # ---------------------------------------------------------------
        # Strategy 2 – Grid + Solar (bez batérie)
        # ---------------------------------------------------------------
        strategy_2_grid_export_status_entity: str = DEFAULT_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY
        strategy_2_grid_export_status_entity_available: bool = False
        strategy_2_grid_export_status_value: str | None = None

        strategy_2_power_grid_entity: str = DEFAULT_STRATEGY_2_POWER_GRID_ENTITY
        strategy_2_power_grid_unit: str = DEFAULT_STRATEGY_2_POWER_GRID_UNIT
        strategy_2_power_grid_entity_available: bool = False
        strategy_2_power_grid_value_w: float = 0.0
        strategy_2_power_grid_dead_zone_w: int = DEFAULT_STRATEGY_2_POWER_GRID_DEAD_ZONE_W
        strategy_2_power_grid_offset_w: int = DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_W
        strategy_2_power_grid_offset_export_limit_w: int = DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W

        strategy_2_solar_sensor_entity: str = DEFAULT_STRATEGY_2_SOLAR_SENSOR_ENTITY
        strategy_2_solar_sensor_entity_available: bool = False
        strategy_2_solar_sensor_unit: str = DEFAULT_STRATEGY_2_SOLAR_SENSOR_UNIT
        strategy_2_maximum_solar_radiation_value: float = DEFAULT_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE
        strategy_2_solar_radiation_value_percent: float = 0.0
        strategy_2_solar_sensor_value_w: float = 0.0
        strategy_2_solar_sensor_attenuation: int = DEFAULT_STRATEGY_2_SOLAR_SENSOR_ATTENUATION

        strategy_2_ramp_up_fast_power_step: int = DEFAULT_STRATEGY_2_RAMP_UP_FAST_POWER_STEP
        strategy_2_ramp_up_slow_power_step: int = DEFAULT_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP
        strategy_2_ramp_down_fast_power_step: int = DEFAULT_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP
        strategy_2_ramp_down_slow_power_step: int = DEFAULT_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP
        strategy_2_power_grid_ramp_up_fast_threshold: int = DEFAULT_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD
        strategy_2_power_grid_ramp_down_fast_threshold: int = DEFAULT_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD
        strategy_2_solar_sensor_ramp_down_fast_threshold: int = DEFAULT_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD


# ******************************************************************************************
# ********************** Heating Coil Controller - Controller *********************************
# ******************************************************************************************

    async def my_controller(self, _notify_others: bool = True):
        """Main My Controller logic."""
        LOGGER.debug("=== MY CONTROLLER - START ===")
        
        # Mode: single - prevent concurrent runs for this instance
        if self._is_running:
            LOGGER.debug("Already running, skipping this cycle")
            return
        
        # Domain-level lock – serializuje beh naprieč všetkými Heating Coil inštanciami
        # Acquiruje sa len pri top-level volaní, nie pri vnútornom volaní z _notify_other_coils
        controller_lock = None
        if _notify_others:
            shared = self.hass.data.get(DOMAIN, {}).get("shared", {})
            controller_lock = shared.get("controller_lock")
            if controller_lock is not None:
                await controller_lock.acquire()

        self._is_running = True

# ******************************************************************************************
# ********************** LOAD CONFIGURATION ************************************************
# ******************************************************************************************

        try:
            LOGGER.debug("Cycle started")

        # Get INTERNAL ENTITIES states (Internal Entities created by this integration, Entity IDs are generated from entity names, not unique_ids)
            try:
                
                entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
                switches = entry_data.get("switches", {})
                numbers  = entry_data.get("numbers", {})

                switch_enable = switches.get(ENTITY_ENABLE)
                switch_export = switches.get(ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT)
                switch_auto_power_control = switches.get(ENTITY_AUTO_POWER_CONTROL)
                number_max_power = numbers.get(ENTITY_MAX_POWER)

                if switch_enable is None or number_max_power is None:
                    LOGGER.warning(
                        "Internal entities not yet ready (enable=%s, max_power=%s), skipping cycle",
                        switch_enable, number_max_power,
                    )
                    return

                self.enable = switch_enable.is_on
                self.settings.only_use_power_above_export_limit = (
                    switch_export.is_on if switch_export is not None else False
                )
                if number_max_power.native_value is None:
                    LOGGER.debug("max_power entity value is None, skipping cycle")
                    return
                self.max_power = float(number_max_power.native_value)

                # Ak je auto_power_control vypnutý, riadiť výkon len manuálne
                # bez ohľadu na stratégiu v konfigurácii – platí len pre tento cyklus
                auto_power_control_on = switch_auto_power_control.is_on if switch_auto_power_control is not None else True
                effective_strategy = self.settings.power_control_strategy
                if not auto_power_control_on:
                    effective_strategy = POWER_CONTROL_STRATEGY_MANUAL
                    LOGGER.debug("auto_power_control OFF – overriding strategy to MANUAL for this cycle")

                LOGGER.debug("Internal Entity States: self.enable=%s, self.max_power=%s, auto_power_control=%s, effective_strategy=%s",
                            self.enable, self.max_power, auto_power_control_on, effective_strategy)

            except Exception as e:
                LOGGER.error(f"Failed to load entities created by this integration. Error details: {e}")
                return

        # Ak je špirála vypnutá, preskočiť celý algoritmus
            if not self.enable and _notify_others:
                self._requested_power_percent = 0.0
                self._power_automation.sync_output(0.0)
                self.sensor_states[ENTITY_OUTPUT_POWER_PERCENT] = 0.0
                self.sensor_states[ENTITY_OUTPUT_POWER_KW] = 0.0
                if not self.settings.virtual_heating_coil:
                    await self._send_dac_value(0.0)
                self._was_enabled = False
                LOGGER.debug("Coil disabled, skipping algorithm")
                return

        # Detekcia prechodu OFF → ON: resetovať internú rampu na 0
            if self.enable and not self._was_enabled:
                self._power_automation.sync_output(0.0)
                LOGGER.debug("Coil just enabled, resetting ramp to 0%%")
            self._was_enabled = self.enable

        # Dynamické nastavenie heating_coil_power pre Master špirály (súčet výkonov Slave špirál)
        # + jednosmerná synchronizácia output_power_during_day_only z Master na Slave
            slave_instances = self._get_slave_instances()
            if slave_instances:
                # Master: heating_coil_power = súčet Slave heating_coil_power
                sum_slave_power = sum(s.settings.heating_coil_power for s in slave_instances)
                if sum_slave_power > 0:
                    self.settings.heating_coil_power = sum_slave_power
                    LOGGER.debug(
                        "Master: heating_coil_power dynamically set to %.1f kW (sum of %d slaves)",
                        sum_slave_power, len(slave_instances),
                    )

                # Synchronizácia output_power_during_day_only z Master na Slave
                for slave in slave_instances:
                    if slave.settings.output_power_during_day_only != self.settings.output_power_during_day_only:
                        slave.settings.output_power_during_day_only = self.settings.output_power_during_day_only
                        LOGGER.debug(
                            "Master→Slave sync: output_power_during_day_only = %s",
                            self.settings.output_power_during_day_only,
                        )

        # Get EXTERNAL ENTITIES states (External Entities defined by user in the configuration of this integration)
        # Používa _get_sensor_value() ktorý preferuje priemerované hodnoty z debounce periódy

        # **** Get grid export status entity **************************************************************
            try:
                if self.settings.grid_export_status_entity:
                    val = self._get_sensor_value(self.settings.grid_export_status_entity)
                    if val is not None:
                        self.settings.grid_export_status_entity_available = True
                        self.settings.grid_export_status_value = str(val) if not isinstance(val, str) else val
                        LOGGER.debug("Grid export status value = %s", self.settings.grid_export_status_value)
                    else:
                        LOGGER.warning(f"Sensor {self.settings.grid_export_status_entity} is not available!")
                        self.settings.grid_export_status_entity_available = False
                        self.settings.grid_export_status_value = None
                else:
                    self.settings.grid_export_status_entity_available = False
                    self.settings.grid_export_status_value = None

            except (ValueError, TypeError) as e:
                LOGGER.error(f"Could not convert grid_export_status sensor: {e}")
                self.settings.grid_export_status_entity_available = False
                self.settings.grid_export_status_value = None

        # **** Get solar sensor entity ****************************************************************
            try:
                if self.settings.solar_sensor_entity:
                    val = self._get_sensor_value(self.settings.solar_sensor_entity)
                    if val is not None and isinstance(val, (int, float)):
                        self.settings.solar_sensor_entity_available = True
                        solar_value_raw = float(val)
                        if self.settings.solar_sensor_unit == "kW":
                            solar_value_w = solar_value_raw * 1000
                        else:
                            solar_value_w = solar_value_raw
                        if self.settings.maximum_solar_radiation_value > 0:
                            self.settings.solar_radiation_value_percent = max(0.0, min(100.0, round(
                                (solar_value_w / self.settings.maximum_solar_radiation_value) * 100, 2
                            )))
                        else:
                            self.settings.solar_radiation_value_percent = 0.0
                        LOGGER.debug("Solar sensor: raw=%.2f, value_w=%.1f, percent=%.2f%%",
                                    solar_value_raw, solar_value_w, self.settings.solar_radiation_value_percent)
                    else:
                        LOGGER.warning(f"Sensor {self.settings.solar_sensor_entity} is not available!")
                        self.settings.solar_sensor_entity_available = False
                        self.settings.solar_radiation_value_percent = 0.0
                else:
                    self.settings.solar_sensor_entity_available = False
                    self.settings.solar_radiation_value_percent = 0.0

            except (ValueError, TypeError) as e:
                LOGGER.error(f"Could not check solar_sensor_entity: {e}")
                self.settings.solar_sensor_entity_available = False
                self.settings.solar_radiation_value_percent = 0.0

        # **** Get PV power entity ********************************************************************
            try:
                if self.settings.pv_power_entity:
                    val = self._get_sensor_value(self.settings.pv_power_entity)
                    if val is not None and isinstance(val, (int, float)):
                        self.settings.pv_power_entity_available = True
                        pv_value_raw = float(val)
                        if self.settings.pv_power_unit == "kW":
                            pv_value_w = pv_value_raw * 1000
                        else:
                            pv_value_w = pv_value_raw
                        if self.settings.pv_power_max_power > 0:
                            self.settings.pv_power_max_power_percent = max(0.0, min(100.0, round(
                                (pv_value_w / self.settings.pv_power_max_power) * 100, 2
                            )))
                        else:
                            self.settings.pv_power_max_power_percent = 0.0
                        LOGGER.debug("PV power: raw=%.2f, value_w=%.1f, percent=%.2f%%",
                                    pv_value_raw, pv_value_w, self.settings.pv_power_max_power_percent)
                    else:
                        LOGGER.warning(f"Sensor {self.settings.pv_power_entity} is not available!")
                        self.settings.pv_power_entity_available = False
                        self.settings.pv_power_max_power_percent = 0.0
                else:
                    self.settings.pv_power_entity_available = False
                    self.settings.pv_power_max_power_percent = 0.0

            except (ValueError, TypeError) as e:
                LOGGER.error(f"Could not check pv_power_entity: {e}")
                self.settings.pv_power_entity_available = False
                self.settings.pv_power_max_power_percent = 0.0

        # **** Get power grid entity ******************************************************************
            try:
                if self.settings.power_grid_entity:
                    val = self._get_sensor_value(self.settings.power_grid_entity)
                    if val is not None and isinstance(val, (int, float)):
                        self.settings.power_grid_entity_available = True
                        power_grid_raw = float(val)
                        if self.settings.power_grid_unit == "kW":
                            self.settings.power_grid_value_w = power_grid_raw * 1000
                        else:
                            self.settings.power_grid_value_w = power_grid_raw
                        LOGGER.debug("Power grid: raw=%.2f, value_w=%.1f",
                                    power_grid_raw, self.settings.power_grid_value_w)
                    else:
                        LOGGER.warning(f"Sensor {self.settings.power_grid_entity} is not available!")
                        self.settings.power_grid_entity_available = False
                        self.settings.power_grid_value_w = 0.0
                else:
                    self.settings.power_grid_entity_available = False
                    self.settings.power_grid_value_w = 0.0

            except (ValueError, TypeError) as e:
                LOGGER.error(f"Could not check power_grid_entity: {e}")
                self.settings.power_grid_entity_available = False
                self.settings.power_grid_value_w = 0.0

        # **** Get battery power entity ***************************************************************
            try:
                if self.settings.battery_power_entity:
                    val = self._get_sensor_value(self.settings.battery_power_entity)
                    if val is not None and isinstance(val, (int, float)):
                        self.settings.battery_power_entity_available = True
                        battery_power_raw = float(val)
                        if self.settings.battery_power_unit == "kW":
                            self.settings.battery_power_value_w = battery_power_raw * 1000
                        else:
                            self.settings.battery_power_value_w = battery_power_raw
                        LOGGER.debug("Battery power: raw=%.2f, value_w=%.1f",
                                    battery_power_raw, self.settings.battery_power_value_w)
                    else:
                        LOGGER.warning(f"Sensor {self.settings.battery_power_entity} is not available!")
                        self.settings.battery_power_entity_available = False
                        self.settings.battery_power_value_w = 0.0
                else:
                    self.settings.battery_power_entity_available = False
                    self.settings.battery_power_value_w = 0.0

            except (ValueError, TypeError) as e:
                LOGGER.error(f"Could not check battery_power_entity: {e}")
                self.settings.battery_power_entity_available = False
                self.settings.battery_power_value_w = 0.0


        # **** Get Strategy 1 sensor entities (ak je aktívna Strategy 1) ****
            if self.settings.power_control_strategy == POWER_CONTROL_STRATEGY_1:
                try:
                    # Grid export status
                    if self.settings.strategy_1_grid_export_status_entity:
                        val = self._get_sensor_value(self.settings.strategy_1_grid_export_status_entity)
                        if val is not None:
                            self.settings.strategy_1_grid_export_status_entity_available = True
                            self.settings.strategy_1_grid_export_status_value = str(val) if not isinstance(val, str) else val
                        else:
                            LOGGER.warning("Strategy 1 grid export status entity %s is not available", self.settings.strategy_1_grid_export_status_entity)
                            self.settings.strategy_1_grid_export_status_entity_available = False
                            self.settings.strategy_1_grid_export_status_value = None
                    else:
                        self.settings.strategy_1_grid_export_status_entity_available = False
                        self.settings.strategy_1_grid_export_status_value = None

                    # Solar sensor
                    if self.settings.strategy_1_solar_sensor_entity:
                        val = self._get_sensor_value(self.settings.strategy_1_solar_sensor_entity)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_1_solar_sensor_entity_available = True
                            s1_solar_raw = float(val)
                            s1_solar_w = s1_solar_raw * 1000 if self.settings.strategy_1_solar_sensor_unit == "kW" else s1_solar_raw
                            self.settings.strategy_1_solar_sensor_value_w = s1_solar_w
                            if self.settings.strategy_1_maximum_solar_radiation_value > 0:
                                self.settings.strategy_1_solar_radiation_value_percent = max(0.0, min(100.0, round(
                                    (s1_solar_w / self.settings.strategy_1_maximum_solar_radiation_value) * 100, 2)))
                            else:
                                self.settings.strategy_1_solar_radiation_value_percent = 0.0
                        else:
                            LOGGER.warning("Strategy 1 solar sensor %s is not available", self.settings.strategy_1_solar_sensor_entity)
                            self.settings.strategy_1_solar_sensor_entity_available = False
                            self.settings.strategy_1_solar_radiation_value_percent = 0.0
                            self.settings.strategy_1_solar_sensor_value_w = 0.0
                    else:
                        self.settings.strategy_1_solar_sensor_entity_available = False
                        self.settings.strategy_1_solar_radiation_value_percent = 0.0
                        self.settings.strategy_1_solar_sensor_value_w = 0.0

                    # Power grid
                    if self.settings.strategy_1_power_grid_entity:
                        val = self._get_sensor_value(self.settings.strategy_1_power_grid_entity)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_1_power_grid_entity_available = True
                            s1_grid_raw = float(val)
                            self.settings.strategy_1_power_grid_value_w = s1_grid_raw * 1000 if self.settings.strategy_1_power_grid_unit == "kW" else s1_grid_raw
                        else:
                            LOGGER.warning("Strategy 1 power grid sensor %s is not available", self.settings.strategy_1_power_grid_entity)
                            self.settings.strategy_1_power_grid_entity_available = False
                            self.settings.strategy_1_power_grid_value_w = 0.0
                    else:
                        self.settings.strategy_1_power_grid_entity_available = False
                        self.settings.strategy_1_power_grid_value_w = 0.0

                    # Battery charging enablement state (ON/OFF)
                    if self.settings.strategy_1_battery_charging_enablement_state:
                        val = self._get_sensor_value(self.settings.strategy_1_battery_charging_enablement_state)
                        if val is not None:
                            self.settings.strategy_1_battery_charging_enablement_state_available = True
                            self.settings.strategy_1_battery_charging_enablement_state_value = str(val) if not isinstance(val, str) else val
                        else:
                            self.settings.strategy_1_battery_charging_enablement_state_available = False
                            self.settings.strategy_1_battery_charging_enablement_state_value = None
                    else:
                        self.settings.strategy_1_battery_charging_enablement_state_available = False
                        self.settings.strategy_1_battery_charging_enablement_state_value = None

                    # Battery State of Charge (SOC) 0-100
                    if self.settings.strategy_1_battery_state_of_charge:
                        val = self._get_sensor_value(self.settings.strategy_1_battery_state_of_charge)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_1_battery_state_of_charge_available = True
                            self.settings.strategy_1_battery_state_of_charge_value = max(0.0, min(100.0, float(val)))
                        else:
                            self.settings.strategy_1_battery_state_of_charge_available = False
                            self.settings.strategy_1_battery_state_of_charge_value = 0.0
                    else:
                        self.settings.strategy_1_battery_state_of_charge_available = False
                        self.settings.strategy_1_battery_state_of_charge_value = 0.0

                    # Battery power
                    if self.settings.strategy_1_battery_power_entity:
                        val = self._get_sensor_value(self.settings.strategy_1_battery_power_entity)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_1_battery_power_entity_available = True
                            s1_batt_raw = float(val)
                            self.settings.strategy_1_battery_power_value_w = s1_batt_raw * 1000 if self.settings.strategy_1_battery_power_unit == "kW" else s1_batt_raw
                        else:
                            LOGGER.warning("Strategy 1 battery power sensor %s is not available", self.settings.strategy_1_battery_power_entity)
                            self.settings.strategy_1_battery_power_entity_available = False
                            self.settings.strategy_1_battery_power_value_w = 0.0
                    else:
                        self.settings.strategy_1_battery_power_entity_available = False
                        self.settings.strategy_1_battery_power_value_w = 0.0

                except Exception as e:
                    LOGGER.error(f"Error reading Strategy 1 sensors: {e}")


        # **** Get Strategy 2 sensor entities (ak je aktívna Strategy 2) ****
            if effective_strategy == POWER_CONTROL_STRATEGY_2:
                try:
                    # Grid export status
                    if self.settings.strategy_2_grid_export_status_entity:
                        val = self._get_sensor_value(self.settings.strategy_2_grid_export_status_entity)
                        if val is not None:
                            self.settings.strategy_2_grid_export_status_entity_available = True
                            self.settings.strategy_2_grid_export_status_value = str(val) if not isinstance(val, str) else val
                        else:
                            LOGGER.warning("Strategy 2 grid export status entity %s is not available", self.settings.strategy_2_grid_export_status_entity)
                            self.settings.strategy_2_grid_export_status_entity_available = False
                            self.settings.strategy_2_grid_export_status_value = None
                    else:
                        self.settings.strategy_2_grid_export_status_entity_available = False
                        self.settings.strategy_2_grid_export_status_value = None

                    # Solar sensor
                    if self.settings.strategy_2_solar_sensor_entity:
                        val = self._get_sensor_value(self.settings.strategy_2_solar_sensor_entity)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_2_solar_sensor_entity_available = True
                            s2_solar_raw = float(val)
                            s2_solar_w = s2_solar_raw * 1000 if self.settings.strategy_2_solar_sensor_unit == "kW" else s2_solar_raw
                            self.settings.strategy_2_solar_sensor_value_w = s2_solar_w
                            if self.settings.strategy_2_maximum_solar_radiation_value > 0:
                                self.settings.strategy_2_solar_radiation_value_percent = max(0.0, min(100.0, round(
                                    (s2_solar_w / self.settings.strategy_2_maximum_solar_radiation_value) * 100, 2)))
                            else:
                                self.settings.strategy_2_solar_radiation_value_percent = 0.0
                        else:
                            LOGGER.warning("Strategy 2 solar sensor %s is not available", self.settings.strategy_2_solar_sensor_entity)
                            self.settings.strategy_2_solar_sensor_entity_available = False
                            self.settings.strategy_2_solar_radiation_value_percent = 0.0
                            self.settings.strategy_2_solar_sensor_value_w = 0.0
                    else:
                        self.settings.strategy_2_solar_sensor_entity_available = False
                        self.settings.strategy_2_solar_radiation_value_percent = 0.0
                        self.settings.strategy_2_solar_sensor_value_w = 0.0

                    # Power grid
                    if self.settings.strategy_2_power_grid_entity:
                        val = self._get_sensor_value(self.settings.strategy_2_power_grid_entity)
                        if val is not None and isinstance(val, (int, float)):
                            self.settings.strategy_2_power_grid_entity_available = True
                            s2_grid_raw = float(val)
                            self.settings.strategy_2_power_grid_value_w = s2_grid_raw * 1000 if self.settings.strategy_2_power_grid_unit == "kW" else s2_grid_raw
                        else:
                            LOGGER.warning("Strategy 2 power grid sensor %s is not available", self.settings.strategy_2_power_grid_entity)
                            self.settings.strategy_2_power_grid_entity_available = False
                            self.settings.strategy_2_power_grid_value_w = 0.0
                    else:
                        self.settings.strategy_2_power_grid_entity_available = False
                        self.settings.strategy_2_power_grid_value_w = 0.0

                except Exception as e:
                    LOGGER.error(f"Error reading Strategy 2 sensors: {e}")
# ******************************************************************************************

            # Automatické riadenie výkonu (power automation)
            master_instance = self._get_master_instance()

            if master_instance is not None:
                # SLAVE: prebrať výkon od mastera namiesto vlastnej stratégie
                effective_max_power = min(master_instance._requested_power_percent, self.max_power)
                LOGGER.debug(
                    "SLAVE mode: master_requested=%.1f%%, own_max_power=%.1f%%, effective_max_power=%.1f%%",
                    master_instance._requested_power_percent, self.max_power, effective_max_power,
                )
            else:
                # MASTER alebo nezávislá špirálka: vlastná automatizácia
                if _notify_others:
                    # Periodický beh – plné vyhodnotenie stratégie
                    # Dočasne aplikovať effective_strategy (môže byť MANUAL kvôli auto_power_control)
                    _original_strategy = self.settings.power_control_strategy
                    self.settings.power_control_strategy = effective_strategy
                    automation_output = self._power_automation.power_automation(self.settings)
                    self.settings.power_control_strategy = _original_strategy
                else:
                    # Notifikácia z iného coilu – len prepočet výstupu z aktuálneho stavu
                    # (stratégia sa nevyhodnocuje znova, aby sa zabránilo viacnásobným krokom)
                    automation_output = self._power_automation._current_output
                # Power automation riadi výkon priamo, Max Power slúži len ako horný strop
                effective_max_power = min(float(automation_output), self.max_power)
                LOGGER.debug(
                    "PowerAutomation: output=%d%%, max_power=%.1f%%, effective_max_power=%.1f%%, full_eval=%s",
                    automation_output, self.max_power, effective_max_power, _notify_others,
                )

            # Vypočítať výstupný výkon (rešpektuje enable switch)
            if self.enable:
                output_power = self.calculate_output_power(
                    max_power=effective_max_power,
                )
                # Uložiť požadovaný výkon pred aplikáciou total power limitu
                self._requested_power_percent = output_power
                output_power = self.apply_total_power_limit(output_power)
            else:
                self._requested_power_percent = 0.0
                output_power = 0.0

            # Obmedzenie výkonu len na denné hodiny (noc = 0)
            if self.settings.output_power_during_day_only and output_power > 0.0:
                if self._is_night():
                    LOGGER.debug("Night detected, output_power forced to 0 (day-only mode)")
                    output_power = 0.0

            # Bezpečnostná poistka proti prehriatiu – má prednosť pred všetkým ostatným
            # Kontroluje sa len pre fyzické špirály (nie virtuálne)
            if not self.settings.virtual_heating_coil:
                if self.check_thermal_protection():
                    LOGGER.warning(
                        "Thermal protection active – forcing output_power to 0 (was %.1f%%)",
                        output_power,
                    )
                    output_power = 0.0

            # Synchronizovať interný stav power_automation na skutočný výstupný výkon
            # (aby rampa pri ďalšom cykle krokovala od skutočného výkonu, nie od interného)
            self._power_automation.sync_output(output_power)

            # Naplánuj ďalší cyklus rampy (po sync, aby ramp_active reflektoval skutočný stav)
            self._schedule_ramp_callback()

            # Vypočítať výkon v kW
            if self.settings.virtual_heating_coil:
                # Virtuálna špirála: output_power_kw = súčet kW slave špirál
                slave_instances = self._get_slave_instances()
                output_power_kw = 0.0
                for slave in slave_instances:
                    slave_kw = slave.sensor_states.get(ENTITY_OUTPUT_POWER_KW)
                    if slave_kw is not None:
                        try:
                            output_power_kw += float(slave_kw)
                        except (ValueError, TypeError):
                            pass
                output_power_kw = round(output_power_kw, 1)
                # Prepočet percent z kW
                if self.settings.heating_coil_power > 0:
                    output_power = round((output_power_kw / self.settings.heating_coil_power) * 100.0, 2)
                    output_power = max(0.0, min(100.0, output_power))
                else:
                    output_power = 0.0
                LOGGER.debug(
                    "Virtual coil: output_power_kw=%.1f kW (sum of %d slaves), output_power=%.1f%%",
                    output_power_kw, len(slave_instances), output_power,
                )
            else:
                output_power_kw = round((output_power / 100.0) * self.settings.heating_coil_power, 1)

            self.sensor_states[ENTITY_OUTPUT_POWER_PERCENT] = output_power
            self.sensor_states[ENTITY_OUTPUT_POWER_KW] = output_power_kw
            
            LOGGER.debug("output_power = %s %%, output_power_kw = %s kW",
                        output_power, output_power_kw)            

            # Vypočítať a odoslať DAC výstup
            dac_value = self.calculate_dac_output(
                power=output_power,
                enable=self.enable,
                zero_power_point=self.settings.zero_power_point,
                maximum_power_point=self.settings.maximum_power_point,
                gamma=self.settings.gamma,
            )
            LOGGER.debug(
                "Power curve: enable=%s, output_power=%.1f, zero=%d, max=%d, gamma=%d → DAC=%.2f",
                self.enable, output_power,
                self.settings.zero_power_point, self.settings.maximum_power_point,
                self.settings.gamma, dac_value,
            )
            await self._send_dac_value(dac_value)

            # Notifikovať ostatné coily aby prepočítali výkon (total power limit)
            if _notify_others:
                await self._notify_other_coils()

            # Virtuálna špirála: po prepočte Slave špirál znovu prečítať ich aktuálne hodnoty
            if self.settings.virtual_heating_coil:
                slave_instances = self._get_slave_instances()
                output_power_kw = 0.0
                for slave in slave_instances:
                    slave_kw = slave.sensor_states.get(ENTITY_OUTPUT_POWER_KW)
                    if slave_kw is not None:
                        try:
                            output_power_kw += float(slave_kw)
                        except (ValueError, TypeError):
                            pass
                output_power_kw = round(output_power_kw, 1)
                if self.settings.heating_coil_power > 0:
                    output_power = round((output_power_kw / self.settings.heating_coil_power) * 100.0, 2)
                    output_power = max(0.0, min(100.0, output_power))
                else:
                    output_power = 0.0
                self.sensor_states[ENTITY_OUTPUT_POWER_PERCENT] = output_power
                self.sensor_states[ENTITY_OUTPUT_POWER_KW] = output_power_kw
                # Synchronizovať internú rampu na skutočný výkon Slave špirál
                # ALE len ak je pokles výrazný (napr. kvôli total power limitu).
                # Malé rozdiely spôsobené zaokrúhlením kW na slave-och sa ignorujú,
                # aby sa zabránilo stall-u (krok 1% sa stráca v zaokrúhlení).
                current_internal = self._power_automation._current_output
                if output_power < current_internal - 2.0:
                    self._power_automation.sync_output(output_power)
                    LOGGER.debug(
                        "Virtual coil sync DOWN (power limit): internal %.1f%% → actual %.1f%%",
                        current_internal, output_power,
                    )
                self._requested_power_percent = output_power
                LOGGER.debug(
                    "Virtual coil (after slave recalc): output_power_kw=%.1f kW, output_power=%.1f%%",
                    output_power_kw, output_power,
                )

# ******************************************************************************************
# ********************** KONIEC LOGIKY CONTROLLERA *****************************************
# ******************************************************************************************

            LOGGER.debug("Control cycle completed with sucess")
            
        except Exception as e:
            LOGGER.error(f"Error !!! {e}")
            return

        finally:

            # Aktualizácia sensorov tohto coilu cez dispatcher
            async_dispatcher_send(self.hass, f"{DOMAIN}_feedback_update_{self._entry_id}")

            # Aktualizácia celkového výkonu v General zariadení – len z top-level volania,
            # nie z vnútorného volania _notify_other_coils (zabráni medzistavom v total_power)
            if _notify_others:
                async_dispatcher_send(self.hass, f"{DOMAIN}_total_power_update")

            self._first_cycle_done = True
            self._is_running = False

            # Uvoľniť domain-level lock
            if controller_lock is not None and controller_lock.locked():
                controller_lock.release()

# ******************************************************************************************
# ************************ Pomocné metódy **************************************************
# ******************************************************************************************

    async def async_handle_solar_decrease(self):
        """Nezávislý handler poklesu solárneho senzora – beží okamžite pri zmene entity.

        Tento handler je nezávislý od periodického my_controller.
        Detekuje pokles solárneho výkonu a okamžite zníži výkon špirály
        bez čakania na tracked_entities_interval.
        """
        # Určiť aktívnu stratégiu (s ohľadom na auto_power_control override)
        _entry_data_h = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        _sw_apc = _entry_data_h.get("switches", {}).get(ENTITY_AUTO_POWER_CONTROL)
        _apc_on = _sw_apc.is_on if _sw_apc is not None else True
        active_strategy = self.settings.power_control_strategy
        if not _apc_on:
            active_strategy = POWER_CONTROL_STRATEGY_MANUAL

        if active_strategy == POWER_CONTROL_STRATEGY_1:
            await self._solar_decrease_handler(
                solar_entity=self.settings.strategy_1_solar_sensor_entity,
                solar_unit=self.settings.strategy_1_solar_sensor_unit,
                prev_attr="_prev_solar_w",
                threshold=self.settings.strategy_1_solar_sensor_ramp_down_fast_threshold,
                fast_step=self.settings.strategy_1_ramp_down_fast_power_step,
                slow_step=self.settings.strategy_1_ramp_down_slow_power_step,
                attenuation=self.settings.strategy_1_solar_sensor_attenuation,
                strategy_label="Strategy 1",
            )
        elif active_strategy == POWER_CONTROL_STRATEGY_2:
            await self._solar_decrease_handler(
                solar_entity=self.settings.strategy_2_solar_sensor_entity,
                solar_unit=self.settings.strategy_2_solar_sensor_unit,
                prev_attr="_prev_solar_w_s2",
                threshold=self.settings.strategy_2_solar_sensor_ramp_down_fast_threshold,
                fast_step=self.settings.strategy_2_ramp_down_fast_power_step,
                slow_step=self.settings.strategy_2_ramp_down_slow_power_step,
                attenuation=self.settings.strategy_2_solar_sensor_attenuation,
                strategy_label="Strategy 2",
            )

    async def _solar_decrease_handler(
        self,
        solar_entity: str,
        solar_unit: str,
        prev_attr: str,
        threshold: float,
        fast_step: float,
        slow_step: float,
        attenuation: int,
        strategy_label: str,
    ):
        """Spoločná logika solar decrease handlera pre Strategy 1 aj Strategy 2."""
        if not solar_entity:
            return

        # Ak je špirála vypnutá, preskočiť
        if self.hass.states.is_state(self.SWITCH_ENTITY_ENABLE, STATE_OFF):
            return

        # Ak práve beží my_controller, preskočiť – prevezme to my_controller
        if self._is_running:
            LOGGER.debug("Solar handler (%s): my_controller is running, skipping", strategy_label)
            return

        val = self._get_sensor_value(solar_entity)
        if val is None or not isinstance(val, (int, float)):
            return

        solar_raw = float(val)
        solar_w = solar_raw * 1000 if solar_unit == "kW" else solar_raw

        prev_w = getattr(self, prev_attr)
        setattr(self, prev_attr, solar_w)

        if prev_w is None or solar_w >= prev_w:
            return

        decrease_w = prev_w - solar_w

        if decrease_w > threshold:
            raw_step = float(fast_step)
        else:
            raw_step = float(slow_step)

        solar_step = raw_step * (attenuation / 100.0)
        if solar_step <= 0:
            return

        old_output = self._power_automation._current_output
        new_output = max(0.0, old_output - solar_step)
        self._power_automation._current_output = new_output

        LOGGER.debug(
            "Solar independent handler (%s): %.1f%% → %.1f%% (raw_step=%.0f%%, attenuation=%d%%, "
            "effective=%.1f%%, decrease=%.0fW, %s)",
            strategy_label, old_output, new_output, raw_step, attenuation, solar_step, decrease_w,
            "FAST" if decrease_w > threshold else "slow",
        )

        # Okamžitá aktualizácia výstupu – zjednodušený pipeline
        self._is_running = True
        try:
            _entry_data  = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
            _switches    = _entry_data.get("switches", {})
            _numbers     = _entry_data.get("numbers", {})
            _sw_enable   = _switches.get(ENTITY_ENABLE)
            _nb_max_power = _numbers.get(ENTITY_MAX_POWER)
            if _sw_enable is None or _nb_max_power is None or _nb_max_power.native_value is None:
                LOGGER.debug("Solar handler (%s): internal entities not ready, skipping", strategy_label)
                return
            self.enable = _sw_enable.is_on
            self.max_power = float(_nb_max_power.native_value)

            effective_max_power = min(new_output, self.max_power)

            if self.enable:
                output_power = self.calculate_output_power(max_power=effective_max_power)
                self._requested_power_percent = output_power
                output_power = self.apply_total_power_limit(output_power)
            else:
                self._requested_power_percent = 0.0
                output_power = 0.0

            if self.settings.output_power_during_day_only and output_power > 0.0:
                if self._is_night():
                    output_power = 0.0

            # Bezpečnostná poistka
            if not self.settings.virtual_heating_coil:
                if self.check_thermal_protection():
                    output_power = 0.0

            self._power_automation.sync_output(output_power)

            if not self.settings.virtual_heating_coil:
                output_power_kw = round((output_power / 100.0) * self.settings.heating_coil_power, 1)
                self.sensor_states[ENTITY_OUTPUT_POWER_PERCENT] = output_power
                self.sensor_states[ENTITY_OUTPUT_POWER_KW] = output_power_kw

                dac_value = self.calculate_dac_output(
                    power=output_power,
                    enable=self.enable,
                    zero_power_point=self.settings.zero_power_point,
                    maximum_power_point=self.settings.maximum_power_point,
                    gamma=self.settings.gamma,
                )
                await self._send_dac_value(dac_value)

                LOGGER.debug(
                    "Solar handler (%s) output: power=%.1f%%, kW=%.1f, DAC=%.2f",
                    strategy_label, output_power, output_power_kw, dac_value,
                )

            async_dispatcher_send(self.hass, f"{DOMAIN}_feedback_update_{self._entry_id}")

        except Exception as e:
            LOGGER.error(f"Solar handler error ({strategy_label}): {e}")
        finally:
            self._is_running = False

    def _get_sensor_value(self, entity_id: str) -> float | str | None:
        """Načíta aktuálnu hodnotu senzora z HA states.

        Args:
            entity_id: entity_id senzora

        Returns:
            float hodnota, str pre non-numerické, alebo None ak nedostupný
        """
        if not entity_id:
            return None
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            return None
        if state_obj.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_NONE, None):
            return None
        try:
            return float(state_obj.state)
        except (ValueError, TypeError):
            return state_obj.state

    def _schedule_ramp_callback(self) -> None:
        """Naplánuj ďalší cyklus controllera ak je rampa aktívna."""
        # Zruš predchádzajúci naplánovaný callback ak existuje
        if self._ramp_cancel_callback is not None:
            self._ramp_cancel_callback()
            self._ramp_cancel_callback = None

        if self._power_automation.ramp_active:
            delay = self._power_automation.next_ramp_delay
            LOGGER.debug("Ramp active, scheduling next cycle in %.1fs", delay)

            @callback
            def _ramp_callback(_now=None):
                """Callback pre ďalší krok rampy."""
                self._ramp_cancel_callback = None
                self.hass.async_create_task(self.my_controller())

            self._ramp_cancel_callback = async_call_later(
                self.hass, delay, _ramp_callback
            )
        else:
            LOGGER.debug("Ramp not active, no next cycle scheduled")

    async def _send_dac_value(self, dac_value: float) -> None:
        """Odošle vypočítanú DAC hodnotu na Modbus.

        Preskočí zápis ak sa hodnota nezmenila oproti poslednej odoslanej.
        Preskočí zápis ak je virtuálna špirála (nemá Modbus komunikáciu).

        Args:
            dac_value: hodnota DAC výstupu (0-100 %) z calculate_dac_output
        """
        # Virtuálna špirála nekomunikuje s Modbus Node
        if self.settings.virtual_heating_coil:
            LOGGER.debug("Virtual heating coil – skipping Modbus DAC write (dac_value=%.2f)", dac_value)
            return

        try:
            from . import get_modbus_node_instance

            entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
            modbus_node_entry_id = entry_data.get(CONF_MODBUS_NODE_ENTRY_ID, "")

            modbus_node = get_modbus_node_instance(self.hass, modbus_node_entry_id)
            if modbus_node is None:
                LOGGER.error("Cannot send DAC output: no Modbus Node available")
                return

            device_id = modbus_node.settings.modbus_device_id
            command = 6  # Write Single Register (0x06)
            port_id = self.settings.dac_output_port_id
            address = int(port_id) - 1  # Adresa 0-31
            dac_ratio = modbus_node.dac_conversion_ratio
            count = int(dac_value * dac_ratio)

            # Preskočiť zápis ak sa hodnota nezmenila
            if count == self._last_dac_count:
                LOGGER.debug("DAC value unchanged (%d), skipping Modbus write", count)
                return

            LOGGER.debug(
                "Sending DAC via ModbusNode [%s]: device_id=%d, command=0x%02x, "
                "port_id=%d, address=%d, value=%d (dac_value=%.2f, ratio=%.2f)",
                modbus_node_entry_id[:8], device_id, command, port_id, address, count, dac_value, dac_ratio,
            )

            result = await modbus_node.modbus_communication(
                device_id=device_id,
                command=command,
                address=address,
                count=count,
            )

            if result['success']:
                self._last_dac_count = count
                LOGGER.debug("DAC write successful (value=%d)", count)
            else:
                LOGGER.error("DAC write failed: %s", result['error'])

        except Exception as e:
            LOGGER.error("Error sending DAC output: %s", e)

    async def modbus_communication(
        self,
        device_id: int,
        command: int,
        address: int,
        count: int
    ) -> dict:
        """
        Modbus komunikácia – deleguje na referovaný ModbusNodeInstance.
        
        Args:
            device_id: Modbus ID zariadenia (1 Byte)
            command: Modbus príkaz/funkčný kód (1 Byte) - napr. 03=Read Holding, 06=Write Single
            address: Modbus adresa registra (2 Bytes)
            count: Počet registrov alebo hodnota na zápis (2 Bytes)
            
        Returns:
            dict: Slovník s výsledkom {'success': bool, 'data': Any, 'error': str}
        """
        modbus_node = self._get_modbus_node()
        if modbus_node is None:
            return {
                'success': False,
                'data': None,
                'error': "No Modbus Node configured or not available",
            }
        
        return await modbus_node.modbus_communication(
            device_id=device_id,
            command=command,
            address=address,
            count=count,
        )

    def _is_night(self) -> bool:
        """Zistí, či je noc podľa HA entity sun.sun.

        Returns:
            True ak je noc (slnko pod horizontom), False ak je deň.
        """
        sun_state = self.hass.states.get("sun.sun")
        if sun_state is None:
            LOGGER.warning("sun.sun entity not available, assuming daytime")
            return False
        return sun_state.state == "below_horizon"

    @staticmethod
    def calculate_output_power(
        max_power: float,
    ) -> float:
        """Vypočíta výstupný výkon na základe max_power.

        Táto funkcia je volaná pred calculate_dac_output a jej výstup
        sa použije ako vstup (parameter power) pre calculate_dac_output.

        Args:
            max_power: hodnota entity Max Power (0-100 %)

        Returns:
            Výstupný výkon (0-100 %)
        """
        return max(0.0, min(100.0, float(max_power)))

    @staticmethod
    def calculate_dac_output(
        power: float,
        enable: bool,
        zero_power_point: int,
        maximum_power_point: int,
        gamma: int,
    ) -> float:
        """Vypočíta hodnotu DAC výstupu na základe power curve nastavení.

        Tok signálu:
        1. Switch ``enable`` gatuje vstup – ak je OFF, effective_input = 0
        2. Normalizácia vstupu na rozsah 0..1
        3. Aplikácia gamma krivky
        4. Mapovanie na výstupný rozsah [zero_power_point .. maximum_power_point]

        Args:
            power: výstupný výkon z calculate_output_power (0-100 %)
            enable: stav entity Enable (True/False)
            zero_power_point: konfig. parameter – DAC hodnota pri 0 % výkonu
            maximum_power_point: konfig. parameter – DAC hodnota pri 100 % výkonu
            gamma: konfig. parameter -50..+50 – tvar krivky

        Returns:
            DAC výstupná hodnota (0-100 %)
        """
        # 1. Switch gatuje vstup
        effective_input = float(power) if enable else 0.0

        # 2. Normalizácia na 0..1
        t = max(0.0, min(1.0, effective_input / 100.0))

        # 3. Gamma krivka
        if gamma != 0 and t > 0.0:
            # Cieľová hodnota stredového bodu (pri t=0.5)
            target_mid = 0.50 * (1.0 + gamma / 100.0)
            target_mid = max(0.01, min(0.99, target_mid))
            gamma_exp = math.log(target_mid) / math.log(0.5)
            curved_t = t ** gamma_exp
        else:
            curved_t = t

        # 4. Mapovanie na výstupný rozsah
        output = zero_power_point + curved_t * (maximum_power_point - zero_power_point)
        return round(output, 2)

    def get_total_power_limit(self) -> float:
        """Vráti súčtový limit výkonu pre všetky špirály (z General zariadenia).

        Returns:
            Maximálny súčtový výkon v kW (0 = bez limitu)
        """
        shared = self.hass.data.get(DOMAIN, {}).get("shared", {})
        return float(shared.get(CONF_HEATING_COIL_TOTAL_POWER, DEFAULT_HEATING_COIL_TOTAL_POWER))

    def _read_coil_requested_power(self, coil_instance) -> float:
        """Načíta POŽADOVANÝ výkon iného coilu (po power_automation, pred total power limitom).

        Číta uloženú hodnotu _requested_power_percent, ktorá obsahuje
        výkon po aplikácii power_automation ale pred total power limitom.

        Returns:
            Požadovaný výkon v percentách (0-100). 0 ak je coil vypnutý.
        """
        return coil_instance._requested_power_percent

    def apply_total_power_limit(self, output_power: float) -> float:
        """Obmedzí output_power tohto coilu tak, aby súčtový výkon všetkých
        Heating Coil zariadení nepresiahol nastavený limit.

        Algoritmus (progressive filling):
        1. Zozbiera požadované výkony všetkých coilov (po power_automation)
        2. Ak celkový výkon ≤ limit → žiadna zmena
        3. Ak je prekročený → coily s nižším požiadavkom dostanú čo chcú,
           zvyšná kapacita sa rozdelí medzi ostatné coily

        Args:
            output_power: požadovaný výstupný výkon tohto coilu (0-100 %)

        Returns:
            Obmedzený výstupný výkon (0-100 %)
        """
        total_power_limit = self.get_total_power_limit()

        # Ak limit je 0, ochrana je vypnutá
        if total_power_limit <= 0:
            return output_power

        domain_data = self.hass.data.get(DOMAIN, {})

        # Ochrana pri štarte – ak nie všetky coily dokončili prvý cyklus,
        # preskočiť limit (inak by coil videl _requested=0 od ešte neinicializovaných coilov)
        for entry_id, entry_data in domain_data.items():
            if entry_id == "shared":
                continue
            if not isinstance(entry_data, dict):
                continue
            if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
                continue
            if entry_data.get(CONF_VIRTUAL_HEATING_COIL, False):
                continue
            coil_inst = entry_data.get("instance")
            if coil_inst is not None and not coil_inst._first_cycle_done:
                LOGGER.debug("Startup protection: not all coils completed first cycle, skipping total power limit")
                return output_power

        # Zozbierať POŽADOVANÉ výkony všetkých Heating Coil zariadení
        coils = []
        for entry_id, entry_data in domain_data.items():
            if entry_id == "shared":
                continue
            if not isinstance(entry_data, dict):
                continue
            if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
                continue

            # Virtuálne špirály preskočiť – ich výkon je len odrazom Slave špirál
            if entry_data.get(CONF_VIRTUAL_HEATING_COIL, False):
                continue

            coil_instance = entry_data.get("instance")
            if coil_instance is None:
                continue

            coil_power_kw = coil_instance.settings.heating_coil_power
            is_this_coil = (entry_id == self._entry_id)

            if is_this_coil:
                requested_percent = output_power
            else:
                requested_percent = self._read_coil_requested_power(coil_instance)

            requested_kw = (requested_percent / 100.0) * coil_power_kw
            coils.append({
                "entry_id": entry_id,
                "requested_kw": requested_kw,
                "coil_power_kw": coil_power_kw,
                "requested_percent": requested_percent,
                "is_this": is_this_coil,
                "granted_kw": 0.0,
            })

        # Celkový požadovaný výkon
        total_requested_kw = sum(c["requested_kw"] for c in coils)

        if total_requested_kw <= total_power_limit:
            LOGGER.debug(
                "Total power check: requested=%.2f kW, limit=%.2f kW → OK",
                total_requested_kw, total_power_limit,
            )
            return output_power

        # Progressive filling: zoradiť podľa požadovaného výkonu vzostupne
        coils_sorted = sorted(coils, key=lambda c: c["requested_kw"])
        remaining_kw = total_power_limit
        remaining_count = len(coils_sorted)

        for coil in coils_sorted:
            if remaining_count <= 0:
                coil["granted_kw"] = 0.0
                continue
            fair_share = remaining_kw / remaining_count
            granted = min(coil["requested_kw"], fair_share)
            coil["granted_kw"] = granted
            remaining_kw -= granted
            remaining_count -= 1

        # Nájsť výsledok pre tento coil
        for coil in coils_sorted:
            if coil["is_this"]:
                if coil["coil_power_kw"] > 0:
                    limited_output_power = round(
                        (coil["granted_kw"] / coil["coil_power_kw"]) * 100.0, 2
                    )
                else:
                    limited_output_power = 0.0
                limited_output_power = max(0.0, min(100.0, limited_output_power))

                LOGGER.info(
                    "Total power LIMIT: requested=%.2f kW > limit=%.2f kW, "
                    "this coil: %.1f%% → %.1f%% (%.2f kW → %.2f kW)",
                    total_requested_kw, total_power_limit,
                    output_power, limited_output_power,
                    coil["requested_kw"], coil["granted_kw"],
                )
                return limited_output_power

        return output_power

    def check_thermal_protection(self) -> bool:
        """Skontroluje stav bezpečnostnej poistky proti prehriatiu.

        Číta teplotný senzor a aktualizuje interný stav poistky s hysterézou:
          - Poistka sa AKTIVUJE keď teplota >= thermal_protection_max_temp
          - Poistka sa DEAKTIVUJE keď teplota <= (thermal_protection_max_temp - THERMAL_PROTECTION_HYSTERESIS)

        Returns:
            True  – poistka je aktívna (špirálu treba vypnúť)
            False – poistka nie je aktívna
        """
        sensor_entity = self.settings.thermal_protection_sensor_entity

        # Ak nie je nastavený senzor, poistka je neaktívna
        if (not sensor_entity) or (sensor_entity == THERMAL_PROTECTION_NO_SENSOR):
            if self._thermal_protection_active:
                self._thermal_protection_active = False
                self.sensor_states[ENTITY_THERMAL_PROTECTION_ACTIVE] = False
                if self.hass is not None and self._entry_id is not None:
                    async_dispatcher_send(self.hass, f"{DOMAIN}_feedback_update_{self._entry_id}")
            return False

        if self.hass is None:
            return self._thermal_protection_active

        state_obj = self.hass.states.get(sensor_entity)
        if state_obj is None or state_obj.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None, ""):
            LOGGER.debug("Thermal protection: sensor %s unavailable, keeping current state=%s", sensor_entity, self._thermal_protection_active)
            return self._thermal_protection_active

        try:
            current_temp = float(state_obj.state)
        except (ValueError, TypeError):
            LOGGER.warning("Thermal protection: cannot convert sensor %s state '%s' to float", sensor_entity, state_obj.state)
            return self._thermal_protection_active

        max_temp = float(self.settings.thermal_protection_max_temp)
        deactivate_temp = max_temp - THERMAL_PROTECTION_HYSTERESIS

        prev_active = self._thermal_protection_active

        if not self._thermal_protection_active:
            # Poistka nie je aktívna – aktivovať ak teplota dosiahla maximum
            if current_temp >= max_temp:
                self._thermal_protection_active = True
                LOGGER.warning(
                    "Thermal protection ACTIVATED: sensor=%s, temp=%.1f >= max_temp=%.1f",
                    sensor_entity, current_temp, max_temp,
                )
        else:
            # Poistka je aktívna – deaktivovať ak teplota klesla pod prah
            if current_temp <= deactivate_temp:
                self._thermal_protection_active = False
                LOGGER.info(
                    "Thermal protection DEACTIVATED: sensor=%s, temp=%.1f <= deactivate_temp=%.1f",
                    sensor_entity, current_temp, deactivate_temp,
                )

        # Ak sa stav zmenil, aktualizovať sensor a notifikovať HA
        if self._thermal_protection_active != prev_active:
            self.sensor_states[ENTITY_THERMAL_PROTECTION_ACTIVE] = self._thermal_protection_active
            if self.hass is not None and self._entry_id is not None:
                async_dispatcher_send(self.hass, f"{DOMAIN}_feedback_update_{self._entry_id}")

        return self._thermal_protection_active

    async def send_dac_output(self, _notify_others: bool = True) -> None:
        """Vypočíta výstup cez power curve a odošle na DAC cez Modbus.

        Čítava aktuálne stavy entít Enable a Max Power z HA,
        aplikuje calculate_output_power → apply_total_power_limit →
        calculate_dac_output transformáciu, aktualizuje senzory
        a zapíše výsledok do Modbus registra.

        Args:
            _notify_others: ak True, po zápise notifikuje ostatné coily
                aby prepočítali svoj výkon (ochrana pred slučkou)
        """
        if self.hass is None or self._entry_id is None:
            LOGGER.error("Cannot send DAC output: hass or entry_id not set")
            return

        # Načítať aktuálne stavy entít
        enable_state = self.hass.states.is_state(self.SWITCH_ENTITY_ENABLE, STATE_ON)

        max_power_obj = self.hass.states.get(self.NUMBER_ENTITY_MAX_POWER)
        if max_power_obj is None or max_power_obj.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            LOGGER.warning("Max Power entity not available, skipping DAC output")
            return
        try:
            max_power_value = float(max_power_obj.state)
        except (ValueError, TypeError):
            LOGGER.error("Cannot convert Max Power state to float: %s", max_power_obj.state)
            return

        # Vypočítať výstupný výkon (rešpektuje enable switch)
        if enable_state:
            output_power = self.calculate_output_power(
                max_power=max_power_value,
            )
            output_power = self.apply_total_power_limit(output_power)
        else:
            output_power = 0.0

        # Obmedzenie výkonu len na denné hodiny (noc = 0)
        if self.settings.output_power_during_day_only and output_power > 0.0:
            if self._is_night():
                LOGGER.debug("Night detected, output_power forced to 0 (day-only mode)")
                output_power = 0.0

        # Aktualizovať senzory
        output_power_kw = round((output_power / 100.0) * self.settings.heating_coil_power, 1)
        self.sensor_states[ENTITY_OUTPUT_POWER_PERCENT] = output_power
        self.sensor_states[ENTITY_OUTPUT_POWER_KW] = output_power_kw
        async_dispatcher_send(self.hass, f"{DOMAIN}_feedback_update_{self._entry_id}")

        # Aktualizácia celkového výkonu v General zariadení
        async_dispatcher_send(self.hass, f"{DOMAIN}_total_power_update")

        # Vypočítať DAC výstup (enable je spracované interne pre offset)
        dac_value = self.calculate_dac_output(
            power=output_power,
            enable=enable_state,
            zero_power_point=self.settings.zero_power_point,
            maximum_power_point=self.settings.maximum_power_point,
            gamma=self.settings.gamma,
        )

        LOGGER.debug(
            "Power curve: enable=%s, max_power=%.1f, output_power=%.1f, zero=%d, max=%d, gamma=%d → DAC=%.2f",
            enable_state, max_power_value, output_power,
            self.settings.zero_power_point, self.settings.maximum_power_point,
            self.settings.gamma, dac_value,
        )

        # Odoslať na Modbus (len ak nie je virtuálna špirála)
        if self.settings.virtual_heating_coil:
            LOGGER.debug("Virtual heating coil – skipping Modbus DAC write (dac_value=%.2f)", dac_value)
        else:
            try:
                from . import get_modbus_node_instance

                entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
                modbus_node_entry_id = entry_data.get(
                    CONF_MODBUS_NODE_ENTRY_ID, ""
                )

                modbus_node = get_modbus_node_instance(self.hass, modbus_node_entry_id)
                if modbus_node is None:
                    LOGGER.error("Cannot send DAC output: no Modbus Node available")
                    return

                device_id = modbus_node.settings.modbus_device_id
                command = 6  # Write Single Register (0x06)
                port_id = self.settings.dac_output_port_id
                address = int(port_id) - 1  # Adresa 0-31
                dac_ratio = modbus_node.dac_conversion_ratio
                count = int(dac_value * dac_ratio)

                LOGGER.debug(
                    "Sending DAC via ModbusNode [%s]: device_id=%d, command=0x%02x, "
                    "port_id=%d, address=%d, value=%d (dac_value=%.2f, ratio=%.2f)",
                    modbus_node_entry_id[:8], device_id, command, port_id, address, count, dac_value, dac_ratio,
                )

                result = await modbus_node.modbus_communication(
                    device_id=device_id,
                    command=command,
                    address=address,
                    count=count,
                )

                if result['success']:
                    LOGGER.debug("DAC write successful (value=%d)", count)
                else:
                    LOGGER.error("DAC write failed: %s", result['error'])

            except Exception as e:
                LOGGER.error("Error sending DAC output: %s", e)

        # Notifikovať ostatné coily aby prepočítali svoj výkon
        # (napr. keď sa tento coil vypne, ostatné môžu zvýšiť výkon)
        if _notify_others:
            await self._notify_other_coils()

    async def _notify_other_coils(self) -> None:
        """Notifikuje všetky ostatné Heating Coil zariadenia aby prepočítali
        svoj výkon a DAC výstup.

        Volané po zmene výkonu tohto coilu, aby sa správne prerozdelil
        súčtový limit výkonu medzi všetky coily.

        Používa _notify_others=False aby sa zabránilo nekonečnej slučke.
        """
        domain_data = self.hass.data.get(DOMAIN, {})

        for entry_id, entry_data in domain_data.items():
            if entry_id == "shared" or entry_id == self._entry_id:
                continue
            if not isinstance(entry_data, dict):
                continue
            if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
                continue

            coil_instance = entry_data.get("instance")
            if coil_instance is not None:
                try:
                    await coil_instance.my_controller(_notify_others=False)
                except Exception as e:
                    LOGGER.error(
                        "Error notifying coil %s to recalculate: %s",
                        entry_id[:8], e,
                    )

