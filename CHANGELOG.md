# Changelog

Release notes, newest first. `tools/release` takes each release's notes from
its section here, and from the sections of any versions since the last
release that were never released on their own.

## 0.11.0

- Overrides: Sunstone's own exceptions to what the topology says, for a
  status dashboard fed by tools that do not always say things the way the
  operations center needs. Kept apart from fixes and never sent to a
  source of truth, each is on one object or port, with a note, who made
  it, when, and an optional expiry. **Override…** in any object's details
  makes one:
  - **Rename** a device, external node, or site: every view, list, and
    search shows the new name, and details give the topology's. A device's
    or external node's name in the topology stays its key underneath.
  - **Alias**: another name discovery and search match.
  - **Tag** and **Label** (key and value), shown in details and found by
    search.
  - **Hide from the map**: left out of every view, with "N hidden from the
    map" and a switch to show them in the legend.
  - **Hide from status**: counts toward no status and raises no problem,
    as priority ignored on the link, a port channel's members, the device,
    every device at a site, or the external node; what it cuts off still
    counts.
  - **Lock a field** at a value, whatever the topology says later: details
    say "Locked here", and "the topology says access" when it differs.
  - On a port: **One device on this port**, merging every CDP and LLDP row
    there into one neighbor, or **Ignore a neighbor**.
- Discovery offers overrides under a neighbor not in the topology on a
  documented port: an alias for the device documented there (a switch
  whose LLDP still sends its old hostname is settled at every port), one
  device on the port, or ignoring the neighbor there.
- The Overrides tab (`x`) lists every override, flagged, applying, not
  applied, and expired, to renew or withdraw. One whose target is gone
  after the topology file is replaced is kept, not applied, and does not
  stop the server. The handover lists overrides made, withdrawn, or
  expired in its span.
- A device rated ignored now keeps its own going down out of status,
  problems, Events, the time slider, and the handover's outages.
- The simulator has a switch renamed whose LLDP still sends its old
  hostname, and a WAN optimizer inline between a WAN edge router and the
  core that answers LLDP itself while CDP passes through: both are found
  by discovery as a device not in the topology on a documented port.
- API: `GET /api/overrides`, `POST /api/overrides`, and
  `POST /api/overrides/{id}/withdraw` and `/renew`; `--overrides` and
  `overrides.json` in the state directory; the handover's `overrides`.
- Fixed: a fix accepted no longer carries into the documentation a value
  an override set on its link.

## 0.10.0

- Priorities on cables and circuits: `ignored`, `low`, `medium`, or
  `high`, for how far an outage climbs and how urgent its problems are.
  An ignored one counts toward no status and raises no problem, as an
  access port users come and go on; a low one degrades its site at most;
  a medium one climbs as every link did before; a high one climbs too,
  and its problems come first, marked High, in Problems (a group of their
  own, by kind or by region), on the wall display, and in the handover. A
  link's own `priority` comes first, then one its devices or its far end
  give (a device's `high` puts its own problems first too), then the
  default for its roles: low for access and interconnect, which the party
  downstream answers for first, and medium for the rest. `priorities`
  changes the defaults. Nothing is high unless the topology says so.
- Link details give a link's priority, where it comes from, and what it
  does ("Low · access, by default · degrades its site at most"), and who
  answers for it first ("Alpha (tenant)", or the enterprise); a problem
  says it too ("Alpha answers first"). Port channels give each member's.
  Search finds links and devices by it ("high priority").
- Resources: what the enterprise depends on beyond its own networks, such
  as a way out to the world, a cloud, or a partner, each with a status of
  its own. `resources` lists each one's circuits (by enterprise CID),
  tunnels, fabrics, and other resources. A resource is operational while
  every member is up and reached from the core, degraded when any is down
  or cut off, and offline when none can be used. The map draws each as a
  hexagon amid its members' sites, and the logical view as a node joined
  to its members, colored by status with Live on. Its details list its
  members and how each is now, and what it is part of; a circuit, tunnel,
  or fabric names the resources it is in. Problems, the wall display, and
  the handover list those not operational; a "what if" says which it
  changes and how; search finds them by name, tag, or description.
- The handover leaves ignored links out of its outages, and Events and the
  time slider their going down and coming back.
- The layered sample rates the data center interconnect's E-Lines and the
  data centers' Internet circuits high, and has five resources: Global
  Access (the ways out at the TIC gateways), Research Peering, Nimbus
  Cloud access, Acme Logistics, and Branch VPN.
- API: `GET /api/status` gives each resource's status, reasons, and
  members; `POST /api/impact` the resources a "what if" changes; problems
  carry `priority` and `responsible`; the handover gives its resources.
- Fixed: the page failed ("500") with a network selected and Live on when
  a shared risk new at that moment had the same consequence as one on the
  network as documented.

## 0.9.0

- What each connection is for at the edge of the enterprise. Links,
  tunnels, and fabrics take `edges`: access, transit, interconnect,
  ingress, egress, peering, and open, as routing policy at each site sets
  them. Where the far end leaves no doubt they are implied: transit across
  a provider between two of our devices, access for a tenant's device,
  interconnect for a partner's, egress for an application's. A circuit
  into a transport says them or reads **TBD**. A link's details list them,
  each with what it does to the security boundary ("Egress · Crosses it
  outward; inbound only as replies"), and search finds them ("egress",
  "tbd").
- What carries each connection. A link's `medium` (fiber, copper, twinax,
  radio, microwave, cellular, satellite) and its path: our own cable, a
  provider's `cross-connect` (as between co-location cages), or a
  carrier's circuit.
- The IDs operations staff quote. Links, tunnels, and fabrics carry the
  enterprise's own CID (`enterprise_cid`; a cable ID on our own cable) and
  the carrier's (`circuit_id`, free-form, so it can hold the local
  exchange carrier's too). Each is the same at the A and Z sides unless
  the Z side has its own or none; into a shared transport, the Z side has
  none. A circuit is named by the enterprise's CID wherever Sunstone names
  it, the carrier's line on a problem gives both, and search finds either,
  or any part of the carrier's.
- Discovery across circuits. Each link says what LLDP and CDP show on our
  port (`neighbors`: the far end, the provider's equipment, or nothing),
  and discovery checks circuits into a transport and links to someone
  else's device too, not only cables. A circuit showing other than it
  says, or one that does not say, is a finding that offers to document
  what is seen ("Document that Circuit TPA-INET-01 shows the provider's
  equipment"), reviewed and accepted like any other fix.
- Our own devices across the boundary. One of our devices seen across a
  link for anything but transit means the boundary is not where it is
  documented; it comes first among the findings.
- Phones and printers on access ports no link documents are endpoints:
  counted, not findings. A switch there still is one.
- A transport joins only the circuits into it that are for transit, or
  whose roles are TBD: a circuit for peering, open, ingress, or egress
  alone carries none of our traffic between our sites, for reach, paths,
  tunnels, and status.
- The layered sample has a research network, peering at IAD and open at
  DAL; a DMZ (ingress) on the data centers' Internet circuits; local
  breakout (egress) at the branches with both transports; co-location
  cross-connects between IAD's halls; a microwave circuit; a circuit whose
  sides have their own IDs; and Tampa's Internet circuit, still TBD.
- An external node whose application we use (a cloud, a SaaS) is
  `kind: application`, not `service`: a service edge is where we publish
  our own, which Sunstone calls ingress. `terms` takes `application` in
  place of `service`.
- Carrier Ethernet. A transport can be a layer-2 service, `service: e-lan`
  (VPLS, EVPN) or `e-tree` (EVPN with root and leaf policies), with its
  `technology`; a point-to-point circuit can be an `e-line` (VPWS, a
  pseudowire, 802.1Q-in-Q) or an `e-access`. An E-Tree circuit is a
  `root` or a leaf. Across a layer-2 service our own routers see each
  other, so a circuit into one can show the far end (`neighbors:
  far-end`), and one port sees several. A leaf reaches only the roots:
  reach, paths, status, impact, and "what if" go from leaf to leaf through
  a root's router, and a leaf with no root reached is cut off from the
  E-Tree. A path between two leaves reads "via Harbor E-Tree › dal-wan-02 ›
  Harbor E-Tree".
- MACsec, as a connection of its own: a tunnel with `kind: macsec`, on the
  physical ports, carrying a network inside the boundary across the
  provider. It rides the link at its ports, or two circuits into one
  layer-2 service, and is up while they are. Its far end can be someone
  else's device. Its `neighbors` says whether LLDP and CDP run `inside` it,
  `alongside` it in clear, or `none`; what the port shows stays its link's
  to say. Only inside does seeing the far end vouch for the encryption. A
  link's details list the MACsec on its ports and how LLDP and CDP relate
  to each; a MACsec connection's details say what it is carried on.
- Port channels with a CID of their own. `lags` lists each channel by its
  two port-channel interfaces, with its `enterprise_cid` (and a `circuit`
  for a carrier's bundle); its members, one or more, are the links whose
  ends name it with `lag`, each with its own cable or circuit ID. A
  bundle's details give the channel's CID and each member's, a member's
  says which channel it is in, and search finds a channel by its CID.
- Neighbors over CDP, LLDP, or both. Discovery takes rows naming one
  device on one port as one neighbor, however differently the protocols
  describe it: a short name and one with a domain, NX-OS's name with its
  chassis serial over CDP, a management address, or an LLDP chassis ID
  alone beside the one device seen over CDP. A port can have several
  neighbors.
- What a port shows can be more than one thing: `neighbors: [provider,
  far-end]` for a circuit whose NTU answers LLDP while CDP passes through
  to the far end. A port showing only one of them is a finding offering
  to document what is seen.
- Two leaves of an E-Tree that see each other are a finding of their own:
  the carrier is not keeping its leaves apart, or the roles are
  documented wrong.
- CDP over tunnels. Point-to-point tunnels are compared where CDP is seen
  over them: a tunnel's details say whether its far end is confirmed, and
  the Discovery list has a tunnel seeing another device or another tunnel
  interface than documented. A tunnel CDP does not run over is never a
  finding. MACsec that LLDP and CDP run inside is checked on its port.
- Paths name the transports they cross ("Harbor E-Tree", not
  "transport:Harbor E-Tree"), and give each side's own interface only.
- The layered sample has carrier Ethernet (`metro`): two E-Lines between
  the data centers in one port channel, each member with MACsec for dci
  and LLDP and CDP inside it; an E-LAN joining Dallas, Fort Worth, Austin,
  and San Antonio, three of them over the local exchange carrier's
  E-Access, with MACsec for corp and LLDP and CDP alongside it in clear;
  an E-Tree rooted at the data centers with four branches as leaves; and
  Austin–San Antonio as an 802.1Q-in-Q E-Line, a port channel of one
  member, whose NTU answers LLDP while CDP passes through. The samples'
  other port channels have CIDs too.

## 0.8.0

- Problems and Events follow the networks chosen in the header. Choosing
  grey keeps the lists to what is grey's: its own devices, links, and
  tunnels, and those of the networks beneath it at grey's sites, as the
  Logical view draws them; a problem is grey's too when it takes something
  from grey. Problems says how many it leaves out ("2 not in corp"), and
  lists only grey and what it rides among the networks not working. The
  counts in the header and tab are still of every problem.
- Problems by region. **By kind** and **By region** switch how Problems
  is grouped, and `j` steps through them in the order shown. The regions
  are the chosen network's own when it names some (grey-west, grey-east),
  else the topology's. Events stay in time order, with a menu to keep them
  to one region.
- A site's details list the networks there and the site's status in each,
  the whole network first: "grey · Degraded · GREY-ATL-DAL down", or
  "red-alpha · Operational\* · blue degraded at DAL". Clicking one selects
  it.
- The Logical view draws the tunnels spokes have built to each other at
  the moment, thinner and with shorter dashes, as the map does, and says
  how many: "corp · 20 sites · 4 spoke to spoke now". They come and go
  without moving the view.
- Fixed: a network's details read "Hall Blocation" for a location not
  working; it is "Hall B location".
- Fixed: `make dev-api` and the dev instance restart on edits to the
  topology file, as `make help` says, not only on code changes.

## 0.7.0

- Problems say what they do to each network. An outage or link down names
  each named network it takes something from, and what: "corp: 2 of 63
  tunnels · BNA cut off". It is what fixing it would bring back, with
  everything else still down, so two circuits down at one branch each say
  they would bring the branch back. Its details list those networks as a
  "what if" does. `GET /api/problems` gives each problem's `networks`.
- Shared risk as things stand now. With Live on, a network's shared risks
  are worked out on top of what is down at the moment shown, and a risk
  only because of it is marked New and listed first: with IAD's Northwind
  circuit down, the Bluebonnet one beside it alone would take 7 of grey's
  15 tunnels. `GET /api/risks?at=<time>`.

## 0.6.0

- "What if" is worked out only when asked. The details panel no longer
  says on every selection what failing it would do: on the 3,000-device
  sample that took the server about a third of a second for each
  selection, and again at every live moment while something stayed
  selected. **What if it fails?** gives the whole answer, as before.
- "What if" and status are faster. On the 3,000-device sample a "what
  if" takes 90 ms instead of 0.34 s, and eight people asking at once
  wait 0.9 s instead of 2.1 s at the median: what failures are compared
  with is kept for the healthy network and for each live moment asked
  about, and status counts partitions with each link once, at the group
  that owns it. Each live moment takes 0.58 s to build instead of 0.67 s.
- Sunstone works behind a reverse proxy that serves it under a path, such
  as `https://example.net/sunstone/`, as well as at a site's root: the web
  UI asks for its files and the API relative to its own page.

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
