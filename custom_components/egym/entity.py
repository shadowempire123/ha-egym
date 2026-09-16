from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def device_info_for(username: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, username.casefold())},
        # Deliberately not the username: the device name prefixes every
        # entity_id, and docs/EGYM-INTEGRATION.md documents them as
        # sensor.egym_* — putting an email address in there would also leak it
        # into dashboards.
        name="eGym",
        manufacturer="eGym",
        model="Member account",
    )
