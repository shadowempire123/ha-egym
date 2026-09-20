from homeassistant.const import Platform

DOMAIN = "egym"
# Keep in sync with the version in manifest.json: it goes into the User-Agent,
# which is the only thing identifying this client to the Netpulse host.
VERSION = "0.3.0"

CONF_BRAND = "brand"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_BODY_VALUES = "body_values"

# eGym/Netpulse rate-limits aggressive polling, and a burst of logins can earn
# the whole household IP a temporary block. Fifteen minutes is already far more
# often than anybody trains. The floor is not a matter of taste: without it the
# options flow would be a way to talk the integration into hammering the login
# endpoint from the user's own address.
DEFAULT_SCAN_INTERVAL = 900
MIN_SCAN_INTERVAL = 300
MAX_SCAN_INTERVAL = 21600

# Bio-age, body fat, BMI, blood pressure and resting heart rate are health
# data. They are stored like any other sensor, which puts them in the recorder
# database and in every backup taken of it -- including backups that go to
# Home Assistant Cloud or a NAS. Hence the switch.
DEFAULT_BODY_VALUES = True

PLATFORMS = [Platform.SENSOR]
