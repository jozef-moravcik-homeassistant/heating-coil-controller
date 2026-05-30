from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" select.py """

"""Select platform for Heating Coil Controller"""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo

from .helpers import load_translations
from .const import (
    DOMAIN,
    VERSION,
    MANUFACTURER,
    MODEL,
    NAME,
    DOCUMENTATION_URL,
)

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    # Žiadne select entity pre žiadny typ zariadenia
    return

class SelectEntityDefinition(SelectEntity, RestoreEntity):

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
        icon: str = "mdi:format-list-checkbox",
        options: list[str] = None,
        default_value: str = None,
        enabled_by_default: bool = True,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the select entity."""
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
            entity_trans = translations.get("entity", {}).get("select", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = False
        if instance.settings.include_device_name_in_entity:
            self._attr_name = f"{instance.settings.device_name} {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"select.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_options = options
        self._default_value = default_value
        self._attr_current_option = default_value
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default
        
        if entity_category is not None:
            self._attr_entity_category = entity_category

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Obnovenie stavu po reštarte
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            if last_state.state in self._attr_options:
                self._attr_current_option = last_state.state
                LOGGER.debug(f"Restored state for {self.entity_id}: {self._attr_current_option}")
            else:
                self._attr_current_option = self._default_value
                LOGGER.debug(f"Invalid restored state for {self.entity_id}, using default: {self._default_value}")
        else:
            self._attr_current_option = self._default_value
            LOGGER.debug(f"No saved state for {self.entity_id}, using default: {self._default_value}")

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
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option in self._attr_options:
            self._attr_current_option = option
            self.async_write_ha_state()
            LOGGER.debug(f"Select {self.entity_id} set to {option}")
        else:
            LOGGER.warning(f"Invalid option {option} for {self.entity_id}")