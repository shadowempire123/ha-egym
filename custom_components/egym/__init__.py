from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import EgymApi, EgymBrandError, async_egym_session
from .const import (
    CONF_BODY_VALUES,
    CONF_BRAND,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_BODY_VALUES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import EgymCoordinator


def _scan_interval(entry: ConfigEntry) -> int:
    """The polling interval, with the floor applied on the way out.

    Clamped here rather than trusted from the entry: options written by an
    older version, or edited by hand in .storage, must not be able to point the
    poller below the rate limit and get the household's address blocked.
    """
    configured = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        return max(int(configured), MIN_SCAN_INTERVAL)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_egym_session(hass)
    try:
        api = EgymApi(
            session,
            entry.data[CONF_BRAND],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            body_values=entry.options.get(CONF_BODY_VALUES, DEFAULT_BODY_VALUES),
        )
    except EgymBrandError as error:
        # Not ConfigEntryNotReady: a stored brand that is not a DNS label will
        # not become one by waiting, and retrying would only keep an entry
        # around that points the login somewhere it should not go.
        raise ConfigEntryError(str(error)) from error

    coordinator = EgymCoordinator(hass, api, _scan_interval(entry))
    try:
        await coordinator.async_config_entry_first_refresh()
    except UpdateFailed as error:
        raise ConfigEntryNotReady(str(error)) from error

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
