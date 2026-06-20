from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" number.py """

"""Number platform for Heating Coil Controller."""

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
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
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_HEATING_COIL,
    DEVICE_TYPE_MODBUS_NODE,
    ENTITY_MAX_POWER,
    DEFAULT_MAX_POWER,
    MIN_MAX_POWER,
    MAX_MAX_POWER,
    CONF_MODBUS_NODE_ENTRY_ID,
    DEFAULT_MODBUS_NODE_ENTRY_ID,
    CONF_DAC_OUTPUT_PORT_ID,
    DEFAULT_DAC_OUTPUT_PORT_ID,
    CONF_MODBUS_DEVICE_ID,
    DEFAULT_MODBUS_DEVICE_ID,
    POWER_CONTROL_STRATEGY_MANUAL,
)

LOGGER = logging.getLogger(__name__)


def _coerce_value(value: float, step: float) -> int | float:
    """Ak je krok celé číslo, vráť int aby HA nezobrazoval desatinné miesto."""
    if value is None:
        return value
    if step == int(step):
        return int(value)
    return value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_type = data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

    # General a Modbus Node nemajú number entity
    if device_type != DEVICE_TYPE_HEATING_COIL:
        return

    instance = data["instance"]
    
    # Načítať translations asynchrónne
    translations = await load_translations(hass)

    entities = [
        NumberEntityDefinition(
            instance,
            entry_id = entry.entry_id,
            translations = translations,
            entity_id = ENTITY_MAX_POWER,
            name = "Max. Power",
            icon = "mdi:flash",
            min_value = MIN_MAX_POWER,
            max_value = MAX_MAX_POWER,
            step = 1,
            default_value = DEFAULT_MAX_POWER,
            enabled_by_default = True,
            mode = NumberMode.BOX,
            native_unit_of_measurement = "%",
            # device_class = NumberDeviceClass.TEMPERATURE,
            # entity_category = EntityCategory.CONFIG,      # EntityCategory.CONFIG - Konfiguračné entity, EntityCategory.DIAGNOSTIC - Diagnostické entity, None (default) - Normálne entity
        ),
    ]

    numbers_dict = {entity._entity_id: entity for entity in entities}
    hass.data[DOMAIN][entry.entry_id]["numbers"] = numbers_dict
    async_add_entities(entities)

class NumberEntityDefinition(NumberEntity, RestoreEntity):

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
        icon: str = "mdi:numeric",
        min_value: float = 0,
        max_value: float = 1,
        step: float = 1,
        default_value: float = None,
        enabled_by_default: bool = True,
        mode: NumberMode = NumberMode.SLIDER,
        native_unit_of_measurement: str | None = None,
        device_class: NumberDeviceClass | None = None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Initialize the number entity."""
        self._instance = instance
        self._entry_id = entry_id
        
        # Sanitize device name for entity ID
        from .const import sanitize_device_name
        device_name_sanitized = sanitize_device_name(instance.settings.device_name)
        
        self._attr_unique_id = f"{entry_id}_{entity_id}"

        # Získať preložený názov entity
        entity_display_name = name
        if translations:
            entity_trans = translations.get("entity", {}).get("number", {}).get(entity_id, {})
            translated_name = entity_trans.get("name")
            if translated_name:
                entity_display_name = translated_name

        self._attr_has_entity_name = True
        if instance.settings.include_device_name_in_entity:
            self._attr_name = f"- {entity_display_name}"
        else:
            self._attr_name = entity_display_name
        
        self.entity_id = f"number.{device_name_sanitized}_{entity_id}"
        self._attr_icon = icon
        self._entity_id = entity_id
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_mode = mode
        self._default_value = default_value
        # Uložiť ako int ak je krok celé číslo → HA nezobrazí desatinné miesto
        self._attr_native_value = _coerce_value(default_value, step)
        self._attr_entity_registry_enabled_default = enabled_by_default
        self._attr_entity_registry_visible_default = enabled_by_default
        
        if native_unit_of_measurement is not None:
            self._attr_native_unit_of_measurement = native_unit_of_measurement
        if device_class is not None:
            self._attr_device_class = device_class
        if entity_category is not None:
            self._attr_entity_category = entity_category
        
        self._group_syncing = False  # Ochrana proti nekonečnej slučke pri synchronizácii skupiny

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Obnovenie stavu po reštarte
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            try:
                restored = float(last_state.state)
                self._attr_native_value = _coerce_value(restored, self._attr_native_step)
                LOGGER.debug(f"Restored state for {self.entity_id}: {self._attr_native_value}")
            except (ValueError, TypeError):
                self._attr_native_value = _coerce_value(self._default_value, self._attr_native_step)
                LOGGER.debug(f"Failed to restore state for {self.entity_id}, using default: {self._default_value}")
        else:
            self._attr_native_value = _coerce_value(self._default_value, self._attr_native_step)
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

    async def async_set_native_value(self, value: float) -> None:
        """Set the value of the number entity."""
        self._attr_native_value = _coerce_value(value, self._attr_native_step)
        self.async_write_ha_state()
        LOGGER.debug(f"Number {self.entity_id} set to {self._attr_native_value}")
        # Synchronizácia max_power v rámci master skupiny
        if self._entity_id == ENTITY_MAX_POWER:
            await self._sync_group_max_power(value)
            # V manuálnom móde aplikovať zmenu okamžite bez čakania na interval
            await self._trigger_manual_mode_update()

    async def _sync_group_max_power(self, value: float) -> None:
        """Synchronizuje max_power z Master na Slave špirálky (jednosmerná synchronizácia).

        Volá sa po zmene max_power slidera. Synchronizácia prebieha len
        z Master na Slave. Ak je tento number Slave, synchronizácia sa nekoná.
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
                peer_numbers = peer_data.get("numbers", {})
                peer_number = peer_numbers.get(ENTITY_MAX_POWER)
                if peer_number is None:
                    continue
                # Nastaviť flag aby peer nespúšťal ďalšiu synchronizáciu
                peer_number._group_syncing = True
                try:
                    await peer_number.async_set_native_value(value)
                    LOGGER.debug("Group sync max_power (Master→Slave): %s → %s (%.1f)", self.entity_id, peer_number.entity_id, value)
                finally:
                    peer_number._group_syncing = False
        finally:
            self._group_syncing = False

    async def _trigger_manual_mode_update(self) -> None:
        """Okamžite spustí my_controller ak je aktívna manuálna stratégia.

        Volá sa po zmene max_power slidera. Týka sa len inštancií kde je
        stratégia MANUAL – ostatné stratégie si riadia vlastný rytmus
        a táto metóda ich neovplyvní.
        """
        try:
            domain_data = self.hass.data.get(DOMAIN, {})
            entry_data = domain_data.get(self._entry_id, {})
            instance = entry_data.get("instance")
            if instance is None:
                return

            strategy = instance.settings.power_control_strategy
            if strategy != POWER_CONTROL_STRATEGY_MANUAL:
                return

            LOGGER.debug(
                "Manual mode: triggering immediate my_controller after max_power change (%.1f%%)",
                self._attr_native_value,
            )
            await instance.my_controller()
        except Exception as e:
            LOGGER.error("Error in _trigger_manual_mode_update: %s", e)