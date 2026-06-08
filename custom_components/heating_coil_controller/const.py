"""The Heating_Coil_Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" const.py """

"""Constants for the Heating_Coil_Controller."""
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNKNOWN, STATE_UNAVAILABLE, STATE_OK, STATE_PROBLEM

DOMAIN = "heating_coil_controller"
VERSION = "0.01.03"
MANUFACTURER = "Jozef Moravcik"
MODEL = "Heating Coil"
NAME = "Heating Coil Controller"
DOCUMENTATION_URL = "https://github.com/jozef-moravcik-homeassistant/heating-coil-controller"

def sanitize_device_name(device_name: str) -> str:
    """Sanitize device name for use in entity IDs."""
    import re
    # Convert to lowercase
    sanitized = device_name.lower()
    # Replace spaces and special characters with underscore
    sanitized = re.sub(r'[^a-z0-9]+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    # Limit length
    sanitized = sanitized[:20]
    return sanitized if sanitized else "device"

##############################################################################################################################
# Services ###################################################################################################################
##############################################################################################################################
SERVICE_SYSTEM_STARTED = "system_started"
SERVICE_TURN_OFF_ALL   = "turn_off_all"
SERVICE_TURN_ON_ALL    = "turn_on_all"

##############################################################################################################################
# States and commands ########################################################################################################
##############################################################################################################################
STATE_NONE = "none"
STATE_FALSE = "false"
STATE_TRUE = "true"
STATE_OPEN = "open"
STATE_CLOSED = "closed"

##############################################################################################################################
# Device type ################################################################################################################
##############################################################################################################################

CONF_DEVICE_TYPE = "device_type"
DEVICE_TYPE_GENERAL     = "general"
DEVICE_TYPE_MODBUS_NODE = "modbus_node"
DEVICE_TYPE_HEATING_COIL = "heating_coil"

DEVICE_TYPE_OPTIONS = [
    DEVICE_TYPE_GENERAL,
    DEVICE_TYPE_MODBUS_NODE,
    DEVICE_TYPE_HEATING_COIL,
]

DEFAULT_DEVICE_TYPE = DEVICE_TYPE_GENERAL

##############################################################################################################################
# Configuration keys #########################################################################################################
##############################################################################################################################

CONF_DEVICE_NAME = "device_name"
DEFAULT_DEVICE_NAME = "Coil 1"

CONF_INCLUDE_DEVICE_NAME_IN_ENTITY = "include_device_name_in_entity"
DEFAULT_INCLUDE_DEVICE_NAME_IN_ENTITY = True

CONF_VIRTUAL_HEATING_COIL = "virtual_heating_coil"
DEFAULT_VIRTUAL_HEATING_COIL = False

# ----------------------------------------------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------------------------------------------

CONF_GRID_EXPORT_STATUS_ENTITY = "grid_export_status_entity"
DEFAULT_CONF_GRID_EXPORT_STATUS_ENTITY = ""

CONF_ENABLE_GRID_EXPORT_STATUS = "enable_grid_export_status"
DEFAULT_ENABLE_GRID_EXPORT_STATUS = False

CONF_OUTPUT_POWER_DURING_DAY_ONLY = "output_power_during_day_only"
DEFAULT_OUTPUT_POWER_DURING_DAY_ONLY = False

# ----------------------------------------------------------------------------------------------------------------------------

##############################################################################################################################
# Power control strategy #####################################################################################################
##############################################################################################################################

CONF_POWER_CONTROL_STRATEGY = "power_control_strategy"

POWER_CONTROL_STRATEGY_MANUAL           = "0"
POWER_CONTROL_STRATEGY_1                = "1"
POWER_CONTROL_STRATEGY_2                = "s2"
POWER_CONTROL_STRATEGY_SOLAR_SENSOR     = "2"
POWER_CONTROL_STRATEGY_PV_POWER         = "3"
POWER_CONTROL_STRATEGY_POWER_GRID       = "4"
POWER_CONTROL_STRATEGY_BATTERY          = "5"

POWER_CONTROL_STRATEGY_OPTIONS = [
    POWER_CONTROL_STRATEGY_MANUAL,
    POWER_CONTROL_STRATEGY_1,
    POWER_CONTROL_STRATEGY_2,
    POWER_CONTROL_STRATEGY_SOLAR_SENSOR,
    POWER_CONTROL_STRATEGY_PV_POWER,
    POWER_CONTROL_STRATEGY_POWER_GRID,
    POWER_CONTROL_STRATEGY_BATTERY,
]

DEFAULT_POWER_CONTROL_STRATEGY = POWER_CONTROL_STRATEGY_MANUAL

# ----------------------------------------------------------------------------------------------------------------------------


##############################################################################################################################
# Internal entity names (will be prefixed with DOMAIN in code) ###############################################################
# These entities are created by this integration #############################################################################
##############################################################################################################################

# Prefix pre entity_id zariadenia General
GENERAL_ENTITY_ID_PREFIX = "heating_coil_general"

# Entity pre zariadenie General
ENTITY_GENERAL_BUTTON_OFF_ALL    = "off_all"
ENTITY_GENERAL_BUTTON_ON_ALL     = "on_all"
ENTITY_GENERAL_SENSOR_TOTAL_POWER = "total_power"

# Prefix pre entity_id zariadenia Modbus Node
MODBUS_NODE_ENTITY_ID_PREFIX = "heating_coil_node"

# Číslo Modbus Node zariadenia (1, 2, 3, ...)
CONF_MODBUS_NODE_NUMBER = "modbus_node_number"

# Entity pre zariadenie Modbus Node
ENTITY_MODBUS_NODE_SENSOR_ERROR_CODE = "error_code"

# Referencia Heating Coil na Modbus Node (entry_id)
CONF_MODBUS_NODE_ENTRY_ID = "modbus_node_entry_id"
DEFAULT_MODBUS_NODE_ENTRY_ID = ""

# Entity pre zariadenie Heating Coil
ENTITY_OUTPUT_POWER_PERCENT = "output_power_percent"
ENTITY_OUTPUT_POWER_KW = "output_power_kw"
ENTITY_ENABLE = "enable"
ENTITY_ONLY_USE_POWER_ABOVE_EXPORT_LIMIT = "only_use_power_above_export_limit"
ENTITY_AUTO_POWER_CONTROL = "auto_power_control"
ENTITY_MAX_POWER = "max_power"

##############################################################################################################################
# Parameters for number sensors ##############################################################################################
##############################################################################################################################
MIN_MAX_POWER = 0        # Minimum value for Max Power
MAX_MAX_POWER = 100      # Maximum value for Max Power
DEFAULT_MAX_POWER = 0    # Default Value for Max Power

##############################################################################################################################
# Modbus connection configuration ############################################################################################
##############################################################################################################################

CONF_MODBUS_CONNECTION_TYPE = "modbus_connection_type"
MODBUS_CONNECTION_EXISTING_NODE = "existing_node"
MODBUS_CONNECTION_USB         = "usb"
MODBUS_CONNECTION_TCP         = "tcp"
MODBUS_CONNECTION_UDP         = "udp"
MODBUS_CONNECTION_TYPE_OPTIONS = [
    MODBUS_CONNECTION_EXISTING_NODE,
    MODBUS_CONNECTION_USB,
    MODBUS_CONNECTION_TCP,
    MODBUS_CONNECTION_UDP,
]
DEFAULT_MODBUS_CONNECTION_TYPE = MODBUS_CONNECTION_EXISTING_NODE

CONF_MODBUS_NODE_NAME             = "modbus_node_name"
CONF_MODBUS_PORT                  = "port"
CONF_MODBUS_BAUDRATE              = "baudrate"
CONF_MODBUS_BYTESIZE              = "bytesize"
CONF_MODBUS_STOPBITS              = "stopbits"
CONF_MODBUS_PARITY                = "parity"
CONF_MODBUS_DELAY                 = "delay"
CONF_MODBUS_MESSAGE_WAIT          = "message_wait_millisecond"
CONF_MODBUS_TIMEOUT               = "timeout"
CONF_MODBUS_HOST                  = "host"
CONF_MODBUS_DEVICE_ID             = "modbus_device_id"

DEFAULT_MODBUS_DEVICE_ID          = 1
MIN_MODBUS_DEVICE_ID              = 1
MAX_MODBUS_DEVICE_ID              = 254

DEFAULT_MODBUS_BAUDRATE           = 9600
DEFAULT_MODBUS_BYTESIZE           = 8
DEFAULT_MODBUS_STOPBITS           = 1
DEFAULT_MODBUS_PARITY             = "N"
DEFAULT_MODBUS_DELAY              = 1
DEFAULT_MODBUS_MESSAGE_WAIT       = 50
DEFAULT_MODBUS_TIMEOUT            = 1
DEFAULT_MODBUS_TCP_PORT           = 502

MODBUS_BAUDRATE_OPTIONS  = [300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200, 128000, 230400, 256000]
MODBUS_BYTESIZE_OPTIONS  = [5, 6, 7, 8]
MODBUS_STOPBITS_OPTIONS  = [1, 2]
# N = None, E = Even, O = Odd, M = Mark
MODBUS_PARITY_OPTIONS    = ["N", "E", "O", "M"]

##############################################################################################################################
# DAC output configuration ###################################################################################################
##############################################################################################################################
CONF_DAC_OUTPUT_PORT_ID = "dac_output_port_id"
DEFAULT_DAC_OUTPUT_PORT_ID = 1
MIN_DAC_OUTPUT_PORT_ID = 1
MAX_DAC_OUTPUT_PORT_ID = 32

CONF_DAC_OUTPUT_TYPE = "dac_output_type"
DAC_OUTPUT_TYPE_0_10V  = "0-10V"
DAC_OUTPUT_TYPE_0_20MA = "0-20mA"
DAC_OUTPUT_TYPE_4_20MA = "4-20mA"
DAC_OUTPUT_TYPE_OPTIONS = [
    DAC_OUTPUT_TYPE_0_10V,
    DAC_OUTPUT_TYPE_0_20MA,
    DAC_OUTPUT_TYPE_4_20MA,
]
DEFAULT_DAC_OUTPUT_TYPE = DAC_OUTPUT_TYPE_0_10V

CONF_DAC_TYPE = "dac_type"
DAC_TYPE_AMVOL08       = "amvol08"
DAC_TYPE_DACI4_I420    = "daci4_i420"
DAC_TYPE_OPTIONS = [
    DAC_TYPE_AMVOL08,
    DAC_TYPE_DACI4_I420,
]
DEFAULT_DAC_TYPE = DAC_TYPE_AMVOL08

# DAC konverzné pomery (digitálna hodnota = analógová hodnota * pomer)
DAC_CONVERSION_RATIOS = {
    DAC_TYPE_AMVOL08:    10.00,   # AMVOL08 (8 x 0-10V)
    DAC_TYPE_DACI4_I420: 40.95,   # DACI4_I4-20 (4 x 4-20mA)
}
DEFAULT_DAC_CONVERSION_RATIO = 10.00

##############################################################################################################################
# Modbus Node error codes (bitové príznaky) ##################################################################################
##############################################################################################################################
MODBUS_ERROR_NONE           = 0     # Žiadna chyba
MODBUS_ERROR_PORT_OPEN      = 1     # bit0: nepodarilo sa otvoriť modbus port
MODBUS_ERROR_COMMUNICATION  = 2     # bit1: nepodarilo sa komunikovať so zariadením
MODBUS_ERROR_UNKNOWN        = 128   # bit7: neznáma chyba

##############################################################################################################################
# Output power curve configuration ###########################################################################################
##############################################################################################################################
CONF_ZERO_POWER_POINT    = "zero_power_point"
CONF_MAXIMUM_POWER_POINT = "maximum_power_point"
CONF_GAMMA               = "gamma"

DEFAULT_ZERO_POWER_POINT    = 0
DEFAULT_MAXIMUM_POWER_POINT = 100
DEFAULT_GAMMA               = 0

MIN_POWER_POINT = 0
MAX_POWER_POINT = 100
MIN_GAMMA       = -50
MAX_GAMMA       = 50

##############################################################################################################################
# Basic settings – Heating coil power ########################################################################################
##############################################################################################################################
CONF_HEATING_COIL_POWER = "heating_coil_power"
DEFAULT_HEATING_COIL_POWER = 5.0
MIN_HEATING_COIL_POWER = 0.0
MAX_HEATING_COIL_POWER = 20.0

CONF_HEATING_COIL_TOTAL_POWER = "heating_coil_total_power"
DEFAULT_HEATING_COIL_TOTAL_POWER = 10.0
MIN_HEATING_COIL_TOTAL_POWER = 0.0
MAX_HEATING_COIL_TOTAL_POWER = 50.0

##############################################################################################################################
# Solar radiation sensor control #############################################################################################
##############################################################################################################################
CONF_SOLAR_SENSOR_ENABLE              = "solar_sensor_enable"
CONF_SOLAR_SENSOR_ENTITY              = "solar_sensor_entity"
CONF_SOLAR_SENSOR_UNIT                = "solar_sensor_unit"
CONF_MAXIMUM_SOLAR_RADIATION_VALUE    = "maximum_solar_radiation_value"
CONF_SOLAR_SENSOR_ATTENUATION         = "solar_sensor_attenuation"
CONF_SOLAR_SENSOR_RAMP_UP_POWER_STEP  = "solar_sensor_ramp_up_power_step"
CONF_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE = "solar_sensor_ramp_up_power_cycle"
CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP  = "solar_sensor_ramp_down_power_step"
CONF_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE = "solar_sensor_ramp_down_power_cycle"

DEFAULT_SOLAR_SENSOR_ENABLE              = False
DEFAULT_SOLAR_SENSOR_ENTITY              = ""
DEFAULT_SOLAR_SENSOR_UNIT                = "kW"
DEFAULT_MAXIMUM_SOLAR_RADIATION_VALUE    = 1500
DEFAULT_SOLAR_SENSOR_ATTENUATION         = 100
DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_STEP  = 2
DEFAULT_SOLAR_SENSOR_RAMP_UP_POWER_CYCLE = 2
DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_STEP  = 2
DEFAULT_SOLAR_SENSOR_RAMP_DOWN_POWER_CYCLE = 2

##############################################################################################################################
# Photovoltaic current power control #########################################################################################
##############################################################################################################################
CONF_PV_POWER_ENABLE              = "pv_power_enable"
CONF_PV_POWER_ENTITY              = "pv_power_entity"
CONF_PV_POWER_UNIT                = "pv_power_unit"
CONF_PV_POWER_MAX_POWER           = "pv_power_max_power"
CONF_PV_POWER_RATIO         = "pv_power_ratio"
CONF_PV_POWER_RAMP_UP_POWER_STEP  = "pv_power_ramp_up_power_step"
CONF_PV_POWER_RAMP_UP_POWER_CYCLE = "pv_power_ramp_up_power_cycle"
CONF_PV_POWER_RAMP_DOWN_POWER_STEP  = "pv_power_ramp_down_power_step"
CONF_PV_POWER_RAMP_DOWN_POWER_CYCLE = "pv_power_ramp_down_power_cycle"

DEFAULT_PV_POWER_ENABLE              = False
DEFAULT_PV_POWER_ENTITY              = ""
DEFAULT_PV_POWER_UNIT                = "kW"
DEFAULT_PV_POWER_MAX_POWER           = 10.0
DEFAULT_PV_POWER_RATIO         = 100
DEFAULT_PV_POWER_RAMP_UP_POWER_STEP  = 2
DEFAULT_PV_POWER_RAMP_UP_POWER_CYCLE = 2
DEFAULT_PV_POWER_RAMP_DOWN_POWER_STEP  = 2
DEFAULT_PV_POWER_RAMP_DOWN_POWER_CYCLE = 2

##############################################################################################################################
# Sensor unit options (shared across all power control sections) #############################################################
##############################################################################################################################
SENSOR_UNIT_W  = "W"
SENSOR_UNIT_KW = "kW"
SENSOR_UNIT_OPTIONS = [SENSOR_UNIT_W, SENSOR_UNIT_KW]
DEFAULT_SENSOR_UNIT = SENSOR_UNIT_KW

##############################################################################################################################
# Power flowing to/from the grid control #####################################################################################
##############################################################################################################################
CONF_POWER_GRID_ENABLE              = "power_grid_enable"
CONF_POWER_GRID_ENTITY              = "power_grid_entity"
CONF_POWER_GRID_UNIT                = "power_grid_unit"
CONF_POWER_GRID_DEAD_ZONE_W        = "power_grid_dead_zone_w"
CONF_POWER_GRID_OFFSET_W           = "power_grid_offset_w"
CONF_POWER_GRID_OFFSET_EXPORT_LIMIT_W = "power_grid_offset_export_limit_w"
CONF_POWER_GRID_RAMP_UP_POWER_STEP  = "power_grid_ramp_up_power_step"
CONF_POWER_GRID_RAMP_UP_POWER_CYCLE = "power_grid_ramp_up_power_cycle"
CONF_POWER_GRID_RAMP_DOWN_POWER_STEP  = "power_grid_ramp_down_power_step"
CONF_POWER_GRID_RAMP_DOWN_POWER_CYCLE = "power_grid_ramp_down_power_cycle"

DEFAULT_POWER_GRID_ENABLE              = False
DEFAULT_POWER_GRID_ENTITY              = ""
DEFAULT_POWER_GRID_UNIT                = "kW"
DEFAULT_POWER_GRID_DEAD_ZONE_W        = 300
DEFAULT_POWER_GRID_OFFSET_W           = 100
DEFAULT_POWER_GRID_OFFSET_EXPORT_LIMIT_W = 9000
DEFAULT_POWER_GRID_RAMP_UP_POWER_STEP  = 2
DEFAULT_POWER_GRID_RAMP_UP_POWER_CYCLE = 2
DEFAULT_POWER_GRID_RAMP_DOWN_POWER_STEP  = 2
DEFAULT_POWER_GRID_RAMP_DOWN_POWER_CYCLE = 2

##############################################################################################################################
# Battery power consumption control ##########################################################################################
##############################################################################################################################
CONF_BATTERY_POWER_ENABLE              = "battery_power_enable"
CONF_BATTERY_POWER_ENTITY              = "battery_power_entity"
CONF_BATTERY_POWER_UNIT                = "battery_power_unit"
CONF_BATTERY_POWER_DEAD_ZONE_W        = "battery_power_dead_zone_w"
CONF_BATTERY_POWER_OFFSET_W           = "battery_power_offset_w"
CONF_BATTERY_POWER_RAMP_UP_POWER_STEP  = "battery_power_ramp_up_power_step"
CONF_BATTERY_POWER_RAMP_UP_POWER_CYCLE = "battery_power_ramp_up_power_cycle"
CONF_BATTERY_POWER_RAMP_DOWN_POWER_STEP  = "battery_power_ramp_down_power_step"
CONF_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE = "battery_power_ramp_down_power_cycle"

DEFAULT_BATTERY_POWER_ENABLE              = False
DEFAULT_BATTERY_POWER_ENTITY              = ""
DEFAULT_BATTERY_POWER_UNIT                = "kW"
DEFAULT_BATTERY_POWER_DEAD_ZONE_W        = 300
DEFAULT_BATTERY_POWER_OFFSET_W           = -1000
DEFAULT_BATTERY_POWER_RAMP_UP_POWER_STEP  = 2
DEFAULT_BATTERY_POWER_RAMP_UP_POWER_CYCLE = 2
DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_STEP  = 2
DEFAULT_BATTERY_POWER_RAMP_DOWN_POWER_CYCLE = 2

##############################################################################################################################
# Strategy 1 – synchronous, interval-driven power control               #######################################################
##############################################################################################################################

# Strategy 1 – part 1 (sensor entities, dead zones, offsets)
CONF_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY = "strategy_1_grid_export_status_entity"
CONF_STRATEGY_1_POWER_GRID_ENTITY         = "strategy_1_power_grid_entity"
CONF_STRATEGY_1_POWER_GRID_UNIT           = "strategy_1_power_grid_unit"
CONF_STRATEGY_1_POWER_GRID_DEAD_ZONE_W    = "strategy_1_power_grid_dead_zone_w"
CONF_STRATEGY_1_POWER_GRID_OFFSET_W       = "strategy_1_power_grid_offset_w"
CONF_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W = "strategy_1_power_grid_offset_export_limit_w"
CONF_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE = "strategy_1_entity_battery_charging_enablement_state"
CONF_STRATEGY_1_BATTERY_STATE_OF_CHARGE           = "strategy_1_entity_battery_state_of_charge"
CONF_STRATEGY_1_BATTERY_POWER_ENTITY      = "strategy_1_battery_power_entity"
CONF_STRATEGY_1_BATTERY_POWER_UNIT        = "strategy_1_battery_power_unit"
CONF_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W = "strategy_1_battery_power_dead_zone_w"
CONF_STRATEGY_1_BATTERY_POWER_OFFSET_W    = "strategy_1_battery_power_offset_w"
CONF_STRATEGY_1_SOLAR_SENSOR_ENTITY       = "strategy_1_solar_sensor_entity"
CONF_STRATEGY_1_SOLAR_SENSOR_UNIT         = "strategy_1_solar_sensor_unit"
CONF_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE = "strategy_1_maximum_solar_radiation_value"
CONF_STRATEGY_1_SOLAR_SENSOR_ATTENUATION  = "strategy_1_solar_sensor_attenuation"

DEFAULT_STRATEGY_1_GRID_EXPORT_STATUS_ENTITY = ""
DEFAULT_STRATEGY_1_POWER_GRID_ENTITY         = ""
DEFAULT_STRATEGY_1_POWER_GRID_UNIT           = "kW"
DEFAULT_STRATEGY_1_POWER_GRID_DEAD_ZONE_W    = 300
DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_W       = 100
DEFAULT_STRATEGY_1_POWER_GRID_OFFSET_EXPORT_LIMIT_W = 9000
DEFAULT_STRATEGY_1_BATTERY_CHARGING_ENABLEMENT_STATE = ""
DEFAULT_STRATEGY_1_BATTERY_STATE_OF_CHARGE           = ""
DEFAULT_STRATEGY_1_BATTERY_POWER_ENTITY      = ""
DEFAULT_STRATEGY_1_BATTERY_POWER_UNIT        = "W"
DEFAULT_STRATEGY_1_BATTERY_POWER_DEAD_ZONE_W = 300
DEFAULT_STRATEGY_1_BATTERY_POWER_OFFSET_W    = -1000
DEFAULT_STRATEGY_1_SOLAR_SENSOR_ENTITY       = ""
DEFAULT_STRATEGY_1_SOLAR_SENSOR_UNIT         = "W"
DEFAULT_STRATEGY_1_MAXIMUM_SOLAR_RADIATION_VALUE = 1500
DEFAULT_STRATEGY_1_SOLAR_SENSOR_ATTENUATION  = 100

# Strategy 1 – ramp parameters (only steps, NO cycles – synchronous with tracked_entities_interval)
CONF_STRATEGY_1_RAMP_UP_FAST_POWER_STEP    = "strategy_1_ramp_up_fast_power_step"
CONF_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP    = "strategy_1_ramp_up_slow_power_step"
CONF_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP  = "strategy_1_ramp_down_fast_power_step"
CONF_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP  = "strategy_1_ramp_down_slow_power_step"
CONF_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD = "strategy_1_power_grid_ramp_up_fast_threshold"
CONF_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD = "strategy_1_power_grid_ramp_down_fast_threshold"
CONF_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD = "strategy_1_battery_ramp_up_fast_threshold"
CONF_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD = "strategy_1_battery_ramp_down_fast_threshold"
CONF_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD = "strategy_1_solar_sensor_ramp_down_fast_threshold"

DEFAULT_STRATEGY_1_RAMP_UP_FAST_POWER_STEP    = 1
DEFAULT_STRATEGY_1_RAMP_UP_SLOW_POWER_STEP    = 1
DEFAULT_STRATEGY_1_RAMP_DOWN_FAST_POWER_STEP  = 25
DEFAULT_STRATEGY_1_RAMP_DOWN_SLOW_POWER_STEP  = 1
DEFAULT_STRATEGY_1_POWER_GRID_RAMP_UP_FAST_THRESHOLD = 4000
DEFAULT_STRATEGY_1_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD = 4000
DEFAULT_STRATEGY_1_BATTERY_RAMP_UP_FAST_THRESHOLD = 4000
DEFAULT_STRATEGY_1_BATTERY_RAMP_DOWN_FAST_THRESHOLD = 4000
DEFAULT_STRATEGY_1_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD = 300

##############################################################################################################################
# Strategy 2 – Grid + Solar (bez batérie) ####################################################################################
##############################################################################################################################
CONF_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY           = "strategy_2_grid_export_status_entity"
CONF_STRATEGY_2_POWER_GRID_ENTITY                   = "strategy_2_power_grid_entity"
CONF_STRATEGY_2_POWER_GRID_UNIT                     = "strategy_2_power_grid_unit"
CONF_STRATEGY_2_POWER_GRID_DEAD_ZONE_W              = "strategy_2_power_grid_dead_zone_w"
CONF_STRATEGY_2_POWER_GRID_OFFSET_W                 = "strategy_2_power_grid_offset_w"
CONF_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W    = "strategy_2_power_grid_offset_export_limit_w"
CONF_STRATEGY_2_SOLAR_SENSOR_ENTITY                 = "strategy_2_solar_sensor_entity"
CONF_STRATEGY_2_SOLAR_SENSOR_UNIT                   = "strategy_2_solar_sensor_unit"
CONF_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE       = "strategy_2_maximum_solar_radiation_value"
CONF_STRATEGY_2_SOLAR_SENSOR_ATTENUATION            = "strategy_2_solar_sensor_attenuation"

CONF_STRATEGY_2_RAMP_UP_FAST_POWER_STEP             = "strategy_2_ramp_up_fast_power_step"
CONF_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP             = "strategy_2_ramp_up_slow_power_step"
CONF_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP           = "strategy_2_ramp_down_fast_power_step"
CONF_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP           = "strategy_2_ramp_down_slow_power_step"
CONF_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD   = "strategy_2_power_grid_ramp_up_fast_threshold"
CONF_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD = "strategy_2_power_grid_ramp_down_fast_threshold"
CONF_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD = "strategy_2_solar_sensor_ramp_down_fast_threshold"

DEFAULT_STRATEGY_2_GRID_EXPORT_STATUS_ENTITY            = ""
DEFAULT_STRATEGY_2_POWER_GRID_ENTITY                    = ""
DEFAULT_STRATEGY_2_POWER_GRID_UNIT                      = "kW"
DEFAULT_STRATEGY_2_POWER_GRID_DEAD_ZONE_W               = 300
DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_W                  = 100
DEFAULT_STRATEGY_2_POWER_GRID_OFFSET_EXPORT_LIMIT_W     = 9000
DEFAULT_STRATEGY_2_SOLAR_SENSOR_ENTITY                  = ""
DEFAULT_STRATEGY_2_SOLAR_SENSOR_UNIT                    = "W"
DEFAULT_STRATEGY_2_MAXIMUM_SOLAR_RADIATION_VALUE        = 1500
DEFAULT_STRATEGY_2_SOLAR_SENSOR_ATTENUATION             = 100

DEFAULT_STRATEGY_2_RAMP_UP_FAST_POWER_STEP              = 1
DEFAULT_STRATEGY_2_RAMP_UP_SLOW_POWER_STEP              = 1
DEFAULT_STRATEGY_2_RAMP_DOWN_FAST_POWER_STEP            = 25
DEFAULT_STRATEGY_2_RAMP_DOWN_SLOW_POWER_STEP            = 1
DEFAULT_STRATEGY_2_POWER_GRID_RAMP_UP_FAST_THRESHOLD    = 4000
DEFAULT_STRATEGY_2_POWER_GRID_RAMP_DOWN_FAST_THRESHOLD  = 4000
DEFAULT_STRATEGY_2_SOLAR_SENSOR_RAMP_DOWN_FAST_THRESHOLD = 300


# Master heating coil
CONF_MASTER_HEATING_COIL_ID = "master_heating_coil_id"
DEFAULT_MASTER_HEATING_COIL_ID = "0"

# Debounce delay (configurable per heating coil)
CONF_TRACKED_ENTITIES_INTERVAL = "tracked_entities_interval"
DEFAULT_TRACKED_ENTITIES_INTERVAL = 5
MIN_TRACKED_ENTITIES_INTERVAL = 1
MAX_TRACKED_ENTITIES_INTERVAL = 30

##############################################################################################################################
# Thermal protection (safety fuse) ###########################################################################################
##############################################################################################################################
CONF_THERMAL_PROTECTION_SENSOR_ENTITY  = "thermal_protection_sensor_entity"
CONF_THERMAL_PROTECTION_MAX_TEMP       = "thermal_protection_max_temp"

THERMAL_PROTECTION_NO_SENSOR           = "---"   # Sentinel value – no sensor selected
THERMAL_PROTECTION_HYSTERESIS          = 2.0     # Fixed hysteresis [°C]

DEFAULT_THERMAL_PROTECTION_SENSOR_ENTITY = THERMAL_PROTECTION_NO_SENSOR
DEFAULT_THERMAL_PROTECTION_MAX_TEMP      = 75

MIN_THERMAL_PROTECTION_MAX_TEMP = 30
MAX_THERMAL_PROTECTION_MAX_TEMP = 90

# Binary sensor entity name for thermal protection state
ENTITY_THERMAL_PROTECTION_ACTIVE = "thermal_protection_active"

##############################################################################################################################
# Default values of static parameters ########################################################################################
##############################################################################################################################
