from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" binary_sensor.py """

"""Binary Sensor platform for Heating Coil Controller."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory, DeviceInfo

from .helpers import load_translations
from .const import *

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    # Žiadne binary sensor entity pre žiadny typ zariadenia
    return

class BinarySensorEntityDefinition(BinarySensorEntity):

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

    @property
    def has_entity_name(self) -> bool:
        """Bypass entity registry cache – always use current setting."""
        return self._attr_has_entity_name

    def __init__(
        self,
        instance,
        entry_id: str,
        entity_id: str,
        name: str,
        translations: dict = None,
        icon: str = "mdi:checkbox-blank-circle",
        default_value: bool = False,
        enabled_by_default: bool = True,
        device_class: BinarySensorDeviceClass | None = None,
        entity_category: EntityCategory | None = None,
        available: bool = True,
    ) -> None:
        """Initialize the binary sensor."""
        self._instance = instance
        self._entry_id = entry_id
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("binary_sensor", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = True
        if instance.settings.include_device_name_in_entity:
            self._attr_name = f"- {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"binary_sensor.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_is_on = default_value
        self._attr_available = available
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default

        if device_class is not None:
            self._attr_device_class = device_class
        if entity_category is not None:
            self._attr_entity_category = entity_category

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
            self._attr_is_on = bool(new_value)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return the state of the binary sensor."""
        return self._attr_is_on
