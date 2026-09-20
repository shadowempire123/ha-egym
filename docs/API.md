# What the eGym/Netpulse API does, and how that was established

This integration talks to **undocumented, reverse-engineered endpoints**. There
is no official eGym API. Everything below was verified against a real member
account on 2026-09-12, with live workout and bio-age data; endpoint paths come
from published reverse-engineering by
[togabrennan/egym-personal-viewer](https://github.com/togabrennan/egym-personal-viewer)
and
[soerenuhrbach/egym-exporter](https://github.com/soerenuhrbach/egym-exporter).

## Disclaimer

- Not affiliated with, endorsed by, or sponsored by eGym or Netpulse.
- Endpoints can change, be restricted or be withdrawn at any time without
  notice, which will break this integration.
- Your gym's terms of service may not permit automated access. Using this is
  your own decision and your own risk.
- Use it with your own account and your own data only.
- Repeated failed logins can earn your address a temporary block. Do not lower
  the polling interval below the enforced floor of 300 seconds, and do not
  script logins against the endpoint.

## What is a "brand"?

eGym is deployed white-label per gym or chain on a Netpulse subdomain, e.g.
`https://mygym.netpulse.com`. The brand is that subdomain. Find yours via:

- Your gym's signup email or welcome flyer ("eGym club code" / "Netpulse brand").
- Asking at the front desk.
- **The club app's store listing** — usually the quickest route. The bundle id
  follows `com.netpulse.<brand>`, and the listing text names the host. A club
  whose brand is `mygym` shows up as `com.netpulse.mygym` with
  `mygym.netpulse.com` in the listing. This worked first try on the account
  this integration was built against.
- Network traffic from the eGym mobile app (look for a `*.netpulse.com` host).

Enter it **without** the domain: `mygym`, not `mygym.netpulse.com`.
`normalize_brand()` in `api.py` accepts nothing but a plain DNS label, for the
reason given in
[the README's security section](../README.md#where-your-password-goes).

## Verified behaviour

- **The login must be form-encoded.** `POST /np/exerciser/login` with a JSON
  body answers HTTP 401 `{"message": "Required parameters are missing"}`; the
  same request as `application/x-www-form-urlencoded` returns HTTP 200 plus a
  `JSESSIONID` cookie.
- **The member id arrives as `uuid`**, with the eGym side of the account as a
  separate `egymAccountId`. Neither `uid` nor `exerciserId` exists.
- **The session cookie is the only credential needed.** Both the workout and
  the bio-age service accept it. Read the cookie case-insensitively — Netpulse
  spells the header `set-cookie` in lower case, and a case-sensitive lookup
  drops it silently, after which *every* request answers
  `403 "Access is denied"` and looks like a permissions problem.
- **A login request that already carries a `JSESSIONID` is refused** with
  HTTP 403. Home Assistant's shared client session keeps a cookie jar, so the
  integration uses its own session with `aiohttp.DummyCookieJar` and tracks the
  cookie by hand.
- **`externalAuthToken` being `null` means nothing.** It was `null` on an
  account returning 47 workouts and a full bio-age profile. Do not gate on it.
- **`emailVerified: false` does not block data either.**
- **`completedAfter` / `completedBefore` must be `YYYY-MM-DDTHH:MM:SSZ`.**
  Every other spelling — `+00:00`, `+0000`, `.000Z` millisecond precision,
  date-only, epoch seconds, epoch millis — is rejected with HTTP 400
  `{"errors": {"completedBefore": "wrongFormat"}}`. Omitting them gives
  `{"errors": {"completedBefore": "empty"}}`.
- **Bio-age is served by the brand host**, not `mobile-api.int.api.egym.com`,
  and is addressed by the Netpulse `uuid`. Calling it with `egymAccountId`
  answers 403.
- **Workouts come back newest first**, under a top-level `workouts` key.
- **The date range is not capped at 30 days.** A 400-day window answers fine,
  so the integration asks for 365 days in one request and derives the 7-, 30-
  and 365-day windows from that single response.

## Response shapes

A workout is `{code, exercises[], createdAt, updatedAt, completedAt, timezone,
workoutPlan*}`. Each exercise carries `source.code`, the important
discriminator:

- `fitness_machine` — actually recorded on a gym machine (`EGYM Leg Press`,
  `Bike Ergometer`, …).
- `connected_app` — mirrored in from Garmin, Strava or Apple Health. eGym
  creates **one workout per connected app for the same real activity**, so a
  single bike ride shows up three times. Counting raw workouts therefore
  over-reports by roughly 3x, which is why `gym_workout_count` filters on
  `fitness_machine`. On the reference account, 46 workouts over five days split
  as Apple Health 18, Garmin 16, Strava 11, Fitness Machine 1 — the same five
  days of training, counted four ways. The honest count is **distinct calendar
  days**, which is what `sensor.egym_active_days_30_days` reports.
- Garmin additionally files a daily summary named `Daily routine` with
  `duration: 0`. It is not a workout, but it is a row, so it can surface as
  "last workout". Deliberately not filtered: the per-activity breakdown on
  `sensor.egym_workouts_30_days` makes it visible instead.

Numbers live at `exercises[].attributes.<name>.value`, e.g. `calories`,
`activity_points`, `distance`, `average_heart_rate`, `heart_rate_history` and
`sets_of_reps_and_weight_or_duration_and_weight` (a list of `{reps, weight}`).

Bio-age is `{totalDetails, muscleDetails, metabolicDetails, cardioDetails,
flexibilityDetails}`, each metric shaped `{value, progress, percentageDiff,
amountDiff, createdAt, timezone}`. Sections and individual metrics can be
`null` — `flexibilityDetails` is `null` until the studio's mobility test has
been done once (verified 2026-09-19: after the test it carries
`flexibilityAge` in the same shape as the other components), as are
`systolicPressure`, `diastolicPressure` and `waistToHipRatio` without manual
entry. `amountDiff` is the difference to the previous measurement in whole
years, `progress` spells the same as `up`/`down`; both are `null` on a first
measurement. `muscleDetails` breaks the muscle score into `upperBodyAge`, `coreAge`
and `lowerBodyAge`, each carrying a `musclesState` field (`NONE` /
`IMBALANCED`) that flags a left/right imbalance. Every section also carries a
`quote.text`, eGym's own nudge about which measurement is still missing,
surfaced as the `hint` attribute on `sensor.egym_bioage_total`.

## Other endpoints, probed 2026-09-12

| Endpoint | Result |
|---|---|
| `/np/exerciser/{uuid}` | works — duplicates the login response |
| `/np/exerciser/{uuid}/stats` | works, all zeros on the reference account |
| `/np/exerciser/{uuid}/challenges` | works — club challenges with full participant rankings. All expired and unjoined here, so no sensor was added |
| `/np/exerciser/{uuid}/notifications` | works — empty |
| `/np/exerciser/{uuid}/{goals,checkins,visits,badges,measurements}` | `404` |
| `/analysis/api/v1.0/exercisers/{uuid}/{measurements,strength,bodyvalues}` | `500` |
| `/workouts/api/workouts/v2.3/exercisers/{uuid}/{statistics,summary,goals,plans}` | `500` |
| `/analysis/**/api-docs`, swagger-ui, actuator | `403` / `404` — no schema to read enums from |

Note that the club challenge endpoint returns **other members' names and
rankings**. Nothing here requests it, and nothing should without those members
having a say in it.

## Known limitations

- Strength-test (1RM) history and training-plan/phase data are not
  implemented. The upstream reference project found that plan and phase
  endpoints answer `403` for member credentials — a trainer or operator role is
  required.
- **Bio-age history is unsolved.**
  `GET /analysis/api/v1.0/exercisers/{uuid}/bioage/history` exists and accepts
  `types=totalBioAge`, but also requires `granularity`, typed server-side as
  `HistoryGranularity`. Roughly 60 candidates were tried — `DAY`/`WEEK`/`MONTH`
  and their lower-case, `-LY` and `PER_` forms, `MEASUREMENT`, `RAW`,
  `SINGLE_VALUE`, ISO durations (`P1D`), bare integers, aggregate names
  (`AVG`, `MEAN`) — and every one answers
  `400 {"errors": {"granularity": "wrongFormat"}}`. No api-docs or swagger
  endpoint is reachable to read the enum from. Only the latest snapshot is
  fetched; Home Assistant's own recorder covers the need instead.
