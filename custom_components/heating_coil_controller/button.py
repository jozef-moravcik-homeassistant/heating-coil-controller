from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" button.py """

"""Button platform for Heating Coil Controller."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory, DeviceInfo

from .helpers import load_translations
from .const import *

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
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
            GeneralButtonEntity(
                hass=hass,
                entry_id=entry.entry_id,
                device_name=device_name,
                include_device_name=include_device_name,
                entity_id_suffix=ENTITY_GENERAL_BUTTON_OFF_ALL,
                name="Turn OFF all",
                translations=translations,
                icon="mdi:power-off",
            ),
            GeneralButtonEntity(
                hass=hass,
                entry_id=entry.entry_id,
                device_name=device_name,
                include_device_name=include_device_name,
                entity_id_suffix=ENTITY_GENERAL_BUTTON_ON_ALL,
                name="Turn ON all",
                translations=translations,
                icon="mdi:power-on",
            ),
        ]
        async_add_entities(entities)
        return

    # -----------------------------------------------------------------------
    # Modbus Node – žiadne button entity
    # -----------------------------------------------------------------------
    if device_type == DEVICE_TYPE_MODBUS_NODE:
        return

    # -----------------------------------------------------------------------
    # Heating Coil – žiadne button entity
    # -----------------------------------------------------------------------
    return

class ButtonEntityDefinition(ButtonEntity):

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
        icon: str = "mdi:gesture-tap-button",
        enabled_by_default: bool = True,
        device_class: ButtonDeviceClass | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the button."""
        self._instance = instance
        self._entry_id = entry_id
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("button", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = True
        if instance.settings.include_device_name_in_entity:
            self._attr_name = f"- {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"button.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default

        if device_class is not None:
            self._attr_device_class = device_class
        if entity_category is not None:
            self._attr_entity_category = entity_category

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.info(f"Button {self._entity_id} pressed")
        # Tu možeš pridať logiku ktorá sa má vykonať pri stlačení tlačidla
        # Napríklad volanie metódy v instance
        # await self._instance.handle_button_press(self._entity_id)


# ===========================================================================
# General Button Entity
# ===========================================================================

class GeneralButtonEntity(ButtonEntity):

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
        icon: str = "mdi:gesture-tap-button",
    ) -> None:
        """Initialize the General button."""
        self._hass = hass
        self._entry_id = entry_id
        self._device_name = device_name
        self._entity_id_suffix = entity_id_suffix

        self._attr_unique_id = f"{entry_id}_{entity_id_suffix}"

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("button", {}).get(entity_id_suffix, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        if include_device_name:
            self._attr_has_entity_name = True
            self._attr_name = entity_display_name
        else:
            self._attr_has_entity_name = False
            self._attr_name = entity_display_name

        self.entity_id = f"button.{GENERAL_ENTITY_ID_PREFIX}_{entity_id_suffix}"
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = True
        self._attr_entity_registry_visible_default = True

    async def async_press(self) -> None:
        """Handle the button press."""
        from . import handle_turn_off_all, handle_turn_on_all
        if self._entity_id_suffix == ENTITY_GENERAL_BUTTON_OFF_ALL:
            await handle_turn_off_all(self._hass)
        elif self._entity_id_suffix == ENTITY_GENERAL_BUTTON_ON_ALL:
            await handle_turn_on_all(self._hass)
