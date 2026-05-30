from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" time.py """

"""Time platform for Heating Coil Controller."""

import logging
from typing import Any
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo

from .helpers import load_translations
from .const import *

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities."""
    # Žiadne time entity pre žiadny typ zariadenia
    return

class TimeEntityDefinition(TimeEntity, RestoreEntity):

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
        icon: str = "mdi:clock-outline",
        default_value: time = None,
        enabled_by_default: bool = True,
        restore_state: bool = True,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the time entity."""
        self._instance = instance
        self._entry_id = entry_id
        self._restore_state = restore_state
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"
        self._attr_translation_key = entity_id

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("time", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        if instance.settings.include_device_name_in_entity:
            self._attr_has_entity_name = True
            self._attr_name = entity_display_name
        else:
            self._attr_has_entity_name = False
            self._attr_name = entity_display_name
        
        self.entity_id = f"time.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_native_value = default_value if default_value else time(12, 0, 0)
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default

        if entity_category is not None:
            self._attr_entity_category = entity_category

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Restore previous state if enabled
        if self._restore_state:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state not in (None, "unknown", "unavailable"):
                try:
                    # Parse time from state string (HH:MM:SS format)
                    time_parts = last_state.state.split(":")
                    if len(time_parts) >= 2:
                        hour = int(time_parts[0])
                        minute = int(time_parts[1])
                        second = int(time_parts[2]) if len(time_parts) > 2 else 0
                        self._attr_native_value = time(hour, minute, second)
                        LOGGER.debug(f"Restored {self.entity_id} time to {self._attr_native_value}")
                except (ValueError, IndexError) as ex:
                    LOGGER.warning(f"Could not restore time for {self.entity_id}: {ex}")

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
        if new_value is not None and isinstance(new_value, time):
            self._attr_native_value = new_value
        self.async_write_ha_state()

    async def async_set_value(self, value: time) -> None:
        """Set new time value."""
        self._attr_native_value = value
        self.async_write_ha_state()
        LOGGER.info(f"Time {self._entity_id} set to {value}")
        # Tu možeš pridať logiku ktorá sa má vykonať pri zmene času
        # Napríklad volanie metódy v instance
        # await self._instance.handle_time_change(self._entity_id, value)

    @property
    def native_value(self) -> time:
        """Return the state of the time entity."""
        return self._attr_native_value
