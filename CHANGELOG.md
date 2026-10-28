# Changelog

Release notes, newest first. `tools/release` takes each release's notes from
its section here.

## Unreleased

- Incidents: a problem becomes an incident, named and numbered, that other
  problems can join, with a timeline worked out from what Sunstone records
  about its devices and links (the source's events, acknowledgements, pages
  and whom they reached, maintenance, fixes) and people's notes, kept with
  it; it clears with its problems, and a postmortem summary closes it. The
  `i` key, `?incident=12`, a copyable postmortem, and the handover lists
  incidents.
- A daily update, off until enabled: `sunstone-update.timer` runs
  `sunstone self-update --unattended`, which installs only a newer release,
  leaves out one whose install failed last time, and logs to the journal.
- `hold_version` under `[update]` keeps updates that pick the release at or
  below a version.
- Behind a proxy: `https_proxy` under `[update]`; CA certificates in
  `/etc/sunstone/ca.d/` trusted for self-update, for a proxy that inspects
  TLS; `tls_strict_x509 = false` for an older inspection CA; and `api` for a
  GitHub Enterprise server.

## 0.1.0

The first release: Sunstone as a Debian package for Ubuntu 26.04 on amd64.

- Installs under `/opt/sunstone` with its own Python 3.15, with settings in
  `/etc/sunstone` and saved state in `/var/lib/sunstone/state`.
- `sudo sunstone self-update` installs a newer signed release in place, after
  backing up the configuration and state, and rolls back if the new version
  does not start; `--check`, `--version`, `--file`, and `--rollback` too.
- `sunstone check` loads the settings, topology, on-call directory, and saved
  files as the server would, and says what it found or what is wrong.
- Everything from the workshop prototype: the geographic, hierarchy, and
  topology views, live state and its history, problems and their impact,
  maintenance, on-call routing and paging, discovery against the
  documentation with fixes and expectations, and shift handovers, saved at
  each shift change and signed for by the incoming shift.
