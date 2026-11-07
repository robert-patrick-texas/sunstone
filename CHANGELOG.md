# Changelog

Release notes, newest first. `tools/release` takes each release's notes from
its section here.

## 0.4.0

- Network status. With Live on, the whole network and each named network,
  and their regions, sites, and locations, are operational, degraded, or
  offline: a device down degrades its group; a link or tunnel down, the
  group it belongs to and the groups below holding its ends; a group no
  anchor reaches is offline and every group above it degraded; a group
  split inside is partitioned. A network is offline when no two of its
  sites reach each other, and reads operational* while what it rides is
  degraded at its sites. `GET /api/status`.
- Problems lists the networks not working as they should first; the
  Networks menu shows each one's state; a network's details say why and
  which of its groups are not operational; the wall display and the
  handover, message included, name them too.
- Tunnels in live state and history: up when their ends reach each other
  through what they ride, worked out from the circuits up, with some
  failing on their own and spokes building tunnels to each other on demand.
  Tunnels take their health's color in the graph views and on the map, and
  Events lists them going down and coming back.
- The topology can name the whole network (`name`), nest regions
  (`regions`), and divide sites into locations (`locations`, and a device's
  `location`); a named network can name its `anchors` and its own
  `regions`. The samples are called Enterprise, with nested regions, halls
  at the data centers, and anchors in the layered sample.

## 0.3.0

- WAN transports and the networks layered over them. A link can go from a
  device into a transport (the Internet, a carrier's private WAN) or to an
  external node someone else runs: a service, a partner's device, or a
  tenant's. Named networks are slices of the whole: the links that carry
  them, with the VLAN, VNI, label, or VRF each end knows them by, and their
  own point-to-point tunnels and fabrics (DMVPN, FlexVPN, AutoVPN, SD-WAN,
  GETVPN), each riding another network, so networks stack.
- A logical view without geography: the networks chosen, or every one,
  with transports, fabrics, and external nodes as nodes of their own, and
  what the networks ride drawn faintly at their sites. A tenant's network
  brings forward the places of the network it rides.
- Networks shown in every view, chosen in the header, by search, or in a
  link (`?network=grey,blue`): their tunnels as arcs on the map, colored by
  how deep they sit, and the rest faded. Sites on the map name the
  transports they have circuits into; the graph views draw transports as
  clouds and external nodes beside them.
- Details for networks, transports, external nodes, tunnels, fabrics, and
  tenants, and search for them by name, tag, technology, or kind.
- A circuit's ends are shown as its A and Z sides, as carriers name them,
  and its load each way as A→Z and Z→A; a cable's ends stay A and B.
- `terms` in the topology gives the organization's own words for these,
  such as `tenant: Customer`; search finds them by either word.
- Circuits into a transport are monitored, raise problems, and count for
  impact and paths, which cross the transport. Tunnels have no health of
  their own yet.
- The layered sample (`data/sample/layers.yaml`), built from these cases,
  and an Internet circuit at every site of the large sample, with a DMVPN
  fabric over it.

## 0.2.0

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
