# Sunstone

**Sunstone** — Network mapping and visualization tool

Sunstone shows network operations staff a map of the network they can pan, zoom, and switch between views of: a geographic map with sites and links, a top-down hierarchy, and automatic topology layouts of the whole network or of the neighborhood around a device.

> **Status:** workshop prototype. It runs on a generated mock topology and simulated live state, and has no integrations yet.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and Node.js 24.

```console
$ make setup
$ make serve                                    # http://127.0.0.1:8000, small sample
$ make serve TOPOLOGY=data/sample/large.yaml    # about 3,000 devices
```

For development, run `make dev-api` and `make dev-web` in two terminals and open http://127.0.0.1:5173. `make help` lists the other tasks.

Sunstone has no sign-in, and anyone who can reach it can save and delete layouts. It listens on 127.0.0.1 by default; give it `--host` only on a network you trust.

## Using it

- **Geographic:** sites and the links between them; line width is total capacity. Click a site, or zoom in, to see its devices on rings around it (upper tiers inside). The rings are a drawing aid: sources give coordinates per site, not per device.
- **Hierarchy:** sites with a core tier on top, other sites below by WAN hops. Double-click a site, or use the details panel, to expand it into tier rows (WAN edge, core, distribution, access). Interface names label the selected device's links, and every link once zoomed in. Networks over 400 devices open with sites collapsed.
- **Topology:** automatic layouts, either of the whole network (collapsible sites, as in the hierarchy) or of a **neighborhood**: the devices within 1–4 hops of a device, site, or link. Choose a force-directed layout, optionally grouped into a frame per site, or a radial one with the center in the middle and a ring per hop. Open a neighborhood with **Show neighborhood** in the details panel or by double-clicking a device; double-click another device to walk on from there. Neighborhoods stop at 400 devices, adding whole hops only, and say what the next hop would have added. Nodes can be dragged, and finished layouts are kept while the page is open, so switching views and back shows the same picture. **Saved layouts** stores the current picture, settings included, under a name on the server, to open again later.
- **Paths:** choose **Path from here** on a device, then click or search for the destination. Every shortest path is found (by number of links; there are no routing costs in the data), drawn in all three views with everything else faded, and listed hop by hop with the interfaces at each end in the details panel. The topology view's **Path** scope draws only the devices on those paths, force-directed or layered by hop.
- **Live** (header toggle): device status and link load over every view, refreshed every 10 seconds. Devices are up (blue), dropping packets (amber, `!`), down (red, `×`, octagon in the graph views), without a recent reading (gray, `?`), or not monitored (hollow). Links are colored by their busier direction, in blue bands up to 80% of capacity, then amber, then red from 95%; down links are dashed and links with no data dotted. Sites take their worst device's color and say how many devices are down. The details panel adds round-trip time and loss from each monitoring position and load out and in on every link. A device or link the source does not watch reads "not monitored", and one without a fresh reading "no data": neither is ever shown as 0%.
- **Problems** (header button, in live mode): everything live state shows wrong, most urgent first. Devices the core cannot reach come first, one entry per connected group, so a branch that loses both circuits is "HOU cut off", not one entry per device. Then links down between devices the core still reaches, congested links (95% or more), packet loss, busy links (80% or more), and devices without a recent reading. Each entry says what it does to the network, for example "16 devices left without redundancy". Clicking one selects it, brings it into view, and shows its impact in every view.
- **History** (in live mode): a time slider under the header covers the last 24 hours in 5-minute steps, with a bar at each step as tall as how much went down then, so branch outages stand out. Moving it back replays that moment in every view, problems and impact included; **Play** steps forward a step a second, and **Back to now** returns to the present. The **Events** tab beside **Problems** lists every change, newest first, with devices at one site that changed together as one row ("PVD: 18 devices down"); clicking a row replays its moment and selects what changed. With a monitored device selected, the details panel charts its round trip from each monitoring position over the day, with down, packet loss, and no-data stretches marked under the chart, and gives each of its links a small load chart; a selected link gets a chart of its load each way. Clicking a chart replays that moment.
- **What if:** **What if it fails?** on a device, site, or link shows what its failure would do: which devices it would cut off from the core, and which would be left depending on a single device (the panel names it). Add more failures to see them together, and remove them one by one. In live mode it starts from what is already down. The details panel always says, for the current selection, what failing it alone would do.
- **Impact** is drawn like a path, with everything unaffected faded: failed devices red with `×` (octagons in the graph views), cut-off devices as red outlines, devices left without redundancy amber with `!`, and lost links dashed red (amber where only some of a bundle are lost).
- **Selection** is shared: whatever is selected stays selected when switching views. The details panel shows a device's neighbors interface by interface, a site's links to other sites, or a link's ends and circuit. Names in it are clickable.
- **Search** with `/`, by device name, site code or name, or management address. `Esc` clears the selection.

## Data

The backend serves one topology file at `GET /api/topology`. The format is YAML with three lists:

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
```

Roles are `wan-edge`, `core`, `distribution`, and `access`. Each link end is a device name plus an interface name, which is the shape NetBox cables, LLDP/CDP neighbor tables, and NMS exports all reduce to. The loader rejects unknown keys, duplicate names, references to missing sites or devices, and an interface used by two links, and it reports every problem at once.

`data/sample/` holds two generated topologies (`make data` regenerates them): `small.yaml` (5 sites, 52 devices) and `large.yaml` (63 sites, 2,960 devices, 5,930 links). Both are fictional.

Live state comes from `GET /api/state`: one snapshot of everything a state source monitors, with two kinds of record, in the shapes monitoring tools such as vakr produce. Each **device** record says up or down and gives round-trip time and loss from each monitoring position; each **interface** record, keyed by device and interface name, gives operational status and percent load in and out. Sunstone works out each link from the interfaces at its two ends, so a link has data if either end is monitored. Anything absent is not monitored; anything `stale` is monitored without a fresh reading. Sources keep a day of history: `GET /api/state?at=<time>` returns the state as of any moment in it, `GET /api/events` the changes seen (devices and links going down and coming back, readings stopping and resuming, packet loss, load crossing 80% and 95%), and `GET /api/history/{device}` one device's readings at each 5-minute step. A source is any object with `snapshot`, `events`, `history`, and a `retention` (`StateSource` in `backend/src/sunstone/live.py`); the only one so far is `SimulatedState` (`simulate.py`). It is deterministic for a given moment, so every viewer sees the same picture and any moment can be replayed: it monitors every WAN edge, core, and distribution device and about half the access switches; load follows each site's time of day with a few WAN circuits running hot; and at any time a few devices are down, a few have stopped reporting, a few drop packets, and a few carrier circuits are down, each for 15 minutes to an hour, starting and ending at different times. In about a third of half-hours a branch loses all of its circuits. A device the monitoring positions cannot reach looks down, as it would to a real poller. Round-trip time grows with distance from the two monitoring positions at the hub sites.

Saved layouts go in a JSON file beside the topology (`small.yaml` → `small.layouts.json`), or wherever `--layouts` says. They are listed, fetched, saved, and deleted at `GET /api/layouts` and `GET`/`PUT`/`DELETE /api/layouts/{name}`. The file is rewritten whole on each change, by writing a new file and moving it into place, and holds at most 200 layouts. Layout files are ignored by git, since they are each user's own arrangements.

## Layout

| Path | What |
|---|---|
| `backend/` | Python, FastAPI, managed with uv. Model and validation (`model.py`), YAML loader, API, CLI, mock generator. |
| `frontend/` | SvelteKit single-page app (Svelte 5, TypeScript), built static and served by the backend. MapLibre GL for the map; Cytoscape.js with fcose for the graph views. `src/lib/graph/` is shared by the graph views, `hierarchy/` and `topo/` are the two views. |
| `data/sample/` | Mock topologies. |

## Decisions so far

- **Stack matches vakr's** (FastAPI, uv, ruff, ty; SvelteKit, Vite, Vitest, Playwright; TypeScript types generated from the backend's OpenAPI schema), so the two projects share tooling and patterns.
- **Data sources, eventually:** NetBox/Nautobot, LLDP/CDP discovery, existing NMS and NOC tools, and vakr for metrics. vakr covers only some devices, so its data will be an optional overlay; a device never needs vakr data to appear on the map.
- **Scale target:** 500–5,000 devices. Views start grouped (sites as points on the map, collapsed sites in the hierarchy) and open up on demand.
- **Hierarchy layout** is a small fixed-row layout rather than ELK.js. Layered-graph algorithms put every link between two different rows, which splits a redundant pair joined by a peer link onto two rows; fixed tier rows keep pairs side by side. The full 3,000-device layout takes about 40 ms.
- **Topology layouts** use fcose, whose cost climbs steeply with size. Measured on the 3,000-device sample: 0.4 s with sites collapsed, but 18 s or more for one pass over the fully expanded network (and its fast draft mode piles sites on top of each other). Above 800 nodes the layout therefore goes site by site, each site's devices alone and then the sites among each other, with a final pass that pushes overlapping sites apart. That takes about 5 s for the full sample. Expanding one site in a graph of up to 300 nodes refines the current picture instead of starting over.
- **Live colors** were checked with a color-vision validator rather than by eye. Healthy is blue, not green: green and red are nearly indistinguishable with red-green color blindness (ΔE 4 deuteranopic), while blue, amber, and red stay apart (worst ΔE 24). Glyphs, line styles, and the legend carry the same information, so color is never the only cue.
- **Live updates** poll every 10 seconds. A full snapshot of the 3,000-device sample is 1.8 MB, 82 KB with the gzip compression the backend now applies. Server-Sent Events (which vakr's API plans) would replace polling once there is a real source.
- **Impact** is measured against the core: every device with the core role, where the data centers, monitoring, and the way to other sites are. A device is cut off when no path of working devices and links reaches any core device, and has no redundancy when every such path runs through one same device. Both come from one depth-first search (articulation points) from a virtual root joined to all core devices, about 5 ms on the 3,000-device sample; a "what if" runs two. Redundancy lost counts only devices that had it before, so devices that were always single-homed do not crowd the list.
- **Outages are grouped, not guessed at.** Monitoring cannot tell a dead router from a live one behind a dead circuit, so an outage names the devices and links where reach stops (both, in that case) and counts what is cut off behind them, instead of claiming a root cause.
- **History comes from the source.** The simulator can work out any moment, so Sunstone stores nothing. A real source would have to keep history itself (vakr keeps time series), or Sunstone would have to record what it sees. Events are the source's too, at 5-minute steps; the backend keeps each step's faults and loads once worked out, so the day's events take about 2 s the first time on the 3,000-device sample (about 3,900 events) and 20 ms after.
- **History charts** follow the dataviz rules used for the live colors: two lines at most per chart (round trip from each position, or load each way), in violet and aqua, validated against each other and against the status colors with color blindness, each named in the key with its latest value. Down, packet-loss, and no-data stretches sit in a strip under the plot rather than on the lines. Hovering, or the arrow keys, read out every line at one time on a line above the chart, so the readout never covers the data or runs off the panel.
- **Problems are worked out in the browser** from each snapshot, about 50 ms on the large sample every 10 seconds. A larger network or faster updates would move this to the backend, which would also let several viewers share it.
- **Map tiles** come from OpenFreeMap's hosted dark style; viewers' browsers need internet access.

## Testing

`make test` runs backend tests (pytest), ruff, ty, svelte-check, prettier, and frontend unit tests (Vitest). `make e2e` builds the UI and runs Playwright tests against the real backend.

Where Chromium's system libraries are missing, run the browser in the Playwright container and point the tests at it:

```console
$ docker run --rm --network host --init mcr.microsoft.com/playwright:v1.64.1-noble \
    /bin/sh -c "cd /tmp && npx -y playwright@1.64.1 run-server --port 3124 --host 127.0.0.1" &
$ PW_WS_ENDPOINT=ws://127.0.0.1:3124/ make e2e
```

## Next

- Sources: NetBox/Nautobot import, then NMS import and LLDP/CDP discovery.
- Live state from real sources: vakr first (it needs the read-only integration role its design calls for), then other monitoring tools, each as a `StateSource`. Each needs history: from the tool, or recorded by Sunstone.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
