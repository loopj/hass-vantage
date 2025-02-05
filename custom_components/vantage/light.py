"""Support for Vantage light entities."""

import functools
from typing import Any, TypeVar, cast

from aiovantage.objects import Load, LoadGroup
from aiovantage.controllers.rgb_loads import RGBLoadTypes

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .config_entry import VantageConfigEntry
from .const import LOGGER
from .entity import VantageEntity, async_register_vantage_objects

# TypeVar for RGB/RGBW color tuples
ColorT = TypeVar("ColorT", tuple[int, int, int], tuple[int, int, int, int])

# Vantage level range for converting between HA brightness and Vantage levels
LEVEL_RANGE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VantageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vantage light entities from config entry."""
    vantage = entry.runtime_data.client
    register_items = functools.partial(
        async_register_vantage_objects, entry, async_add_entities
    )

    # Set up all light-type objects
    def load_filter(obj: Load) -> bool:
        return obj.is_light

    register_items(vantage.loads, VantageLight, load_filter)
    register_items(vantage.rgb_loads, VantageRGBLight)
    register_items(vantage.load_groups, VantageLightGroup)


class VantageLight(VantageEntity[Load], LightEntity):
    """Vantage load light entity."""

    def __post_init__(self) -> None:
        """Initialize the light."""
        # Look up the power profile for this load to determine if it is dimmable
        power_profile = self.client.power_profiles.get(self.obj.power_profile)

        # Set up the light based on the power profile
        self._attr_supported_color_modes: set[str] = set()

        if power_profile and power_profile.is_dimmable:
            self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_features |= LightEntityFeature.TRANSITION
        else:
            self._attr_supported_color_modes.add(ColorMode.ONOFF)
            self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self.obj.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if self.obj.level is None:
            return None

        return value_to_brightness(LEVEL_RANGE, float(self.obj.level))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        transition = kwargs.get(ATTR_TRANSITION, 0)
        level = brightness_to_value(LEVEL_RANGE, kwargs.get(ATTR_BRIGHTNESS, 255))

        await self.async_request_call(self.obj.turn_on(transition, level))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        transition = kwargs.get(ATTR_TRANSITION, 0)

        await self.async_request_call(self.obj.turn_off(transition))


class VantageRGBLight(VantageEntity[RGBLoadTypes], LightEntity):
    """Vantage RGB load light entity."""

    def __post_init__(self) -> None:
        """Initialize the light."""
        # Set up the light based on the color type
        self._attr_supported_color_modes: set[str] = set()

        match self.obj.color_type:
            case self.obj.ColorType.HSL:
                self._attr_supported_color_modes.add(ColorMode.HS)
                self._attr_color_mode = ColorMode.HS
                self._attr_supported_features |= LightEntityFeature.TRANSITION
            case self.obj.ColorType.RGB:
                self._attr_supported_color_modes.add(ColorMode.RGB)
                self._attr_color_mode = ColorMode.RGB
                self._attr_supported_features |= LightEntityFeature.TRANSITION
            case self.obj.ColorType.RGBW:
                self._attr_supported_color_modes.add(ColorMode.RGBW)
                self._attr_color_mode = ColorMode.RGBW
            case self.obj.ColorType.CCT:
                self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)
                self._attr_color_mode = ColorMode.COLOR_TEMP
                self._attr_min_color_temp_kelvin = self.obj.min_temp
                self._attr_max_color_temp_kelvin = self.obj.max_temp
                self._attr_supported_features |= LightEntityFeature.TRANSITION
            case _:
                # Treat all other color types as dimmable non-color lights
                self._attr_supported_color_modes.add(ColorMode.BRIGHTNESS)
                self._attr_color_mode = ColorMode.BRIGHTNESS
                self._attr_supported_features |= LightEntityFeature.TRANSITION

                LOGGER.warning(
                    "Unsupported color type %s for RGB light %s",
                    self.obj.color_type,
                    self.obj.name,
                )

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self.obj.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if self.obj.level is None:
            return None

        return value_to_brightness(LEVEL_RANGE, float(self.obj.level))

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        if self.obj.hsl is None:
            return None

        return self.obj.hsl[:2]

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the rgb color value [int, int, int]."""
        return self.obj.rgb

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the rgbw color value [int, int, int, int]."""
        return self.obj.rgbw

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the CT color value in Kelvin."""
        return self.obj.color_temp

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_RGBW_COLOR in kwargs:
            # Turn on the light with the provided RGBW color
            rgbw: tuple[int, int, int, int] = kwargs[ATTR_RGBW_COLOR]

            # Scale the brightness of the color if provided
            if brightness := kwargs.get(ATTR_BRIGHTNESS) is not None:
                rgbw = scale_color_brightness(rgbw, brightness)

            await self.async_request_call(self.obj.set_rgbw(*rgbw))

        elif ATTR_RGB_COLOR in kwargs:
            # Turn on the light with the provided RGB color
            rgb: tuple[int, int, int] = kwargs[ATTR_RGB_COLOR]
            transition = kwargs.get(ATTR_TRANSITION, 0)

            # Scale the brightness of the color if provided
            if brightness := kwargs.get(ATTR_BRIGHTNESS) is not None:
                rgb = scale_color_brightness(rgb, brightness)

            await self.async_request_call(self.obj.dissolve_rgb(*rgb, transition))

        elif ATTR_HS_COLOR in kwargs:
            # Turn on the light with the provided HS color and brightness, default to
            # 100% brightness if not provided
            hue, saturation = kwargs[ATTR_HS_COLOR]
            level = brightness_to_value(LEVEL_RANGE, kwargs.get(ATTR_BRIGHTNESS, 255))
            transition = kwargs.get(ATTR_TRANSITION, 0)

            await self.async_request_call(
                self.obj.dissolve_hsl(hue, saturation, level, transition)
            )

        else:
            # Set the color temperature, if provided
            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                color_temp: int = kwargs[ATTR_COLOR_TEMP_KELVIN]

                await self.async_request_call(self.obj.set_color_temp(color_temp))

            # Turn on the light with the provided brightness, default to 100%
            transition = kwargs.get(ATTR_TRANSITION, 0)
            level = brightness_to_value(LEVEL_RANGE, kwargs.get(ATTR_BRIGHTNESS, 255))

            await self.async_request_call(self.obj.turn_on(transition, level))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        transition = kwargs.get(ATTR_TRANSITION, 0)

        await self.async_request_call(self.obj.turn_off(transition))


class VantageLightGroup(VantageEntity[LoadGroup], LightEntity):
    """Vantage light group entity."""

    _attr_icon = "mdi:lightbulb-group"

    def __post_init__(self) -> None:
        """Initialize a Vantage light group."""
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_features |= LightEntityFeature.TRANSITION

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device specific attributes."""
        device_info = super().device_info

        if device_info:
            device_info["entry_type"] = dr.DeviceEntryType.SERVICE

        return device_info

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self.obj.is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if self.obj.level is None:
            return None

        return value_to_brightness(LEVEL_RANGE, float(self.obj.level))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        transition = kwargs.get(ATTR_TRANSITION, 0)
        level = brightness_to_value(LEVEL_RANGE, kwargs.get(ATTR_BRIGHTNESS, 255))

        await self.async_request_call(self.obj.turn_on(transition, level))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        transition = kwargs.get(ATTR_TRANSITION, 0)

        await self.async_request_call(self.obj.turn_off(transition))


def scale_color_brightness(color: ColorT, brightness: int | None) -> ColorT:
    """Scale the brightness of an RGB/RGBW color tuple."""
    if brightness is None:
        return color

    return cast(ColorT, tuple(int(round(c * brightness / 255)) for c in color))
