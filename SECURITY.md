# Security policy

## Reporting a vulnerability

Please report anything security-relevant privately, through GitHub's
[report a vulnerability](https://github.com/shadowempire123/ha-egym/security/advisories/new)
form, rather than in a public issue.

Do not include your eGym password, your member id, or your own measurements in
a report. If a reproduction needs configuration, the diagnostics download is
built for it: it reports which fields arrived and of what type, never their
values.

This is a hobby project with one maintainer, so there is no response-time
guarantee. Reports are looked at.

## What is in scope

- Anything that could send the member's credentials somewhere other than
  `https://<brand>.netpulse.com` — brand validation is the obvious candidate.
- Credentials, session cookie or member id appearing in the log, in an error
  shown in the UI, or in a diagnostics download.
- Health data (bio-age, body fat, BMI, blood pressure, resting heart rate)
  appearing in a diagnostics download.
- Anything that causes the integration to hammer the eGym login endpoint, which
  gets the user's own address blocked.

## What is not

- **That the eGym API is undocumented and unauthorised.** It is, deliberately
  and in the open; see [docs/API.md](docs/API.md). That is a terms-of-service
  question between a member and their gym, not a vulnerability.
- **That health data reaches the recorder database and your backups.** That is
  how Home Assistant sensors work, it is documented in the README, and the
  options flow can turn those sensors off entirely.
- **That the config entry stores the password in a recoverable form.** Home
  Assistant config entry storage is not encrypted at rest, which is true of
  every integration that needs a password. Protecting `.storage` is the
  installation's job.
