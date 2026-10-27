# Sunstone

**Sunstone** — Network mapping and visualization tool

Sunstone shows network operations staff a map of the network they can pan, zoom, and switch between views of: a geographic map with sites and links, a top-down hierarchy, and automatic topology layouts of the whole network or of the neighborhood around a device.

> **Status:** workshop prototype. It runs on generated mock data, shows structure only (no live state), and has no integrations yet.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and Node.js 24.

```console
$ make setup
$ make serve                                    # http://127.0.0.1:8000, small sample
$ make serve TOPOLOGY=data/sample/large.yaml    # about 3,000 devices
```

For development, run `make dev-api` and `make dev-web` in two terminals and open http://127.0.0.1:5173. `make help` lists the other tasks.

## Using it

- **Geographic:** sites and the links between them; line width is total capacity. Click a site, or zoom in, to see its devices on rings around it (upper tiers inside). The rings are a drawing aid: sources give coordinates per site, not per device.
- **Hierarchy:** sites with a core tier on top, other sites below by WAN hops. Double-click a site, or use the details panel, to expand it into tier rows (WAN edge, core, distribution, access). Interface names label the selected device's links, and every link once zoomed in. Networks over 400 devices open with sites collapsed.
- **Topology:** automatic layouts, either of the whole network (collapsible sites, as in the hierarchy) or of a **neighborhood**: the devices within 1–4 hops of a device, site, or link. Choose a force-directed layout, optionally grouped into a frame per site, or a radial one with the center in the middle and a ring per hop. Open a neighborhood with **Show neighborhood** in the details panel or by double-clicking a device; double-click another device to walk on from there. Neighborhoods stop at 400 devices, adding whole hops only, and say what the next hop would have added. Nodes can be dragged, and finished layouts are kept while the page is open, so switching views and back shows the same picture.
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

- Topology: paths between two devices, and saving hand-arranged layouts beyond the browser session.
- Sources: NetBox/Nautobot import, then NMS import and LLDP/CDP discovery.
- Live state: up/down status, then utilization and latency overlays (vakr among the sources).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
