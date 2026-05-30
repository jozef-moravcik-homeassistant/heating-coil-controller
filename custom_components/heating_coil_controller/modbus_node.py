from __future__ import annotations
"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" modbus_node.py """

"""Modbus Node – centralizovaná Modbus komunikácia pre Heating Coil zariadenia."""

import asyncio
import logging
import dataclasses

from homeassistant.core import HomeAssistant
from .const import *

try:
    from pymodbus.client import (
        ModbusSerialClient,
        ModbusTcpClient,
        ModbusUdpClient,
    )
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False

LOGGER = logging.getLogger(__name__)


class ModbusNodeInstance:
    """Centralizovaná Modbus komunikačná inštancia.
    
    Jedno fyzické Modbus zariadenie (DAC) je reprezentované jedným ModbusNodeInstance.
    Viacero Heating Coil zariadení môže zdieľať jeden ModbusNodeInstance.
    asyncio.Lock zabezpečuje, že na jednom Modbus porte prebieha vždy len jedna komunikácia.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._lock = asyncio.Lock()

        # Modbus klient
        self.modbus_client = None
        self._modbus_client_params = None

        # Nastavenia – budú nastavené z __init__.py
        self.settings = self.Settings()

        # Posledný chybový kód (pre error_code sensor) – bitové príznaky
        self.error_code: int = MODBUS_ERROR_NONE

    @dataclasses.dataclass
    class Settings:
        modbus_connection_type: str = DEFAULT_MODBUS_CONNECTION_TYPE
        modbus_node_name: str = ""
        port: str = ""
        baudrate: int = DEFAULT_MODBUS_BAUDRATE
        bytesize: int = DEFAULT_MODBUS_BYTESIZE
        stopbits: int = DEFAULT_MODBUS_STOPBITS
        parity: str = DEFAULT_MODBUS_PARITY
        delay: int = DEFAULT_MODBUS_DELAY
        message_wait_millisecond: int = DEFAULT_MODBUS_MESSAGE_WAIT
        timeout: int = DEFAULT_MODBUS_TIMEOUT
        host: str = ""
        modbus_device_id: int = DEFAULT_MODBUS_DEVICE_ID
        dac_type: str = DEFAULT_DAC_TYPE

    @property
    def dac_conversion_ratio(self) -> float:
        """Vráti konverzný pomer pre aktuálny typ DAC."""
        return DAC_CONVERSION_RATIOS.get(self.settings.dac_type, DEFAULT_DAC_CONVERSION_RATIO)

    def close_modbus_client(self):
        """Zatvorí Modbus klienta ak existuje."""
        if self.modbus_client is not None:
            try:
                if hasattr(self.modbus_client, 'close'):
                    self.modbus_client.close()
                    LOGGER.debug("ModbusNode [%s]: client closed", self._entry_id[:8])
            except Exception as e:
                LOGGER.error("ModbusNode [%s]: error closing client: %s", self._entry_id[:8], e)
            finally:
                self.modbus_client = None

    async def modbus_communication(
        self,
        device_id: int,
        command: int,
        address: int,
        count: int,
    ) -> dict:
        """
        Univerzálna metóda pre Modbus komunikáciu – thread-safe cez asyncio.Lock.

        Args:
            device_id: Modbus ID zariadenia (1 Byte)
            command: Modbus funkčný kód (napr. 03=Read Holding, 06=Write Single)
            address: Modbus adresa registra (2 Bytes)
            count: Počet registrov alebo hodnota na zápis (2 Bytes)

        Returns:
            dict: {'success': bool, 'data': Any, 'error': str}
        """
        async with self._lock:
            result = await self._modbus_communication_unsafe(
                device_id, command, address, count
            )

        # Aktualizovať error_code sensor
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, f"{DOMAIN}_modbus_node_update_{self._entry_id}")

        return result

    async def _modbus_communication_unsafe(
        self,
        device_id: int,
        command: int,
        address: int,
        count: int,
    ) -> dict:
        """Vnútorná implementácia Modbus komunikácie (bez locku).
        
        Pri zlyhaní zatvorí klienta a automaticky vykoná jeden retry
        s novým pripojením.
        """
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            result = await self._modbus_single_attempt(
                device_id, command, address, count, attempt,
            )
            if result['success']:
                return result

            # Zlyhanie – zatvoriť klienta aby sa pri ďalšom pokuse vytvoril nový
            LOGGER.warning(
                "ModbusNode [%s]: attempt %d/%d failed: %s – closing client for reconnect",
                self._entry_id[:8], attempt, max_attempts, result['error'],
            )
            self.close_modbus_client()

        # Všetky pokusy zlyhali
        return result

    async def _modbus_single_attempt(
        self,
        device_id: int,
        command: int,
        address: int,
        count: int,
        attempt: int,
    ) -> dict:
        """Jeden pokus o Modbus komunikáciu."""
        result = {
            'success': False,
            'data': None,
            'error': None,
        }

        try:
            conn_type = self.settings.modbus_connection_type

            # ***** Existing Node *****
            if conn_type == MODBUS_CONNECTION_EXISTING_NODE:
                node_name = self.settings.modbus_node_name
                if not node_name:
                    result['error'] = "Modbus node name not configured"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_PORT_OPEN
                    return result

                from homeassistant.components.modbus import DOMAIN as MODBUS_DOMAIN
                if MODBUS_DOMAIN not in self.hass.data:
                    result['error'] = "Modbus integration not loaded"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_PORT_OPEN
                    return result

                modbus_hubs = self.hass.data[MODBUS_DOMAIN]
                if node_name not in modbus_hubs:
                    result['error'] = f"Modbus node '{node_name}' not found"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_PORT_OPEN
                    return result

                hub = modbus_hubs[node_name]

                if command == 3:  # Read Holding Registers
                    response = await hub.async_pb_call(
                        device_id, address, count, "holding"
                    )
                elif command == 6:  # Write Single Register
                    response = await hub.async_pb_call(
                        device_id, address, count, "write_register"
                    )
                else:
                    result['error'] = f"Unsupported command: {command}"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_UNKNOWN
                    return result

                if response and not response.isError():
                    result['success'] = True
                    result['data'] = response
                    self.error_code = MODBUS_ERROR_NONE
                else:
                    result['error'] = f"Modbus communication error: {response}"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_COMMUNICATION

            # ***** USB / TCP / UDP *****
            else:
                if not PYMODBUS_AVAILABLE:
                    result['error'] = "pymodbus library not available"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_PORT_OPEN
                    return result

                current_params = {
                    'type': conn_type,
                    'port': str(self.settings.port) if self.settings.port else '',
                    'baudrate': self.settings.baudrate if conn_type == MODBUS_CONNECTION_USB else None,
                    'bytesize': self.settings.bytesize if conn_type == MODBUS_CONNECTION_USB else None,
                    'stopbits': self.settings.stopbits if conn_type == MODBUS_CONNECTION_USB else None,
                    'parity': self.settings.parity if conn_type == MODBUS_CONNECTION_USB else None,
                    'host': self.settings.host if conn_type in (MODBUS_CONNECTION_TCP, MODBUS_CONNECTION_UDP) else None,
                    'timeout': self.settings.timeout,
                }

                if self._modbus_client_params != current_params:
                    LOGGER.debug("ModbusNode [%s]: params changed, reconnecting", self._entry_id[:8])
                    self.close_modbus_client()
                    self._modbus_client_params = current_params

                # Vytvorenie klienta
                if self.modbus_client is None:
                    if conn_type == MODBUS_CONNECTION_USB:
                        self.modbus_client = ModbusSerialClient(
                            port=self.settings.port,
                            baudrate=self.settings.baudrate,
                            bytesize=self.settings.bytesize,
                            stopbits=self.settings.stopbits,
                            parity=self.settings.parity,
                            timeout=self.settings.timeout,
                        )
                    elif conn_type == MODBUS_CONNECTION_TCP:
                        port = self._safe_port(self.settings.port, DEFAULT_MODBUS_TCP_PORT)
                        self.modbus_client = ModbusTcpClient(
                            host=self.settings.host,
                            port=port,
                            timeout=self.settings.timeout,
                        )
                    elif conn_type == MODBUS_CONNECTION_UDP:
                        port = self._safe_port(self.settings.port, DEFAULT_MODBUS_TCP_PORT)
                        self.modbus_client = ModbusUdpClient(
                            host=self.settings.host,
                            port=port,
                            timeout=self.settings.timeout,
                        )

                # Pripojenie
                if not self.modbus_client.connected:
                    await self.hass.async_add_executor_job(self.modbus_client.connect)

                if not self.modbus_client.connected:
                    result['error'] = f"Failed to connect to Modbus device (attempt {attempt})"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_PORT_OPEN
                    return result

                # Nastavenie slave ID
                slave_set = False
                for attr in ('slave', 'unit', 'unit_id', 'slave_id'):
                    if hasattr(self.modbus_client, attr):
                        try:
                            setattr(self.modbus_client, attr, device_id)
                            slave_set = True
                            break
                        except Exception:
                            pass

                # Vykonanie príkazu
                response = None
                try:
                    if command == 3:  # Read Holding Registers
                        if slave_set:
                            response = await self.hass.async_add_executor_job(
                                self.modbus_client.read_holding_registers, address, count
                            )
                        else:
                            try:
                                response = await self.hass.async_add_executor_job(
                                    self.modbus_client.read_holding_registers, address, count, device_id
                                )
                            except TypeError:
                                response = await self.hass.async_add_executor_job(
                                    self.modbus_client.read_holding_registers, address, count
                                )
                    elif command == 6:  # Write Single Register
                        LOGGER.debug(
                            "ModbusNode [%s]: write register addr=%d val=%d dev=%d (attempt %d)",
                            self._entry_id[:8], address, count, device_id, attempt,
                        )
                        if slave_set:
                            response = await self.hass.async_add_executor_job(
                                self.modbus_client.write_register, address, count
                            )
                        else:
                            try:
                                response = await self.hass.async_add_executor_job(
                                    self.modbus_client.write_register, address, count, device_id
                                )
                            except TypeError:
                                response = await self.hass.async_add_executor_job(
                                    self.modbus_client.write_register, address, count
                                )
                    else:
                        result['error'] = f"Unsupported command: {command}"
                        LOGGER.error(result['error'])
                        self.error_code |= MODBUS_ERROR_UNKNOWN
                        return result
                except Exception as e:
                    result['error'] = f"Modbus call exception (attempt {attempt}): {str(e)}"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_COMMUNICATION
                    return result

                if response and not response.isError():
                    result['success'] = True
                    result['data'] = response
                    self.error_code = MODBUS_ERROR_NONE
                else:
                    result['error'] = f"Modbus communication error (attempt {attempt}): {response}"
                    LOGGER.error(result['error'])
                    self.error_code |= MODBUS_ERROR_COMMUNICATION

        except Exception as e:
            result['error'] = f"Exception in modbus_communication (attempt {attempt}): {str(e)}"
            LOGGER.error(result['error'])
            self.error_code |= MODBUS_ERROR_UNKNOWN

        return result

    @staticmethod
    def _safe_port(value, default: int) -> int:
        """Konvertuje hodnotu portu na int."""
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
