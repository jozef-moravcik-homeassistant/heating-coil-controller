from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" switch.py """

"""Switch platform for Heating Coil Controller."""

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
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
    """Set up switch entities."""
    instance = hass.data[DOMAIN][entry.entry_id]["instance"]
    
    # Načítať translations asynchrónne
    translations = await load_translations(hass)

    entities = [
        SwitchEntityDefinition(
            instance,
            entry_id = entry.entry_id,
            entity_id = ENTITY_ENABLE,
            name = "ON/OFF",
            translations = translations,
            icon = "mdi:power",
            icon_off = "mdi:power-off",
            initial_state = True,
            enabled_by_default = True,
            restore_state = True,
            device_class = SwitchDeviceClass.SWITCH,      # SwitchDeviceClass.OUTLET - Zásuvka/Outlet, SwitchDeviceClass.SWITCH - Základný prepínač, None (default) - Bez klasifikácie
            # entity_category = EntityCategory.CONFIG,      # EntityCategory.CONFIG - Konfiguračné entity, EntityCategory.DIAGNOSTIC - Diagnostické entity, None (default) - Normálne entity
        ),
        SwitchEntityDefinition(
            instance,
            entry_id = entry.entry_id,
            entity_id = ENTITY_AUTO_POWER_CONTROL,
            name = "Automatic power control",
            translations = translations,
            icon = "mdi:auto-mode",
            icon_off = "mdi:car-cruise-control",
            initial_state = True,
            enabled_by_default = True,
            restore_state = True,
            device_class = SwitchDeviceClass.SWITCH,
        ),
        SwitchEntityDefinition(
            instance,
            entry_id = entry.entry_id,
            entity_id = ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT,
            name = "Only use power above the export limit",
            translations = translations,
            icon = "mdi:transmission-tower-export",
            icon_off = "mdi:transmission-tower-export",
            initial_state = False,
            enabled_by_default = True,
            restore_state = True,
            device_class = SwitchDeviceClass.SWITCH,
        ),
    ]

    switches_dict = {entity._entity_id: entity for entity in entities}
    hass.data[DOMAIN][entry.entry_id]["switches"] = switches_dict
    async_add_entities(entities)

class SwitchEntityDefinition(SwitchEntity, RestoreEntity):

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
        icon: str = "mdi:toggle-switch-variant",
        icon_off: str | None = None,
        initial_state: bool = False,
        enabled_by_default: bool = True,
        restore_state: bool = True,
        device_class: SwitchDeviceClass | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the switch."""
        self._instance = instance
        self._entry_id = entry_id
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("switch", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = True
        if instance.settings.include_device_name_in_entity:
            self._attr_name = f"- {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"switch.{device_name_sanitized}_{entity_id}"
        self._icon_on = icon
        self._icon_off = icon_off if icon_off else icon
        self._entity_id = entity_id
        self._initial_state = initial_state
        self._attr_is_on = initial_state
        self._restore_state = restore_state
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default
        
        if device_class is not None:
            self._attr_device_class = device_class
        if entity_category is not None:
            self._attr_entity_category = entity_category
        
        self._group_syncing = False  # Ochrana proti nekonečnej slučke pri synchronizácii skupiny
    
    @property
    def icon(self):
        """Return the icon based on current state."""
        return self._icon_on if self._attr_is_on else self._icon_off

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Obnovenie stavu po reštarte (len ak je restore_state povolené)
        if self._restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                self._attr_is_on = last_state.state == "on"
                LOGGER.debug(f"Restored state for {self.entity_id}: {self._attr_is_on}")
            else:
                # Ak nemáme uložený stav, použijeme initial_state
                self._attr_is_on = self._initial_state
                LOGGER.debug(f"No saved state for {self.entity_id}, using initial: {self._attr_is_on}")
        
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()
        LOGGER.debug(f"Switch {self.entity_id} turned ON")
        # Synchronizácia ON/OFF stavu v rámci master skupiny
        if self._entity_id == ENTITY_ENABLE:
            await self._sync_group_enable(True)
        if self._entity_id == ENTITY_AUTO_POWER_CONTROL:
            await self._sync_group_auto_power_control(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()
        LOGGER.debug(f"Switch {self.entity_id} turned OFF")
        # Synchronizácia ON/OFF stavu v rámci master skupiny
        if self._entity_id == ENTITY_ENABLE:
            await self._sync_group_enable(False)
        if self._entity_id == ENTITY_AUTO_POWER_CONTROL:
            await self._sync_group_auto_power_control(False)

    async def _sync_group_enable(self, turn_on: bool) -> None:
        """Synchronizuje ON/OFF stav z Master na Slave špirálky (jednosmerná synchronizácia).

        Volá sa po zmene enable switchu. Synchronizácia prebieha len
        z Master na Slave. Ak je tento switch Slave, synchronizácia sa nekoná.
        Chráni sa proti nekonečnej slučke cez _group_syncing flag.
        """
        if self._group_syncing:
            return
        self._group_syncing = True
        try:
            from .helpers import get_slave_entry_ids, get_master_entry_id

            # Zistiť či som Master (nemám vlastného mastera)
            my_master = get_master_entry_id(self.hass, self._entry_id)
            if my_master is not None:
                # Som Slave – nesynchronizujem nikoho
                return

            # Som Master – synchronizovať len na mojich Slave
            slaves = get_slave_entry_ids(self.hass, self._entry_id)
            if not slaves:
                return

            domain_data = self.hass.data.get(DOMAIN, {})

            for peer_eid in slaves:
                peer_data = domain_data.get(peer_eid, {})
                if not isinstance(peer_data, dict):
                    continue
                peer_switches = peer_data.get("switches", {})
                peer_switch = peer_switches.get(ENTITY_ENABLE)
                if peer_switch is None:
                    continue
                # Nastaviť flag aby peer nespúšťal ďalšiu synchronizáciu
                peer_switch._group_syncing = True
                try:
                    if turn_on:
                        await peer_switch.async_turn_on()
                    else:
                        await peer_switch.async_turn_off()
                    LOGGER.debug("Group sync (Master→Slave): %s → %s", self.entity_id, peer_switch.entity_id)
                finally:
                    peer_switch._group_syncing = False
        finally:
            self._group_syncing = False

    async def _sync_group_auto_power_control(self, turn_on: bool) -> None:
        """Synchronizuje auto_power_control stav z Master na Slave špirálky.

        Volá sa po zmene auto_power_control switchu. Synchronizácia prebieha len
        z Master na Slave. Ak je tento switch Slave, synchronizácia sa nekoná.
        Chráni sa proti nekonečnej slučke cez _group_syncing flag.
        """
        if self._group_syncing:
            return
        self._group_syncing = True
        try:
            from .helpers import get_slave_entry_ids, get_master_entry_id

            my_master = get_master_entry_id(self.hass, self._entry_id)
            if my_master is not None:
                return

            slaves = get_slave_entry_ids(self.hass, self._entry_id)
            if not slaves:
                return

            domain_data = self.hass.data.get(DOMAIN, {})

            for peer_eid in slaves:
                peer_data = domain_data.get(peer_eid, {})
                if not isinstance(peer_data, dict):
                    continue
                peer_switches = peer_data.get("switches", {})
                peer_switch = peer_switches.get(ENTITY_AUTO_POWER_CONTROL)
                if peer_switch is None:
                    continue
                peer_switch._group_syncing = True
                try:
                    if turn_on:
                        await peer_switch.async_turn_on()
                    else:
                        await peer_switch.async_turn_off()
                    LOGGER.debug("Group sync auto_power_control (Master→Slave): %s → %s", self.entity_id, peer_switch.entity_id)
                finally:
                    peer_switch._group_syncing = False
        finally:
            self._group_syncing = False