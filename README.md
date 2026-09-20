# eGym for Home Assistant

[![hacs][hacs-badge]][hacs-url]

Home Assistant integration for **eGym / Netpulse** member accounts. It signs in
to your gym's Netpulse portal, fetches your workout history and your bio-age
profile, and exposes them as sensors: how often you trained, how hard, and what
the last EGYM machine circuit actually looked like.

> **Not affiliated with eGym or Netpulse.** This is an independent, unofficial
> integration built against an undocumented API — there is no public eGym API.
> It can be changed or withdrawn at any time, which will break this integration
> without warning. Your gym's terms of service may not permit automated access;
> that is your decision to make. The eGym and Netpulse names identify the
> service this talks to and belong to their owners.
>
> It is **not a medical device**. Bio-age, body fat, BMI and blood pressure are
> whatever eGym measured or you typed into their app, carried across unchanged.

## What you get

Around 40 sensors, all named `sensor.egym_*`.

**How often you trained** — three different questions, three different numbers:

| Entity | Notes |
| --- | --- |
| `sensor.egym_active_days_30_days`, `_7_days`, `_12_months` | Distinct calendar days with any activity. **The number to trust** |
| `sensor.egym_gym_days_30_days`, `_12_months` | Distinct days with a gym-machine workout |
| `sensor.egym_gym_workouts_30_days`, `_7_days` | Workouts recorded on a gym machine |
| `sensor.egym_workouts_30_days` | Raw rows — see the caveat below |
| `sensor.egym_days_since_last_workout`, `_gym_workout` | |

> eGym mirrors Garmin, Strava and Apple Health into the same feed and files
> **one workout per connected app for the same real activity**, so a single
> bike ride appears three times. Raw workout counts therefore over-report by
> roughly 3x. `sensor.egym_workouts_30_days` carries a `sources` and an
> `activities` breakdown as attributes, which makes the double counting
> visible instead of leaving it as a footnote.

**Totals:** `calories_30_days`, `activity_points_30_days` (and `_7_days`),
`training_time_30_days`, `distance_30_days`, `training_volume_30_days`.

**Most recent workout:** `last_workout` (timestamp), `last_workout_type`,
`_duration`, `_distance`, `_calories`, `_activity_points`, `_heart_rate`.

**Most recent gym workout:** `last_gym_workout` (timestamp, with `exercises`,
`sets`, `volume_kg` and `top_weight_kg` attributes), `_duration`, `_calories`,
`_activity_points`, plus:

- `last_gym_workout_volume` — reps × weight summed over every set, in kg. The
  single number that says whether a session was harder than the one before.
  `unknown` for a pure-cardio session rather than a misleading `0`.
- `last_gym_workout_top_weight` — heaviest weight moved.

**Bio-age and body values** — `bioage_total`, `_cardio`, `_metabolic`,
`_muscle`, `_flexibility` (unknown until the studio's mobility test has been
done once), the three muscle regions `_upper_body` / `_core` / `_lower_body`
(each with a `muscles_state` attribute flagging a left/right imbalance), plus
`body_fat`, `bmi`, `vo2max`, `resting_heart_rate` and, once entered in the eGym
app, `waist_to_hip_ratio` and `blood_pressure_systolic` / `_diastolic`.

The total and the four component ages carry a `change` attribute — eGym's own
difference to the previous measurement in years, negative when the score got
younger — and a `measured_at` timestamp of the visit that set them.

**These are health data and can be switched off entirely** — see
[Options](#options).

Bio-age is reported in whole years, spelled `Jahre` rather than the SI symbol
`a`: Home Assistant does not translate units, and `57 a` reads as nothing at
all.

### History comes from Home Assistant, not from eGym

Every numeric sensor carries a `state_class`, so most of them accumulate
long-term statistics. They start empty and fill in from the day you install
this — eGym exposes no retrievable value history (see
[docs/API.md](docs/API.md#known-limitations)), so there is nothing to backfill
them with.

## Requirements

Home Assistant 2025.1 or newer, and an eGym/Netpulse member account at a gym
that uses it.

## Installation

### HACS, in one click

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.][hacs-repo-badge]][hacs-repo-url]

The button opens this repository in HACS on your own instance. Select
**Download**, then restart Home Assistant.

It goes through [My Home Assistant][my-ha], which asks your browser for the
address of your instance the first time and remembers it afterwards. Nothing is
sent anywhere else — the page only redirects you. If you would rather not use
it, the manual route below does exactly the same thing.

### HACS, by hand

1. HACS → three-dot menu → **Custom repositories**.
2. Add `https://github.com/shadowempire123/ha-egym` with category
   **Integration**.
3. Download **eGym**, then restart Home Assistant.

### Without HACS

Copy `custom_components/egym` into your Home Assistant `config` directory and
restart.

### Then add it

[![Open your Home Assistant instance and start setting up a new integration.][config-flow-badge]][config-flow-url]

Or **Settings → Devices & services → Add integration → eGym**. Either way you
need the restart first: Home Assistant only picks up a new integration at
startup.

## Configuration

You need three things: your **brand**, your member **username or email**, and
your **password**. The credentials are verified during setup.

The brand is your gym's Netpulse subdomain — `mygym` for
`mygym.netpulse.com`. [docs/API.md](docs/API.md#what-is-a-brand) lists the ways
to find it; the quickest is usually your club app's store listing, whose bundle
id follows `com.netpulse.<brand>`.

If eGym stops accepting your password, Home Assistant asks for a new one
through the usual re-authentication prompt. The integration does not have to be
removed and set up again — which matters here, because a service that
rate-limits failed logins is not one you want an integration retrying a dead
password against every fifteen minutes.

## Options

**Settings → Devices & services → eGym → Configure**

- **Polling interval** — 5 minutes to 6 hours, 15 minutes by default. The floor
  is enforced in code, not just in the form: see [Rate limiting](#rate-limiting).
- **Body and bio-age sensors** — on by default. Switched off, those sensors are
  not created **and the bio-age service is not called at all**, so the data
  never reaches Home Assistant in the first place. See below for why you might
  want that.

## Security and privacy

### What this integration knows about you

Your training history and, unless you turn it off, a set of health
measurements: bio-age, body fat, BMI, VO2max, resting heart rate and blood
pressure. That is a different class of data from a light switch, so:

- **It lands in the recorder database and in your backups.** A Home Assistant
  sensor's history is stored like any other, which means it is in
  `home-assistant_v2.db` and in every backup of it — including backups that go
  to Home Assistant Cloud or a NAS. This is not specific to this integration,
  but it is worth knowing before you enable it. The **Body and bio-age
  sensors** option exists for exactly this; you can also exclude the entities
  from `recorder` in `configuration.yaml` if you want the current value without
  the history.
- **It is visible to every Home Assistant user who can see the entities.**
  Home Assistant has no per-user entity permissions. A shared dashboard shows
  your body fat to whoever is looking at it.
- **The device is named "eGym", not after you.** The device name prefixes every
  entity id, so naming it after the account would put an email address into
  every `entity_id` and onto every dashboard.

### Where your password goes

Only to `https://<brand>.netpulse.com`, form-encoded, over TLS.

The brand is user input that decides the hostname the password is posted to, so
it is validated against an allow list — lower-case letters, digits and hyphens,
in the shape of a DNS label — and nothing else is accepted. A deny list would
not do: a brand of `evil.com#`, `attacker.example/x` or `user@evil.com` all
move that host somewhere else, and the login request would carry your
credentials there. The check runs in the config flow *and* again when the entry
is loaded, so an entry written by an older version or edited by hand in
`.storage` cannot get around it either.

The password itself is stored where Home Assistant stores config entries, and
is never written to the log. The session cookie is held in memory only. Error
messages have your member id stripped out of them before they are raised,
because they end up in the log and, during setup, on screen.

### Rate limiting

eGym rate-limits frequent requests, and repeated failed logins can get your
address temporarily blocked — which affects your phone and the eGym app too,
not just Home Assistant. Three things guard against that:

- One update is **one request** (two with body values on). The full 365 days
  come back in a single call, and the 7-, 30- and 365-day windows are derived
  from it.
- The polling interval has a **floor of 300 seconds**, applied when the entry
  is loaded rather than only in the options form.
- A **refused login** is not retried. It raises a re-authentication prompt,
  which also stops the polling until you answer it. An *expired session* is
  different and gets one silent login — that is the ordinary case.

### Reporting a problem

**Settings → Devices & services → eGym → the three dots → Download
diagnostics** produces a report designed to be pasted into a public issue.

It works the opposite way round from the usual redaction list: nothing is
included unless it is on an allow list of counts, and every other field is
reduced to its **type** rather than its value. `"bioage_total": "int"` tells a
maintainer the parser found a reading without telling anybody what your bio-age
is. The raw API responses are reduced to their shape — field names and types
survive, which is what identifies a renamed key, while the values do not. A
value-based scrub runs over the finished report as a second line of defence.

Your username and password are removed, and the per-exercise breakdown is
reduced to a count — the names in it are your training profile, not anything
the API defines. The connected-app breakdown (Garmin, Strava, Apple Health) is
kept: it names a service rather than a person, and the triple counting those
cause is what most reports are about.

**The brand is kept**, deliberately: it names the gym rather than you, and it
is the one setting that differs between installations, so a report without it
usually cannot be answered.

## Icon and logo

The brand images live in `custom_components/egym/brand/` and are served by Home
Assistant itself through its brands proxy, at
`/api/brands/integration/egym/icon.png`. Local images take priority over the
brands CDN, so nothing has to be registered anywhere: since Home Assistant
2026.3 the [brands repository](https://github.com/home-assistant/brands) no
longer accepts icons for custom integrations. On older versions the frontend
falls back to the CDN, which has no entry for this integration and answers with
a placeholder. Only the icon is affected either way.

The mark is a plain dumbbell drawn by `scripts/make_brand_images.py`, not
eGym's logo. Naming their product in a README is one thing; shipping their
trademark in a repository is another.

## Development

The test suite runs without a Home Assistant installation — the handful of
`homeassistant` and `aiohttp` names the modules need are stubbed in
`tests/conftest.py`:

```bash
pip install -r requirements_test.txt
pytest
```

Releasing is a single step: bump `version` in `manifest.json` and `VERSION` in
`const.py`, add a `CHANGELOG.md` section for it, then push the matching `v*`
tag. A workflow publishes the release with those changelog entries as its
notes, and refuses the tag if the two versions disagree.

[docs/API.md](docs/API.md) records what the undocumented API actually does,
which endpoints were probed and what they answered, and what is still unsolved.

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[hacs-repo-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-repo-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=shadowempire123&repository=ha-egym&category=integration
[config-flow-badge]: https://my.home-assistant.io/badges/config_flow_start.svg
[config-flow-url]: https://my.home-assistant.io/redirect/config_flow_start/?domain=egym
[my-ha]: https://my.home-assistant.io/
