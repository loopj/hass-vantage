from aiovantage import Vantage
from aiovantage.config_client.objects import DryContact
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .entity import VantageEntity


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    # Get the client from the hass data store
    vantage: Vantage = hass.data[DOMAIN][config_entry.entry_id]

    # Dry contacts are binary sensors
    async for dry_contact in vantage.dry_contacts:
        entity = VantageDryContact(vantage, dry_contact)
        await entity.fetch_relations()
        async_add_entities([entity])


class VantageDryContact(VantageEntity[DryContact], BinarySensorEntity):
    """Representation of a Vantage dry contact."""

    def __init__(self, client: Vantage, obj: DryContact):
        """Initialize a Vantage dry contact."""
        super().__init__(client, client.dry_contacts, obj)

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return self.obj.triggered