from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" config_flow.py """

"""Config flow for Heating Coil Controller."""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    EntitySelector,
    EntitySelectorConfig,
)
import homeassistant.helpers.config_validation as cv

from .heating_coil_controller import Heating_Coil_Controller_Instance
from .config_change_logger import log_config_snapshot
from .const import *

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pomocné funkcie
# ---------------------------------------------------------------------------

async def _get_modbus_node_names(hass: HomeAssistant) -> list[str]:
    """Vráti zoznam názvov existujúcich Modbus nodes (hubov) v systéme."""
    return list(hass.data.get("modbus", {}).keys())


async def _get_free_serial_ports(hass: HomeAssistant) -> list[str]:
    """Vráti dostupné sériové porty, ktoré ešte nie sú použité v Modbus nodes (type: serial)."""
    import serial.tools.list_ports  # pyserial je závislosť HA

    # Získaj všetky systémové sériové porty
    all_ports: list[str] = await hass.async_add_executor_job(
        lambda: sorted(p.device for p in serial.tools.list_ports.comports())
    )

    # Pokús sa zistiť porty, ktoré už používajú existujúce Modbus huby
    used_ports: set[str] = set()
    for hub in hass.data.get("modbus", {}).values():
        try:
            # ModbusHub ukladá port v rôznych atribútoch podľa verzie pymodbus
            for attr in ("port", "_port", "com_port"):
                port_val = getattr(hub, attr, None)
                if isinstance(port_val, str) and port_val.startswith("/"):
                    used_ports.add(port_val)
                    break
        except Exception:
            pass

    return [p for p in all_ports if p not in used_ports]


def _current(entry, key, default):
    """Získa aktuálnu hodnotu z options alebo data config_entry."""
    return entry.options.get(key, entry.data.get(key, default))


def _safe_tcp_port(value, default: int) -> int:
    """Konvertuje hodnotu portu na int.
    
    Ochrana pred prípadom keď je v config_entry uložený USB port (/dev/ttyACM0)
    a používateľ prepne typ pripojenia na TCP/UDP.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _get_modbus_node_entries(hass: HomeAssistant) -> list[dict]:
    """Vráti zoznam existujúcich Modbus Node config entries.
    
    Vracia list s dict: {"value": entry_id, "label": device_name}
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    nodes = []
    for e in entries:
        if e.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_MODBUS_NODE:
            name = e.data.get(CONF_DEVICE_NAME, "Modbus Node")
            nodes.append({"value": e.entry_id, "label": name})
    return nodes


def _is_master_for_others(hass: HomeAssistant, entry_id: str) -> bool:
    """Vráti True ak je táto Heating Coil nastavená ako MASTER pre iné Heating Coils."""
    entries = hass.config_entries.async_entries(DOMAIN)
    for e in entries:
        if e.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
            continue
        if e.entry_id == entry_id:
            continue
        master_id = e.options.get(CONF_MASTER_HEATING_COIL_ID, e.data.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID))
        if master_id == entry_id:
            return True
    return False


def _get_master_heating_coil_options(hass: HomeAssistant, current_entry_id: str | None) -> list[dict]:
    """Vráti zoznam možností pre výber MASTER Heating Coil.

    Vráti DISABLED (id=0) + všetky Heating Coil entries okrem:
    - práve konfigurovanej (current_entry_id)
    - tých, ktoré už majú nastavený vlastný MASTER (t.j. nie sú nezávislé)

    Args:
        hass: HomeAssistant inštancia
        current_entry_id: entry_id práve konfigurovanej Heating Coil (None pre novú)

    Returns:
        list[dict]: zoznam s {"value": entry_id/0, "label": device_name}
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    options = [{"value": "0", "label": "DISABLED"}]
    for e in entries:
        if e.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_HEATING_COIL:
            continue
        # Vynechať práve konfigurovanú
        if current_entry_id and e.entry_id == current_entry_id:
            continue
        # Vynechať tie, ktoré už majú nastavený MASTER (nie sú nezávislé)
        master_id = e.options.get(CONF_MASTER_HEATING_COIL_ID, e.data.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID))
        if master_id != DEFAULT_MASTER_HEATING_COIL_ID:
            continue
        name = e.data.get(CONF_DEVICE_NAME, "Heating Coil")
        options.append({"value": e.entry_id, "label": name})
    return options


# ===========================================================================
# ConfigFlow
# ===========================================================================

class HeatingCoilControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}

    # Inicializačná metóda, ktorá presmeruje config flow na prvý krok konfigurácie
    # Táto metóda tu musí byť, nesmie sa vymazať !!!
    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        return await self.async_step_device_type(user_input)

    # ------------------------------------------------------------------
    # Krok 0 – Výber typu zariadenia
    # ------------------------------------------------------------------
    async def async_step_device_type(self, user_input=None):
        """Handle device type selection."""
        errors = {}

        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        existing_types = {
            e.data.get(CONF_DEVICE_TYPE) for e in existing_entries
        }

        has_general = DEVICE_TYPE_GENERAL in existing_types
        has_modbus_node = DEVICE_TYPE_MODBUS_NODE in existing_types

        if user_input is not None:
            device_type = user_input[CONF_DEVICE_TYPE]
            self._data[CONF_DEVICE_TYPE] = device_type

            # General je jedinečné – povoliť len jedno
            if device_type == DEVICE_TYPE_GENERAL and has_general:
                return self.async_abort(reason="general_already_configured")

            if device_type == DEVICE_TYPE_GENERAL:
                self._data[CONF_DEVICE_NAME] = "General"
                return await self.async_step_general_basic_settings()

            elif device_type == DEVICE_TYPE_MODBUS_NODE:
                # Auto-assign "Modbus Node N"
                import re
                used_numbers: set[int] = set()
                for e in existing_entries:
                    name = e.data.get(CONF_DEVICE_NAME, "")
                    m = re.match(r"Modbus Node (\d+)$", name)
                    if m:
                        used_numbers.add(int(m.group(1)))
                n = 1
                while n in used_numbers:
                    n += 1
                self._data[CONF_DEVICE_NAME] = f"Modbus Node {n}"
                self._modbus_node_number = n
                self._data[CONF_MODBUS_NODE_NUMBER] = n
                return await self.async_step_modbus_node_basic_settings()

            elif device_type == DEVICE_TYPE_HEATING_COIL:
                return await self.async_step_control_parameters()

        # Určenie predvoleného typu zariadenia
        if not has_general:
            default_type = DEVICE_TYPE_GENERAL
        elif not has_modbus_node:
            default_type = DEVICE_TYPE_MODBUS_NODE
        else:
            default_type = DEVICE_TYPE_HEATING_COIL

        # Zostavenie zoznamu dostupných typov (General len ak ešte neexistuje)
        available_types = []
        if not has_general:
            available_types.append(DEVICE_TYPE_GENERAL)
        available_types.append(DEVICE_TYPE_MODBUS_NODE)
        available_types.append(DEVICE_TYPE_HEATING_COIL)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_TYPE,
                    default=default_type,
                ): SelectSelector(SelectSelectorConfig(
                    options=available_types,
                    mode=SelectSelectorMode.LIST,
                    translation_key="device_type",
                )),
            }
        )

        return self.async_show_form(
            step_id="device_type",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 0a – General: Základné nastavenie
    # ------------------------------------------------------------------
    async def async_step_general_basic_settings(self, user_input=None):
        """Handle General basic settings step."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            await self.async_set_unique_id(f"{DOMAIN}_general")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="General",
                data=self._data,
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                    default=False,
                ): cv.boolean,
                vol.Required(
                    CONF_HEATING_COIL_TOTAL_POWER,
                    default=self._data.get(CONF_HEATING_COIL_TOTAL_POWER, DEFAULT_HEATING_COIL_TOTAL_POWER),
                ): NumberSelector(NumberSelectorConfig(min=MIN_HEATING_COIL_TOTAL_POWER, max=MAX_HEATING_COIL_TOTAL_POWER, step=0.1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="general_basic_settings",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 0b – Modbus Node: Základné nastavenie
    # ------------------------------------------------------------------
    async def async_step_modbus_node_basic_settings(self, user_input=None):
        """Handle Modbus Node basic settings step."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_modbus_connection_type()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                    default=DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY,
                ): cv.boolean,
                vol.Required(
                    CONF_MODBUS_DEVICE_ID,
                    default=self._data.get(CONF_MODBUS_DEVICE_ID, DEFAULT_MODBUS_DEVICE_ID),
                ): NumberSelector(NumberSelectorConfig(min=MIN_MODBUS_DEVICE_ID, max=MAX_MODBUS_DEVICE_ID, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_DAC_TYPE,
                    default=self._data.get(CONF_DAC_TYPE, DEFAULT_DAC_TYPE),
                ): SelectSelector(SelectSelectorConfig(
                    options=DAC_TYPE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="dac_type",
                )),
            }
        )

        return self.async_show_form(
            step_id="modbus_node_basic_settings",
            data_schema=data_schema,
            errors=errors,
        )

    async def _create_modbus_node_entry(self):
        """Vytvorí config entry pre Modbus Node zariadenie."""
        device_name = self._data.get(CONF_DEVICE_NAME, "Modbus Node")
        n = getattr(self, "_modbus_node_number", 1)
        await self.async_set_unique_id(f"{DOMAIN}_modbus_node_{n}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=device_name,
            data=self._data,
        )

    # ------------------------------------------------------------------
    # Krok 1 – Control Parameters (Heating Coil)
    # ------------------------------------------------------------------
    async def async_step_control_parameters(self, user_input=None):
        """Handle the step 1. - Control Parameters."""
        errors = {}

        if user_input is not None:
            # Auto-assign lowest free "Heating Coil N" name
            import re
            existing_entries = self.hass.config_entries.async_entries(DOMAIN)
            used_numbers = set()
            for e in existing_entries:
                name = e.data.get(CONF_DEVICE_NAME, "")
                m = re.match(r"Heating Coil (\d+)$", name)
                if m:
                    used_numbers.add(int(m.group(1)))
            n = 1
            while n in used_numbers:
                n += 1
            self._data[CONF_DEVICE_NAME] = f"Heating Coil {n}"
            self._device_number = n

            self._data.update(user_input)

            # Ak je virtuálna špirála, preskočiť Modbus a Output Power Curve
            if self._data.get(CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL):
                return await self.async_step_power_control_strategy()

            return await self.async_step_modbus_device_settings()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                    default=DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY,
                ): cv.boolean,
                vol.Required(
                    CONF_HEATING_COIL_POWER,
                    default=self._data.get(CONF_HEATING_COIL_POWER, DEFAULT_HEATING_COIL_POWER),
                ): NumberSelector(NumberSelectorConfig(min=MIN_HEATING_COIL_POWER, max=MAX_HEATING_COIL_POWER, step=0.1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_VIRTUAL_HEATING_COIL,
                    default=self._data.get(CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL),
                ): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="control_parameters",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2 – Modbus: výber typu pripojenia
    # ------------------------------------------------------------------
    async def async_step_modbus_connection_type(self, user_input=None):
        """Handle modbus connection type selection."""
        errors = {}

        if user_input is not None:
            connection_type = user_input[CONF_MODBUS_CONNECTION_TYPE]
            self._data.update(user_input)

            if connection_type == MODBUS_CONNECTION_EXISTING_NODE:
                # Overiť, či existujú nejaké Modbus nodes
                nodes = await _get_modbus_node_names(self.hass)
                if not nodes:
                    errors["base"] = "no_modbus_nodes"
                else:
                    return await self.async_step_modbus_existing_node()

            elif connection_type == MODBUS_CONNECTION_USB:
                return await self.async_step_modbus_usb()

            elif connection_type == MODBUS_CONNECTION_TCP:
                return await self.async_step_modbus_tcp()

            elif connection_type == MODBUS_CONNECTION_UDP:
                return await self.async_step_modbus_udp()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_CONNECTION_TYPE,
                    default=self._data.get(CONF_MODBUS_CONNECTION_TYPE, DEFAULT_MODBUS_CONNECTION_TYPE),
                ): SelectSelector(SelectSelectorConfig(
                    options=MODBUS_CONNECTION_TYPE_OPTIONS,
                    mode=SelectSelectorMode.LIST,
                    translation_key="modbus_connection_type",
                )),
            }
        )

        return self.async_show_form(
            step_id="modbus_connection_type",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2a – Existujúci Modbus Node
    # ------------------------------------------------------------------
    async def async_step_modbus_existing_node(self, user_input=None):
        """Handle existing modbus node selection."""
        errors = {}

        if user_input is not None:
            # Uložiť Existing Node parameter s prefixom aj bez
            self._data["node_" + CONF_MODBUS_NODE_NAME] = user_input[CONF_MODBUS_NODE_NAME]
            self._data[CONF_MODBUS_NODE_NAME] = user_input[CONF_MODBUS_NODE_NAME]
            return await self._create_modbus_node_entry()

        nodes = await _get_modbus_node_names(self.hass)
        current_node = self._data.get("node_" + CONF_MODBUS_NODE_NAME, "")
        # Ak current_node nie je v zozname, použiť prvý dostupný
        if current_node not in nodes:
            current_node = nodes[0] if nodes else ""

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_NODE_NAME,
                    default=current_node,
                ): SelectSelector(SelectSelectorConfig(
                    options=nodes,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
            }
        )

        return self.async_show_form(
            step_id="modbus_existing_node",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2b – USB port (type: serial)
    # ------------------------------------------------------------------
    async def async_step_modbus_usb(self, user_input=None):
        """Handle USB serial port modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť USB parametre s prefixom aj bez
            self._data["usb_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["usb_" + CONF_MODBUS_BAUDRATE] = user_input[CONF_MODBUS_BAUDRATE]
            self._data["usb_" + CONF_MODBUS_BYTESIZE] = user_input[CONF_MODBUS_BYTESIZE]
            self._data["usb_" + CONF_MODBUS_STOPBITS] = user_input[CONF_MODBUS_STOPBITS]
            self._data["usb_" + CONF_MODBUS_PARITY] = user_input[CONF_MODBUS_PARITY]
            self._data["usb_" + CONF_MODBUS_DELAY] = user_input[CONF_MODBUS_DELAY]
            self._data["usb_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["usb_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_BAUDRATE] = user_input[CONF_MODBUS_BAUDRATE]
            self._data[CONF_MODBUS_BYTESIZE] = user_input[CONF_MODBUS_BYTESIZE]
            self._data[CONF_MODBUS_STOPBITS] = user_input[CONF_MODBUS_STOPBITS]
            self._data[CONF_MODBUS_PARITY] = user_input[CONF_MODBUS_PARITY]
            self._data[CONF_MODBUS_DELAY] = user_input[CONF_MODBUS_DELAY]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return await self._create_modbus_node_entry()

        available_ports = await _get_free_serial_ports(self.hass)

        # Ak nie sú žiadne voľné porty, zobraz chybovú správu
        if not available_ports:
            errors["base"] = "no_serial_ports"
            available_ports = []

        port_schema_field = (
            SelectSelector(SelectSelectorConfig(
                options=available_ports,
                mode=SelectSelectorMode.DROPDOWN,
            ))
            if available_ports
            else TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )
        
        # Načítať USB hodnoty z prefixovaných kľúčov
        current_port = self._data.get("usb_" + CONF_MODBUS_PORT, "")
        # Ak current_port nie je serial port (napr. je to "502"), použiť prvý dostupný
        if not (current_port and (current_port.startswith("/dev/") or current_port.startswith("COM") or current_port in available_ports)):
            current_port = available_ports[0] if available_ports else ""

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=current_port,
                ): port_schema_field,
                vol.Required(
                    CONF_MODBUS_BAUDRATE,
                    default=str(self._data.get("usb_" + CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_BAUDRATE_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_baudrate",
                )),
                vol.Required(
                    CONF_MODBUS_BYTESIZE,
                    default=str(self._data.get("usb_" + CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_BYTESIZE_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_bytesize",
                )),
                vol.Required(
                    CONF_MODBUS_STOPBITS,
                    default=str(self._data.get("usb_" + CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_STOPBITS_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_stopbits",
                )),
                vol.Required(
                    CONF_MODBUS_PARITY,
                    default=str(self._data.get("usb_" + CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY)),
                ): SelectSelector(SelectSelectorConfig(
                    options=MODBUS_PARITY_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_parity",
                )),
                vol.Required(
                    CONF_MODBUS_DELAY,
                    default=self._data.get("usb_" + CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY),
                ): NumberSelector(NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=self._data.get("usb_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=self._data.get("usb_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_usb",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2c – TCP server (type: tcp)
    # ------------------------------------------------------------------
    async def async_step_modbus_tcp(self, user_input=None):
        """Handle TCP modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť TCP parametre s prefixom aj bez
            self._data["tcp_" + CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data["tcp_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["tcp_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["tcp_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return await self._create_modbus_node_entry()
        
        # Načítať TCP hodnoty z prefixovaných kľúčov
        current_host = self._data.get("tcp_" + CONF_MODBUS_HOST, "")
        current_port = self._data.get("tcp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        # Zabezpečiť že port je číslo
        try:
            current_port = int(float(current_port))
        except (ValueError, TypeError):
            current_port = DEFAULT_MODBUS_TCP_PORT

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST,
                    default=current_host,
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=current_port,
                ): NumberSelector(NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=self._data.get("tcp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=self._data.get("tcp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_tcp",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2d – UDP server (type: udp)
    # ------------------------------------------------------------------
    async def async_step_modbus_udp(self, user_input=None):
        """Handle UDP modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť UDP parametre s prefixom aj bez
            self._data["udp_" + CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data["udp_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["udp_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["udp_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return await self._create_modbus_node_entry()
        
        # Načítať UDP hodnoty z prefixovaných kľúčov
        current_host = self._data.get("udp_" + CONF_MODBUS_HOST, "")
        current_port = self._data.get("udp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        # Zabezpečiť že port je číslo
        try:
            current_port = int(float(current_port))
        except (ValueError, TypeError):
            current_port = DEFAULT_MODBUS_TCP_PORT

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST,
                    default=current_host,
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=current_port,
                ): NumberSelector(NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=self._data.get("udp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=self._data.get("udp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_udp",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 3 – Modbus Device Settings (Heating Coil)
    # ------------------------------------------------------------------
    async def async_step_modbus_device_settings(self, user_input=None):
        """Handle Modbus Device Settings step."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_output_power_curve()

        # Získať zoznam dostupných Modbus Node zariadení
        modbus_nodes = _get_modbus_node_entries(self.hass)
        if not modbus_nodes:
            errors["base"] = "no_modbus_node_entries"

        node_options = [n["value"] for n in modbus_nodes] if modbus_nodes else [""]
        node_labels = {n["value"]: n["label"] for n in modbus_nodes}

        # Predvolená hodnota – prvý dostupný node
        current_node = self._data.get(CONF_MODBUS_NODE_ENTRY_ID, "")
        if current_node not in node_options and node_options:
            current_node = node_options[0]

        schema_fields = {}

        if modbus_nodes:
            schema_fields[vol.Required(
                CONF_MODBUS_NODE_ENTRY_ID,
                default=current_node,
            )] = SelectSelector(SelectSelectorConfig(
                options=[
                    {"value": n["value"], "label": n["label"]}
                    for n in modbus_nodes
                ],
                mode=SelectSelectorMode.DROPDOWN,
            ))

        schema_fields[vol.Required(
            CONF_DAC_OUTPUT_PORT_ID,
            default=self._data.get(CONF_DAC_OUTPUT_PORT_ID, DEFAULT_DAC_OUTPUT_PORT_ID),
        )] = NumberSelector(NumberSelectorConfig(min=MIN_DAC_OUTPUT_PORT_ID, max=MAX_DAC_OUTPUT_PORT_ID, step=1, mode=NumberSelectorMode.BOX))

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="modbus_device_settings",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 4 – Output Power Curve
    # ------------------------------------------------------------------
    async def async_step_output_power_curve(self, user_input=None):
        """Handle Output Power Curve step."""
        errors = {}

        if user_input is not None:
            zero = int(user_input[CONF_ZERO_POWER_POINT])
            maximum = int(user_input[CONF_MAXIMUM_POWER_POINT])
            if zero >= maximum:
                errors["base"] = "zero_power_point_too_high"
            else:
                self._data.update(user_input)
                return await self.async_step_thermal_protection()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_ZERO_POWER_POINT,
                    default=self._data.get(CONF_ZERO_POWER_POINT, DEFAULT_ZERO_POWER_POINT),
                ): NumberSelector(NumberSelectorConfig(min=MIN_POWER_POINT, max=MAX_POWER_POINT, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MAXIMUM_POWER_POINT,
                    default=self._data.get(CONF_MAXIMUM_POWER_POINT, DEFAULT_MAXIMUM_POWER_POINT),
                ): NumberSelector(NumberSelectorConfig(min=MIN_POWER_POINT, max=MAX_POWER_POINT, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_GAMMA,
                    default=self._data.get(CONF_GAMMA, DEFAULT_GAMMA),
                ): NumberSelector(NumberSelectorConfig(min=MIN_GAMMA, max=MAX_GAMMA, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="output_power_curve",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 4b – Thermal protection (safety fuse) – ConfigFlow
    # ------------------------------------------------------------------
    async def async_step_thermal_protection(self, user_input=None):
        """Handle Thermal Protection step (ConfigFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_power_control_strategy()

        # Zostaviť zoznam teplotných senzorov s friendly_name ako label
        temp_sensor_options_dicts = [{"value": THERMAL_PROTECTION_NO_SENSOR, "label": "- - -"}]
        for state in sorted(
            self.hass.states.async_all("sensor"),
            key=lambda s: (s.attributes.get("friendly_name") or s.entity_id).lower(),
        ):
            if (
                state.attributes.get("device_class") == "temperature"
                or state.attributes.get("unit_of_measurement") in ("°C", "°F", "K")
            ):
                friendly = state.attributes.get("friendly_name") or state.entity_id
                temp_sensor_options_dicts.append({"value": state.entity_id, "label": f"{friendly} ({state.entity_id})"})

        current_sensor = self._data.get(CONF_THERMAL_PROTECTION_SENSOR_ENTITY, DEFAULT_THERMAL_PROTECTION_SENSOR_ENTITY)
        known_values = {o["value"] for o in temp_sensor_options_dicts}
        if current_sensor and current_sensor not in known_values:
            temp_sensor_options_dicts.insert(1, {"value": current_sensor, "label": current_sensor})

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_THERMAL_PROTECTION_SENSOR_ENTITY,
                    default=current_sensor,
                ): SelectSelector(SelectSelectorConfig(
                    options=temp_sensor_options_dicts,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Required(
                    CONF_THERMAL_PROTECTION_MAX_TEMP,
                    default=self._data.get(CONF_THERMAL_PROTECTION_MAX_TEMP, DEFAULT_THERMAL_PROTECTION_MAX_TEMP),
                ): NumberSelector(NumberSelectorConfig(
                    min=MIN_THERMAL_PROTECTION_MAX_TEMP,
                    max=MAX_THERMAL_PROTECTION_MAX_TEMP,
                    step=1,
                    unit_of_measurement="°C",
                    mode=NumberSelectorMode.BOX,
                )),
            }
        )

        return self.async_show_form(
            step_id="thermal_protection",
            data_schema=data_schema,
        )

    # ------------------------------------------------------------------
    # Krok 4a – Power Control Strategy
    # ------------------------------------------------------------------
    async def async_step_power_control_strategy(self, user_input=None):
        """Handle Power Control Strategy step."""
        if user_input is not None:
            self._data.update(user_input)
            # Ak je vybraný MASTER, vynútiť MANUAL stratégiu a preskočiť ďalšie sekcie
            master_id = user_input.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID)
            if master_id != DEFAULT_MASTER_HEATING_COIL_ID:
                self._data[CONF_POWER_CONTROL_STRATEGY] = POWER_CONTROL_STRATEGY_MANUAL
                return await self.async_step_advanced_parameters()
            strategy = user_input.get(CONF_POWER_CONTROL_STRATEGY, DEFAULT_POWER_CONTROL_STRATEGY)
            if strategy == POWER_CONTROL_STRATEGY_SOLAR_SENSOR:
                return await self.async_step_solar_sensor_details()
            elif strategy == POWER_CONTROL_STRATEGY_PV_POWER:
                return await self.async_step_pv_power_details()
            elif strategy == POWER_CONTROL_STRATEGY_POWER_GRID:
                return await self.async_step_power_grid_details()
            elif strategy == POWER_CONTROL_STRATEGY_BATTERY:
                return await self.async_step_battery_power_details()
            elif strategy == POWER_CONTROL_STRATEGY_1:
                return await self.async_step_strategy_1_settings_part_1()
            elif strategy == POWER_CONTROL_STRATEGY_2:
                return await self.async_step_strategy_2_settings_part_1()
            else:
                return await self.async_step_advanced_parameters()

        master_options = _get_master_heating_coil_options(self.hass, None)
        is_virtual = self._data.get(CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL)

        schema_dict = {
            vol.Required(
                CONF_POWER_CONTROL_STRATEGY,
                default=self._data.get(CONF_POWER_CONTROL_STRATEGY, DEFAULT_POWER_CONTROL_STRATEGY),
            ): SelectSelector(SelectSelectorConfig(
                options=POWER_CONTROL_STRATEGY_OPTIONS,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="power_control_strategy",
            )),
        }

        # Selector pre MASTER sa nezobrazí ak je virtuálna špirála
        if not is_virtual:
            schema_dict[vol.Required(
                CONF_MASTER_HEATING_COIL_ID,
                default=self._data.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID),
            )] = SelectSelector(SelectSelectorConfig(
                options=master_options,
                mode=SelectSelectorMode.DROPDOWN,
            ))

        schema_dict[vol.Required(
            CONF_OUTPUT_POWER_DURING_DAY_ONLY,
            default=self._data.get(CONF_OUTPUT_POWER_DURING_DAY_ONLY, DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY),
        )] = cv.boolean

        schema_dict[vol.Required(
            CONF_TRACKED_ENTITIES_INTERVAL,
            default=self._data.get(CONF_TRACKED_ENTITIES_INTERVAL, DEFAULT_TRACKED_ENTITIES_INTERVAL),
        )] = NumberSelector(NumberSelectorConfig(min=MIN_TRACKED_ENTITIES_INTERVAL, max=MAX_TRACKED_ENTITIES_INTERVAL, step=1, mode=NumberSelectorMode.BOX))

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="power_control_strategy", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 5a – Solar Sensor Details
    # ------------------------------------------------------------------
    async def async_step_solar_sensor_details(self, user_input=None):
        """Handle Solar Sensor Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_SOLAR_SENSOR_ENTITY, DEFAULT_SOLAR_SENSOR_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_SOLAR_SENSOR_UNIT, DEFAULT_SOLAR_SENSOR_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_MAXIMUM_SOLAR_RADIATION_VALUE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_SOLAR_SENSOR_ATTENUATION, DEFAULT_SOLAR_SENSOR_ATTENUATION),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="solar_sensor_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 6a – PV Power Details
    # ------------------------------------------------------------------
    async def async_step_pv_power_details(self, user_input=None):
        """Handle PV Power Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PV_POWER_ENTITY,
                    default=self._data.get(CONF_PV_POWER_ENTITY, DEFAULT_PV_POWER_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_PV_POWER_UNIT,
                    default=self._data.get(CONF_PV_POWER_UNIT, DEFAULT_PV_POWER_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_PV_POWER_MAX_POWER,
                    default=self._data.get(CONF_PV_POWER_MAX_POWER, DEFAULT_PV_POWER_MAX_POWER),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=0.1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RATIO,
                    default=self._data.get(CONF_PV_POWER_RATIO, DEFAULT_PV_POWER_RATIO),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_PV_POWER_RAMP_UP_POWER_STEP, DEFAULT_PV_POWER_RAMP_UP_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_PV_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_UP_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_PV_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_PV_POWER_RAMP_DOWN_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_DOWN_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="pv_power_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 7a – Power Grid Details
    # ------------------------------------------------------------------
    async def async_step_power_grid_details(self, user_input=None):
        """Handle Power Grid Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_POWER_GRID_ENTITY, DEFAULT_POWER_GRID_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_POWER_GRID_UNIT,
                    default=self._data.get(CONF_POWER_GRID_UNIT, DEFAULT_POWER_GRID_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_POWER_GRID_DEAD_ZONE_W, DEFAULT_POWER_GRID_DEAD_ZONE_W),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_POWER_GRID_OFFSET_W, DEFAULT_POWER_GRID_OFFSET_W),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_POWER_GRID_OFFSET_EXPORT_LIMIT_W),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_POWER_GRID_RAMP_UP_POWER_STEP, DEFAULT_POWER_GRID_RAMP_UP_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_POWER_GRID_RAMP_UP_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_UP_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_POWER_GRID_RAMP_DOWN_POWER_STEP, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="power_grid_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 8a – Battery Power Details
    # ------------------------------------------------------------------
    async def async_step_battery_power_details(self, user_input=None):
        """Handle Battery Power Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_POWER_ENTITY,
                    default=self._data.get(CONF_BATTERY_POWER_ENTITY, DEFAULT_BATTERY_POWER_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_BATTERY_POWER_UNIT,
                    default=self._data.get(CONF_BATTERY_POWER_UNIT, DEFAULT_BATTERY_POWER_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_BATTERY_POWER_DEAD_ZONE_W,
                    default=self._data.get(CONF_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_BATTERY_POWER_DEAD_ZONE_W),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_OFFSET_W,
                    default=self._data.get(CONF_BATTERY_POWER_OFFSET_W, DEFAULT_BATTERY_POWER_OFFSET_W),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_UP_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="battery_power_details", data_schema=data_schema)

    async def async_step_strategy_1_settings_part_1(self, user_input=None):
        """Handle Strategy 1 Parameters part 1 step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_strategy_1_settings_part_2()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY, DEFAULT_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_ENTITY, DEFAULT_STRATEGY_1_POWER_GRID_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_UNIT, DEFAULT_STRATEGY_1_POWER_GRID_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W, DEFAULT_STRATEGY_1_POWER_GRID_DEAD_ZONE_W),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_OFFSET_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_W),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE, DEFAULT_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE),
                ): EntitySelector(EntitySelectorConfig(domain=["sensor", "input_boolean"])),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE, DEFAULT_STRATEGY_1_BATTERY_STATE_OF_CHARGE),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_ENTITY, DEFAULT_STRATEGY_1_BATTERY_POWER_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_UNIT, DEFAULT_STRATEGY_1_BATTERY_POWER_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W, DEFAULT_STRATEGY_1_BATTERY_POWER_OFFSET_W),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_UNIT, DEFAULT_STRATEGY_1_SOLAR_SENSOR_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ATTENUATION),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_1_settings_part_1", data_schema=data_schema)

    async def async_step_strategy_1_settings_part_2(self, user_input=None):
        """Handle Strategy 1 Parameters part 2 step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_FAST_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_1_settings_part_2", data_schema=data_schema)


    # ------------------------------------------------------------------
    # Krok 5b – Strategy 2 Settings part 1 (ConfigFlow)
    # ------------------------------------------------------------------
    async def async_step_strategy_2_settings_part_1(self, user_input=None):
        """Handle Strategy 2 Parameters part 1 step (ConfigFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_strategy_2_settings_part_2()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY, DEFAULT_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_ENTITY, DEFAULT_STRATEGY_2_POWER_GRID_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_UNIT,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_UNIT, DEFAULT_STRATEGY_2_POWER_GRID_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W, DEFAULT_STRATEGY_2_POWER_GRID_DEAD_ZONE_W),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_OFFSET_W, DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_W),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY, DEFAULT_STRATEGY_2_SOLAR_SENSOR_ENTITY),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_UNIT, DEFAULT_STRATEGY_2_SOLAR_SENSOR_UNIT),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION, DEFAULT_STRATEGY_2_SOLAR_SENSOR_ATTENUATION),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_2_settings_part_1", data_schema=data_schema)

    async def async_step_strategy_2_settings_part_2(self, user_input=None):
        """Handle Strategy 2 Parameters part 2 step (ConfigFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_UP_FAST_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_2_settings_part_2", data_schema=data_schema)


    # ------------------------------------------------------------------
    # Finalize – uloženie konfigurácie
    # ------------------------------------------------------------------
    async def async_step_advanced_parameters(self, user_input=None):
        """Finalize entry creation."""
        device_name = self._data.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME)
        device_number = getattr(self, "_device_number", 1)
        unique_id = f"heating_coil_{device_number}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=device_name,
            data=self._data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return HeatingCoilControllerOptionsFlowHandler()


# ===========================================================================
# OptionsFlow
# ===========================================================================

class HeatingCoilControllerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Heating Coil Controller."""

    def __init__(self):
        """Initialize options flow."""
        super().__init__()
        self._data = {}
        self._migrated = False
        self._base_data_loaded = False
    
    async def _ensure_prefixed_values(self):
        """Načíta existujúce prefixované hodnoty z config_entry a vytvorí defaults pre chýbajúce."""
        if self._migrated:
            return
        
        self._migrated = True
        current_data = dict(self.config_entry.data)
        current_data.update(self.config_entry.options)
        
        # VŽDY načítať USB parametre ak existujú v config_entry
        self._data["usb_" + CONF_MODBUS_PORT] = current_data.get("usb_" + CONF_MODBUS_PORT, "")
        self._data["usb_" + CONF_MODBUS_BAUDRATE] = current_data.get("usb_" + CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE)
        self._data["usb_" + CONF_MODBUS_BYTESIZE] = current_data.get("usb_" + CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE)
        self._data["usb_" + CONF_MODBUS_STOPBITS] = current_data.get("usb_" + CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS)
        self._data["usb_" + CONF_MODBUS_PARITY] = current_data.get("usb_" + CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY)
        self._data["usb_" + CONF_MODBUS_DELAY] = current_data.get("usb_" + CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY)
        self._data["usb_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get("usb_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
        self._data["usb_" + CONF_MODBUS_TIMEOUT] = current_data.get("usb_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # Ak USB parametre sú prázdne a aktuálne nastavenie je USB, skopírovať z neprefixovaných
        if not self._data["usb_" + CONF_MODBUS_PORT]:
            port = current_data.get(CONF_MODBUS_PORT, "")
            if isinstance(port, str) and (port.startswith("/dev/") or port.startswith("COM")):
                self._data["usb_" + CONF_MODBUS_PORT] = port
                self._data["usb_" + CONF_MODBUS_BAUDRATE] = current_data.get(CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE)
                self._data["usb_" + CONF_MODBUS_BYTESIZE] = current_data.get(CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE)
                self._data["usb_" + CONF_MODBUS_STOPBITS] = current_data.get(CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS)
                self._data["usb_" + CONF_MODBUS_PARITY] = current_data.get(CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY)
                self._data["usb_" + CONF_MODBUS_DELAY] = current_data.get(CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY)
                self._data["usb_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get(CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
                self._data["usb_" + CONF_MODBUS_TIMEOUT] = current_data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # VŽDY načítať TCP parametre ak existujú v config_entry
        self._data["tcp_" + CONF_MODBUS_HOST] = current_data.get("tcp_" + CONF_MODBUS_HOST, "")
        self._data["tcp_" + CONF_MODBUS_PORT] = current_data.get("tcp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        self._data["tcp_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get("tcp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
        self._data["tcp_" + CONF_MODBUS_TIMEOUT] = current_data.get("tcp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # Ak TCP parametre sú prázdne a aktuálne nastavenie je TCP, skopírovať z neprefixovaných
        if not self._data["tcp_" + CONF_MODBUS_HOST]:
            host = current_data.get(CONF_MODBUS_HOST, "")
            if host:
                self._data["tcp_" + CONF_MODBUS_HOST] = host
                port = current_data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
                try:
                    port = int(float(port))
                except (ValueError, TypeError):
                    port = DEFAULT_MODBUS_TCP_PORT
                self._data["tcp_" + CONF_MODBUS_PORT] = port
                self._data["tcp_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get(CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
                self._data["tcp_" + CONF_MODBUS_TIMEOUT] = current_data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # VŽDY načítať UDP parametre ak existujú v config_entry
        self._data["udp_" + CONF_MODBUS_HOST] = current_data.get("udp_" + CONF_MODBUS_HOST, "")
        self._data["udp_" + CONF_MODBUS_PORT] = current_data.get("udp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        self._data["udp_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get("udp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
        self._data["udp_" + CONF_MODBUS_TIMEOUT] = current_data.get("udp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # Ak UDP parametre sú prázdne, skopírovať z TCP alebo z neprefixovaných
        if not self._data["udp_" + CONF_MODBUS_HOST]:
            # Najprv skúsiť TCP
            if self._data["tcp_" + CONF_MODBUS_HOST]:
                self._data["udp_" + CONF_MODBUS_HOST] = self._data["tcp_" + CONF_MODBUS_HOST]
                self._data["udp_" + CONF_MODBUS_PORT] = self._data["tcp_" + CONF_MODBUS_PORT]
                self._data["udp_" + CONF_MODBUS_MESSAGE_WAIT] = self._data["tcp_" + CONF_MODBUS_MESSAGE_WAIT]
                self._data["udp_" + CONF_MODBUS_TIMEOUT] = self._data["tcp_" + CONF_MODBUS_TIMEOUT]
            else:
                # Inak z neprefixovaných ak je to UDP typ
                host = current_data.get(CONF_MODBUS_HOST, "")
                if host:
                    self._data["udp_" + CONF_MODBUS_HOST] = host
                    port = current_data.get(CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
                    try:
                        port = int(float(port))
                    except (ValueError, TypeError):
                        port = DEFAULT_MODBUS_TCP_PORT
                    self._data["udp_" + CONF_MODBUS_PORT] = port
                    self._data["udp_" + CONF_MODBUS_MESSAGE_WAIT] = current_data.get(CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT)
                    self._data["udp_" + CONF_MODBUS_TIMEOUT] = current_data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)
        
        # VŽDY načítať Existing Node parametre ak existujú v config_entry
        self._data["node_" + CONF_MODBUS_NODE_NAME] = current_data.get("node_" + CONF_MODBUS_NODE_NAME, current_data.get(CONF_MODBUS_NODE_NAME, ""))

    # Inicializačná metóda, ktorá presmeruje config flow na prvý krok konfigurácie
    # Táto metóda tu musí byť, nesmie sa vymazať !!!
    async def async_step_init(self, user_input=None):
        """Handle the initial step of options flow."""
        # Načítať VŠETKY aktuálne hodnoty z config_entry do self._data hneď na začiatku
        # Tým sa zabezpečí, že pri prepínaní stratégií sa nezresetujú parametre
        if not self._base_data_loaded:
            self._base_data_loaded = True
            current_data = dict(self.config_entry.data)
            current_data.update(self.config_entry.options)
            self._data.update(current_data)

        device_type = self.config_entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_HEATING_COIL)

        if device_type == DEVICE_TYPE_GENERAL:
            return await self.async_step_general_basic_settings(user_input)

        if device_type == DEVICE_TYPE_MODBUS_NODE:
            return await self.async_step_modbus_node_basic_settings(user_input)

        # Heating Coil – pôvodný options flow
        return await self.async_step_control_parameters(user_input)

    # ------------------------------------------------------------------
    # General: Základné nastavenie (Options)
    # ------------------------------------------------------------------
    async def async_step_general_basic_settings(self, user_input=None):
        """Handle General basic settings options step."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                    default=_current(self.config_entry, CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY),
                ): cv.boolean,
                vol.Required(
                    CONF_HEATING_COIL_TOTAL_POWER,
                    default=self._data.get(CONF_HEATING_COIL_TOTAL_POWER, _current(self.config_entry, CONF_HEATING_COIL_TOTAL_POWER, DEFAULT_HEATING_COIL_TOTAL_POWER)),
                ): NumberSelector(NumberSelectorConfig(min=MIN_HEATING_COIL_TOTAL_POWER, max=MAX_HEATING_COIL_TOTAL_POWER, step=0.1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(step_id="general_basic_settings", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Modbus Node: Základné nastavenie (Options)
    # ------------------------------------------------------------------
    async def async_step_modbus_node_basic_settings(self, user_input=None):
        """Handle Modbus Node basic settings options step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_modbus_connection_type()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                    default=_current(self.config_entry, CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY),
                ): cv.boolean,
                vol.Required(
                    CONF_MODBUS_DEVICE_ID,
                    default=self._data.get(CONF_MODBUS_DEVICE_ID, _current(self.config_entry, CONF_MODBUS_DEVICE_ID, DEFAULT_MODBUS_DEVICE_ID)),
                ): NumberSelector(NumberSelectorConfig(min=MIN_MODBUS_DEVICE_ID, max=MAX_MODBUS_DEVICE_ID, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_DAC_TYPE,
                    default=self._data.get(CONF_DAC_TYPE, _current(self.config_entry, CONF_DAC_TYPE, DEFAULT_DAC_TYPE)),
                ): SelectSelector(SelectSelectorConfig(
                    options=DAC_TYPE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="dac_type",
                )),
            }
        )

        return self.async_show_form(step_id="modbus_node_basic_settings", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 1 – Control Parameters (Heating Coil Options)
    # ------------------------------------------------------------------
    async def async_step_control_parameters(self, user_input=None):
        """Handle the step 1. - Control Parameters."""

        if user_input is not None:
            self._data.update(user_input)

            # Ak je virtuálna špirála, preskočiť Modbus a Output Power Curve
            if self._data.get(CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL):
                return await self.async_step_power_control_strategy()

            return await self.async_step_modbus_device_settings()

        is_master = _is_master_for_others(self.hass, self.config_entry.entry_id)

        schema_fields = {
            vol.Required(
                CONF_INCLUDE_DEVICE_NAME_IN_ENTITY,
                default=_current(self.config_entry, CONF_INCLUDE_DEVICE_NAME_IN_ENTITY, DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY),
            ): cv.boolean,
        }

        # Výkon špirály sa nezobrazuje ak je Master (počíta sa automaticky zo Slave)
        if not is_master:
            schema_fields[vol.Required(
                CONF_HEATING_COIL_POWER,
                default=self._data.get(CONF_HEATING_COIL_POWER, _current(self.config_entry, CONF_HEATING_COIL_POWER, DEFAULT_HEATING_COIL_POWER)),
            )] = NumberSelector(NumberSelectorConfig(min=MIN_HEATING_COIL_POWER, max=MAX_HEATING_COIL_POWER, step=0.1, mode=NumberSelectorMode.BOX))

        schema_fields[vol.Required(
            CONF_VIRTUAL_HEATING_COIL,
            default=self._data.get(CONF_VIRTUAL_HEATING_COIL, _current(self.config_entry, CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL)),
        )] = cv.boolean

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(step_id="control_parameters", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 2 – Modbus: výber typu pripojenia
    # ------------------------------------------------------------------
    async def async_step_modbus_connection_type(self, user_input=None):
        """Handle modbus connection type selection."""
        errors = {}
        # Zabezpečiť migráciu prefixovaných hodnôt
        await self._ensure_prefixed_values()

        if user_input is not None:
            connection_type = user_input[CONF_MODBUS_CONNECTION_TYPE]
            self._data.update(user_input)

            if connection_type == MODBUS_CONNECTION_EXISTING_NODE:
                nodes = await _get_modbus_node_names(self.hass)
                if not nodes:
                    errors["base"] = "no_modbus_nodes"
                else:
                    return await self.async_step_modbus_existing_node()

            elif connection_type == MODBUS_CONNECTION_USB:
                return await self.async_step_modbus_usb()

            elif connection_type == MODBUS_CONNECTION_TCP:
                return await self.async_step_modbus_tcp()

            elif connection_type == MODBUS_CONNECTION_UDP:
                return await self.async_step_modbus_udp()

        current_type = _current(self.config_entry, CONF_MODBUS_CONNECTION_TYPE, DEFAULT_MODBUS_CONNECTION_TYPE)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_CONNECTION_TYPE,
                    default=self._data.get(CONF_MODBUS_CONNECTION_TYPE, current_type),
                ): SelectSelector(SelectSelectorConfig(
                    options=MODBUS_CONNECTION_TYPE_OPTIONS,
                    mode=SelectSelectorMode.LIST,
                    translation_key="modbus_connection_type",
                )),
            }
        )

        return self.async_show_form(
            step_id="modbus_connection_type",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2a – Existujúci Modbus Node
    # ------------------------------------------------------------------
    async def async_step_modbus_existing_node(self, user_input=None):
        """Handle existing modbus node selection."""
        errors = {}

        if user_input is not None:
            # Uložiť Existing Node parameter s prefixom aj bez
            self._data["node_" + CONF_MODBUS_NODE_NAME] = user_input[CONF_MODBUS_NODE_NAME]
            self._data[CONF_MODBUS_NODE_NAME] = user_input[CONF_MODBUS_NODE_NAME]
            return self.async_create_entry(title="", data=self._data)

        nodes = await _get_modbus_node_names(self.hass)
        # Načítať z prefixovaného kľúča v config_entry
        current_node = _current(self.config_entry, "node_" + CONF_MODBUS_NODE_NAME, nodes[0] if nodes else "")
        # Ak current_node nie je v zozname, použiť prvý dostupný
        if current_node not in nodes:
            current_node = nodes[0] if nodes else ""

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_NODE_NAME,
                    default=current_node,
                ): SelectSelector(SelectSelectorConfig(
                    options=nodes,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
            }
        )

        return self.async_show_form(
            step_id="modbus_existing_node",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2b – USB port (type: serial)
    # ------------------------------------------------------------------
    async def async_step_modbus_usb(self, user_input=None):
        """Handle USB serial port modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť USB parametre s prefixom aj bez (rovnako ako v Init Flow)
            self._data["usb_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["usb_" + CONF_MODBUS_BAUDRATE] = user_input[CONF_MODBUS_BAUDRATE]
            self._data["usb_" + CONF_MODBUS_BYTESIZE] = user_input[CONF_MODBUS_BYTESIZE]
            self._data["usb_" + CONF_MODBUS_STOPBITS] = user_input[CONF_MODBUS_STOPBITS]
            self._data["usb_" + CONF_MODBUS_PARITY] = user_input[CONF_MODBUS_PARITY]
            self._data["usb_" + CONF_MODBUS_DELAY] = user_input[CONF_MODBUS_DELAY]
            self._data["usb_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["usb_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_BAUDRATE] = user_input[CONF_MODBUS_BAUDRATE]
            self._data[CONF_MODBUS_BYTESIZE] = user_input[CONF_MODBUS_BYTESIZE]
            self._data[CONF_MODBUS_STOPBITS] = user_input[CONF_MODBUS_STOPBITS]
            self._data[CONF_MODBUS_PARITY] = user_input[CONF_MODBUS_PARITY]
            self._data[CONF_MODBUS_DELAY] = user_input[CONF_MODBUS_DELAY]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return self.async_create_entry(title="", data=self._data)

        available_ports = await _get_free_serial_ports(self.hass)
        # Načítať USB port z prefixovaného kľúča v config_entry
        current_port = _current(self.config_entry, "usb_" + CONF_MODBUS_PORT, "")

        if not available_ports:
            errors["base"] = "no_serial_ports"

        # Konvertovať current_port na string (môže byť float 502.0)
        current_port = str(current_port) if current_port else ""
        
        # Ak aktuálny port nie je v zozname, pridáme ho (napr. po reštarte)
        if current_port and current_port.startswith(("/dev/", "COM")) and current_port not in available_ports:
            available_ports = [current_port] + available_ports
        
        # Načítať port
        port_to_use = current_port
        # Ak nie je serial port, použiť prvý dostupný
        if not (port_to_use and (port_to_use.startswith("/dev/") or port_to_use.startswith("COM") or port_to_use in available_ports)):
            port_to_use = available_ports[0] if available_ports else ""

        port_schema_field = (
            SelectSelector(SelectSelectorConfig(
                options=available_ports,
                mode=SelectSelectorMode.DROPDOWN,
            ))
            if available_ports
            else TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=port_to_use,
                ): port_schema_field,
                vol.Required(
                    CONF_MODBUS_BAUDRATE,
                    default=str(_current(self.config_entry, "usb_" + CONF_MODBUS_BAUDRATE, DEFAULT_MODBUS_BAUDRATE)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_BAUDRATE_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_baudrate",
                )),
                vol.Required(
                    CONF_MODBUS_BYTESIZE,
                    default=str(_current(self.config_entry, "usb_" + CONF_MODBUS_BYTESIZE, DEFAULT_MODBUS_BYTESIZE)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_BYTESIZE_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_bytesize",
                )),
                vol.Required(
                    CONF_MODBUS_STOPBITS,
                    default=str(_current(self.config_entry, "usb_" + CONF_MODBUS_STOPBITS, DEFAULT_MODBUS_STOPBITS)),
                ): SelectSelector(SelectSelectorConfig(
                    options=[str(x) for x in MODBUS_STOPBITS_OPTIONS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_stopbits",
                )),
                vol.Required(
                    CONF_MODBUS_PARITY,
                    default=_current(self.config_entry, "usb_" + CONF_MODBUS_PARITY, DEFAULT_MODBUS_PARITY),
                ): SelectSelector(SelectSelectorConfig(
                    options=MODBUS_PARITY_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="modbus_parity",
                )),
                vol.Required(
                    CONF_MODBUS_DELAY,
                    default=_current(self.config_entry, "usb_" + CONF_MODBUS_DELAY, DEFAULT_MODBUS_DELAY),
                ): NumberSelector(NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=_current(self.config_entry, "usb_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=_current(self.config_entry, "usb_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_usb",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2c – TCP server (type: tcp)
    # ------------------------------------------------------------------
    async def async_step_modbus_tcp(self, user_input=None):
        """Handle TCP modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť TCP parametre s prefixom aj bez
            self._data["tcp_" + CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data["tcp_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["tcp_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["tcp_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return self.async_create_entry(title="", data=self._data)
        
        # Načítať TCP hodnoty z prefixovaných kľúčov v config_entry
        current_host = _current(self.config_entry, "tcp_" + CONF_MODBUS_HOST, "")
        current_port = _current(self.config_entry, "tcp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        # Zabezpečiť že port je číslo
        try:
            current_port = int(float(current_port))
        except (ValueError, TypeError):
            current_port = DEFAULT_MODBUS_TCP_PORT

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST,
                    default=current_host,
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=current_port,
                ): NumberSelector(NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=_current(self.config_entry, "tcp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=_current(self.config_entry, "tcp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_tcp",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 2d – UDP server (type: udp)
    # ------------------------------------------------------------------
    async def async_step_modbus_udp(self, user_input=None):
        """Handle UDP modbus configuration."""
        errors = {}

        if user_input is not None:
            # Uložiť UDP parametre s prefixom aj bez
            self._data["udp_" + CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data["udp_" + CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data["udp_" + CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data["udp_" + CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            # Uložiť aj bez prefixu pre finálne uloženie
            self._data[CONF_MODBUS_HOST] = user_input[CONF_MODBUS_HOST]
            self._data[CONF_MODBUS_PORT] = user_input[CONF_MODBUS_PORT]
            self._data[CONF_MODBUS_MESSAGE_WAIT] = user_input[CONF_MODBUS_MESSAGE_WAIT]
            self._data[CONF_MODBUS_TIMEOUT] = user_input[CONF_MODBUS_TIMEOUT]
            return self.async_create_entry(title="", data=self._data)
        
        # Načítať UDP hodnoty z prefixovaných kľúčov v config_entry
        current_host = _current(self.config_entry, "udp_" + CONF_MODBUS_HOST, "")
        current_port = _current(self.config_entry, "udp_" + CONF_MODBUS_PORT, DEFAULT_MODBUS_TCP_PORT)
        # Zabezpečiť že port je číslo
        try:
            current_port = int(float(current_port))
        except (ValueError, TypeError):
            current_port = DEFAULT_MODBUS_TCP_PORT

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODBUS_HOST,
                    default=current_host,
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=current_port,
                ): NumberSelector(NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_MESSAGE_WAIT,
                    default=_current(self.config_entry, "udp_" + CONF_MODBUS_MESSAGE_WAIT, DEFAULT_MODBUS_MESSAGE_WAIT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MODBUS_TIMEOUT,
                    default=_current(self.config_entry, "udp_" + CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT),
                ): NumberSelector(NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="modbus_udp",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 3 – Modbus Device Settings (Heating Coil Options)
    # ------------------------------------------------------------------
    async def async_step_modbus_device_settings(self, user_input=None):
        """Handle Modbus Device Settings step."""
        errors = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_output_power_curve()

        # Získať zoznam dostupných Modbus Node zariadení
        modbus_nodes = _get_modbus_node_entries(self.hass)
        if not modbus_nodes:
            errors["base"] = "no_modbus_node_entries"

        current_node = self._data.get(
            CONF_MODBUS_NODE_ENTRY_ID,
            _current(self.config_entry, CONF_MODBUS_NODE_ENTRY_ID, DEFAULT_MODBUS_NODE_ENTRY_ID),
        )
        node_options = [n["value"] for n in modbus_nodes] if modbus_nodes else []
        if current_node not in node_options and node_options:
            current_node = node_options[0]

        schema_fields = {}

        if modbus_nodes:
            schema_fields[vol.Required(
                CONF_MODBUS_NODE_ENTRY_ID,
                default=current_node,
            )] = SelectSelector(SelectSelectorConfig(
                options=[
                    {"value": n["value"], "label": n["label"]}
                    for n in modbus_nodes
                ],
                mode=SelectSelectorMode.DROPDOWN,
            ))

        schema_fields[vol.Required(
            CONF_DAC_OUTPUT_PORT_ID,
            default=self._data.get(CONF_DAC_OUTPUT_PORT_ID, _current(self.config_entry, CONF_DAC_OUTPUT_PORT_ID, DEFAULT_DAC_OUTPUT_PORT_ID)),
        )] = NumberSelector(NumberSelectorConfig(min=MIN_DAC_OUTPUT_PORT_ID, max=MAX_DAC_OUTPUT_PORT_ID, step=1, mode=NumberSelectorMode.BOX))

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="modbus_device_settings",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 4 – Output Power Curve
    # ------------------------------------------------------------------
    async def async_step_output_power_curve(self, user_input=None):
        """Handle Output Power Curve step."""
        errors = {}

        if user_input is not None:
            zero = int(user_input[CONF_ZERO_POWER_POINT])
            maximum = int(user_input[CONF_MAXIMUM_POWER_POINT])
            if zero >= maximum:
                errors["base"] = "zero_power_point_too_high"
            else:
                self._data.update(user_input)
                return await self.async_step_thermal_protection()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_ZERO_POWER_POINT,
                    default=self._data.get(CONF_ZERO_POWER_POINT, _current(self.config_entry, CONF_ZERO_POWER_POINT, DEFAULT_ZERO_POWER_POINT)),
                ): NumberSelector(NumberSelectorConfig(min=MIN_POWER_POINT, max=MAX_POWER_POINT, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_MAXIMUM_POWER_POINT,
                    default=self._data.get(CONF_MAXIMUM_POWER_POINT, _current(self.config_entry, CONF_MAXIMUM_POWER_POINT, DEFAULT_MAXIMUM_POWER_POINT)),
                ): NumberSelector(NumberSelectorConfig(min=MIN_POWER_POINT, max=MAX_POWER_POINT, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_GAMMA,
                    default=self._data.get(CONF_GAMMA, _current(self.config_entry, CONF_GAMMA, DEFAULT_GAMMA)),
                ): NumberSelector(NumberSelectorConfig(min=MIN_GAMMA, max=MAX_GAMMA, step=1, mode=NumberSelectorMode.BOX)),
            }
        )

        return self.async_show_form(
            step_id="output_power_curve",
            data_schema=data_schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Krok 4b – Thermal protection (safety fuse) – OptionsFlow
    # ------------------------------------------------------------------
    async def async_step_thermal_protection(self, user_input=None):
        """Handle Thermal Protection step (OptionsFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_power_control_strategy()

        # Zostaviť zoznam teplotných senzorov s friendly_name ako label
        temp_sensor_options_dicts = [{"value": THERMAL_PROTECTION_NO_SENSOR, "label": "- - -"}]
        for state in sorted(
            self.hass.states.async_all("sensor"),
            key=lambda s: (s.attributes.get("friendly_name") or s.entity_id).lower(),
        ):
            if (
                state.attributes.get("device_class") == "temperature"
                or state.attributes.get("unit_of_measurement") in ("°C", "°F", "K")
            ):
                friendly = state.attributes.get("friendly_name") or state.entity_id
                temp_sensor_options_dicts.append({"value": state.entity_id, "label": f"{friendly} ({state.entity_id})"})

        current_sensor = self._data.get(
            CONF_THERMAL_PROTECTION_SENSOR_ENTITY,
            _current(self.config_entry, CONF_THERMAL_PROTECTION_SENSOR_ENTITY, DEFAULT_THERMAL_PROTECTION_SENSOR_ENTITY),
        )
        known_values = {o["value"] for o in temp_sensor_options_dicts}
        if current_sensor and current_sensor not in known_values:
            temp_sensor_options_dicts.insert(1, {"value": current_sensor, "label": current_sensor})

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_THERMAL_PROTECTION_SENSOR_ENTITY,
                    default=current_sensor,
                ): SelectSelector(SelectSelectorConfig(
                    options=temp_sensor_options_dicts,
                    mode=SelectSelectorMode.DROPDOWN,
                )),
                vol.Required(
                    CONF_THERMAL_PROTECTION_MAX_TEMP,
                    default=self._data.get(
                        CONF_THERMAL_PROTECTION_MAX_TEMP,
                        _current(self.config_entry, CONF_THERMAL_PROTECTION_MAX_TEMP, DEFAULT_THERMAL_PROTECTION_MAX_TEMP),
                    ),
                ): NumberSelector(NumberSelectorConfig(
                    min=MIN_THERMAL_PROTECTION_MAX_TEMP,
                    max=MAX_THERMAL_PROTECTION_MAX_TEMP,
                    step=1,
                    unit_of_measurement="°C",
                    mode=NumberSelectorMode.BOX,
                )),
            }
        )

        return self.async_show_form(
            step_id="thermal_protection",
            data_schema=data_schema,
        )

    # ------------------------------------------------------------------
    # Krok 4a – Power Control Strategy
    # ------------------------------------------------------------------
    async def async_step_power_control_strategy(self, user_input=None):
        """Handle Power Control Strategy step."""
        if user_input is not None:
            self._data.update(user_input)
            # Ak je vybraný MASTER, vynútiť MANUAL stratégiu a preskočiť ďalšie sekcie
            master_id = user_input.get(CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID)
            if master_id != DEFAULT_MASTER_HEATING_COIL_ID:
                self._data[CONF_POWER_CONTROL_STRATEGY] = POWER_CONTROL_STRATEGY_MANUAL
                return await self.async_step_advanced_parameters()
            strategy = user_input.get(CONF_POWER_CONTROL_STRATEGY, DEFAULT_POWER_CONTROL_STRATEGY)
            if strategy == POWER_CONTROL_STRATEGY_SOLAR_SENSOR:
                return await self.async_step_solar_sensor_details()
            elif strategy == POWER_CONTROL_STRATEGY_PV_POWER:
                return await self.async_step_pv_power_details()
            elif strategy == POWER_CONTROL_STRATEGY_POWER_GRID:
                return await self.async_step_power_grid_details()
            elif strategy == POWER_CONTROL_STRATEGY_BATTERY:
                return await self.async_step_battery_power_details()
            elif strategy == POWER_CONTROL_STRATEGY_1:
                return await self.async_step_strategy_1_settings_part_1()
            elif strategy == POWER_CONTROL_STRATEGY_2:
                return await self.async_step_strategy_2_settings_part_1()
            else:
                return await self.async_step_advanced_parameters()

        is_master = _is_master_for_others(self.hass, self.config_entry.entry_id)
        is_virtual = self._data.get(CONF_VIRTUAL_HEATING_COIL, _current(self.config_entry, CONF_VIRTUAL_HEATING_COIL, DEFAULT_VIRTUAL_HEATING_COIL))

        schema_dict = {
            vol.Required(
                CONF_POWER_CONTROL_STRATEGY,
                default=self._data.get(CONF_POWER_CONTROL_STRATEGY, _current(self.config_entry, CONF_POWER_CONTROL_STRATEGY, DEFAULT_POWER_CONTROL_STRATEGY)),
            ): SelectSelector(SelectSelectorConfig(
                options=POWER_CONTROL_STRATEGY_OPTIONS,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="power_control_strategy",
            )),
        }

        # Selector pre MASTER sa zobrazí len ak táto špiráľa NIE je MASTER pre iné a NIE je virtuálna
        if not is_master and not is_virtual:
            master_options = _get_master_heating_coil_options(self.hass, self.config_entry.entry_id)
            valid_values = {opt["value"] for opt in master_options}
            stored_master = self._data.get(CONF_MASTER_HEATING_COIL_ID, _current(self.config_entry, CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID))
            if stored_master not in valid_values:
                stored_master = DEFAULT_MASTER_HEATING_COIL_ID
            schema_dict[vol.Required(
                CONF_MASTER_HEATING_COIL_ID,
                default=stored_master,
            )] = SelectSelector(SelectSelectorConfig(
                options=master_options,
                mode=SelectSelectorMode.DROPDOWN,
            ))

        schema_dict[vol.Required(
            CONF_OUTPUT_POWER_DURING_DAY_ONLY,
            default=self._data.get(CONF_OUTPUT_POWER_DURING_DAY_ONLY, _current(self.config_entry, CONF_OUTPUT_POWER_DURING_DAY_ONLY, DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY)),
        )] = cv.boolean

        # Tracked entities interval sa nezobrazuje pre Slave špirály (ovládané Masterom)
        current_master = self._data.get(CONF_MASTER_HEATING_COIL_ID, _current(self.config_entry, CONF_MASTER_HEATING_COIL_ID, DEFAULT_MASTER_HEATING_COIL_ID))
        if current_master == DEFAULT_MASTER_HEATING_COIL_ID:
            schema_dict[vol.Required(
                CONF_TRACKED_ENTITIES_INTERVAL,
                default=self._data.get(CONF_TRACKED_ENTITIES_INTERVAL, _current(self.config_entry, CONF_TRACKED_ENTITIES_INTERVAL, DEFAULT_TRACKED_ENTITIES_INTERVAL)),
            )] = NumberSelector(NumberSelectorConfig(min=MIN_TRACKED_ENTITIES_INTERVAL, max=MAX_TRACKED_ENTITIES_INTERVAL, step=1, mode=NumberSelectorMode.BOX))

        data_schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="power_control_strategy", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 5a – Solar Sensor Details
    # ------------------------------------------------------------------
    async def async_step_solar_sensor_details(self, user_input=None):
        """Handle Solar Sensor Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_SOLAR_SENSOR_ENTITY, _current(self.config_entry, CONF_SOLAR_SENSOR_ENTITY, DEFAULT_SOLAR_SENSOR_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_SOLAR_SENSOR_UNIT, _current(self.config_entry, CONF_SOLAR_SENSOR_UNIT, DEFAULT_SOLAR_SENSOR_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_MAXIMUM_SOLAR_RADIATION_VALUE, _current(self.config_entry, CONF_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_MAXIMUM_SOLAR_RADIATION_VALUE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_SOLAR_SENSOR_ATTENUATION, _current(self.config_entry, CONF_SOLAR_SENSOR_ATTENUATION, DEFAULT_SOLAR_SENSOR_ATTENUATION)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP, _current(self.config_entry, CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE, _current(self.config_entry, CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP, _current(self.config_entry, CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE, _current(self.config_entry, CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE, DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="solar_sensor_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 6a – PV Power Details
    # ------------------------------------------------------------------
    async def async_step_pv_power_details(self, user_input=None):
        """Handle PV Power Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PV_POWER_ENTITY,
                    default=self._data.get(CONF_PV_POWER_ENTITY, _current(self.config_entry, CONF_PV_POWER_ENTITY, DEFAULT_PV_POWER_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_PV_POWER_UNIT,
                    default=self._data.get(CONF_PV_POWER_UNIT, _current(self.config_entry, CONF_PV_POWER_UNIT, DEFAULT_PV_POWER_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_PV_POWER_MAX_POWER,
                    default=self._data.get(CONF_PV_POWER_MAX_POWER, _current(self.config_entry, CONF_PV_POWER_MAX_POWER, DEFAULT_PV_POWER_MAX_POWER)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=0.1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RATIO,
                    default=self._data.get(CONF_PV_POWER_RATIO, _current(self.config_entry, CONF_PV_POWER_RATIO, DEFAULT_PV_POWER_RATIO)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_PV_POWER_RAMP_UP_POWER_STEP, _current(self.config_entry, CONF_PV_POWER_RAMP_UP_POWER_STEP, DEFAULT_PV_POWER_RAMP_UP_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_PV_POWER_RAMP_UP_POWER_CYCLE, _current(self.config_entry, CONF_PV_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_UP_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_PV_POWER_RAMP_DOWN_POWER_STEP, _current(self.config_entry, CONF_PV_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_PV_POWER_RAMP_DOWN_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE, _current(self.config_entry, CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_PV_POWER_RAMP_DOWN_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="pv_power_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 7a – Power Grid Details
    # ------------------------------------------------------------------
    async def async_step_power_grid_details(self, user_input=None):
        """Handle Power Grid Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_POWER_GRID_ENTITY, _current(self.config_entry, CONF_POWER_GRID_ENTITY, DEFAULT_POWER_GRID_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_POWER_GRID_UNIT,
                    default=self._data.get(CONF_POWER_GRID_UNIT, _current(self.config_entry, CONF_POWER_GRID_UNIT, DEFAULT_POWER_GRID_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_POWER_GRID_DEAD_ZONE_W, _current(self.config_entry, CONF_POWER_GRID_DEAD_ZONE_W, DEFAULT_POWER_GRID_DEAD_ZONE_W)),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_POWER_GRID_OFFSET_W, _current(self.config_entry, CONF_POWER_GRID_OFFSET_W, DEFAULT_POWER_GRID_OFFSET_W)),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W, _current(self.config_entry, CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_POWER_GRID_OFFSET_EXPORT_LIMIT_W)),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_POWER_GRID_RAMP_UP_POWER_STEP, _current(self.config_entry, CONF_POWER_GRID_RAMP_UP_POWER_STEP, DEFAULT_POWER_GRID_RAMP_UP_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_POWER_GRID_RAMP_UP_POWER_CYCLE, _current(self.config_entry, CONF_POWER_GRID_RAMP_UP_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_UP_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_POWER_GRID_RAMP_DOWN_POWER_STEP, _current(self.config_entry, CONF_POWER_GRID_RAMP_DOWN_POWER_STEP, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE, _current(self.config_entry, CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE, DEFAULT_POWER_GRID_RAMP_DOWN_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="power_grid_details", data_schema=data_schema)

    # ------------------------------------------------------------------
    # Krok 8a – Battery Power Details
    # ------------------------------------------------------------------
    async def async_step_battery_power_details(self, user_input=None):
        """Handle Battery Power Control details step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_POWER_ENTITY,
                    default=self._data.get(CONF_BATTERY_POWER_ENTITY, _current(self.config_entry, CONF_BATTERY_POWER_ENTITY, DEFAULT_BATTERY_POWER_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_BATTERY_POWER_UNIT,
                    default=self._data.get(CONF_BATTERY_POWER_UNIT, _current(self.config_entry, CONF_BATTERY_POWER_UNIT, DEFAULT_BATTERY_POWER_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_BATTERY_POWER_DEAD_ZONE_W,
                    default=self._data.get(CONF_BATTERY_POWER_DEAD_ZONE_W, _current(self.config_entry, CONF_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_BATTERY_POWER_DEAD_ZONE_W)),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_OFFSET_W,
                    default=self._data.get(CONF_BATTERY_POWER_OFFSET_W, _current(self.config_entry, CONF_BATTERY_POWER_OFFSET_W, DEFAULT_BATTERY_POWER_OFFSET_W)),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_UP_POWER_STEP,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_UP_POWER_STEP, _current(self.config_entry, CONF_BATTERY_POWER_RAMP_UP_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE, _current(self.config_entry, CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_UP_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP, _current(self.config_entry, CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE,
                    default=self._data.get(CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE, _current(self.config_entry, CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE, DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="battery_power_details", data_schema=data_schema)

    async def async_step_strategy_1_settings_part_1(self, user_input=None):
        """Handle Strategy 1 Parameters part 1 step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_strategy_1_settings_part_2()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY, _current(self.config_entry, CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY, DEFAULT_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_ENTITY, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_ENTITY, DEFAULT_STRATEGY_1_POWER_GRID_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_UNIT, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_UNIT, DEFAULT_STRATEGY_1_POWER_GRID_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W, DEFAULT_STRATEGY_1_POWER_GRID_DEAD_ZONE_W)),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_OFFSET_W, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_OFFSET_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_W)),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W)),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE, DEFAULT_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE)),
                ): EntitySelector(EntitySelectorConfig(domain=["sensor", "input_boolean"])),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE, DEFAULT_STRATEGY_1_BATTERY_STATE_OF_CHARGE)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_ENTITY, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_POWER_ENTITY, DEFAULT_STRATEGY_1_BATTERY_POWER_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_UNIT, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_POWER_UNIT, DEFAULT_STRATEGY_1_BATTERY_POWER_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W, DEFAULT_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W)),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W, DEFAULT_STRATEGY_1_BATTERY_POWER_OFFSET_W)),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY, _current(self.config_entry, CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_UNIT, _current(self.config_entry, CONF_STRATEGY_1_SOLAR_SENSOR_UNIT, DEFAULT_STRATEGY_1_SOLAR_SENSOR_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE, _current(self.config_entry, CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION, _current(self.config_entry, CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION, DEFAULT_STRATEGY_1_SOLAR_SENSOR_ATTENUATION)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_1_settings_part_1", data_schema=data_schema)

    async def async_step_strategy_1_settings_part_2(self, user_input=None):
        """Handle Strategy 1 Parameters part 2 step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_FAST_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP, DEFAULT_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_1_settings_part_2", data_schema=data_schema)


    # ------------------------------------------------------------------
    # Krok 5b – Strategy 2 Settings part 1 (OptionsFlow)
    # ------------------------------------------------------------------
    async def async_step_strategy_2_settings_part_1(self, user_input=None):
        """Handle Strategy 2 Parameters part 1 step (OptionsFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_strategy_2_settings_part_2()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY, _current(self.config_entry, CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY, DEFAULT_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_ENTITY, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_ENTITY, DEFAULT_STRATEGY_2_POWER_GRID_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_UNIT,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_UNIT, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_UNIT, DEFAULT_STRATEGY_2_POWER_GRID_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W, DEFAULT_STRATEGY_2_POWER_GRID_DEAD_ZONE_W)),
                ): NumberSelector(NumberSelectorConfig(min=-5000, max=5000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_OFFSET_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_OFFSET_W, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_OFFSET_W, DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_W)),
                ): NumberSelector(NumberSelectorConfig(min=-10000, max=10000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W, DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W)),
                ): NumberSelector(NumberSelectorConfig(min=-100000, max=100000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY, _current(self.config_entry, CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY, DEFAULT_STRATEGY_2_SOLAR_SENSOR_ENTITY)),
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_UNIT,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_UNIT, _current(self.config_entry, CONF_STRATEGY_2_SOLAR_SENSOR_UNIT, DEFAULT_STRATEGY_2_SOLAR_SENSOR_UNIT)),
                ): SelectSelector(SelectSelectorConfig(
                    options=SENSOR_UNIT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="sensor_unit",
                )),
                vol.Required(
                    CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE,
                    default=self._data.get(CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE, _current(self.config_entry, CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE, DEFAULT_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=2000, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION, _current(self.config_entry, CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION, DEFAULT_STRATEGY_2_SOLAR_SENSOR_ATTENUATION)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_2_settings_part_1", data_schema=data_schema)

    async def async_step_strategy_2_settings_part_2(self, user_input=None):
        """Handle Strategy 2 Parameters part 2 step (OptionsFlow)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced_parameters()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD, DEFAULT_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD,
                    default=self._data.get(CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, _current(self.config_entry, CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD, DEFAULT_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=50000, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_UP_FAST_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP,
                    default=self._data.get(CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP, _current(self.config_entry, CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP, DEFAULT_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP)),
                ): NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="strategy_2_settings_part_2", data_schema=data_schema)


    # ------------------------------------------------------------------
    # Finalize – uloženie konfigurácie
    # ------------------------------------------------------------------
    async def async_step_advanced_parameters(self, user_input=None):
        """Finalize options entry."""
        try:
            await self.hass.async_add_executor_job(
                log_config_snapshot,
                self.config_entry.entry_id,
                self.config_entry.title,
                self._data,
            )
        except Exception:
            pass
        return self.async_create_entry(title="", data=self._data)

