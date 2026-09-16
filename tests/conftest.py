"""Run the integration's modules without a Home Assistant installation.

The modules under test need only a handful of names from ``homeassistant`` and
``aiohttp``, so both are stubbed here. That keeps the suite runnable with
nothing but pytest: no Home Assistant checkout, no network, no event loop
plugin.

The package is assembled by hand rather than imported normally, because
``custom_components/egym/__init__.py`` pulls in the full config-entry
machinery. Giving a synthetic ``egym`` module a ``__path__`` lets the submodules
be imported on their own, with their relative imports intact; ``load_entrypoint``
below loads the real ``__init__.py`` under its own name for the one test that
needs it.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parent.parent / "custom_components" / "egym"


def _stub_homeassistant() -> None:
    homeassistant = types.ModuleType("homeassistant")

    const = types.ModuleType("homeassistant.const")

    class Platform:
        SENSOR = "sensor"

    class UnitOfLength:
        KILOMETERS = "km"

    class UnitOfMass:
        KILOGRAMS = "kg"

    class UnitOfTime:
        DAYS = "d"
        HOURS = "h"
        MINUTES = "min"

    const.Platform = Platform
    const.PERCENTAGE = "%"
    const.UnitOfLength = UnitOfLength
    const.UnitOfMass = UnitOfMass
    const.UnitOfTime = UnitOfTime

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda func: func

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})

    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exceptions.ConfigEntryError = type("ConfigEntryError", (Exception,), {})
    exceptions.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})

    # A faithful stand-in for Home Assistant's redaction helper: it replaces the
    # values of matching keys and recurses. Testing the diagnostics module
    # against a fake that did less would prove nothing.
    components = types.ModuleType("homeassistant.components")
    diagnostics = types.ModuleType("homeassistant.components.diagnostics")
    redacted = "**REDACTED**"

    def async_redact_data(data, to_redact):
        if isinstance(data, dict):
            return {
                key: (redacted if key in to_redact else async_redact_data(value, to_redact))
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [async_redact_data(item, to_redact) for item in data]
        return data

    diagnostics.async_redact_data = async_redact_data
    diagnostics.REDACTED = redacted

    sensor = types.ModuleType("homeassistant.components.sensor")

    class SensorEntityDescription:
        def __init__(self, key, **kwargs):
            self.key = key
            self.name = kwargs.get("name")
            self.icon = kwargs.get("icon")
            self.device_class = kwargs.get("device_class")
            self.native_unit_of_measurement = kwargs.get("native_unit_of_measurement")
            self.state_class = kwargs.get("state_class")

    class SensorDeviceClass:
        DISTANCE = "distance"
        DURATION = "duration"
        TIMESTAMP = "timestamp"
        WEIGHT = "weight"

    class SensorStateClass:
        MEASUREMENT = "measurement"

    sensor.SensorEntity = type("SensorEntity", (), {})
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass

    helpers = types.ModuleType("homeassistant.helpers")

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = dict

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_create_clientsession = lambda hass, **kwargs: object()
    aiohttp_client.async_get_clientsession = lambda hass: object()

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})

    class DataUpdateCoordinator:
        # The real class is generic; the integration subclasses it as
        # DataUpdateCoordinator[dict[str, Any]].
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, hass, *, logger=None, name=None, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
            self.last_update_success = True

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    util = types.ModuleType("homeassistant.util")
    util_dt = types.ModuleType("homeassistant.util.dt")
    # Deliberately UTC rather than the machine's zone: "which calendar day is
    # this" is timezone-dependent, and a suite whose answers move with the
    # runner's TZ is worse than useless.
    util_dt.as_local = lambda moment: moment.astimezone(UTC)
    util.dt = util_dt
    # ``import homeassistant.util.dt as dt_util`` resolves through sys.modules
    # on its own, but the attribute chain has to exist for anything that
    # reaches for it the other way round.
    homeassistant.util = util
    homeassistant.const = const

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.config_entries": config_entries,
            "homeassistant.exceptions": exceptions,
            "homeassistant.components": components,
            "homeassistant.components.diagnostics": diagnostics,
            "homeassistant.components.sensor": sensor,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.device_registry": device_registry,
            "homeassistant.helpers.entity_platform": entity_platform,
            "homeassistant.helpers.aiohttp_client": aiohttp_client,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.util": util,
            "homeassistant.util.dt": util_dt,
        }
    )


def _stub_aiohttp() -> None:
    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    aiohttp.ClientError = ClientError
    aiohttp.ClientTimeout = ClientTimeout
    aiohttp.ClientSession = type("ClientSession", (), {})
    aiohttp.ClientResponse = type("ClientResponse", (), {})
    aiohttp.DummyCookieJar = type("DummyCookieJar", (), {})

    sys.modules["aiohttp"] = aiohttp


def _install_package() -> None:
    package = types.ModuleType("egym")
    package.__path__ = [str(INTEGRATION)]
    sys.modules["egym"] = package


def load_entrypoint():
    """Import the real ``__init__.py`` under a name of its own.

    ``egym`` itself is the synthetic package above, so the file that sets the
    config entry up cannot be reached by importing it normally. The dotted name
    keeps ``__package__`` at ``egym``, which is what its relative imports need.
    """
    spec = importlib.util.spec_from_file_location("egym._entrypoint", INTEGRATION / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_stub_homeassistant()
_stub_aiohttp()
_install_package()
