# Changelog

Release notes, newest first. `tools/release` takes each release's notes from
its section here.

## 0.5.0

- "What if" across the layers. Besides the devices a failure would cut off
  or leave without redundancy, the answer says what it does to the whole
  network and each named network it reaches: its status before and after,
  the tunnels it loses out of how many, the circuits it loses at each site
  out of how many it has there, and the sites cut off from it. A network
  that stays up says so, and why it carries a caveat: failing hou-wsw-01
  takes 2 of Houston's 4 circuits from black, and blue, grey, and red-alpha
  stay up over the other two. The details panel's line for the selection
  says the same, and the tunnels lost are drawn lost on the map and in the
  graph views. `POST /api/impact` returns `networks`.
- A carrier can fail as a whole: **What if Mesa Carrier fails?** on a
  circuit's details fails every circuit it provides (`fail=provider:Mesa
  Carrier` in a link, `{kind: provider}` to `POST /api/impact`).
- Shared risk: a network's details list what beneath it would take two or
  more of its tunnels down at once on its own, a device, a link, or a
  provider's circuits, with the sites it would cut off, worst first; items
  with the same consequence are one line, and **What if** shows one
  failing. A tunnel's details list the risks it shares, and with which
  tunnels. `GET /api/risks`.
- Fixed: a group's partitions are counted between its own parts, the
  groups directly inside it and its own devices, so a site split inside no
  longer makes its region and the whole network read partitioned; and the
  Internet joins the circuits into it when the whole is judged.

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
