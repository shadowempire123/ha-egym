from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    EgymApi,
    EgymApiError,
    EgymAuthError,
    EgymBrandError,
    async_egym_session,
    normalize_brand,
)
from .const import (
    CONF_BODY_VALUES,
    CONF_BRAND,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_BODY_VALUES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

# Without this the password is typed into a plain text box and stands there in
# clear on screen, in front of whoever is in the room and in any screenshot
# that ends up in an issue.
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _async_validate(hass, brand: str, username: str, password: str) -> None:
    """Sign in once, so bad credentials surface here instead of at setup."""
    if not username or not password:
        raise EgymAuthError("Username and password are required")
    api = EgymApi(async_egym_session(hass), brand, username, password)
    await api.async_login()


class EgymConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                brand = normalize_brand(user_input[CONF_BRAND])
                username = user_input[CONF_USERNAME].strip()
                await _async_validate(self.hass, brand, username, user_input[CONF_PASSWORD])
            except EgymBrandError:
                errors["base"] = "invalid_brand"
            except EgymAuthError:
                errors["base"] = "invalid_auth"
            except EgymApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{brand}::{username.casefold()}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=username,
                    data={
                        CONF_BRAND: brand,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BRAND): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """Entry point when eGym stops accepting the stored password.

        Without this the integration keeps presenting the same refused password
        until somebody deletes and re-adds it -- which is both a nuisance and,
        against a service that rate-limits failed logins, a good way to get the
        address blocked.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None):
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_validate(
                    self.hass,
                    entry.data[CONF_BRAND],
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except EgymAuthError:
                errors["base"] = "invalid_auth"
            except EgymApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EgymOptionsFlowHandler()


class EgymOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(
                data={
                    # Clamped again in __init__.py; the selector's own minimum
                    # is only a hint to the browser.
                    CONF_SCAN_INTERVAL: max(
                        int(user_input[CONF_SCAN_INTERVAL]), MIN_SCAN_INTERVAL
                    ),
                    CONF_BODY_VALUES: user_input[CONF_BODY_VALUES],
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=60,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_BODY_VALUES,
                        default=options.get(CONF_BODY_VALUES, DEFAULT_BODY_VALUES),
                    ): BooleanSelector(),
                }
            ),
        )
