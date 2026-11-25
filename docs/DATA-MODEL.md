# Data model

## Topology

The backend serves one topology file at `GET /api/topology`, with the fixes accepted into it applied (see below). The format is YAML with three lists, and more, all optional, for what is layered over them (below):

```yaml
sites:
- {code: DAL, name: Dallas DC, region: South, lat: 32.7767, lon: -96.797}
devices:
- {name: dal-core-01, site: DAL, role: core, platform: N9K-C9364C, mgmt_ip: 10.1.0.3}
links:
- a: {device: dal-core-01, interface: HundredGigE1/0/3, lag: Port-channel1}
  b: {device: dal-core-02, interface: HundredGigE1/0/3, lag: Port-channel1}
  speed_mbps: 100000
- a: {device: hou-wan-01, interface: TenGigabitEthernet1/0/3}
  b: {device: dal-wan-01, interface: TenGigabitEthernet1/0/1}
  speed_mbps: 10000
  kind: wan
  circuit: {provider: Mesa Carrier, circuit_id: ME-595185}
  enterprise_cid: HOU-DAL-01      # the enterprise's own; on a cable, its cable ID
```

Roles are `wan-edge`, `core`, `distribution`, and `access`. Each link end is a device name plus an interface name, which is the shape NetBox cables, LLDP/CDP neighbor tables, and NMS exports all reduce to. The loader rejects unknown keys, duplicate names, references to missing sites or devices, and an interface used by two links, and it reports every problem at once.

What is layered over the links, and beyond them, uses NetBox's and Nautobot's names where they have the object:

```yaml
networks:                       # named slices of the whole
- {name: black, boundary: outside}
- {name: grey}
- {name: red-alpha, tenant: Alpha, rides: [grey]}   # no tunnels of its own
transports:                     # provider networks: drawn as clouds
- {name: INET, kind: internet, network: black}
- {name: Harbor E-Tree, kind: private-wan, network: metro, service: e-tree, technology: MPLS EVPN}
externals:                      # run by someone else
- {name: Nimbus Cloud, kind: application, reached_over: [INET]}
- {name: alpha-hou-1, kind: tenant, tenant: Alpha, network: red-alpha, platform: Inline encryptor}
tenants:
- {name: Alpha}
links:
- a: {device: hou-wsw-01, interface: GigabitEthernet0/0/0}
  b: {transport: INET}          # a circuit into a transport
  kind: wan
  speed_mbps: 1000
  circuit: {provider: Northwind Fiber, circuit_id: NO-382359}   # the carrier's CID
  carries: [{network: black, vlan: 30}]
  medium: fiber                 # fiber, copper, twinax, radio, microwave, cellular, satellite
  enterprise_cid: HOU-INET-01   # the A side's only: the Z side is the transport
  edges: [transit, egress]      # roles at the edge; without them, TBD into a transport
  neighbors: provider           # what LLDP and CDP show on our port: far-end, provider, nothing
- a: {device: dal-wan-02, interface: GigabitEthernet0/0/3}
  b: {transport: Harbor E-Tree, role: root}   # into an E-Tree: a root, or a leaf by default
  kind: wan
  speed_mbps: 1000
  circuit: {provider: Harbor Transit, circuit_id: HA-643873}
  neighbors: far-end            # across a layer-2 service, our devices on it
- a: {device: aus-wan-01, interface: TenGigabitEthernet0/1/0, lag: Port-channel10}
  b: {device: sat-wan-02, interface: TenGigabitEthernet0/1/0, lag: Port-channel10}
  kind: wan
  speed_mbps: 10000
  circuit:
    provider: Mesa Carrier
    circuit_id: {a: ME-502327 / Pecos Bell 12/KXFU/204411, z: ME-502327 / Gulf Coast Bell 31/KQGS/558120}
    service: e-line             # or e-access; into a transport, the transport's
    technology: 802.1Q-in-Q
  enterprise_cid: {a: AUS-SAT-01, z: SAT-AUS-01}   # each side its own
  neighbors: [provider, far-end]                   # the NTU over LLDP, the far end over CDP
- a: {device: iad-core-01, interface: TenGigabitEthernet0/1/2}
  b: {device: iad-dist-01, interface: TenGigabitEthernet0/1/0}
  speed_mbps: 10000
  circuit: {provider: Granite Colo, circuit_id: XC-40017, type: cross-connect}   # the provider's cable
  enterprise_cid: IAD-C0006
- a: {device: hou-gry-01, interface: GigabitEthernet0/0/1}
  b: {device: hou-gsw-01, interface: GigabitEthernet0/0/0}
  speed_mbps: 1000
  carries: [{network: grey, vlan: 200, b: {vlan: 400}}]   # VLAN 200 at A, 400 at B
tunnels:                        # point to point, riding another network
- name: GREY-HOU-DAL
  network: grey
  rides: blue
  technology: GRE+IPsec
  a: {device: hou-gry-01, interface: Tunnel201, source: Loopback0}
  b: {device: dal-gry-01, interface: Tunnel202, source: Loopback0}
- name: MACSEC-DAL-FTW
  kind: macsec                  # on the physical ports, which have no source
  network: corp
  rides: metro
  technology: GCM-AES-XPN-256
  neighbors: alongside          # how LLDP and CDP relate to it: inside, alongside, or none
  a: {device: dal-wan-02, interface: GigabitEthernet0/0/2}
  b: {device: ftw-wan-01, interface: GigabitEthernet0/0/2}   # across the E-LAN
lags:                           # port channels; members name them with lag
- a: {device: aus-wan-01, interface: Port-channel10}
  b: {device: sat-wan-02, interface: Port-channel10}
  enterprise_cid: AUS-SAT-PO01
fabrics:                        # tunnels made from members
- name: DMVPN-INET
  network: corp
  rides: black
  shape: hub-spoke-dynamic      # or hub-spoke, full-mesh, group
  technology: DMVPN phase 3
  members:
  - {device: dal-wan-01, interface: Tunnel100, role: hub, source: Loopback0}
  - {device: aus-wan-01, interface: Tunnel100, role: spoke, source: Loopback0}
terms: {tenant: Customer}       # the organization's own words
```

Groups, for status, also take NetBox's names:

```yaml
name: Enterprise                # or Global, Nationwide; without one, Network
regions:                        # regions inside regions; without them, a site's region stands alone
- {name: Central}
- {name: South, parent: Central}
locations:                      # parts of a site, inside each other: buildings, floors, halls
- {site: DAL, name: Hall A}
- {site: DAL, name: Cage 4, parent: Hall A}
devices:
- {name: dal-core-01, site: DAL, role: core, location: Hall A}
networks:
- name: grey
  anchors: [DAL, IAD]           # where it is reached from
  regions:                      # its own regions, when not the sites'
    grey-west: [DAL, HOU, OKC, TPA]
    grey-east: [IAD, ATL, CLT, MEM, BNA, RDU]
```

A site's `region` names one of `regions`, when there are any. A device's `location` is one at its own site. Without `anchors`, a network is reached from its sites with core devices, or else the largest group of its sites that reach each other; the whole network is reached from its core devices, as impact is.

A link's B end can be a transport or an external node instead of a device; its A end is always a device. For a circuit, `a` is its A side and `b` its Z side, as on the circuit order (for a circuit into a transport, the Z side is the transport), and Sunstone calls them that wherever it shows a circuit's ends and the load each way (A→Z, Z→A); a cable's ends are its A and B ends, as NetBox names them. A network is everything that carries it: the links that say so, with the VLAN, VXLAN VNI, MPLS label, or VRF each end knows it by (the same at both ends unless an end says otherwise), circuits into a transport whose network it is, and its own tunnels and fabrics. Each tunnel and fabric says which network it rides, so networks stack, and one network's tunnels can ride different networks: grey rides blue where there is blue, and black elsewhere. A tunnel's far end can be an external node known only by name and address (`b: {external: Acme Logistics, peer: 198.51.100.7}`). A fabric's tunnels are worked out from its members: each spoke to each hub, spokes to each other on demand for `hub-spoke-dynamic`, every pair for `full-mesh`, and none for `group` (GETVPN), whose members reach each other directly. `technology` is a label; `shape` is what Sunstone draws. `tags` on networks, transports, external nodes, tunnels, and fabrics are found by search. `terms` gives the organization's word for `network`, `transport`, `external`, `application`, `partner`, `tenant`, `tunnel`, or `fabric`, used everywhere Sunstone names them. The loader also rejects unknown networks, transports, external nodes, and tenants; a network that rides itself, through any number of others; a tunnel interface used twice, or one that is cabled; a tunnel leaving from a cabled interface that does not carry what it rides; a circuit into a transport that is not `kind: wan`, or that carries another network than the transport's; and fabric members that do not fit its shape.

Each connection also says what carries it and what it is for. `medium` is what carries the bits at our port. A link with a `circuit` crosses a provider's path: a carrier's service (`type: carrier`, the default), or the provider's cable (`type: cross-connect`, as between co-location cages); one without is our own cable, fiber, or radio. `circuit_id` is the carrier's CID, as the carrier writes it, so it can hold several (the local exchange carrier's beside the carrier's), and `enterprise_cid` the enterprise's own: on our own cable, its cable ID. Each is one value for both sides, or `{a: ..., z: ...}`: `z` left out is the same as `a`, and `z: ''` leaves the Z side blank; into a shared transport, a single value is the A side's only. Tunnels and fabrics take `enterprise_cid` too, and a `circuit` when they are a provider's service. `edges` lists a link's, tunnel's, or fabric's roles at the edge of the enterprise: `access`, `transit`, `interconnect`, `ingress`, `egress`, `peering`, and `open`. Without them, a role is implied where the far end leaves no doubt (transit across a provider's circuit or cross-connect between two of our devices, and for tunnels and fabrics between them; access for a tenant's node; interconnect for a partner's; egress for an application's), a link between two of our devices with nothing between them is internal, and a circuit into a transport is TBD. A transport joins only the circuits into it that are for transit, or TBD: reach, paths, the tunnels riding the transport's network, and status go across it by those alone. `neighbors` says what LLDP and CDP show on our port: `far-end`, `provider` (its NTU or PE), or `nothing`, or a list of the first two, as for a circuit whose NTU answers LLDP while CDP passes through to the far end; between two of our devices it is the far end unless it says otherwise, and into a transport or to an external node it is not said until it is.

A transport can be a layer-2 service, `service: e-lan` (many to many: VPLS, EVPN) or `e-tree` (one to many: EVPN with root and leaf policies), with a `technology` label; without one it is routed. Across a layer-2 service our own devices see each other, so a circuit into one can show the far end: the other devices on it, or for an E-Tree leaf, the roots. Each circuit into an E-Tree is a `role: root` on its transport end, or a leaf. A leaf reaches only the roots: reach, paths, status, and "what if" go from one leaf to another through a root's router, and a leaf no root reaches is cut off from the E-Tree. A circuit takes a `service` and `technology` of its own when it is point to point: `e-line` (VPWS, a pseudowire, 802.1Q-in-Q, a trunk carrying our VLANs across), or `e-access` (from a UNI to another operator's NNI, as a local exchange carrier's access to the carrier is). MACsec is a tunnel with `kind: macsec`: its ends are the physical ports of the link it rides, or of two circuits into one layer-2 service, it has no source, and it is up while those links are; its far end can be an external node its link goes to. Its `neighbors` says how LLDP and CDP relate to it: they run `inside` it, `alongside` it in clear, or `none`; what the port shows is still its link's to say. `lags` lists port channels between two of our devices, each by its two channel interfaces, with an `enterprise_cid` and a `circuit` of its own; its members, one or more, are the links whose ends name it with `lag`, each with its own IDs. The loader rejects a circuit into a routed transport that shows the far end, the provider's equipment on a link without a circuit, a role or a kind of neighbor named twice, `nothing` with anything else, a tunnel other than MACsec saying how LLDP and CDP relate to it, a root into anything but an E-Tree, an E-Tree with no root, an E-Line into a transport, MACsec on a port no link uses, with a source, between ports no one link or layer-2 service joins, between two leaves, or twice between the same ports, and a port channel listed twice, with no members, or with a member ending elsewhere than its far channel.


## Priorities

Every cable and circuit is part of the enterprise, and has a priority that says how far its outage climbs and how urgent its problems are; resources gather what the enterprise depends on beyond its own networks, each with a status of its own:

```yaml
priorities: {interconnect: medium}   # defaults by role, internal, or tbd, in place of the built-in ones
devices:
- {name: iad-wan-02, site: IAD, role: wan-edge, priority: high}   # its cables and circuits, and its own problems
links:
- a: {device: dal-wan-01, interface: GigabitEthernet0/0/0}
  b: {transport: INET}
  enterprise_cid: DAL-INET-01
  edges: [transit, egress, ingress]
  priority: high                # its own, before its devices' and its roles'
resources:
- name: Global Access
  description: Ways out to the world at the TIC gateways
  tags: [tic]
  circuits: [DAL-INET-01, DAL-INET-02, DAL-REN-01, IAD-INET-01, IAD-INET-02]   # by enterprise CID
- name: Nimbus Cloud access
  circuits: [IAD-NIMBUS-01]
  resources: [Global Access]    # resources inside resources
- {name: Acme Logistics, tunnels: [Acme VPN]}
- {name: Branch VPN, fabrics: [DMVPN-INET, DMVPN-MPLS]}
```

`priority` is `ignored`, `low`, `medium`, or `high` (written out: YAML reads a bare `off` as false). A cable or circuit down that is ignored counts toward no status and raises no problem, as an access port users come and go on; a low one degrades its location and site, never its region, the whole network, or a named network above the site; a medium one climbs as far as the status rules take it; and a high one climbs too, and its problems come first, marked High. A link's own `priority` comes first; then one its devices or its far end (an external node) give, the higher where both ends give one; then the default for its roles, the highest where it has several: low for access and interconnect, which the party downstream answers for first (the tenant, partner, or application at the far end, or the transport's provider), and medium for the rest, internal cables and TBD circuits included. `priorities` changes the defaults by role, `internal`, or `tbd`. Nothing is high unless the topology says so. A device's `high` also puts its own problems first, and its `ignored` keeps its own going down out of status, problems, Events, and the handover's outages, though what it cuts off still counts. Priorities change only how far a link's own outage climbs: a site cut off is still offline, and raises every level, whatever its circuits' priorities, and a partition is still degraded.

## Resources

`resources` lists what the enterprise depends on beyond its own networks: a way out to the world, a cloud, a partner. Its members are `circuits`, by the enterprise CID of either side (a cable's too), and `tunnels`, `fabrics`, and other `resources`, by name. A resource is operational while every member is: a circuit or a tunnel up with its device reached from the core, a fabric with all its tunnels up (a group, with all its members reached), and each resource inside it operational. It is offline when none of them can be used, and degraded otherwise. It counts its members whatever their priorities. The loader rejects an unknown priority or role in `priorities`, a resource named twice or with no members, a circuit no link has or that two links have, an unknown tunnel, fabric, or resource, a member listed twice, and a resource inside itself.

## Samples

`data/sample/` holds three generated topologies (`make data` regenerates them): `small.yaml` (5 sites, 52 devices), `large.yaml` (63 sites, 2,960 devices, 5,993 links, with an Internet circuit at every site and a DMVPN fabric over the Internet), and `layers.yaml` (22 sites, 116 devices, 191 links, 32 tunnels, 3 fabrics, 2 port channels, 5 resources). The layered sample has two data centers and twenty branches on the Internet, a carrier's MPLS, or both, and two point-to-point circuits; DCI and DMVPN hubs on the same routers; blue between outer routers, blue2 where blue does not reach, and grey between inner routers riding either or black directly; two tenants' networks over grey through their own encryptors, side by side at two sites; a partner's VPN; a cloud reached directly and over the Internet, and a mail application; a research network, peering at IAD and open at DAL; and carrier Ethernet (metro, outside the boundary): two E-Lines between the data centers bundled into one port channel (DAL-IAD-PO01), each member with MACsec carrying dci, with LLDP and CDP inside it, so the far end shows though Mesa passes nothing of ours; Mesa's E-LAN joining Dallas, Fort Worth, Austin, and San Antonio, the three branches over Pecos Bell's E-Access, with MACsec carrying corp from Dallas to each and between Austin and San Antonio, with LLDP and CDP alongside it in clear, so each port shows Mesa's NTU and every router on the E-LAN; and Harbor's E-Tree, rooted at both data centers, with Oklahoma City, Tulsa, Little Rock, and Memphis as leaves. Houston has two WAN switches with two Internet circuits each from three providers, and a blue router trunked to both; Tampa has one switch carrying grey in VLAN 200 and black in VLAN 30, trunked to a router whose grey tunnel rides black. All three call the whole network Enterprise, put their regions inside Central, Eastern, and Western, and put the data centers' devices in two halls: the WAN edge and core in Hall A, the rest in Hall B. The layered sample's networks name their anchors, the data centers, and grey has regions of its own. Every connection in the samples has a CID, by where it goes (`DAL-INET-01`, `HOU-DAL-01`, `IAD-NIMBUS-01`, `DAL-ELAN-01`) or, for a cable, by site (`DAL-C0001`), tunnels and fabrics in turn (`TUN-0001`, `FAB-01`), and port channels by where they go (`DAL-PO01`, `DAL-IAD-PO01`); links of 10 Gbps and more, and circuits, are fiber, the rest copper. The Internet circuits are transit and egress in the large sample. In the layered one, the Internet, MPLS, and point-to-point circuits are transit; the data centers' Internet circuits are egress (the central way out) and ingress (a DMZ) too; the branches with both transports break out locally (egress), and the rest send everything through the data centers. The research network's circuits are peering at IAD and open at DAL, Nimbus Cloud's direct circuit is interconnect, and Tampa's Internet circuit is TBD and does not say what it shows. Mesa's branch circuits carry the local exchange carrier's CID too, AUS–SAT has each side's own IDs and is an 802.1Q-in-Q E-Line, a port channel of one member (AUS-SAT-PO01) whose NTU answers LLDP while CDP passes through to the far end, DAL–FTW is microwave, and IAD's halls are joined by the co-location provider's cross-connects (Granite Colo, which shared risk lists beside iad-wan-01 as taking 7 of grey's 15 tunnels). Circuits show the provider's NTU where the provider leaves LLDP and CDP on (Northwind, Harbor, Mesa, and the research network) and nothing elsewhere; tenants' encryptors show nothing. The data center interconnect's two E-Lines and the data centers' four Internet circuits are high priority, as the mission essential functions there rely on them; the tenants' encryptors' cables and Nimbus Cloud's direct circuit are low by default, Alpha's, Bravo's, and Nimbus's to answer for first. Five resources gather what the enterprise depends on: Global Access (the ways out at the data centers, the TIC gateways: their Internet circuits and the research network's open circuit at DAL), Research Peering (IAD's circuit into the research network), Nimbus Cloud access (its direct circuit, and Global Access), Acme Logistics (the partner's VPN), and Branch VPN (corp's two DMVPN fabrics). All are fictional.

## Live state

Live state comes from `GET /api/state`: one snapshot of everything a state source monitors, with two kinds of record, in the shapes monitoring tools such as vakr produce. Each **device** record says up or down and gives round-trip time and loss from each monitoring position; each **interface** record, keyed by device and interface name, gives operational status and percent load in and out. Sunstone works out each link from the interfaces at its two ends, so a link has data if either end is monitored; a circuit into a transport, or a link to an external node, has one end to read. Anything absent is not monitored; anything `stale` is monitored without a fresh reading. Sources keep a day of history: `GET /api/state?at=<time>` returns the state as of any moment in it, `GET /api/events` the changes seen (devices and links going down and coming back, readings stopping and resuming, packet loss, load crossing 80% and 95%), and `GET /api/history/{device}` one device's readings at each 5-minute step. A source is any object with `snapshot`, `events`, `history`, and a `retention` (`StateSource` in `backend/src/sunstone/live.py`); the only one so far is `SimulatedState` (`simulate.py`). It is deterministic for a given moment, so every viewer sees the same picture and any moment can be replayed: it monitors every WAN edge, core, and distribution device and about half the access switches; load follows each site's time of day with a few WAN circuits running hot; and at any time a few devices are down, a few have stopped reporting, a few drop packets, and a few carrier circuits are down, each for 15 minutes to an hour, starting and ending at different times. In about a third of half-hours a branch loses all of its circuits. A device the monitoring positions cannot reach looks down, as it would to a real poller; transports join the devices whose circuits go into them. Snapshots also say which tunnels are up (`tunnels`: each point-to-point tunnel by name, and each tunnel a fabric is made of as `FABRIC:a~b`, with those built spoke to spoke on demand listed while they are up); a source that does not report a tunnel leaves it taken to be up. The simulator works them out from the bottom up: a tunnel is up when its ends reach each other through what it rides, around what has failed, so a circuit down takes down the blue tunnels over it and the grey ones over those, unless they find another way; a few tunnels also fail on their own for 15 minutes to an hour; and in each hub-spoke-dynamic fabric, one pair of spokes in 20 builds a tunnel for 15 minutes at a time. Events include tunnels going down and coming back (`tunnel-down`, `tunnel-up`, with `tunnel`). Round-trip time grows with distance from the two monitoring positions at the hub sites.

## Problems, impact, and status

Problems, impacts, and status are worked out on the server. `GET /api/status?at=<time>` returns the whole network's status and each named network's (`status`, `reasons`, `caveats`, how many `sites` and how many `reached`, `tunnels_down`, and the `groups` not operational, each with its `kind`, `id`, `status`, and `reasons`), and each resource's (`status`, `reasons`, and its `members`, each with its `kind`, `name`, `status`, `reason`, and for a circuit its `link`), for the same moment as the state shown. `GET /api/problems?at=<time>` returns the problems in the state as of a moment (pass the `generated_at` of the state shown, so the two match), each with what it does to the network, and for an outage or link down, `networks`: each named network fixing it would give something back to or change the status of, as `POST /api/impact` gives them, `before` with it fixed and `after` as things are; `POST /api/impact` answers a "what if": given devices, sites, links, and providers (`{kind: provider, id}`, every circuit it provides) to suppose failed, and optionally the moment whose live state to start from, it returns which devices they would cut off, which they would leave without redundancy, whether everything named was down or cut off already, and `networks`: the whole network and each named network they change, bottom up, each with its status `before`, its status `after` (as `GET /api/status` gives it), how many `tunnels` it has, and the `tunnels_lost`, `links_lost`, and `sites_lost`; and `resources`, each resource they change, with its status `before` and `after`. `GET /api/risks` returns each named network with two or more tunnels, bottom up, with its shared risks worst first: each a list of `items` (`kind` `device`, `link`, or `provider`, and `id`) that would each, failing alone on the network as documented, take down the same `tunnels` and cut off the same `sites`; at most 40 per network, with how many `more`. With `at=<time>`, they are worked out on top of what is down at that moment (`at` says which), and a risk only because of it is `new` and comes first.

## Maintenance and acknowledgements

Maintenance windows and acknowledgements go in another JSON file beside the topology (`small.operations.json`), or wherever `--operations` says, kept the same way and also ignored by git. Windows are listed, planned, changed, and deleted at `GET`/`POST /api/maintenance` and `PUT`/`DELETE /api/maintenance/{id}`; a window names devices, sites, and links that must exist in the topology, and lasts at most 7 days. `POST /api/acks` acknowledges a problem there is now, by its id, and `DELETE /api/acks?problem=<id>` withdraws it. Problems from `GET /api/problems` carry their `priority` (`high` ones come first), who answers for them first when it is not the enterprise (`responsible`), the windows that account for them (`planned`), their acknowledgement (`ack`), the team that owns them (`team`), whether they are urgent (`urgency`), and where their page stands (`paging`); events carry `planned`. `POST /api/pages` records a page to the team that owns a problem there is now, and `DELETE /api/pages?problem=<id>` withdraws it; `POST /api/covers` and `DELETE /api/covers/{id}` add and remove covers. Pages and covers go in the same file.

## On-call

The on-call directory is a YAML file beside the topology (`small.oncall.yaml`), or wherever `--oncall` says; without one, everything else works and the on-call list says where to put it. `make data` writes one for each sample, with fictional people and phone numbers from the range set aside for fiction (555-0100 to 555-0199). An excerpt:

```yaml
people:
- {id: pat-rivera, name: Pat Rivera, phone: +1 214 555 0100}
teams:
- id: network-central
  name: Network Central
  rotation: {people: [pat-rivera, lee-chen], every_days: 7, handoff: '09:00', timezone: America/Chicago, starts: '2026-01-05'}
  manager: dana-novak
  escalation:                      # the default
  - {after_min: 0, to: primary}
  - {after_min: 15, to: secondary}
  - {after_min: 30, to: manager}
routes:                            # tried in order; the first that matches owns it
- {team: wan, match: {kinds: [wan]}}
- {team: datacenter, match: {sites: [DAL, IAD]}}
- {team: network-central, match: {regions: [South]}}
- {team: noc}                      # no conditions: everything else
carriers:
- {provider: Mesa Carrier, phone: +1 800 555 0102, portal: 'https://noc.mesa.example'}
urgency: {loss: low}               # kinds left out keep their defaults
handovers: {at: ['07:00', '19:00'], timezone: America/Chicago}   # when the NOC's shifts change
```

A route's conditions (`sites`, `regions`, `roles`, `kinds`, `providers`) must all hold, each for any of the values listed: a site matches on its code and region, a device also on its role, a link on its kind and carrier and on the sites, regions, and roles at either end. Turns start at `starts` with the first person and hand over every `every_days` at `handoff` local time (quote it: unquoted, YAML reads `10:00` as a number); the next person in turn is secondary. `handovers` lists the local times the NOC's shifts change each day, each a handover; without it, none is saved. The loader rejects unknown keys, references to people, teams, sites, regions, and carriers that do not exist, unknown time zones, and escalation out of order, and reports every problem at once. `GET /api/oncall?at=<time>` returns each team's shift then and the next, with the people, carriers, and covers; `GET /api/ownership` returns the team that owns each site, device, and link.

## Discovery

Discovery comes from `GET /api/discovery?at=<time>`: the run in effect at a moment of the last day, or now, every 15 minutes, each compared with the topology once for every viewer. Findings carry `first_seen` and `last_seen`, the ends of the unbroken stretch of runs around the moment that show them (null when it reaches back as far as history goes, or is still seen in the latest run); `gone` lists findings of earlier runs not in this one, and `history_from` is the earliest run history has. It returns the devices that answered, the check of each documented link not confirmed (`provider` and `nothing` as documented, `mismatch`, `differs` from what it says it shows, `not-seen`, `down`, `unstated` for a link that does not say what it shows, or `unchecked`; the rest are confirmed), the findings, each with the documented and seen ends and the devices involved, every cable seen other than as documented (`seen`), for drawing, and how many `endpoints` each device has on ports no link documents. Neighbor rows carry what the neighbor says it is (`capabilities`: router, switch, access point, phone, host), its `mgmt_address`, and over LLDP its `chassis_id`; one that says only phone or host is an endpoint. Rows on one port naming one device, over either protocol or both, are one neighbor (see Using it). `tunnels` gives each point-to-point tunnel's check by CDP over it, and each MACsec connection's inside it: `confirmed`, `mismatch`, `quiet` (CDP does not run over it; never a finding), `not-seen` (MACsec that LLDP and CDP run inside, up, its far end not seen), `not-inside` (MACsec they run alongside or not at all, which discovery cannot vouch for), `down`, or `unchecked`; a finding about a tunnel names it in `tunnel`. Neighbor tables are matched to the topology however devices spell things: names with a domain or in another case, and ports in full or short form (`TenGigabitEthernet1/0/1` or `Te1/0/1`). A source is any object with `discover(at)` and an `interval` (`DiscoverySource` in `backend/src/sunstone/discovery.py`); the only one so far is `SimulatedDiscovery`. Every device the live state source watches and finds up answers, reporting each real cable whose ports are up, and across circuits and on links to someone else's device what is really there (`Beyond` in `cabling.py`): what each says it shows, the provider's NTU on a circuit into a transport that does not say, and phones and printers, up to three on each watched access switch. The simulated network's real cabling (`cabling.py`) differs from its documentation by about one of each kind per thousand links: a link with a media converter that hides each end from the other's LLDP, uplinks on another port or on the other switch of the distribution pair, cables between access switches, ports leading to lab switches not in the topology, and a switch with LLDP and CDP off. Across circuits, there is one of each: a carrier's circuit between two of our devices that passes nothing, though it does not say so; a circuit into a transport said to show nothing that shows its NTU; and, where two circuits into one transport are for something other than transit, a layer-2 path across it on which each router sees the other (in the layered sample, the research network's). They stay the same for a topology, as documentation drift does, except the lab switches, each plugged in for about half of all three-hour blocks. The live state simulator follows the same cabling: a documented port with no cable is down, and the port a cable really reaches carries its traffic. Some devices report over CDP with their platform and full port names, others over LLDP with a domain and short port names, and NX-OS devices over both: over CDP with their chassis serial after their name, over LLDP with their name alone or, one in four, only their chassis ID and management address. A provider's NTU answers over LLDP, and takes LLDP's frames, so across a circuit that shows it, the far end is seen over CDP alone. Across a layer-2 service, each circuit that shows the far end sees the others on it that do (an E-Tree leaf, the roots), and a port with MACsec that LLDP and CDP run inside sees only its MACsec far ends, while one they run alongside sees and is seen as any other. CDP runs over about two in three GRE tunnels, both ways while the tunnel is up. Across layer 2 and tunnels there is one more of each kind of drift: two leaves of an E-Tree that see each other, and a tunnel whose far end is on another tunnel interface than documented.

## Fixes

Fixes accepted into the documentation go in a JSON file beside the topology (`small.changes.json`), or wherever `--changes` says, also ignored by git. The topology file is left as it is: `GET /api/topology` serves it with the changes applied in turn, and everything else follows that. Each finding that discovery can fix carries a `fix`: its `kind` (`move`, `add`, `retire`, or `document`, which sets what a link says it shows), a `summary`, and the link `before` and `after`. `GET /api/review?finding=<id>` works out what accepting the fix of a finding in the latest run would do now: the ports it takes out of the documentation and puts in, with what Live reads on each (`removes`, `adds`), or for documenting what a link shows, which changes no port, its ports (`involved`); the devices it would leave depending on a single device (`exposed`), give a second way to the core again (`restored`), or leave with no documented way to the core at all (`cut_off`); and the problems it would clear and raise, by title. `POST /api/changes` accepts it, with `by` and an optional `note`; `GET /api/changes` lists the change set, newest first; `DELETE /api/changes/{id}` reverts a change, or answers 409 if a later one depends on it. With `expect: true` and a `note`, `POST /api/changes` marks a finding expected instead (a link not seen, a neighbor not in the topology, or a device reporting no neighbors; others answer 409), kept in the change set as a change of kind `expect` and withdrawn the same way; `GET /api/review?finding=<id>&expect=true` returns what Live reads now on the ports it is about (`involved`). `GET /api/discovery` sets expected findings aside: they move from `findings` to `expected`, their cables are not in `seen`, and the links not seen that they explain are checked `expected`. A not-seen link of a switch expected to report no neighbors is set aside too, with the switch's finding as its `covered_by`. A change that no longer applies to the topology file, as when the file is replaced, stops the server starting, naming the change and the file.

## Overrides

Overrides go in a JSON file beside the topology (`layers.overrides.json`), or wherever `--overrides` says, ignored by git, apart from the change set: they are Sunstone's own and never meant for a source of truth. Each has a `target` (`kind`: `site`, `device`, `link`, `lag`, `external`, `transport`, `tunnel`, `fabric`, `resource`, `network`, or `port`; `id`: the site's code, the link's or port channel's id, or anything else's name, and for a port its device; `interface`, for a port only), a `kind`, a `key` and `value` where it needs them, a `note`, `by`, `at`, an optional `expires`, and once renewed or withdrawn, who did it and when. The kinds, and what each is made on:

| Kind | On | Key | Value | What it does |
|---|---|---|---|---|
| `rename` | site, device, external node | | the new name | A site's name is changed in the topology served; a device or external node keeps its name as the key, and the views show the new one. Discovery and search match it. |
| `alias` | site, device, external node | | another name | Discovery and search match it. |
| `tag` | anything but a port | | a word | Shown with the object's own tags; search finds it. |
| `label` | anything but a port | the key | the value | Shown in details; search finds it. |
| `hide-map` | anything but a network or port | | | Left out of every drawing. |
| `hide-status` | site, device, link, port channel, external node | | | Priority `ignored` on the link, the channel's members, the device, every device at the site, or the external node. |
| `lock` | anything but a port | the field | its value | The field is kept at the value. Fields: a site's `region`, `lat`, `lon`; a device's `site`, `role`, `platform`, `mgmt_ip`, `location`, `priority`; a link's `speed_mbps`, `kind`, `medium`, `priority`, `enterprise_cid`; a port channel's, tunnel's, or fabric's `enterprise_cid`, and the last two's `technology`; an external node's `kind`, `tenant`, `network`, `platform`, `description`, `priority`; a transport's `kind`, `provider`, `technology`, `description`; a resource's `description`; a network's `tenant`, `description`. |
| `one-device` | port | | the device it is | Every CDP and LLDP row on the port is one neighbor, by that name, and its port from its own row if it is one of ours. |
| `ignore-neighbor` | port | | the neighbor, as reported | Its rows on the port are dropped before discovery compares, with the rows it gives about the port if it is one of ours. |

`GET /api/topology` serves the topology with the fixes and then the overrides applied, in the order they were made; everything else follows that. `GET /api/overrides` lists those not withdrawn, newest first, each with its `state` (`active`, `expired`, or `not-applied`), a `reason` for one not applied ("No device bhm-acc-01 now", or what the topology will not take), and `topology_value`: what the topology says, for a lock that differs from it, and a site's name in the topology, for one renamed. `POST /api/overrides` makes one, answering 409 when its target is not there, the topology will not take it, or it repeats a tag, alias, or ignored neighbor there, and 422 when it would have expired already; a rename, a lock of a field, a label of a key, hiding, and one device on a port take the place of the one there, which is withdrawn. `POST /api/overrides/{id}/withdraw` (`by`) withdraws one, and `POST /api/overrides/{id}/renew` (`by`, `expires`, null for never) gives it a new expiry. An override whose target is gone when the topology file is replaced is kept and not applied; one whose time is up stops applying at the next request after it. The handover's `overrides` lists those made, withdrawn, or expired in its span (`event`, `at`, `override`), latest first.

## Rules

Rules go in the same file, under `rules`. Each has a `name`, a `match`, a `kind`, a `key` and `value` where it needs them, a `note`, `by`, `at`, an optional `expires`, its `excepted` objects (`target`, `by`, `at`), and once renewed or withdrawn, who did it and when. `match.of` is the kind of object (as a target's `kind`), and its tests are lists of patterns (`*` for any run of characters, `?` for one, whole value, ignoring case): every test given must hold, by any of its patterns. What each kind of object can be tested by:

| On | Tests |
|---|---|
| site | `name` (code or name), `region`, `tag` |
| device | `name` (in the topology, new, or alias), `site` (code or name), `region`, `role`, `platform`, `priority`, `tag` |
| port | as a device, and `interface` (`Gi1/0/48`, `GigabitEthernet1/0/48`, `*/0/48`), which it needs |
| link | `name` (its id or either CID), `site` and `region` (either end's), `role` (at the edge: `transit`, `access`…, `internal` between two of our devices, `tbd` until documented), `kind`, `medium`, `priority` (its rating), `tag` |
| port channel | `name`, `site`, `region`, `tag` |
| external node | `name`, `kind`, `tenant`, `platform`, `priority`, `tag` |
| transport | `name`, `kind`, `tag` |
| tunnel, fabric, resource, network | `name`, `tag` |

A region matches the regions inside it too, and a tag the topology's own or one an override on the object adds. The kinds are an override's but `rename` and `alias`: `tag`, `label`, `hide-map`, `hide-status`, `lock` (at one value), and on ports `ignore-neighbor` (the value is a pattern for the neighbor's name: `SEP*`, `*-acc-*`, `*` for any) and `one-device` (no value: one neighbor by the name its rows give). A rule sees the topology with the fixes and the overrides on single objects applied, never what another rule adds. Where an object can have one of a kind at a time (a label of a key, a lock of a field, hiding), its own override wins over any rule, and a newer rule over an older one; rules' changes to the topology are made before the overrides', in one validation. A rule on ports is found in the neighbor tables, as no list has every port: a row on a port it is on naming a neighbor it ignores is dropped, and so is that neighbor's row about the port, even when the device the rule is on does not answer.

`GET /api/overrides` lists `rules` beside `overrides`, newest first, each with its `state`, a `reason` for one not applied, `matches` (what it applies on now: `target`, and for a lock, the `topology_value` where it differs), and `overridden` (what it matches where an override on the object or a newer rule wins); a rule on ports matches devices. `POST /api/rules/preview` takes a rule and makes nothing: what it would apply on, what wins over it, and for a rule on ports, the titles of the latest run's findings it would set aside and raise. `POST /api/rules` makes one, answering 409 for a name in use, one doing what a rule there does, or one the topology will not take, and 422 when it would have expired already. `POST /api/rules/{id}/withdraw` (`by`), `/renew` (`by`, `expires`), `/except` (`target`, `by`: take an object out of it), and `/include` (put it back). The handover's `rules` lists those made, withdrawn, or expired in its span (`event`, `at`, `rule`).

## Version, handover, and incidents

`GET /api/version` says which release is serving; self-update waits for it after a restart.

`GET /api/handover?hours=<1–24>` (12 if left out) returns the shift handover for the span ending now: the problems now, routed as `GET /api/problems` routes them; the outages that began or ended in the span (`title`, `target`, `devices`, `links`, `start` and `end`, null for before history and still down, and `planned`); the pages and acknowledgements made in it, newest first; maintenance that ended in the span, is open, or opens within as long again; the changes recorded in it; the discovery findings first seen in it and still seen; and who is on call now. Acknowledgements and pages keep their problem's `title` from when they were made. It also carries the `notes` written since the last shift change, the shifts' `timezone`, and the `message` (`subject` and `text`). `GET /api/handovers` lists the handovers saved at shift changes, latest first, each in a line (`id`, `since`, `until`, how many `problems`, `unhandled`, `outages`, `still_down`, and `notes`, and `signed`), with the `next` shift change and `current`, the id of the handover the shift on now took over with; `GET /api/handovers/{id}` returns one as it was saved, with its `id`, the notes written during its shift, and `signed` (`by`, `note`, and `at`), null until someone signs for it. `POST /api/handovers/{id}/sign-off` (`by`, and an optional `note`) signs for the current one, and answers 409 if it is not the current one or has been signed for already. `POST /api/shift-notes` (`text`, `by`) writes a note for the next shift, and `DELETE /api/shift-notes/{id}` withdraws one, or answers 409 once it has been handed over. Notes go in the operations file. Saved handovers go in a JSON file beside the topology (`small.handovers.json`), or wherever `--handovers` says, also ignored by git; the latest 60 are kept, a month of 12-hour shifts, at about 80 KB each on the 3,000-device sample.

`GET /api/incidents` lists the incidents, newest first, each in a line (`number`, `title`, `status`: `open`, `cleared`, or `closed`; `began`, `opened_at`, `opened_by`, `cleared_at`, `closed_at`, and the ids of its `problems`). `POST /api/incidents` (`problem`, `title`, `by`, and an optional first `note`) opens one from a problem there is now, answering 404 if there is no such problem and 409 if it is in an incident not yet closed. `GET /api/incidents/{number}` returns one: its `problems` (each as it was when it joined: `title`, `kind`, `target`, the `devices` and `links` it concerns, how many devices it left unreachable (`lost`) or without redundancy (`exposed`), when it `began`, who added it, and `cleared_at`), `notes`, `closed` (`summary`, `by`, `at`), the `timeline` (each entry with `at`, `kind`, `text`, `by`, a `target` to select, and `planned`), the first acknowledgement and page, and the `message`. `POST /api/incidents/{number}/problems` (`problem`, `by`) adds a problem, `POST /api/incidents/{number}/notes` (`text`, `by`) writes a note, and `POST /api/incidents/{number}/close` (`summary`, `by`) closes it; each answers 409 once it is closed. `GET /api/problems` gives each problem's `incident`. Incidents go in a JSON file beside the topology (`small.incidents.json`), or wherever `--incidents` says, also ignored by git: the latest 500, each with the timeline entries kept from elsewhere, about 3 KB for one with a short timeline.

## Saved state

Saved layouts go in a JSON file beside the topology (`small.yaml` → `small.layouts.json`), or wherever `--layouts` says. They are listed, fetched, saved, and deleted at `GET /api/layouts` and `GET`/`PUT`/`DELETE /api/layouts/{name}`. The file is rewritten whole on each change, by writing a new file and moving it into place, and holds at most 200 layouts. Layout files are ignored by git, since they are each user's own arrangements.

With `--state-dir`, or `state_dir` in a settings file, saved files all go in that directory instead, one per kind: `layouts.json`, `operations.json`, `changes.json`, `overrides.json`, `handovers.json`, and `incidents.json`. The package puts them in `/var/lib/sunstone/state`.
