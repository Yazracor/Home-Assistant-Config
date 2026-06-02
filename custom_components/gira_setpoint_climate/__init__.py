"""Gira KNX setpoint climate proxy."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
from homeassistant.helpers import config_validation as cv, discovery

DOMAIN = "gira_setpoint_climate"
CONF_CLIMATES = "climates"
CONF_SOURCE_CLIMATE = "source_climate"
CONF_HEAT_COOL_ENTITY = "heat_cool_entity"
CONF_BASE_SETPOINT_ADDRESS = "base_setpoint_address"
CONF_DEAD_BAND = "dead_band"
CONF_HEAT_STATE = "heat_state"
CONF_COOL_STATE = "cool_state"

DEFAULT_HEAT_STATE = "on"
DEFAULT_COOL_STATE = "off"

CLIMATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_SOURCE_CLIMATE): cv.entity_id,
        vol.Required(CONF_BASE_SETPOINT_ADDRESS): cv.string,
        vol.Required(CONF_HEAT_COOL_ENTITY): cv.entity_id,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_DEAD_BAND, default=2.0): vol.Coerce(float),
        vol.Optional(CONF_HEAT_STATE, default=DEFAULT_HEAT_STATE): cv.string,
        vol.Optional(CONF_COOL_STATE, default=DEFAULT_COOL_STATE): cv.string,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_CLIMATES): vol.All(cv.ensure_list, [CLIMATE_SCHEMA])})},
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up YAML-configured Gira setpoint climates."""
    hass.data[DOMAIN] = config.get(DOMAIN, {})
    hass.async_create_task(discovery.async_load_platform(hass, "climate", DOMAIN, {}, config))
    return True
