"""Climate proxy that writes Gira base setpoints corrected for heat/cool mode."""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID, UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from . import (
    CONF_BASE_SETPOINT_ADDRESS,
    CONF_CLIMATES,
    CONF_COOL_STATE,
    CONF_COOLING_SETPOINT_OFFSET,
    CONF_CURRENT_TEMPERATURE_ENTITY,
    CONF_DEAD_BAND,
    CONF_HEAT_COOL_ENTITY,
    CONF_HEAT_STATE,
    CONF_SOURCE_CLIMATE,
    CONF_TARGET_TEMPERATURE_ENTITY,
    DOMAIN,
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Gira setpoint climate entities."""
    climates = hass.data.get(DOMAIN, {}).get(CONF_CLIMATES, [])
    async_add_entities(GiraSetpointClimate(hass, climate_config) for climate_config in climates)


class GiraSetpointClimate(ClimateEntity):
    """Proxy a KNX climate and compensate writes to the Gira base setpoint."""

    _attr_has_entity_name = False
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the proxy climate."""
        self.hass = hass
        self._attr_name = config[CONF_NAME]
        self._attr_unique_id = config.get(CONF_UNIQUE_ID)
        self._source_climate = config.get(CONF_SOURCE_CLIMATE)
        self._current_temperature_entity = config.get(CONF_CURRENT_TEMPERATURE_ENTITY)
        self._target_temperature_entity = config.get(CONF_TARGET_TEMPERATURE_ENTITY)
        self._heat_cool_entity = config[CONF_HEAT_COOL_ENTITY]
        self._base_setpoint_address = config[CONF_BASE_SETPOINT_ADDRESS]
        self._cooling_setpoint_offset = config.get(
            CONF_COOLING_SETPOINT_OFFSET, config[CONF_DEAD_BAND]
        )
        self._heat_state = config[CONF_HEAT_STATE].lower()
        self._cool_state = config[CONF_COOL_STATE].lower()

    async def async_added_to_hass(self) -> None:
        """Register state listeners."""
        await super().async_added_to_hass()
        watched_entities = [
            entity
            for entity in (
                self._source_climate,
                self._current_temperature_entity,
                self._target_temperature_entity,
                self._heat_cool_entity,
            )
            if entity is not None
        ]
        remove_listener = async_track_state_change_event(
            self.hass,
            watched_entities,
            self._async_state_changed,
        )
        self.async_on_remove(remove_listener)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Update Home Assistant when the source entities change."""
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        """Return the current room temperature."""
        if self._current_temperature_entity is not None:
            return _float_state(self.hass.states.get(self._current_temperature_entity))
        if self._source_climate is None:
            return None
        return _float_attr(self.hass.states.get(self._source_climate), "current_temperature")

    @property
    def target_temperature(self) -> float | None:
        """Return the active Gira target temperature."""
        if self._target_temperature_entity is not None:
            return _float_state(self.hass.states.get(self._target_temperature_entity))
        if self._source_climate is None:
            return None
        source_target = _float_attr(self.hass.states.get(self._source_climate), "temperature")
        if source_target is not None:
            return source_target
        return None

    @property
    def min_temp(self) -> float:
        """Return the minimum setpoint."""
        if self._source_climate is None:
            return 7.0
        return _float_attr(self.hass.states.get(self._source_climate), "min_temp") or 7.0

    @property
    def max_temp(self) -> float:
        """Return the maximum setpoint."""
        if self._source_climate is None:
            return 32.0
        return _float_attr(self.hass.states.get(self._source_climate), "max_temp") or 32.0

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return supported HVAC modes."""
        return [HVACMode.HEAT, HVACMode.COOL]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the central heat/cool mode."""
        return HVACMode.COOL if self._is_cooling() else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the source HVAC action when available."""
        if self._source_climate is None:
            return None
        action = self.hass.states.get(self._source_climate)
        if action is None:
            return None
        source_action = action.attributes.get("hvac_action")
        if source_action in {item.value for item in HVACAction}:
            return HVACAction(source_action)
        return None

    async def async_set_temperature(self, **kwargs) -> None:
        """Set active target temperature by writing the corrected Gira base setpoint."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        requested = float(temperature)
        base_setpoint = (
            requested - self._cooling_setpoint_offset if self._is_cooling() else requested
        )

        await self.hass.services.async_call(
            "knx",
            "send",
            {
                "address": self._base_setpoint_address,
                "type": "temperature",
                "payload": round(base_setpoint, 1),
            },
            blocking=True,
        )
        self.async_write_ha_state()

    def _is_cooling(self) -> bool:
        """Return true when the central heat/cool feedback indicates cooling."""
        state = self.hass.states.get(self._heat_cool_entity)
        if state is None:
            return False
        return state.state.lower() == self._cool_state


def _float_attr(state, attribute: str) -> float | None:
    """Read a numeric state attribute."""
    if state is None:
        return None
    value = state.attributes.get(attribute)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_state(state) -> float | None:
    """Read a numeric entity state."""
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None
