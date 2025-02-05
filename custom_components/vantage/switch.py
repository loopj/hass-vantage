"""Support for Vantage switch entities."""

import functools
from typing import Any

from aiovantage.objects import GMem, Load

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entry import VantageConfigEntry
from .entity import VantageEntity, VantageVariableEntity, async_register_vantage_objects


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VantageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vantage switch entities from config entry."""
    vantage = entry.runtime_data.client
    register_items = functools.partial(
        async_register_vantage_objects, entry, async_add_entities
    )

    # Register Load switch entities
    def load_filter(obj: Load) -> bool:
        return obj.is_relay or obj.is_motor

    register_items(vantage.loads, VantageLoadSwitch, load_filter)

    # Register GMem switch entities
    def gmem_filter(obj: GMem) -> bool:
        return obj.is_bool

    register_items(vantage.gmem, VantageVariableSwitch, gmem_filter)


class VantageLoadSwitch(VantageEntity[Load], SwitchEntity):
    """Vantage relay load switch entity."""

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self.obj.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.async_request_call(self.obj.turn_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.async_request_call(self.obj.turn_off())


class VantageVariableSwitch(VantageVariableEntity, SwitchEntity):
    """Vantage boolean variable switch entity."""

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        if isinstance(self.obj.value, int):
            return bool(self.obj.value)

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.async_request_call(self.obj.set_value(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.async_request_call(self.obj.set_value(False))
