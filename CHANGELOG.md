# Changelog

## 0.3.0 — 2026-09-20

### Added
- **`sensor.egym_bioage_flexibility`.** The fourth component of the bio-age.
  `flexibilityDetails` is `null` until the studio's mobility test has been done
  once, which is why the sensor did not exist so far — after the test the
  section arrives in the same shape as cardio, metabolic and muscle, and the
  sensor fills itself in. Counts as a body value, so the `body_values` option
  switches it off with the others.
- **`change` and `measured_at` attributes on the total and on each component
  age.** `change` is eGym's own `amountDiff`, the difference to the previous
  measurement in whole years (negative means younger; absent on a first
  measurement); `measured_at` is the visit that set the value. That is what
  the eGym kiosk draws as its trend arrow, and it now sits next to the number
  on a dashboard instead of needing the recorder history to be worked out.

## 0.2.0 — 2026-09-16

The first release as a standalone repository, and the first one hardened for
other people's installations rather than the author's. Everything below is new
relative to the version that lived inside a private Home Assistant config repo.

### Security
- **The brand is validated against an allow list instead of a deny list.** The
  brand is interpolated into `https://<brand>.netpulse.com`, and the login
  posts the member's username and password to that host — so it decides where
  the password goes. The previous check rejected `.` and `/` and let `@`, `:`,
  `#`, `?`, a backslash, whitespace and every non-ASCII look-alike straight
  through, which is enough to move the host: `user@evil.com` and
  `attacker.example/x` both aim the credentials somewhere else. It now has to
  be a plain DNS label — lower-case letters, digits, hyphens — and the check
  runs when the config entry is loaded as well as in the config flow, so an
  entry written by an older version or edited by hand in `.storage` cannot get
  around it.
- **The password field is a password field.** It was a plain text box, so the
  password stood in clear on screen during setup, in front of whoever was in
  the room and in any screenshot that ended up in an issue.
- **A refused login no longer repeats forever.** The coordinator retried the
  stored password on every cycle, which against a service that rate-limits
  failed logins is how the household's IP address gets blocked — affecting the
  phone and the eGym app too, not just Home Assistant. A refused *login* is now
  told apart from an expired *session*: the first raises a re-authentication
  prompt and stops the polling, the second gets one silent login, as before.
- **The polling interval has an enforced floor of 300 seconds**, applied when
  the entry is loaded rather than only in the options form, so options written
  by an older version or edited by hand cannot point the poller below the rate
  limit.
- **The member id is stripped out of error messages.** It sits in the path of
  every data request, and those messages reach the log and, during setup, the
  screen.
- **Requests have a timeout** (30 s). A host that accepts the connection and
  then goes quiet used to hold the update open indefinitely, and the
  integration stopped reporting without ever logging a failure.
- **Network errors arrive as this integration's own error type** rather than as
  an unexpected exception in the log.
- **A failed login clears the previous session.** The old cookie and member id
  stayed behind, so the next request went out looking like it still had a
  working session.

### Added
- **Diagnostics** — Settings → Devices & services → eGym → the three dots →
  Download diagnostics. What this integration holds is health data: bio-age,
  body fat, BMI, VO2max, resting heart rate, blood pressure, and a dated record
  of when somebody trained. A diagnostics file gets pasted into public issues,
  and unlike a password that cannot be taken back afterwards. So the report
  inverts the usual rule: nothing is included unless it is on an allow list of
  counts, and every other field is reduced to its *type* —
  `"bioage_total": "int"` says the parser found a reading without saying what
  anybody's bio-age is. The raw API responses are reduced to their shape, which
  keeps the field names that identify a renamed key while dropping every value.
  A value-based scrub runs over the finished report as a second line of
  defence. Reducing a payload to its shape keeps dictionary *keys*, which is
  right for an API's field names and wrong for the per-exercise breakdown,
  whose keys are the member's own training profile — that one is reduced to a
  count. The connected-app breakdown stays, because its keys name a service
  rather than a person and the triple counting they cause is what most reports
  are about. The brand is deliberately kept too: it names the gym, not the
  member, and a report without it usually cannot be answered.
- **Re-authentication.** When eGym stops accepting the stored password, Home
  Assistant asks for a new one. Until now the only way out was deleting the
  integration and setting it up again.
- **An options flow that has something in it.** The "Configure" button used to
  open a handler that created an empty entry and showed no form at all, which
  from the outside looks like a broken integration. It now offers the polling
  interval and the body-values switch.
- **The polling interval is configurable** (5 minutes to 6 hours, 15 minutes by
  default). It had been hard wired.
- **Body and bio-age sensors can be switched off.** They are health data, and a
  sensor's history lives in the recorder database and therefore in every backup
  taken of it. Switched off, the sensors are not created *and the bio-age
  service is not called at all* — fetching the data and then declining to build
  sensors from it would leave it sitting in memory and in anything that
  inspects the coordinator, which is not what the switch says.
- **Brand images**, served by Home Assistant's own brands proxy from
  `custom_components/egym/brand/`. A plain dumbbell drawn by
  `scripts/make_brand_images.py`, not eGym's logo.
- **A test suite that runs without Home Assistant installed**, and a CI
  workflow running hassfest, HACS validation, ruff and pytest — plus a weekly
  scheduled run, because Home Assistant releases monthly and hassfest tracks
  the current version.
- **A release workflow** that publishes the changelog section for a tag as the
  release notes, and refuses a tag that disagrees with `manifest.json` —
  because HACS matches releases against the manifest, so a mismatched release
  would never be offered as an update.
- **`SECURITY.md`**, and an issue template that asks for the brand and the
  diagnostics rather than a screenshot of the sensors.
- **`docs/API.md`** — what the undocumented API actually does, which endpoints
  were probed and what they answered, and what is still unsolved.

### Changed
- The `User-Agent` now carries the integration's real version instead of a
  hard-coded `0.1`.
