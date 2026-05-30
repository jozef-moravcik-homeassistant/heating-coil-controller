from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" helpers.py """

"""Shared helper functions for Heating Coil Controller."""

import logging
from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


async def load_translations(hass: HomeAssistant) -> dict:
    """Load translations for the current language.
    
    Tries to load the translation file for the active HA language.
    Falls back to strings.json if the language file does not exist.
    Returns an empty dict on any error.
    """
    import json
    import os

    def _load_file() -> dict:
        try:
            language = hass.config.language if hass else "en"

            translations_path = os.path.join(
                os.path.dirname(__file__), "translations", f"{language}.json"
            )

            # Fallback na strings.json ak preklad pre daný jazyk neexistuje
            if not os.path.exists(translations_path):
                translations_path = os.path.join(
                    os.path.dirname(__file__), "strings.json"
                )

            if os.path.exists(translations_path):
                with open(translations_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as ex:
            LOGGER.warning("Failed to load translations: %s", ex)
        return {}

    return await hass.async_add_executor_job(_load_file)


def get_master_entry_id(hass: HomeAssistant, entry_id: str) -> str | None:
    """Vráti entry_id mastera pre danú špirálku, alebo None ak nemá mastera.

    Args:
        hass: HomeAssistant inštancia
        entry_id: entry_id špirálky, pre ktorú hľadáme mastera

    Returns:
        entry_id mastera alebo None
    """
    from .const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL, CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID

    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry_id, {})
    if not isinstance(entry_data, dict):
        return None
    if entry_data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
        return None

    master_id = entry_data.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID)
    if master_id == DEFAULT_MASTER_HEATING_COIL_ID:
        return None

    # Overiť, že master existuje
    master_data = domain_data.get(master_id, {})
    if isinstance(master_data, dict) and master_data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_HEATING_COIL:
        return master_id

    return None


def get_slave_entry_ids(hass: HomeAssistant, master_entry_id: str) -> list[str]:
    """Vráti zoznam entry_id slave špirálok pre daného mastera.

    Args:
        hass: HomeAssistant inštancia
        master_entry_id: entry_id mastera

    Returns:
        list entry_id slave špirálok
    """
    from .const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL, CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID

    domain_data = hass.data.get(DOMAIN, {})
    slaves = []

    for eid, edata in domain_data.items():
        if eid == "shared" or eid == master_entry_id:
            continue
        if not isinstance(edata, dict):
            continue
        if edata.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
            continue
        mid = edata.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID)
        if mid == master_entry_id:
            slaves.append(eid)

    return slaves


def get_group_peer_entry_ids(hass: HomeAssistant, entry_id: str) -> list[str]:
    """Vráti zoznam entry_id všetkých ostatných členov skupiny (master + slaves, okrem seba).

    Ak je entry_id master → vráti všetky jeho slave.
    Ak je entry_id slave → vráti mastera + všetky ostatné slave toho istého mastera.
    Ak nie je v žiadnej skupine → vráti prázdny zoznam.

    Args:
        hass: HomeAssistant inštancia
        entry_id: entry_id špirálky

    Returns:
        list entry_id ostatných členov skupiny
    """
    peers = []

    # Zistiť či som slave (mám mastera)
    master_id = get_master_entry_id(hass, entry_id)

    if master_id is not None:
        # Som slave → master + ostatné slave rovnakého mastera
        peers.append(master_id)
        for sid in get_slave_entry_ids(hass, master_id):
            if sid != entry_id:
                peers.append(sid)
    else:
        # Možno som master → vrátiť mojich slave
        slaves = get_slave_entry_ids(hass, entry_id)
        peers.extend(slaves)

    return peers
