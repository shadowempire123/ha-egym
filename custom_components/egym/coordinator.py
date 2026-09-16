from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EgymApi, EgymApiError, EgymAuthError, EgymLoginRejected
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EgymCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: EgymApi,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.api = api
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """One update, and at most one login attempt inside it.

        The order of the handlers is the whole point. An expired session is
        ordinary and gets one silent login. A *refused* login means the stored
        password no longer works, and retrying it on the next cycle -- and the
        one after that, forever -- is how an account earns a temporary block on
        the household's IP address. Netpulse rate-limits repeated failed
        logins, so that one is turned into a re-authentication prompt, which
        also stops the polling until somebody answers it.
        """
        try:
            return await self.api.async_fetch_data()
        except EgymLoginRejected as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except EgymAuthError:
            try:
                await self.api.async_login()
                return await self.api.async_fetch_data()
            except EgymLoginRejected as error:
                raise ConfigEntryAuthFailed(str(error)) from error
            except EgymApiError as error:
                # Includes a second EgymAuthError: the login was accepted and
                # the session still bounced. Retrying that in a loop would get
                # nowhere, so it waits for the next scheduled update.
                raise UpdateFailed(str(error)) from error
        except EgymApiError as error:
            raise UpdateFailed(str(error)) from error
