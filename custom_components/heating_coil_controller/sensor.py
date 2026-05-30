from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" sensor.py """

"""Sensor platform for Heating Coil Controller."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory, DeviceInfo

from .helpers import load_translations
from .const import *

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_type = data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

    # Načítať translations asynchrónne
    translations = await load_translations(hass)

    # -----------------------------------------------------------------------
    # General – entity pre General zariadenie
    # -----------------------------------------------------------------------
    if device_type == DEVICE_TYPE_GENERAL:
        device_name = data.get(CONF_DEVICE_NAME, "General")
        include_device_name = data.get(CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY)

        entities = [
            GeneralSensorEntity(
                hass=hass,
                entry_id=entry.entry_id,
                device_name=device_name,
                include_device_name=include_device_name,
                entity_id_suffix=ENTITY_GENERAL_SENSOR_TOTAL_POWER,
                name="Total Power",
                translations=translations,
                icon="mdi:flash",
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement="kW",
                suggested_display_precision=1,
            ),
        ]
        async_add_entities(entities)
        return

    # -----------------------------------------------------------------------
    # Modbus Node – žiadne sensor entity
    # -----------------------------------------------------------------------
    if device_type == DEVICE_TYPE_MODBUS_NODE:
        device_name = data.get(CONF_DEVICE_NAME, "Modbus Node")
        include_device_name = data.get(CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY)
        node_number = data.get(CONF_MODBUS_NODE_NUMBER, 1)

        entities = [
            ModbusNodeSensorEntity(
                hass=hass,
                entry_id=entry.entry_id,
                device_name=device_name,
                include_device_name=include_device_name,
                node_number=node_number,
                entity_id_suffix=ENTITY_MODBUS_NODE_SENSOR_ERROR_CODE,
                name="Error Code",
                translations=translations,
                icon="mdi:alert-circle-outline",
            ),
        ]
        async_add_entities(entities)
        return

    # -----------------------------------------------------------------------
    # Heating Coil – pôvodné entity
    # -----------------------------------------------------------------------
    instance = data["instance"]

    entities = [
        SensorEntityDefinition(
            instance, 
            entry_id = entry.entry_id, 
            entity_id = ENTITY_OUTPUT_POWER_PERCENT, 
            name = "Output Power [%]",
            translations = translations, 
            icon = "mdi:flash-outline",
            default_value = "0",
            enabled_by_default = True,
            state_class = SensorStateClass.MEASUREMENT,
            native_unit_of_measurement = "%",
            suggested_display_precision = 0,
            # entity_category = EntityCategory.DIAGNOSTIC,      # EntityCategory.CONFIG - Konfiguračné entity, EntityCategory.DIAGNOSTIC - Diagnostické entity, None (default) - Normálne entity
        ),
        SensorEntityDefinition(
            instance, 
            entry_id = entry.entry_id, 
            entity_id = ENTITY_OUTPUT_POWER_KW, 
            name = "Output Power [kW]",
            translations = translations, 
            icon = "mdi:flash",
            default_value = "0.0",
            enabled_by_default = True,
            device_class = SensorDeviceClass.POWER,
            state_class = SensorStateClass.MEASUREMENT,
            native_unit_of_measurement = "kW",
            suggested_display_precision = 1,
            # entity_category = EntityCategory.DIAGNOSTIC,      # EntityCategory.CONFIG - Konfiguračné entity, EntityCategory.DIAGNOSTIC - Diagnostické entity, None (default) - Normálne entity
        ),
    ]

    async_add_entities(entities)

class SensorEntityDefinition(SensorEntity):

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._instance.settings.device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
            configuration_url=DOCUMENTATION_URL,
        )

    def __init__(
        self,
        instance,
        entry_id: str,
        entity_id: str,
        name: str,
        translations: dict = None,
        icon: str = "mdi:eye",
        default_value: str = None,
        enabled_by_default: bool = True,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        native_unit_of_measurement: str | None = None,
        suggested_display_precision: int | None = None,
        suggested_unit_of_measurement: str | None = None,
        entity_category: EntityCategory | None = None,
        options: list[str] | None = None,
        available: bool = True,
        last_reset: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        self._instance = instance
        self._entry_id = entry_id
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"
        self._attr_translation_key = entity_id

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("sensor", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = False
        if instance.settings.include_device_name_in_entity:
            # has_entity_name = True: HA automaticky pridá názov zariadenia, entite nastavíme "- Sensor 1"
            # výsledok: "Heating Coil 1 - Sensor 1"
            self._attr_name = f"{instance.settings.device_name} {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"sensor.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_native_value = default_value
        self._attr_available = available
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default

        if device_class is not None:
            self._attr_device_class = device_class
        if state_class is not None:
            self._attr_state_class = state_class
        if native_unit_of_measurement is not None:
            self._attr_native_unit_of_measurement = native_unit_of_measurement
        if suggested_display_precision is not None:
            self._attr_suggested_display_precision = suggested_display_precision
        if suggested_unit_of_measurement is not None:
            self._attr_suggested_unit_of_measurement = suggested_unit_of_measurement
        if entity_category is not None:
            self._attr_entity_category = entity_category
        if options is not None:
            self._attr_options = options
        if last_reset is not None:
            self._attr_last_reset = last_reset

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Subscribe to updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_feedback_update_{self._entry_id}",
                self._handle_feedback_update,
            )
        )

    @callback
    def _handle_feedback_update(self) -> None:
        """Handle feedback update."""
        new_value = self._instance.sensor_states.get(self._entity_id)
        if new_value is not None:
            self._attr_native_value = new_value
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        return self._attr_native_value


# ===========================================================================
# General Sensor Entity
# ===========================================================================

class GeneralSensorEntity(SensorEntity):

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
            configuration_url=DOCUMENTATION_URL,
        )

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
        include_device_name: bool,
        entity_id_suffix: str,
        name: str,
        translations: dict = None,
        icon: str = "mdi:eye",
        default_value: str = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        native_unit_of_measurement: str | None = None,
        suggested_display_precision: int | None = None,
    ) -> None:
        """Initialize the General sensor."""
        self._hass = hass
        self._entry_id = entry_id
        self._device_name = device_name
        self._entity_id_suffix = entity_id_suffix

        self._attr_unique_id = f"{entry_id}_{entity_id_suffix}"
        self._attr_translation_key = entity_id_suffix

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("sensor", {}).get(entity_id_suffix, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        if include_device_name:
            self._attr_has_entity_name = True
            self._attr_name = entity_display_name
        else:
            self._attr_has_entity_name = False
            self._attr_name = entity_display_name

        self.entity_id = f"sensor.{GENERAL_ENTITY_ID_PREFIX}_{entity_id_suffix}"
        self._attr_icon = icon
        self._attr_native_value = default_value
        self._attr_entity_registry_enabled_default = True
        self._attr_entity_registry_visible_default = True

        if device_class is not None:
            self._attr_device_class = device_class
        if state_class is not None:
            self._attr_state_class = state_class
        if native_unit_of_measurement is not None:
            self._attr_native_unit_of_measurement = native_unit_of_measurement
        if suggested_display_precision is not None:
            self._attr_suggested_display_precision = suggested_display_precision

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Subscribe to total power updates from all Heating Coil zariadení
        if self._entity_id_suffix == ENTITY_GENERAL_SENSOR_TOTAL_POWER:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{DOMAIN}_total_power_update",
                    self._handle_total_power_update,
                )
            )

    @callback
    def _handle_total_power_update(self) -> None:
        """Vypočíta celkový súčtový výkon všetkých Heating Coil zariadení.
        
        Virtuálne špirály sa nezapočítavajú (ich výkon je súčtom Slave špirál,
        ktoré sa započítavajú priamo).
        """
        domain_data = self.hass.data.get(DOMAIN, {})
        total_kw = 0.0

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

            power_kw = coil_instance.sensor_states.get(ENTITY_OUTPUT_POWER_KW)
            if power_kw is not None:
                try:
                    total_kw += float(power_kw)
                except (ValueError, TypeError):
                    pass

        self._attr_native_value = round(total_kw, 1)
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._attr_native_value


# ===========================================================================
# Modbus Node Sensor Entity
# ===========================================================================

class ModbusNodeSensorEntity(SensorEntity):

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
            configuration_url=DOCUMENTATION_URL,
        )

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
        include_device_name: bool,
        node_number: int,
        entity_id_suffix: str,
        name: str,
        translations: dict = None,
        icon: str = "mdi:eye",
        default_value: str = None,
    ) -> None:
        """Initialize the Modbus Node sensor."""
        self._hass = hass
        self._entry_id = entry_id
        self._device_name = device_name
        self._node_number = node_number
        self._entity_id_suffix = entity_id_suffix

        self._attr_unique_id = f"{entry_id}_{entity_id_suffix}"
        self._attr_translation_key = entity_id_suffix

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("sensor", {}).get(entity_id_suffix, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        if include_device_name:
            self._attr_has_entity_name = True
            self._attr_name = entity_display_name
        else:
            self._attr_has_entity_name = False
            self._attr_name = entity_display_name

        self.entity_id = f"sensor.{MODBUS_NODE_ENTITY_ID_PREFIX}_{node_number}_{entity_id_suffix}"
        self._attr_icon = icon
        self._attr_native_value = 0
        self._attr_entity_registry_enabled_default = True
        self._attr_entity_registry_visible_default = True

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Subscribe to Modbus Node updates
        if self._entity_id_suffix == ENTITY_MODBUS_NODE_SENSOR_ERROR_CODE:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{DOMAIN}_modbus_node_update_{self._entry_id}",
                    self._handle_error_code_update,
                )
            )

    @callback
    def _handle_error_code_update(self) -> None:
        """Načíta error_code z ModbusNodeInstance a aktualizuje senzor."""
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(self._entry_id)
        if entry_data and isinstance(entry_data, dict):
            modbus_node = entry_data.get("modbus_node_instance")
            if modbus_node is not None:
                self._attr_native_value = modbus_node.error_code
                self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._attr_native_value